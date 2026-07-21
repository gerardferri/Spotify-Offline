from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ytmp3studio.domain.models import DependencyItem, DependencyState, DependencyStatus, Settings
from ytmp3studio.backend.adapters.media_files import MediaFiles


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class DependencyService:
    def __init__(self, ytdlp: Any, ffmpeg: Any) -> None:
        self._ytdlp = ytdlp
        self._ffmpeg = ffmpeg

    def check(self, settings: Settings) -> DependencyStatus:
        ytdlp = self._safe_check(self._ytdlp, "yt-dlp")
        ffmpeg = self._safe_check(self._ffmpeg, "ffmpeg")
        path = Path(settings.download_dir)
        writable = False
        try:
            MediaFiles.ensure_writable_directory(path)
            writable = True
        except OSError:
            writable = False
        return DependencyStatus(ytdlp, ffmpeg, writable, str(path), utc_now())

    @staticmethod
    def _safe_check(adapter: Any, name: str) -> DependencyItem:
        try:
            result = adapter.check()
            if isinstance(result, DependencyItem):
                return result
            if isinstance(result, dict):
                return DependencyItem(name=name, **result)
            return DependencyItem(name, DependencyState.ERROR, message="Diagnóstico no válido")
        except ModuleNotFoundError as exc:
            return DependencyItem(name, DependencyState.MISSING, message=str(exc))
        except Exception as exc:
            return DependencyItem(name, DependencyState.ERROR, message=f"{type(exc).__name__}: {exc}")
