"""Google Drive for desktop integration through its locally mounted folder."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import hashlib
import logging
import os
from pathlib import Path
import zipfile
from ytmp3studio.backend.google_drive_service import (
    APP_FOLDER_NAME,
    DriveFolder,
    DriveLibrarySnapshot,
    DriveTrack,
)


_AUDIO_EXTENSIONS = frozenset(
    {".aac", ".flac", ".m4a", ".mp3", ".oga", ".ogg", ".opus", ".wav", ".webm"}
)
_MY_DRIVE_NAMES = ("Mi unidad", "My Drive")
DOWNLOADS_FOLDER_NAME = "Descargas"
EXPORTS_FOLDER_NAME = "Exportaciones ZIP"
_INVALID_FOLDER_CHARACTERS = frozenset('<>:"|?*')
_MAX_FOLDER_NAME_LENGTH = 100
_RESERVED_WINDOWS_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{number}" for number in range(1, 10)}
    | {f"LPT{number}" for number in range(1, 10)}
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LocalDriveLocation:
    mount: Path
    my_drive: Path
    music_root: Path


class LocalGoogleDriveService:
    """Scan a DriveFS mount and expose the same DTOs as the Drive API service."""

    def __init__(self, music_root: str | Path) -> None:
        self.music_root = Path(music_root)

    @property
    def configured(self) -> bool:
        return self.music_root.parent.is_dir()

    @property
    def downloads_root(self) -> Path:
        """Subfolder that receives finished MP3 files so they become a playlist."""

        return self.music_root / DOWNLOADS_FOLDER_NAME

    @property
    def exports_root(self) -> Path:
        """Folder that stores downloadable playlist archives."""

        return self.music_root / EXPORTS_FOLDER_NAME

    def is_connected(self) -> bool:
        return self.configured

    def ensure_downloads_folder(self) -> Path:
        if not self.configured:
            raise RuntimeError("Google Drive para ordenador no está disponible.")
        self.downloads_root.mkdir(parents=True, exist_ok=True)
        return self.downloads_root

    def list_folders(self) -> list[str]:
        """List visible folders directly below the music root."""

        if not self.music_root.is_dir():
            return []
        return sorted(
            (
                path.name
                for path in self.music_root.iterdir()
                if path.is_dir()
                and not path.name.startswith(".")
                and path.name != EXPORTS_FOLDER_NAME
            ),
            key=str.casefold,
        )

    def refresh_zip_exports(self) -> list[str]:
        """Create or update archives for direct playlist folders."""

        updated: list[str] = []
        try:
            folders = sorted(
                (
                    path
                    for path in self.music_root.iterdir()
                    if path.is_dir()
                    and not path.name.startswith(".")
                    and path.name != EXPORTS_FOLDER_NAME
                ),
                key=lambda path: path.name.casefold(),
            )
        except OSError:
            logger.exception("No se han podido leer las carpetas para exportar ZIP.")
            return updated

        for folder in folders:
            zip_path = self.exports_root / f"{folder.name}.zip"
            temporary_path = zip_path.with_suffix(".zip.tmp")
            try:
                audio_files = sorted(
                    (
                        path
                        for path in folder.iterdir()
                        if path.is_file()
                        and path.suffix.casefold() in _AUDIO_EXTENSIONS
                    ),
                    key=lambda path: path.name.casefold(),
                )
                if not audio_files:
                    if zip_path.exists():
                        zip_path.unlink()
                    continue

                stale = not zip_path.is_file()
                if not stale:
                    zip_mtime = zip_path.stat().st_mtime
                    try:
                        with zipfile.ZipFile(zip_path) as archive:
                            audio_entry_count = sum(
                                Path(info.filename).suffix.casefold()
                                in _AUDIO_EXTENSIONS
                                for info in archive.infolist()
                            )
                    except (OSError, zipfile.BadZipFile):
                        stale = True
                    else:
                        stale = audio_entry_count != len(audio_files) or any(
                            path.stat().st_mtime > zip_mtime for path in audio_files
                        )
                if not stale:
                    continue

                self.exports_root.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(
                    temporary_path,
                    "w",
                    compression=zipfile.ZIP_DEFLATED,
                ) as archive:
                    for path in audio_files:
                        archive.write(path, arcname=path.name)
                os.replace(temporary_path, zip_path)
                updated.append(folder.name)
            except OSError:
                logger.exception(
                    "No se ha podido actualizar la exportación ZIP de %s.",
                    folder.name,
                )
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    logger.exception(
                        "No se ha podido eliminar el ZIP temporal de %s.",
                        folder.name,
                    )

        return updated

    def zip_path_for(self, name: str) -> Path | None:
        """Return an existing archive for a safe playlist name."""

        try:
            folder_name = _validate_folder_name(name)
        except ValueError:
            return None
        if folder_name == EXPORTS_FOLDER_NAME:
            return None
        zip_path = self.exports_root / f"{folder_name}.zip"
        try:
            return zip_path if zip_path.is_file() else None
        except OSError:
            return None

    def resolve_folder(self, name: str | None) -> Path:
        """Create and resolve a safe destination below the music root."""

        if name is None or not name.strip():
            target = self.downloads_root
        else:
            folder_name = _validate_folder_name(name)
            if folder_name == EXPORTS_FOLDER_NAME:
                raise ValueError(
                    "La carpeta Exportaciones ZIP está reservada. Elige otro nombre."
                )
            target = self.music_root / folder_name

        resolved_root = self.music_root.resolve()
        resolved_target = target.resolve()
        if resolved_target.parent != resolved_root:
            raise ValueError(
                "La carpeta debe estar dentro de la carpeta musical de Google Drive. "
                "Elige un nombre de subcarpeta simple."
            )
        try:
            resolved_target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ValueError(
                "No se ha podido crear esa carpeta en Google Drive. "
                "Prueba con otro nombre más sencillo."
            ) from exc
        return resolved_target

    def scan_library(self) -> DriveLibrarySnapshot:
        if not self.configured:
            raise RuntimeError("Google Drive para ordenador no está disponible.")
        self.music_root.mkdir(parents=True, exist_ok=True)
        self.ensure_downloads_folder()
        try:
            self.refresh_zip_exports()
        except Exception:
            logger.exception("No se han podido actualizar las exportaciones ZIP.")
        root_id = _stable_id(self.music_root)
        root = DriveFolder(root_id, APP_FOLDER_NAME, "root", _modified(self.music_root))
        folders: list[DriveFolder] = []
        tracks: list[DriveTrack] = []
        folder_ids = {self.music_root: root_id}

        for current, directory_names, file_names in os.walk(self.music_root):
            current_path = Path(current)
            directory_names[:] = sorted(
                (
                    name
                    for name in directory_names
                    if not name.startswith(".")
                    and not (
                        current_path == self.music_root
                        and name == EXPORTS_FOLDER_NAME
                    )
                ),
                key=str.casefold,
            )
            parent_id = folder_ids[current_path]
            for name in directory_names:
                path = current_path / name
                folder_id = _stable_id(path)
                folder_ids[path] = folder_id
                folders.append(
                    DriveFolder(folder_id, name, parent_id, _modified(path))
                )
            for name in sorted(file_names, key=str.casefold):
                path = current_path / name
                if path.suffix.casefold() not in _AUDIO_EXTENSIONS:
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                tracks.append(
                    DriveTrack(
                        id=_stable_id(path),
                        name=name,
                        folder_id=parent_id,
                        mime_type=_mime_type(path.suffix),
                        size_bytes=stat.st_size,
                        modified_time=_modified(path),
                        checksum=None,
                        local_path=str(path),
                    )
                )

        token_source = "\n".join(
            f"{track.id}:{track.size_bytes}:{track.modified_time}" for track in tracks
        )
        changes_token = hashlib.sha256(token_source.encode("utf-8")).hexdigest()
        return DriveLibrarySnapshot(root, tuple(folders), tuple(tracks), changes_token)


def _validate_folder_name(name: str) -> str:
    """Validate and normalize a direct playlist folder name."""

    folder_name = name.strip()
    reserved_name = folder_name.split(".", 1)[0].upper()
    invalid = (
        not folder_name
        or "/" in folder_name
        or "\\" in folder_name
        or folder_name in {".", ".."}
        or Path(folder_name).is_absolute()
        or reserved_name in _RESERVED_WINDOWS_NAMES
        or any(char in _INVALID_FOLDER_CHARACTERS for char in folder_name)
        # Control characters and overlong names reach the filesystem as an
        # OSError, which would surface as an opaque server error.
        or any(ord(char) < 32 for char in folder_name)
        or len(folder_name) > _MAX_FOLDER_NAME_LENGTH
    )
    if invalid:
        raise ValueError(
            "El nombre de la carpeta no es válido. Usa un nombre simple de "
            f"hasta {_MAX_FOLDER_NAME_LENGTH} caracteres, sin rutas, sin "
            "nombres reservados y sin los caracteres < > : \" | ? *."
        )
    return folder_name


def detect_google_drive() -> LocalDriveLocation | None:
    """Find a mounted Google Drive volume without reading account internals."""

    override = os.environ.get("YTMP3_GOOGLE_DRIVE_ROOT")
    if override:
        root = Path(override).expanduser()
        return LocalDriveLocation(root.parent, root.parent, root)
    if os.name != "nt":
        return None
    for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
        mount = Path(f"{letter}:\\")
        if _volume_label(mount).casefold() != "google drive":
            continue
        for name in _MY_DRIVE_NAMES:
            my_drive = mount / name
            if my_drive.is_dir():
                return LocalDriveLocation(mount, my_drive, my_drive / APP_FOLDER_NAME)
    return None


def _stable_id(path: Path) -> str:
    try:
        stat = path.stat()
        identity = f"{stat.st_dev}:{stat.st_ino}"
        if stat.st_ino:
            return "local-" + hashlib.sha256(identity.encode("ascii")).hexdigest()[:24]
    except OSError:
        pass
    normalized = str(path.resolve()).casefold()
    return "local-" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def _modified(path: Path) -> str | None:
    try:
        from datetime import datetime, timezone

        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat().replace("+00:00", "Z")
    except OSError:
        return None


def _mime_type(extension: str) -> str:
    return {
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".aac": "audio/aac",
        ".flac": "audio/flac",
        ".wav": "audio/wav",
        ".ogg": "audio/ogg",
        ".oga": "audio/ogg",
        ".opus": "audio/opus",
        ".webm": "audio/webm",
    }.get(extension.casefold(), "application/octet-stream")


def _volume_label(root: Path) -> str:
    if os.name != "nt":
        return ""
    volume = ctypes.create_unicode_buffer(261)
    filesystem = ctypes.create_unicode_buffer(261)
    serial = ctypes.c_ulong()
    maximum_component = ctypes.c_ulong()
    flags = ctypes.c_ulong()
    try:
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            str(root),
            volume,
            len(volume),
            ctypes.byref(serial),
            ctypes.byref(maximum_component),
            ctypes.byref(flags),
            filesystem,
            len(filesystem),
        )
    except (AttributeError, OSError):
        return ""
    return volume.value if ok else ""
