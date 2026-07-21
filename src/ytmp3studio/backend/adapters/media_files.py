"""Safe naming, atomic publication and job-scoped temporary files."""

from __future__ import annotations

import errno
import os
from pathlib import Path
import re
import shutil
from threading import Lock
import unicodedata
from uuid import UUID, uuid4


_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class MediaFiles:
    TEMP_ROOT_NAME = ".ytmp3studio-tmp"
    _publication_lock = Lock()

    @staticmethod
    def safe_stem(title: str, *, max_length: int = 180) -> str:
        normalized = unicodedata.normalize("NFC", str(title or ""))
        normalized = _INVALID.sub("_", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip(" .")
        if not normalized:
            normalized = "Sin título"
        if normalized.upper() in _WINDOWS_RESERVED:
            normalized = f"_{normalized}"
        normalized = normalized[:max_length].rstrip(" .") or "Sin título"
        return normalized

    @classmethod
    def unique_destination(cls, output_dir: str | Path, title: str, suffix: str = ".mp3") -> Path:
        directory = Path(output_dir)
        stem = cls.safe_stem(title)
        suffix = suffix if suffix.startswith(".") else f".{suffix}"
        candidate = directory / f"{stem}{suffix}"
        number = 2
        while candidate.exists():
            candidate = directory / f"{stem} ({number}){suffix}"
            number += 1
        return candidate

    @classmethod
    def job_temp_dir(cls, output_dir: str | Path, job_id: str) -> Path:
        # Canonical UUIDs prevent traversal and make ownership auditable.
        canonical = str(UUID(str(job_id)))
        return Path(output_dir) / cls.TEMP_ROOT_NAME / canonical

    @classmethod
    def ensure_job_temp_dir(cls, output_dir: str | Path, job_id: str) -> Path:
        temp_dir = cls.job_temp_dir(output_dir, job_id)
        temp_dir.mkdir(parents=True, exist_ok=True)
        return temp_dir

    @classmethod
    def cleanup_job_temp(cls, output_dir: str | Path, job_id: str) -> bool:
        temp_root = (Path(output_dir) / cls.TEMP_ROOT_NAME).resolve()
        target = cls.job_temp_dir(output_dir, job_id).resolve()
        if target.parent != temp_root:
            raise ValueError("El temporal no pertenece al directorio administrado")
        if not target.exists():
            return False
        shutil.rmtree(target)
        try:
            temp_root.rmdir()  # only removes an empty managed root
        except OSError:
            pass
        return True

    @classmethod
    def cleanup_temp(cls, temp_dir: str | Path) -> bool:
        """Remove exactly one managed UUID directory, never its siblings.

        This accepts the persisted ``DownloadJob.temp_dir`` value used by the
        queue service, while retaining the same containment guarantees as
        :meth:`cleanup_job_temp`.
        """
        target = Path(temp_dir).resolve()
        if target.parent.name != cls.TEMP_ROOT_NAME:
            raise ValueError("El temporal no pertenece al directorio administrado")
        try:
            UUID(target.name)
        except (ValueError, AttributeError) as exc:
            raise ValueError("El temporal no tiene un identificador de trabajo válido") from exc
        if not target.exists():
            return False
        if not target.is_dir():
            raise ValueError("La ruta temporal administrada no es un directorio")
        shutil.rmtree(target)
        try:
            target.parent.rmdir()
        except OSError:
            pass
        return True

    @staticmethod
    def publish_atomic(temporary_file: str | Path, destination: str | Path) -> Path:
        source = Path(temporary_file)
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            source.replace(target)
        except OSError as exc:
            if exc.errno == errno.EXDEV:
                raise OSError("El temporal y el destino deben estar en el mismo volumen") from exc
            raise
        return target

    @classmethod
    def publish_unique(cls, temporary_file: str | Path, output_dir: str | Path, title: str) -> Path:
        """Choose a collision-free name and publish it as one critical section."""
        with cls._publication_lock:
            destination = cls.unique_destination(output_dir, title)
            return cls.publish_atomic(temporary_file, destination)

    @staticmethod
    def ensure_writable_directory(directory: str | Path) -> Path:
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".ytmp3studio-write-{os.getpid()}-{uuid4().hex}.tmp"
        try:
            with probe.open("xb"):
                pass
        finally:
            probe.unlink(missing_ok=True)
        return path
