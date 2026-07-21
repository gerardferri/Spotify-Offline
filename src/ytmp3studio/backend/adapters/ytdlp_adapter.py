"""Isolated integration with :mod:`yt_dlp`.

The module is deliberately importable when yt-dlp is not installed.  This is
important for the dependency diagnostics screen and for deterministic tests.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import importlib
import re
from typing import Any

from pathlib import Path
from threading import Event

from ytmp3studio.domain.errors import AppError, ErrorCode
from ytmp3studio.domain.models import (
    DependencyItem,
    DependencyState,
    DownloadJob,
    Progress,
    SearchResult,
)
from ytmp3studio.domain.ports import ProgressCallback

from .ffmpeg_adapter import FfmpegAdapter
from .media_files import MediaFiles


@dataclass(frozen=True, slots=True)
class YtDlpDiagnostic:
    available: bool
    version: str | None = None
    detail: str | None = None


class YtDlpAdapter:
    """Search and download adapter.

    ``ydl_factory`` is injectable so no unit test imports yt-dlp or reaches the
    network.  In production it defaults to ``yt_dlp.YoutubeDL``.
    """

    def __init__(
        self,
        ydl_factory: Callable[[dict[str, Any]], Any] | None = None,
        *,
        ffmpeg: FfmpegAdapter | None = None,
        media_files: MediaFiles | None = None,
    ) -> None:
        self._ydl_factory = ydl_factory
        self._ffmpeg = ffmpeg or FfmpegAdapter()
        self._media_files = media_files or MediaFiles()

    @staticmethod
    def normalize_search_entry(entry: Mapping[str, Any] | None) -> SearchResult | None:
        """Turn an incomplete yt-dlp entry into a domain result.

        Entries without a video id or a usable YouTube URL are discarded.  A
        malformed single entry never poisons the complete result page.
        """
        if not isinstance(entry, Mapping):
            return None
        raw_id = entry.get("id") or entry.get("video_id")
        video_id = str(raw_id).strip() if raw_id is not None else ""
        if not video_id:
            return None

        raw_url = entry.get("webpage_url") or entry.get("original_url") or entry.get("url")
        webpage_url = str(raw_url).strip() if raw_url is not None else ""
        if not webpage_url or not webpage_url.startswith(("http://", "https://")):
            # Flat playlist/search entries commonly expose only an id.
            webpage_url = f"https://www.youtube.com/watch?v={video_id}"

        title = _clean_text(entry.get("title")) or "Sin título"
        channel = (
            _clean_text(entry.get("channel"))
            or _clean_text(entry.get("uploader"))
            or _clean_text(entry.get("channel_id"))
            or "Canal desconocido"
        )
        duration = _non_negative_int(entry.get("duration"))
        thumbnail = _clean_text(entry.get("thumbnail")) or _last_thumbnail_url(entry.get("thumbnails"))
        live_status = (_clean_text(entry.get("live_status")) or "").lower()
        is_live = bool(entry.get("is_live")) or live_status in {
            "is_live",
            "is_upcoming",
            "post_live",
        }
        availability = _clean_text(entry.get("availability"))
        return SearchResult(
            video_id=video_id,
            webpage_url=webpage_url,
            title=title,
            channel=channel,
            duration_seconds=duration,
            thumbnail_url=thumbnail,
            availability=availability,
            is_live=is_live,
        )

    def search(self, query: str, limit: int = 12) -> list[SearchResult]:
        query = query.strip()
        if not query or not 1 <= limit <= 50:
            raise ValueError("query no puede estar vacía y limit debe estar entre 1 y 50")
        options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": "in_playlist",
            "noplaylist": True,
            "socket_timeout": 15,
        }
        try:
            with self._factory()(options) as ydl:
                payload = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
        except ModuleNotFoundError as exc:
            raise AppError(ErrorCode.YTDLP_MISSING, "yt-dlp no está instalado.", str(exc)) from exc
        except Exception as exc:  # external library exposes many exception subclasses
            mapped = _map_ytdlp_exception(exc)
            if mapped.code == ErrorCode.DOWNLOAD_FAILED:
                mapped = AppError(
                    ErrorCode.SEARCH_FAILED,
                    "No se pudo completar la búsqueda.",
                    mapped.technical_message,
                    mapped.recoverable,
                )
            raise mapped from exc

        entries = payload.get("entries", ()) if isinstance(payload, Mapping) else ()
        results: list[SearchResult] = []
        for entry in entries or ():
            try:
                normalized = self.normalize_search_entry(entry)
            except (TypeError, ValueError, OverflowError):
                normalized = None
            if normalized is not None:
                results.append(normalized)
        return results

    def resolve(self, video_id: str) -> SearchResult:
        video_id = video_id.strip()
        if not video_id:
            raise AppError(ErrorCode.INVALID_INPUT, "El identificador del vídeo no es válido.")
        source_url = f"https://www.youtube.com/watch?v={video_id}"
        options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
            "socket_timeout": 15,
        }
        try:
            with self._factory()(options) as ydl:
                payload = ydl.extract_info(source_url, download=False)
        except ModuleNotFoundError as exc:
            raise AppError(ErrorCode.YTDLP_MISSING, "yt-dlp no está instalado.", str(exc)) from exc
        except Exception as exc:
            raise _map_ytdlp_exception(exc) from exc
        result = self.normalize_search_entry(payload)
        if result is None:
            raise AppError(
                ErrorCode.VIDEO_UNAVAILABLE,
                "No se pudieron obtener los datos del vídeo.",
                f"yt-dlp devolvió metadatos incompletos para {video_id}",
            )
        if result.is_live:
            raise AppError(ErrorCode.LIVE_NOT_SUPPORTED, "Los directos no son compatibles.")
        return result

    def download(self, job: DownloadJob, progress: ProgressCallback, stop_event: Event) -> Path:
        """Download, convert and atomically publish one job's MP3."""
        if stop_event.is_set():
            raise AppError(ErrorCode.CANCELLED, "La descarga se ha detenido.", recoverable=True)
        temp_dir = Path(job.temp_dir).resolve()
        expected_temp_dir = self._media_files.job_temp_dir(job.output_dir, job.id).resolve()
        if temp_dir != expected_temp_dir:
            raise AppError(
                ErrorCode.INVALID_INPUT,
                "La ruta temporal del trabajo no es válida.",
                f"expected={expected_temp_dir} actual={temp_dir}",
            )
        temp_dir.mkdir(parents=True, exist_ok=True)
        template = str(temp_dir / "source.%(ext)s")

        def hook(status: dict[str, Any]) -> None:
            if stop_event.is_set():
                raise AppError(ErrorCode.CANCELLED, "La descarga se ha detenido.", recoverable=True)
            if status.get("status") not in {"downloading", "finished"}:
                return
            downloaded = _non_negative_int(status.get("downloaded_bytes"))
            total = _non_negative_int(status.get("total_bytes") or status.get("total_bytes_estimate"))
            percent = (downloaded * 100.0 / total) if downloaded is not None and total else None
            progress(Progress(
                job_id=job.id,
                phase="downloading",
                downloaded_bytes=downloaded,
                total_bytes=total,
                percent=percent,
                speed_bps=_non_negative_float(status.get("speed")),
                eta_seconds=_non_negative_int(status.get("eta")),
            ))

        result = self.download_audio(job.source_url, template, progress_hook=hook, stop_event=stop_event)
        if stop_event.is_set():
            raise AppError(ErrorCode.CANCELLED, "La descarga se ha detenido.", recoverable=True)
        source = self._downloaded_path(result, temp_dir)
        progress(Progress(job_id=job.id, phase="converting", percent=None))
        converted = temp_dir / "converted.tmp.mp3"
        self._ffmpeg.convert_to_mp3(
            source,
            converted,
            job.quality_kbps,
            stop_event=stop_event,
        )
        if stop_event.is_set():
            raise AppError(ErrorCode.CANCELLED, "La conversión se ha detenido.", recoverable=True)
        return self._media_files.publish_unique(converted, job.output_dir, job.title)

    def download_audio(
        self,
        source_url: str,
        output_template: str,
        *,
        progress_hook: Callable[[dict[str, Any]], None] | None = None,
        stop_event: Event | None = None,
    ) -> Mapping[str, Any]:
        """Download the best source audio, retaining yt-dlp ``.part`` files."""
        options: dict[str, Any] = {
            "format": "bestaudio/best",
            "outtmpl": output_template,
            "continuedl": True,
            "nopart": False,
            "noplaylist": True,
            "quiet": True,
            "socket_timeout": 15,
        }
        if progress_hook is not None:
            options["progress_hooks"] = [progress_hook]
        try:
            with self._factory()(options) as ydl:
                result = ydl.extract_info(source_url, download=True)
        except ModuleNotFoundError as exc:
            raise AppError(ErrorCode.YTDLP_MISSING, "yt-dlp no está instalado.", str(exc)) from exc
        except AppError:
            raise
        except Exception as exc:
            if stop_event is not None and stop_event.is_set():
                raise AppError(ErrorCode.CANCELLED, "La descarga se ha detenido.", recoverable=True) from exc
            raise _map_ytdlp_exception(exc) from exc
        return result if isinstance(result, Mapping) else {}

    @staticmethod
    def _downloaded_path(result: Mapping[str, Any], temp_dir: Path) -> Path:
        candidates: list[Any] = [result.get("filepath"), result.get("_filename")]
        requested = result.get("requested_downloads")
        if isinstance(requested, list):
            candidates.extend(
                item.get("filepath") for item in requested if isinstance(item, Mapping)
            )
        for candidate in candidates:
            if candidate and Path(str(candidate)).is_file():
                return Path(str(candidate))
        files = sorted(path for path in temp_dir.glob("source.*") if not path.name.endswith(".part"))
        if files:
            return files[0]
        raise AppError(
            ErrorCode.FILE_NOT_FOUND,
            "No se encontró el audio descargado.",
            f"No hay archivo fuente en {temp_dir}",
        )

    def diagnose(self) -> YtDlpDiagnostic:
        try:
            module = importlib.import_module("yt_dlp")
        except (ImportError, ModuleNotFoundError) as exc:
            return YtDlpDiagnostic(False, detail=str(exc))
        try:
            version_module = importlib.import_module("yt_dlp.version")
            version = getattr(version_module, "__version__", None) or getattr(module, "__version__", None)
            return YtDlpDiagnostic(True, str(version) if version else None)
        except Exception as exc:
            # An installed package remains operational even if its optional
            # version metadata cannot be read.
            version = getattr(module, "__version__", None)
            return YtDlpDiagnostic(True, str(version) if version else None, f"Versión desconocida: {exc}")

    def check(self) -> DependencyItem:
        """Return the domain diagnostic consumed by ``DependencyService``."""
        diagnostic = self.diagnose()
        return DependencyItem(
            name="yt-dlp",
            state=DependencyState.OK if diagnostic.available else DependencyState.MISSING,
            version=diagnostic.version,
            message=diagnostic.detail,
        )

    def _factory(self) -> Callable[[dict[str, Any]], Any]:
        if self._ydl_factory is not None:
            return self._ydl_factory
        module = importlib.import_module("yt_dlp")
        return module.YoutubeDL


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def _non_negative_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = int(float(value))
    except (TypeError, ValueError, OverflowError):
        return None
    return result if result >= 0 else None


def _last_thumbnail_url(value: Any) -> str | None:
    if not isinstance(value, (list, tuple)):
        return None
    for item in reversed(value):
        if isinstance(item, Mapping):
            url = _clean_text(item.get("url"))
            if url:
                return url
    return None


def _non_negative_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if result >= 0 else None


def _map_ytdlp_exception(exc: Exception) -> AppError:
    text = str(exc)
    lowered = text.lower()
    if any(marker in lowered for marker in ("sign in", "login", "age-restricted", "confirm your age")):
        return AppError(ErrorCode.AGE_OR_LOGIN_REQUIRED, "El vídeo requiere iniciar sesión o verificar la edad.", text)
    if any(marker in lowered for marker in ("private video", "video unavailable", "has been removed")):
        return AppError(ErrorCode.VIDEO_UNAVAILABLE, "El vídeo no está disponible.", text)
    if any(marker in lowered for marker in ("timed out", "timeout", "temporary failure", "http error 5")):
        return AppError(ErrorCode.NETWORK_ERROR, "No se pudo conectar con YouTube.", text, True)
    if any(marker in lowered for marker in ("no space left", "disk full", "not enough space")):
        return AppError(ErrorCode.DISK_FULL, "No hay espacio suficiente en el disco.", text)
    if any(marker in lowered for marker in ("permission denied", "access is denied")):
        return AppError(ErrorCode.PERMISSION_DENIED, "No hay permiso para escribir el archivo.", text)
    if any(marker in lowered for marker in ("update yt-dlp", "update to a newer version", "outdated")):
        return AppError(ErrorCode.YTDLP_OUTDATED, "yt-dlp necesita actualizarse.", text)
    return AppError(ErrorCode.DOWNLOAD_FAILED, "No se pudo descargar el audio.", text, False)
