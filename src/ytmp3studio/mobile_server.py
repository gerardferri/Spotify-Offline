"""Personal HTTP API and local web app for YT-MP3 Studio.

The server binds to loopback by default. Expose it through a private HTTPS
transport such as Tailscale Serve; do not forward the port on the router.
The iPhone API requires a persistent bearer token. ``--web`` also serves the
PWA on the same loopback-only address, so it can be used directly from a PC
browser without exposing a port or requiring a token in that browser.
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
from threading import Lock, Timer
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit
import webbrowser

from ytmp3studio.backend.adapters.ffmpeg_adapter import FfmpegAdapter
from ytmp3studio.backend.adapters.media_files import MediaFiles
from ytmp3studio.backend.adapters.ytdlp_adapter import YtDlpAdapter
from ytmp3studio.backend.logging_config import configure_logging, user_data_dir
from ytmp3studio.backend.google_drive_client import (
    DriveConfigurationError,
    GoogleApiError,
    GoogleDriveClient,
)
from ytmp3studio.backend.google_drive_service import GoogleDriveService
from ytmp3studio.backend.queue_service import QueueService
from ytmp3studio.backend.search_service import SearchService
from ytmp3studio.domain.errors import AppError, ErrorCode
from ytmp3studio.domain.models import LibraryTrack
from ytmp3studio.persistence.database import Database
from ytmp3studio.persistence.drive_repository import DriveRepository
from ytmp3studio.persistence.repositories import (
    DownloadJobRepository,
    HistoryRepository,
    LibraryRepository,
    SettingsRepository,
)


logger = logging.getLogger("ytmp3studio.mobile_server")
DEFAULT_ORIGIN = "https://gerardferri.github.io"
MAX_BODY_BYTES = 64 * 1024
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PWA_DIRECTORY = PROJECT_ROOT / "prototype"


class MobileBackend:
    """Qt-free composition root for search, queue and library access."""

    def __init__(
        self,
        database_path: str | Path | None = None,
        *,
        drive_redirect_uri: str = "http://127.0.0.1:8766/api/drive/callback",
        google_client_path: str | Path | None = None,
        drive_client: Any | None = None,
    ) -> None:
        self.database = Database(database_path or user_data_dir() / "ytmp3studio.db")
        self.database.migrate()
        self.jobs = DownloadJobRepository(self.database)
        self.library = LibraryRepository(self.database)
        self.settings = SettingsRepository(self.database)
        self.history = HistoryRepository(self.database)
        drive_data = user_data_dir()
        self.drive_client = drive_client or GoogleDriveClient(
            google_client_path or drive_data / "google-client-secret.json",
            drive_data / "google-drive-token.json",
            drive_redirect_uri,
        )
        self.drive_service = GoogleDriveService(self.drive_client, self.drive_client)
        self.drive_repository = DriveRepository(self.database)
        self._drive_sync_lock = Lock()
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

    def drive_status(self) -> dict[str, Any]:
        configured = bool(getattr(self.drive_client, "configured", True))
        connected = configured and self.drive_client.is_connected()
        status = self.drive_repository.status(connected=connected)
        status.update(
            {
                "configured": configured,
                "syncing": self._drive_sync_lock.locked(),
                "setup_required": None if configured else "google-client-secret.json",
            }
        )
        return status

    def drive_authorization_url(self) -> str:
        return self.drive_service.authorization_url()

    def complete_drive_authorization(self, code: str, state: str) -> dict[str, Any]:
        validator = getattr(self.drive_client, "validate_state", None)
        if validator is not None and not validator(state):
            raise ValueError("La respuesta de Google no coincide con la conexión iniciada.")
        connection = self.drive_service.connect(code)
        return self._sync_drive(connection.account_email, connection.account_name)

    def sync_drive(self) -> dict[str, Any]:
        if not self.drive_client.is_connected():
            raise ValueError("Conecta primero tu cuenta de Google Drive desde el PC.")
        connection = self.drive_service.connection_state()
        return self._sync_drive(connection.account_email, connection.account_name)

    def _sync_drive(self, account_email: str | None, account_name: str | None) -> dict[str, Any]:
        if not self._drive_sync_lock.acquire(blocking=False):
            raise ValueError("Google Drive ya se está sincronizando.")
        try:
            snapshot = self.drive_service.scan_library()
            return self.drive_repository.replace_snapshot(
                snapshot,
                account_email=account_email,
                account_name=account_name,
            )
        except Exception as exc:
            self.drive_repository.record_error(str(exc))
            raise
        finally:
            self._drive_sync_lock.release()

    def disconnect_drive(self) -> dict[str, Any]:
        self.drive_service.disconnect()
        self.drive_repository.clear()
        return self.drive_status()

    def drive_tracks(self, folder_id: str | None = None) -> list[dict[str, Any]]:
        return self.drive_repository.list_tracks(folder_id)

    def download_drive_track(self, file_id: str, range_header: str | None = None):
        if not any(track["file_id"] == file_id for track in self.drive_repository.list_tracks()):
            raise ValueError("La canción de Google Drive no existe en el catálogo.")
        return self.drive_client.download(file_id, range_header)

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
        *,
        static_dir: Path | None = None,
        allow_local_web_without_token: bool = False,
    ) -> None:
        self.backend = backend
        self.token = token
        self.allowed_origins = {origin.rstrip("/") for origin in allowed_origins}
        self.static_dir = static_dir.resolve() if static_dir else None
        self.allow_local_web_without_token = allow_local_web_without_token
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
        parsed = urlsplit(self.path)
        if not parsed.path.startswith("/api/") and self._send_static(parsed.path):
            return
        if not self._authorize():
            return
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
            if parsed.path == "/api/drive/status":
                self._json(HTTPStatus.OK, {"drive": self.server.backend.drive_status()})
                return
            if parsed.path == "/api/drive/callback":
                params = parse_qs(parsed.query)
                if params.get("error"):
                    self._redirect("/?drive=error")
                    return
                code = params.get("code", [""])[0]
                state = params.get("state", [""])[0]
                self.server.backend.complete_drive_authorization(code, state)
                self._redirect("/?drive=connected")
                return
            if parsed.path.startswith("/api/drive/folders/") and parsed.path.endswith("/tracks"):
                folder_id = parsed.path.removeprefix("/api/drive/folders/").removesuffix("/tracks").strip("/")
                self._json(HTTPStatus.OK, {"tracks": self.server.backend.drive_tracks(folder_id)})
                return
            if parsed.path.startswith("/api/drive/files/") and parsed.path.endswith("/audio"):
                file_id = parsed.path.removeprefix("/api/drive/files/").removesuffix("/audio").strip("/")
                self._send_drive_audio(file_id)
                return
            if parsed.path.startswith("/api/tracks/") and parsed.path.endswith("/audio"):
                track_id = parsed.path.removeprefix("/api/tracks/").removesuffix("/audio").strip("/")
                self._send_audio(track_id)
                return
            self._json_error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Ruta no encontrada.")
        except ValueError as exc:
            self._json_error(HTTPStatus.BAD_REQUEST, "INVALID_INPUT", str(exc))
        except (DriveConfigurationError, GoogleApiError) as exc:
            self._json_error(HTTPStatus.SERVICE_UNAVAILABLE, "GOOGLE_DRIVE_ERROR", str(exc))
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
            if parsed.path == "/api/jobs":
                payload = self._read_json()
                video_id = str(payload.get("video_id", "")).strip()
                quality_value = payload.get("quality_kbps")
                quality = None if quality_value in (None, "") else int(quality_value)
                self._json(HTTPStatus.ACCEPTED, {"jobs": self.server.backend.enqueue(video_id, quality)})
                return
            if parsed.path == "/api/drive/connect":
                if not self._is_local_web_request():
                    self._json_error(HTTPStatus.FORBIDDEN, "LOCAL_ONLY", "Conecta Google Drive desde el PC.")
                    return
                self._json(HTTPStatus.OK, {"authorization_url": self.server.backend.drive_authorization_url()})
                return
            if parsed.path == "/api/drive/sync":
                self._json(HTTPStatus.OK, {"drive": self.server.backend.sync_drive()})
                return
            if parsed.path == "/api/drive/disconnect":
                if not self._is_local_web_request():
                    self._json_error(HTTPStatus.FORBIDDEN, "LOCAL_ONLY", "Desconecta Google Drive desde el PC.")
                    return
                self._json(HTTPStatus.OK, {"drive": self.server.backend.disconnect_drive()})
                return
            self._json_error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Ruta no encontrada.")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            self._json_error(HTTPStatus.BAD_REQUEST, "INVALID_INPUT", "Petici\u00f3n no v\u00e1lida.", detail=str(exc))
        except (DriveConfigurationError, GoogleApiError) as exc:
            self._json_error(HTTPStatus.SERVICE_UNAVAILABLE, "GOOGLE_DRIVE_ERROR", str(exc))
        except AppError as exc:
            self._app_error(exc)
        except Exception as exc:  # pragma: no cover
            logger.exception("Unhandled mobile API error")
            self._json_error(HTTPStatus.INTERNAL_SERVER_ERROR, ErrorCode.INTERNAL_ERROR.value, "Se produjo un error interno en el PC.")

    def _authorize(self) -> bool:
        if not self._origin_allowed():
            self._json_error(HTTPStatus.FORBIDDEN, "ORIGIN_DENIED", "Origen no permitido.")
            return False
        if self._is_local_web_request():
            return True
        header = self.headers.get("Authorization", "")
        supplied = header.removeprefix("Bearer ").strip() if header.startswith("Bearer ") else ""
        if not supplied or not hmac.compare_digest(supplied, self.server.token):
            self._json_error(HTTPStatus.UNAUTHORIZED, "UNAUTHORIZED", "Clave del servidor incorrecta.")
            return False
        return True

    def _is_local_web_request(self) -> bool:
        """Allow the locally served browser UI, never a remote web origin."""
        if not self.server.allow_local_web_without_token:
            return False
        host = self.headers.get("Host", "").lower()
        expected_hosts = {
            f"127.0.0.1:{self.server.server_port}",
            f"localhost:{self.server.server_port}",
        }
        if host not in expected_hosts:
            return False
        origin = self.headers.get("Origin", "").rstrip("/")
        return not origin or origin in {f"http://{value}" for value in expected_hosts}

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
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

    def _send_static(self, request_path: str) -> bool:
        """Serve only files in the shipped PWA directory, without traversal."""
        root = self.server.static_dir
        if root is None:
            return False
        relative = "index.html" if request_path in ("", "/") else request_path.lstrip("/")
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return True
        if not candidate.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return True
        data = candidate.read_bytes()
        content_type, _ = mimetypes.guess_type(candidate.name)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)
        return True

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

    def _redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

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

    def _send_drive_audio(self, file_id: str) -> None:
        data, headers, status = self.server.backend.download_drive_track(
            file_id, self.headers.get("Range")
        )
        self.send_response(status)
        self._cors_headers()
        self.send_header("Content-Type", headers.get("Content-Type", "audio/mpeg"))
        self.send_header("Accept-Ranges", "bytes")
        if headers.get("Content-Range"):
            self.send_header("Content-Range", headers["Content-Range"])
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

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
    parser.add_argument("--google-client", type=Path, help="Archivo OAuth de aplicación de escritorio descargado de Google Cloud")
    parser.add_argument("--web", action="store_true", help="Sirve la aplicaciÃ³n web local para usarla desde el PC")
    parser.add_argument("--open-browser", action="store_true", help="Abre la aplicaciÃ³n web en el navegador (requiere --web)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.open_browser and not args.web:
        raise SystemExit("--open-browser requiere --web")
    if args.web and args.host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("--web solo se puede usar en una interfaz local (127.0.0.1, localhost o ::1)")
    if args.web and not PWA_DIRECTORY.is_dir():
        raise SystemExit(f"No se ha encontrado la PWA en {PWA_DIRECTORY}")
    configure_logging()
    token = load_or_create_token(args.token)
    backend = MobileBackend(
        args.database,
        drive_redirect_uri=f"http://127.0.0.1:{args.port}/api/drive/callback",
        google_client_path=args.google_client,
    )
    server = MobileApiServer(
        (args.host, args.port),
        backend,
        token,
        {DEFAULT_ORIGIN, *args.allow_origin},
        static_dir=PWA_DIRECTORY if args.web else None,
        allow_local_web_without_token=args.web,
    )
    if args.web:
        url = f"http://{args.host}:{server.server_port}"
        print("YT-MP3 Studio web para PC")
        print(f"AplicaciÃ³n web local: {url}")
        print("Solo acepta conexiones de este PC; no abre puertos en el router.")
        if args.open_browser:
            Timer(0.2, lambda: webbrowser.open(url)).start()
    else:
        print("YT-MP3 Studio para iPhone")
        print(f"Servidor local: http://{args.host}:{server.server_port}")
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
