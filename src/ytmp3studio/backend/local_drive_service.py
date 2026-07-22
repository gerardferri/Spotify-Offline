"""Google Drive for desktop integration through its locally mounted folder."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
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

    def is_connected(self) -> bool:
        return self.configured

    def ensure_downloads_folder(self) -> Path:
        if not self.configured:
            raise RuntimeError("Google Drive para ordenador no está disponible.")
        self.downloads_root.mkdir(parents=True, exist_ok=True)
        return self.downloads_root

    def scan_library(self) -> DriveLibrarySnapshot:
        if not self.configured:
            raise RuntimeError("Google Drive para ordenador no está disponible.")
        self.music_root.mkdir(parents=True, exist_ok=True)
        self.ensure_downloads_folder()
        root_id = _stable_id(self.music_root)
        root = DriveFolder(root_id, APP_FOLDER_NAME, "root", _modified(self.music_root))
        folders: list[DriveFolder] = []
        tracks: list[DriveTrack] = []
        folder_ids = {self.music_root: root_id}

        for current, directory_names, file_names in os.walk(self.music_root):
            current_path = Path(current)
            directory_names[:] = sorted(
                (name for name in directory_names if not name.startswith(".")),
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
