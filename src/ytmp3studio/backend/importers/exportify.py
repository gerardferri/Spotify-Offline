"""Read CSV and ZIP exports created by exportify.net.

The importer intentionally exposes its own immutable DTOs.  Integrating layers can
translate them to domain or persistence models without coupling CSV parsing to
those models.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO


_MAX_CSV_SIZE = 50 * 1024 * 1024
_MAX_ZIP_CSV_TOTAL = 200 * 1024 * 1024
_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WHITESPACE = re.compile(r"\s+")
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


@dataclass(frozen=True, slots=True)
class ExportifyTrack:
    track_uri: str
    track_name: str
    artist_names: str
    album_name: str
    duration_ms: int | None
    source_row: int

    @property
    def spotify_id(self) -> str | None:
        """Return the Spotify track id when the URI is a regular track URI."""
        prefix = "spotify:track:"
        if self.track_uri.casefold().startswith(prefix):
            value = self.track_uri[len(prefix) :].strip()
            return value or None
        return None


@dataclass(frozen=True, slots=True)
class ExportifyPlaylist:
    name: str
    safe_name: str
    is_liked_songs: bool
    tracks: tuple[ExportifyTrack, ...]
    source_file: str
    duplicate_count: int = 0


@dataclass(frozen=True, slots=True)
class ExportifyIssue:
    source_file: str
    message: str
    row: int | None = None


@dataclass(frozen=True, slots=True)
class ExportifyImportResult:
    playlists: tuple[ExportifyPlaylist, ...]
    issues: tuple[ExportifyIssue, ...]

    @property
    def track_count(self) -> int:
        return sum(len(playlist.tracks) for playlist in self.playlists)

    @property
    def duplicate_count(self) -> int:
        return sum(playlist.duplicate_count for playlist in self.playlists)


def sanitize_playlist_name(name: str, *, max_length: int = 120) -> str:
    """Make a playlist name safe as one Windows path component."""
    cleaned = _INVALID_FILENAME_CHARS.sub("_", name)
    cleaned = _WHITESPACE.sub(" ", cleaned).strip().rstrip(". ")
    if not cleaned:
        cleaned = "Playlist"
    if cleaned.upper() in _WINDOWS_RESERVED_NAMES:
        cleaned = f"_{cleaned}"
    cleaned = cleaned[:max_length].rstrip(". ")
    return cleaned or "Playlist"


class ExportifyImporter:
    """Import one Exportify CSV or a ZIP containing several Exportify CSVs."""

    def import_file(self, path: str | Path) -> ExportifyImportResult:
        source = Path(path)
        suffix = source.suffix.casefold()
        if suffix not in {".csv", ".zip"}:
            return ExportifyImportResult(
                (),
                (ExportifyIssue(source.name, "Formato no compatible; selecciona un CSV o ZIP."),),
            )
        try:
            if suffix == ".csv":
                if source.stat().st_size > _MAX_CSV_SIZE:
                    raise ValueError("El CSV supera el límite de 50 MB.")
                data = source.read_bytes()
                playlist, issues = self._parse_csv(data, source.name)
                return ExportifyImportResult(
                    (playlist,) if playlist is not None else (), tuple(issues)
                )
            return self._import_zip(source)
        except Exception as exc:
            return ExportifyImportResult((), (ExportifyIssue(source.name, str(exc)),))

    def _import_zip(self, path: Path) -> ExportifyImportResult:
        playlists: list[ExportifyPlaylist] = []
        issues: list[ExportifyIssue] = []
        with zipfile.ZipFile(path) as archive:
            members = [
                item
                for item in archive.infolist()
                if not item.is_dir()
                and item.filename.casefold().endswith(".csv")
                and "__macosx" not in item.filename.casefold().split("/")
            ]
            if not members:
                return ExportifyImportResult(
                    (), (ExportifyIssue(path.name, "El ZIP no contiene archivos CSV."),)
                )

            declared_total = sum(member.file_size for member in members)
            if declared_total > _MAX_ZIP_CSV_TOTAL:
                return ExportifyImportResult(
                    (),
                    (ExportifyIssue(path.name, "Los CSV del ZIP superan el límite de 200 MB."),),
                )

            for member in members:
                source_name = member.filename.replace("\\", "/")
                if member.file_size > _MAX_CSV_SIZE:
                    issues.append(
                        ExportifyIssue(source_name, "El CSV supera el límite de 50 MB.")
                    )
                    continue
                try:
                    with archive.open(member) as stream:
                        data = _read_limited(stream, _MAX_CSV_SIZE)
                    playlist, csv_issues = self._parse_csv(data, source_name)
                    issues.extend(csv_issues)
                    if playlist is not None:
                        playlists.append(playlist)
                except Exception as exc:
                    issues.append(ExportifyIssue(source_name, str(exc)))

        return ExportifyImportResult(tuple(playlists), tuple(issues))

    def _parse_csv(
        self, data: bytes, source_file: str
    ) -> tuple[ExportifyPlaylist | None, list[ExportifyIssue]]:
        issues: list[ExportifyIssue] = []
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            return None, [
                ExportifyIssue(source_file, f"El CSV no está codificado en UTF-8: {exc}")
            ]

        if not text.strip():
            return None, [ExportifyIssue(source_file, "El CSV está vacío.")]

        reader = csv.DictReader(io.StringIO(text, newline=""), dialect=_detect_dialect(text))
        if reader.fieldnames is None:
            return None, [ExportifyIssue(source_file, "El CSV no contiene cabeceras.")]

        columns = _map_columns(reader.fieldnames)
        required = {"track_uri", "track_name", "artist_names", "album_name", "duration_ms"}
        missing = sorted(required - columns.keys())
        if missing:
            labels = ", ".join(_COLUMN_LABELS[item] for item in missing)
            return None, [
                ExportifyIssue(source_file, f"Faltan columnas de Exportify: {labels}.")
            ]

        tracks: list[ExportifyTrack] = []
        seen: set[tuple[str, ...]] = set()
        duplicate_count = 0
        for row_number, row in enumerate(reader, start=2):
            title = _cell(row, columns["track_name"])
            artists = _cell(row, columns["artist_names"])
            if not title or not artists:
                issues.append(
                    ExportifyIssue(
                        source_file,
                        "Fila omitida: faltan el nombre de la canción o el artista.",
                        row_number,
                    )
                )
                continue

            uri = _cell(row, columns["track_uri"])
            album = _cell(row, columns["album_name"])
            raw_duration = _cell(row, columns["duration_ms"])
            duration: int | None = None
            if raw_duration:
                try:
                    duration = int(raw_duration)
                    if duration < 0:
                        raise ValueError
                except ValueError:
                    issues.append(
                        ExportifyIssue(
                            source_file,
                            f"Duración no válida ({raw_duration!r}); se importó sin duración.",
                            row_number,
                        )
                    )
                    duration = None

            identity = _track_identity(uri, title, artists, album, duration)
            if identity in seen:
                duplicate_count += 1
                continue
            seen.add(identity)
            tracks.append(
                ExportifyTrack(uri, title, artists, album, duration, row_number)
            )

        playlist_name = _playlist_name(source_file)
        return (
            ExportifyPlaylist(
                playlist_name,
                sanitize_playlist_name(playlist_name),
                _is_liked_songs(playlist_name),
                tuple(tracks),
                source_file,
                duplicate_count,
            ),
            issues,
        )


_COLUMN_ALIASES = {
    "track_uri": {"track uri", "spotify uri", "uri"},
    "track_name": {"track name", "track title", "title"},
    "artist_names": {"artist name s", "artist names", "artist name", "artists"},
    "album_name": {"album name", "album"},
    "duration_ms": {"duration ms", "track duration ms"},
}
_COLUMN_LABELS = {
    "track_uri": "Track URI",
    "track_name": "Track Name",
    "artist_names": "Artist Name(s)",
    "album_name": "Album Name",
    "duration_ms": "Duration (ms)",
}


def _canonical_header(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.lstrip("\ufeff"))
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return _WHITESPACE.sub(" ", re.sub(r"[^a-z0-9]+", " ", normalized.casefold())).strip()


def _map_columns(fieldnames: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for actual in fieldnames:
        canonical = _canonical_header(actual)
        for key, aliases in _COLUMN_ALIASES.items():
            if key not in result and canonical in aliases:
                result[key] = actual
                break
    return result


def _detect_dialect(text: str) -> type[csv.Dialect] | csv.Dialect:
    sample = text[:8192]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        return csv.excel


def _cell(row: dict[str, str | None], column: str) -> str:
    return (row.get(column) or "").strip()


def _fold(value: str) -> str:
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", value).casefold()).strip()


def _track_identity(
    uri: str, title: str, artists: str, album: str, duration: int | None
) -> tuple[str, ...]:
    if uri:
        # Preserve the case-sensitive base62 Spotify identifier.
        return ("uri", uri)
    return ("metadata", _fold(title), _fold(artists), _fold(album), str(duration or ""))


def _playlist_name(source_file: str) -> str:
    filename = source_file.replace("\\", "/").rsplit("/", 1)[-1]
    name = Path(filename).stem.strip()
    return name or "Playlist"


def _is_liked_songs(name: str) -> bool:
    canonical = _canonical_header(name)
    return canonical in {
        "liked songs",
        "liked song",
        "canciones que te gustan",
        "canciones favoritas",
        "saved tracks",
        "your library",
    }


def _read_limited(stream: BinaryIO, limit: int) -> bytes:
    data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError("El CSV supera el límite de 50 MB.")
    return data
