"""Personal HTTP API used by the iPhone PWA.

The server binds to loopback by default. Expose it through a private HTTPS
transport such as Tailscale Serve; do not forward the port on the router.
Every API request requires the persistent bearer token printed at startup.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from enum import Enum
import hmac
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import mimetypes
from pathlib import Path
import secrets
import sys
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

from ytmp3studio.backend.adapters.ffmpeg_adapter import FfmpegAdapter
from ytmp3studio.backend.adapters.media_files import MediaFiles
from ytmp3studio.backend.adapters.ytdlp_adapter import YtDlpAdapter
from ytmp3studio.backend.logging_config import configure_logging, user_data_dir
from ytmp3studio.backend.queue_service import QueueService
from ytmp3studio.backend.search_service import SearchService
from ytmp3studio.domain.errors import AppError, ErrorCode
from ytmp3studio.domain.models import LibraryTrack
from ytmp3studio.persistence.database import Database
from ytmp3studio.persistence.repositories import (
    DownloadJobRepository,
    HistoryRepository,
    LibraryRepository,
    SettingsRepository,
)


logger = logging.getLogger("ytmp3studio.mobile_server")
DEFAULT_ORIGIN = "https://gerardferri.github.io"
MAX_BODY_BYTES = 64 * 1024


class MobileBackend:
    """Qt-free composition root for search, queue and library access."""

    def __init__(self, database_path: str | Path | None = None) -> None:
        self.database = Database(database_path or user_data_dir() / "ytmp3studio.db")
        self.database.migrate()
        self.jobs = DownloadJobRepository(self.database)
        self.library = LibraryRepository(self.database)
        self.settings = SettingsRepository(self.database)
        self.history = HistoryRepository(self.database)
        ffmpeg = FfmpegAdapter()
        self.provider = YtDlpAdapter(ffmpeg=ffmpeg, media_files=MediaFiles())
        self.search_service = SearchService(self.provider)
        self.queue = QueueService(
            self.jobs,
            self.library,
            self.history,
            self.provider,
            self.settings.get,
        )
        self.queue.start(recover=True)

    def search(self, query: str, limit: int) -> list[dict[str, Any]]:
        return [_jsonable(result) for result in self.search_service.search(query, limit)]

    def enqueue(self, video_id: str, quality_kbps: int | None) -> list[dict[str, Any]]:
        return [_jsonable(job) for job in self.queue.enqueue([video_id], quality_kbps)]

    def queue_snapshot(self) -> list[dict[str, Any]]:
        library, _total = self.library.list("", limit=5000, offset=0)
        track_by_job = {track.job_id: track.id for track in library if track.job_id}
        result: list[dict[str, Any]] = []
        for job in self.queue.snapshot():
            item = _jsonable(job)
            item["track_id"] = track_by_job.get(job.id)
            result.append(item)
        return result

    def get_track(self, track_id: str) -> LibraryTrack | None:
        return self.library.get(track_id)

    def close(self) -> None:
        self.queue.shutdown()
        self.database.close()


class MobileApiServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        backend: MobileBackend,
        token: str,
        allowed_origins: set[str],
    ) -> None:
        self.backend = backend
        self.token = token
        self.allowed_origins = {origin.rstrip("/") for origin in allowed_origins}
        super().__init__(address, MobileRequestHandler)

    def handle_error(self, request: Any, client_address: tuple[str, int]) -> None:
        error = sys.exc_info()[1]
        if isinstance(error, (BrokenPipeError, ConnectionResetError)):
            logger.debug("Mobile client disconnected early: %s", client_address[0])
            return
        super().handle_error(request, client_address)


class MobileRequestHandler(BaseHTTPRequestHandler):
    server: MobileApiServer
    protocol_version = "HTTP/1.1"

    def do_OPTIONS(self) -> None:  # noqa: N802
        if not self._origin_allowed():
            self._json_error(HTTPStatus.FORBIDDEN, "ORIGIN_DENIED", "Origen no permitido.")
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if not self._authorize():
            return
        parsed = urlsplit(self.path)
        try:
            if parsed.path == "/api/health":
                self._json(HTTPStatus.OK, {"ok": True, "name": "YT-MP3 Studio PC"})
                return
            if parsed.path == "/api/search":
                params = parse_qs(parsed.query)
                query = params.get("q", [""])[0]
                limit = min(25, max(1, int(params.get("limit", ["12"])[0])))
                self._json(HTTPStatus.OK, {"results": self.server.backend.search(query, limit)})
                return
            if parsed.path == "/api/jobs":
                self._json(HTTPStatus.OK, {"jobs": self.server.backend.queue_snapshot()})
                return
            if parsed.path.startswith("/api/tracks/") and parsed.path.endswith("/audio"):
                track_id = parsed.path.removeprefix("/api/tracks/").removesuffix("/audio").strip("/")
                self._send_audio(track_id)
                return
            self._json_error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Ruta no encontrada.")
        except ValueError as exc:
            self._json_error(HTTPStatus.BAD_REQUEST, "INVALID_INPUT", str(exc))
        except AppError as exc:
            self._app_error(exc)
        except Exception as exc:  # pragma: no cover
            logger.exception("Unhandled mobile API error")
            self._json_error(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                ErrorCode.INTERNAL_ERROR.value,
                "Se produjo un error interno en el PC.",
                detail=f"{type(exc).__name__}: {exc}",
            )

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorize():
            return
        parsed = urlsplit(self.path)
        try:
            if parsed.path != "/api/jobs":
                self._json_error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Ruta no encontrada.")
                return
            payload = self._read_json()
            video_id = str(payload.get("video_id", "")).strip()
            quality_value = payload.get("quality_kbps")
            quality = None if quality_value in (None, "") else int(quality_value)
            self._json(HTTPStatus.ACCEPTED, {"jobs": self.server.backend.enqueue(video_id, quality)})
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            self._json_error(HTTPStatus.BAD_REQUEST, "INVALID_INPUT", "Petici\u00f3n no v\u00e1lida.", detail=str(exc))
        except AppError as exc:
            self._app_error(exc)
        except Exception as exc:  # pragma: no cover
            logger.exception("Unhandled mobile API error")
            self._json_error(HTTPStatus.INTERNAL_SERVER_ERROR, ErrorCode.INTERNAL_ERROR.value, "Se produjo un error interno en el PC.")

    def _authorize(self) -> bool:
        if not self._origin_allowed():
            self._json_error(HTTPStatus.FORBIDDEN, "ORIGIN_DENIED", "Origen no permitido.")
            return False
        header = self.headers.get("Authorization", "")
        supplied = header.removeprefix("Bearer ").strip() if header.startswith("Bearer ") else ""
        if not supplied or not hmac.compare_digest(supplied, self.server.token):
            self._json_error(HTTPStatus.UNAUTHORIZED, "UNAUTHORIZED", "Clave del servidor incorrecta.")
            return False
        return True

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        normalized = origin.rstrip("/")
        if normalized in self.server.allowed_origins:
            return True
        return normalized.startswith("http://localhost:") or normalized.startswith("http://127.0.0.1:")

    def _cors_headers(self) -> None:
        origin = self.headers.get("Origin")
        if origin and self._origin_allowed():
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Cache-Control", "no-store")

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Content-Length no v\u00e1lido") from exc
        if length <= 0 or length > MAX_BODY_BYTES:
            raise ValueError("El cuerpo de la petici\u00f3n est\u00e1 vac\u00edo o es demasiado grande.")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Se esperaba un objeto JSON.")
        return payload

    def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self._cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _json_error(
        self,
        status: HTTPStatus,
        code: str,
        message: str,
        *,
        detail: str | None = None,
    ) -> None:
        error: dict[str, Any] = {"code": code, "message": message}
        if detail:
            error["detail"] = detail
        self._json(status, {"error": error})

    def _app_error(self, error: AppError) -> None:
        code = error.code.value if isinstance(error.code, Enum) else str(error.code)
        status = HTTPStatus.BAD_REQUEST if code == ErrorCode.INVALID_INPUT.value else HTTPStatus.SERVICE_UNAVAILABLE
        self._json_error(status, code, error.user_message, detail=error.suggested_action)

    def _send_audio(self, track_id: str) -> None:
        track = self.server.backend.get_track(track_id)
        if track is None:
            self._json_error(HTTPStatus.NOT_FOUND, "TRACK_NOT_FOUND", "La pista no existe.")
            return
        path = Path(track.file_path)
        if not path.is_file():
            self._json_error(HTTPStatus.NOT_FOUND, "FILE_NOT_FOUND", "El MP3 ya no est\u00e1 en el PC.")
            return
        size = path.stat().st_size
        start, end, partial = _parse_range(self.headers.get("Range"), size)
        length = end - start + 1
        self.send_response(HTTPStatus.PARTIAL_CONTENT if partial else HTTPStatus.OK)
        self._cors_headers()
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "audio/mpeg")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        self.send_header("Content-Disposition", f"inline; filename*=UTF-8''{quote(path.name)}")
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with path.open("rb") as audio:
            audio.seek(start)
            remaining = length
            while remaining:
                chunk = audio.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def log_message(self, format_string: str, *args: Any) -> None:
        logger.info("mobile_api client=%s %s", self.client_address[0], format_string % args)


def _parse_range(header: str | None, size: int) -> tuple[int, int, bool]:
    if not header:
        return 0, max(0, size - 1), False
    if not header.startswith("bytes=") or "," in header:
        raise AppError(ErrorCode.INVALID_INPUT, "Rango de audio no v\u00e1lido.")
    raw_start, separator, raw_end = header[6:].partition("-")
    if not separator:
        raise AppError(ErrorCode.INVALID_INPUT, "Rango de audio no v\u00e1lido.")
    if raw_start:
        start = int(raw_start)
        end = int(raw_end) if raw_end else size - 1
    else:
        suffix = int(raw_end)
        start, end = max(0, size - suffix), size - 1
    if size <= 0 or start < 0 or end < start or start >= size:
        raise AppError(ErrorCode.INVALID_INPUT, "Rango de audio fuera del archivo.")
    return start, min(end, size - 1), True


def _jsonable(value: Any) -> dict[str, Any]:
    raw = asdict(value)
    return {key: item.value if isinstance(item, Enum) else item for key, item in raw.items()}


def _token_path() -> Path:
    return user_data_dir() / "mobile-server-token.txt"


def load_or_create_token(explicit: str | None = None) -> str:
    if explicit:
        if len(explicit) < 24:
            raise ValueError("La clave debe tener al menos 24 caracteres.")
        return explicit
    path = _token_path()
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    path.write_text(token, encoding="utf-8")
    return token


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Servidor personal para la PWA de YT-MP3 Studio")
    parser.add_argument("--host", default="127.0.0.1", help="Interfaz local (por defecto: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8766, help="Puerto local (por defecto: 8766)")
    parser.add_argument("--token", help="Clave fija; si se omite se genera y guarda una segura")
    parser.add_argument("--allow-origin", action="append", default=[], help="Origen HTTPS adicional permitido")
    parser.add_argument("--database", type=Path, help="Base de datos alternativa para pruebas")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging()
    token = load_or_create_token(args.token)
    backend = MobileBackend(args.database)
    server = MobileApiServer((args.host, args.port), backend, token, {DEFAULT_ORIGIN, *args.allow_origin})
    print("YT-MP3 Studio para iPhone")
    print(f"Servidor local: http://{args.host}:{args.port}")
    print(f"Clave: {token}")
    print("Mant\u00e9n esta ventana abierta. Pulsa Ctrl+C para detener el servidor.")

    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        backend.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
