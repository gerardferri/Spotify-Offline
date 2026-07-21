"""Application service for Exportify imports and playlist downloads."""

from __future__ import annotations

import csv
from dataclasses import asdict, replace
from hashlib import sha1
import os
from pathlib import Path
import threading
from typing import Any
from uuid import uuid4

from PySide6.QtGui import QImage

from ytmp3studio.backend.adapters.media_files import MediaFiles
from ytmp3studio.backend.importers.exportify import ExportifyImporter
from ytmp3studio.backend.playlist_matcher import PlaylistMatcher
from ytmp3studio.domain.errors import invalid_input
from ytmp3studio.domain.models import (
    DownloadJob, JobState, LibraryTrack, Playlist, PlaylistEntry,
    PlaylistTrackState, SpotifyTrack,
)
from ytmp3studio.persistence.database import utc_now
from ytmp3studio.persistence.playlist_repository import PlaylistRepository, new_playlist


class PlaylistService:
    def __init__(
        self,
        repository: PlaylistRepository,
        library_repository: Any,
        search_service: Any,
        queue_service: Any,
        settings_getter: Any,
        *,
        importer: ExportifyImporter | None = None,
        matcher: PlaylistMatcher | None = None,
    ) -> None:
        self._repository = repository
        self._library = library_repository
        self._search = search_service
        self._queue = queue_service
        self._settings_getter = settings_getter
        self._importer = importer or ExportifyImporter()
        self._matcher = matcher or PlaylistMatcher()
        self._lock = threading.RLock()

    def import_exportify(self, path: str) -> list[dict[str, Any]]:
        result = self._importer.import_file(path)
        if not result.playlists:
            message = result.issues[0].message if result.issues else "El archivo no contiene playlists."
            raise invalid_input(message)
        by_source: dict[str, str] = {}
        for imported in result.playlists:
            source_key = imported.source_file.replace("\\", "/").casefold()
            existing = self._repository.get_by_source_key(source_key)
            display_name = imported.name.replace("_", " ").strip() or imported.name
            playlist = new_playlist(
                source_key,
                display_name,
                is_liked_songs=imported.is_liked_songs,
                cover_path=existing.cover_path if existing else None,
            )
            tracks = [
                SpotifyTrack(
                    track_key=_track_key(track.track_uri, track.artist_names, track.track_name, track.duration_ms),
                    spotify_uri=track.track_uri or None,
                    title=track.track_name,
                    artist=track.artist_names,
                    album=track.album_name or None,
                    duration_ms=track.duration_ms,
                    created_at=utc_now(),
                    updated_at=utc_now(),
                )
                for track in imported.tracks
            ]
            sync = self._repository.sync_playlist(playlist, tracks)
            by_source[imported.source_file.replace("\\", "/").casefold()] = sync.playlist_id
        for issue in result.issues:
            playlist_id = by_source.get(issue.source_file.replace("\\", "/").casefold())
            self._repository.add_error(
                "EXPORTIFY_IMPORT",
                issue.message,
                playlist_id=playlist_id,
                row_number=issue.row,
            )
        self.rebuild_all_projections()
        return self.list_playlists()

    def list_playlists(self) -> list[dict[str, Any]]:
        return [self._playlist_view(item) for item in self._repository.list_playlists()]

    def get_playlist(self, playlist_id: str) -> dict[str, Any]:
        playlist = self._require_playlist(playlist_id)
        result = self._playlist_view(playlist)
        result["tracks"] = [self._entry_view(entry) for entry in self._repository.list_entries(playlist_id)]
        return result

    def download_playlist(self, playlist_id: str, *, failed_only: bool = False) -> dict[str, int]:
        with self._lock:
            return self._download_playlist_locked(playlist_id, failed_only=failed_only)

    def _download_playlist_locked(self, playlist_id: str, *, failed_only: bool) -> dict[str, int]:
        self._require_playlist(playlist_id)
        queued = failed = skipped = 0
        for entry in self._repository.list_entries(playlist_id):
            state = entry.item.state
            if failed_only and state is not PlaylistTrackState.FAILED:
                continue
            if entry.track.library_track_id:
                self._repository.update_state(entry.track.track_key, PlaylistTrackState.DOWNLOADED)
                skipped += 1
                continue
            if entry.track.current_job_id:
                skipped += 1
                continue
            decision = self._find(entry)
            if not decision.accepted or decision.result is None:
                self._repository.update_state(
                    entry.track.track_key,
                    PlaylistTrackState.FAILED,
                    error_code="NO_RELIABLE_MATCH",
                    error_message=decision.reason,
                )
                failed += 1
                continue
            jobs = self._queue.enqueue([decision.result.video_id])
            self._repository.bind_job(entry.track.track_key, jobs[0].id)
            queued += 1
        self.rebuild_playlist_projection(playlist_id)
        return {"queued": queued, "failed": failed, "skipped": skipped}

    def retry_failures(self, playlist_id: str) -> dict[str, int]:
        return self.download_playlist(playlist_id, failed_only=True)

    def stop_downloads(self, playlist_id: str) -> dict[str, int]:
        """Cancel every active/queued job referenced by one playlist."""

        with self._lock:
            self._require_playlist(playlist_id)
            job_ids = {
                entry.track.current_job_id
                for entry in self._repository.list_entries(playlist_id)
                if entry.track.current_job_id
            }
            stopped = 0
            already_finished = 0
            for job_id in job_ids:
                try:
                    job = self._queue.cancel(job_id)
                except Exception:
                    # A completion can win the race between snapshot and cancel.
                    already_finished += 1
                    continue
                if job.state is JobState.CANCELLED:
                    self._repository.release_job(job_id)
                stopped += 1
            return {"stopped": stopped, "already_finished": already_finished}

    def replace_track(self, playlist_id: str, track_key: str) -> dict[str, int]:
        candidates = self.replacement_candidates(playlist_id, track_key)
        if not candidates:
            self._repository.update_state(
                track_key, PlaylistTrackState.FAILED,
                error_code="NO_ALTERNATIVE_MATCH",
                error_message="No se encontraron versiones alternativas.",
            )
            return {"queued": 0, "failed": 1, "skipped": 0}
        return self.queue_replacement(playlist_id, track_key, candidates[0]["video_id"])

    def replacement_candidates(self, playlist_id: str, track_key: str) -> list[dict[str, Any]]:
        with self._lock:
            return self._replacement_candidates_locked(playlist_id, track_key)

    def _replacement_candidates_locked(self, playlist_id: str, track_key: str) -> list[dict[str, Any]]:
        self._require_playlist(playlist_id)
        entry = next(
            (value for value in self._repository.list_entries(playlist_id) if value.track.track_key == track_key),
            None,
        )
        if entry is None:
            raise invalid_input("La canción no pertenece a esta playlist.")
        current_video_id = None
        if entry.track.library_track_id:
            current = self._library.get(entry.track.library_track_id)
            current_video_id = current.video_id if current else None
        results = self._search.search(
            self._matcher.query(entry.track.artist, entry.track.title), 12
        )
        if current_video_id:
            results = [item for item in results if item.video_id != current_video_id]
        ranked = sorted(
            (
                (self._matcher.score(entry.track.artist, entry.track.title, entry.track.duration_ms, item), item)
                for item in results
                if not item.is_live
            ),
            key=lambda pair: pair[0],
            reverse=True,
        )
        return [
            {
                "video_id": item.video_id,
                "title": item.title,
                "channel": item.channel,
                "duration_seconds": item.duration_seconds,
                "score": round(score, 1),
            }
            for score, item in ranked[:10]
        ]

    def queue_replacement(self, playlist_id: str, track_key: str, video_id: str) -> dict[str, int]:
        with self._lock:
            self._require_playlist(playlist_id)
            if not any(
                entry.track.track_key == track_key
                for entry in self._repository.list_entries(playlist_id)
            ):
                raise invalid_input("La canción no pertenece a esta playlist.")
            jobs = self._queue.enqueue([video_id])
            self._repository.bind_job(track_key, jobs[0].id)
            return {"queued": 1, "failed": 0, "skipped": 0}

    def choose_cover(self, playlist_id: str, source: str) -> str:
        playlist = self._require_playlist(playlist_id)
        image = QImage(source)
        if image.isNull():
            raise invalid_input("No se pudo leer la imagen seleccionada.")
        folder = self._playlist_dir(playlist)
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / "cover.jpg"
        temporary = folder / ".cover.tmp.jpg"
        if not image.save(str(temporary), "JPG", 92):
            raise invalid_input("No se pudo guardar la portada.")
        os.replace(temporary, target)
        self._repository.set_cover(playlist_id, url=None, path=str(target))
        return str(target)

    def on_job_updated(self, job: DownloadJob) -> bool:
        if job.state is JobState.FAILED:
            return self._repository.mark_failed(
                job.id, job.error_code or "DOWNLOAD_FAILED", job.error_message or "La descarga falló."
            )
        if job.state is JobState.CANCELLED:
            return self._repository.release_job(job.id)
        return False

    def on_job_completed(self, job: DownloadJob, library_track: LibraryTrack) -> LibraryTrack:
        imported = self._track_for_job(job.id)
        if imported is None:
            return library_track
        old_library_id = imported.library_track_id
        old_track = self._library.get(old_library_id) if old_library_id else None
        target = self._master_path(imported)
        target.parent.mkdir(parents=True, exist_ok=True)
        source = Path(library_track.file_path)
        backup: Path | None = None
        if source.resolve() != target.resolve():
            if target.exists():
                backup = target.with_name(f".{target.name}.{uuid4().hex}.old")
                os.replace(target, backup)
            os.replace(source, target)
        updated = replace(
            library_track,
            title=f"{imported.artist} - {imported.title}",
            channel=imported.artist,
            duration_seconds=(imported.duration_ms // 1000) if imported.duration_ms else library_track.duration_seconds,
            file_path=str(target),
            file_size_bytes=target.stat().st_size,
        )
        self._library.save(updated)
        self._repository.complete_job(job.id, updated.id)
        self.rebuild_track_projections(imported.track_key)
        if old_track is not None and old_track.id != updated.id:
            self._library.remove(old_track.id)
            old_path = Path(old_track.file_path)
            if old_path != target and old_path.is_file():
                old_path.unlink(missing_ok=True)
        if backup is not None:
            backup.unlink(missing_ok=True)
        return updated

    def rebuild_all_projections(self) -> None:
        for playlist in self._repository.list_playlists():
            self.rebuild_playlist_projection(playlist.id)

    def rebuild_track_projections(self, track_key: str) -> None:
        for playlist in self._repository.list_playlists():
            if any(entry.track.track_key == track_key for entry in self._repository.list_entries(playlist.id)):
                self.rebuild_playlist_projection(playlist.id)

    def rebuild_playlist_projection(self, playlist_id: str) -> None:
        playlist = self._require_playlist(playlist_id)
        folder = self._playlist_dir(playlist)
        folder.mkdir(parents=True, exist_ok=True)
        entries = self._repository.list_entries(playlist_id)
        expected: set[Path] = set()
        m3u_lines = ["#EXTM3U"]
        errors: list[tuple[str, str, str]] = []
        used_names: set[str] = set()
        for entry in entries:
            if entry.item.state is PlaylistTrackState.FAILED:
                errors.append((entry.track.artist, entry.track.title, entry.item.error_message or "Error"))
            if not entry.track.library_track_id:
                continue
            local = self._library.get(entry.track.library_track_id)
            if local is None or not Path(local.file_path).is_file():
                continue
            stem = MediaFiles.safe_stem(f"{entry.track.artist} - {entry.track.title}")
            name = f"{stem}.mp3"
            if name.casefold() in used_names:
                name = f"{stem} [{_short_key(entry.track.track_key)}].mp3"
            used_names.add(name.casefold())
            link = folder / name
            expected.add(link)
            source = Path(local.file_path)
            if not link.exists() or not _same_file(link, source):
                link.unlink(missing_ok=True)
                try:
                    os.link(source, link)
                except OSError:
                    # Filesystems without hard links still get an ordered playlist file.
                    pass
            m3u_lines.append(name if link.exists() else os.path.relpath(source, folder))
        for candidate in folder.glob("*.mp3"):
            if candidate not in expected:
                candidate.unlink(missing_ok=True)
        (folder / "playlist.m3u8").write_text("\n".join(m3u_lines) + "\n", encoding="utf-8")
        error_path = folder / "errores.csv"
        if errors:
            with error_path.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(("Artista", "Canción", "Error"))
                writer.writerows(errors)
        else:
            error_path.unlink(missing_ok=True)

    def _find(self, entry: PlaylistEntry):
        query = self._matcher.query(entry.track.artist, entry.track.title)
        # Most songs should be resolved from a small, cheap first page. Only
        # widen the candidate set when that page has no trustworthy match.
        results = self._search.search(query, 5)
        decision = self._matcher.choose(
            entry.track.artist, entry.track.title, entry.track.duration_ms, results
        )
        if decision.accepted:
            return decision
        expanded = self._search.search(query, 20)
        return self._matcher.choose(
            entry.track.artist, entry.track.title, entry.track.duration_ms, expanded
        )

    def _track_for_job(self, job_id: str) -> SpotifyTrack | None:
        with self._repository.database.connection() as connection:
            row = connection.execute(
                "SELECT track_key FROM spotify_tracks WHERE current_job_id = ?", (job_id,)
            ).fetchone()
        return None if row is None else self._repository.get_track(row["track_key"])

    def _master_path(self, track: SpotifyTrack) -> Path:
        root = Path(self._settings_getter().download_dir).expanduser()
        return root / "Audio" / _short_key(track.track_key, 16) / f"{MediaFiles.safe_stem(f'{track.artist} - {track.title}')}.mp3"

    def _playlist_dir(self, playlist: Playlist) -> Path:
        root = Path(self._settings_getter().download_dir).expanduser()
        return root / "Playlists" / MediaFiles.safe_stem(playlist.name, max_length=120)

    def _require_playlist(self, playlist_id: str) -> Playlist:
        playlist = self._repository.get(playlist_id)
        if playlist is None:
            raise invalid_input("La playlist no existe.")
        return playlist

    @staticmethod
    def _playlist_view(playlist: Playlist) -> dict[str, Any]:
        return asdict(playlist)

    @staticmethod
    def _entry_view(entry: PlaylistEntry) -> dict[str, Any]:
        return {
            "track_key": entry.track.track_key,
            "title": entry.track.title,
            "artist": entry.track.artist,
            "album": entry.track.album,
            "duration_ms": entry.track.duration_ms,
            "status": entry.item.state.value,
            "error_message": entry.item.error_message,
            "library_track_id": entry.track.library_track_id,
        }


def _track_key(uri: str, artist: str, title: str, duration_ms: int | None) -> str:
    if uri.strip():
        # Spotify IDs use a case-sensitive base62 alphabet.
        return uri.strip()
    raw = f"{artist.casefold()}\0{title.casefold()}\0{duration_ms or ''}".encode("utf-8")
    return "metadata:" + sha1(raw).hexdigest()


def _short_key(value: str, length: int = 8) -> str:
    if value.casefold().startswith("spotify:track:"):
        value = value.rsplit(":", 1)[-1]
    safe = "".join(char for char in value if char.isalnum())
    return (safe or sha1(value.encode("utf-8")).hexdigest())[:length]


def _same_file(first: Path, second: Path) -> bool:
    try:
        return os.path.samefile(first, second)
    except OSError:
        return False
