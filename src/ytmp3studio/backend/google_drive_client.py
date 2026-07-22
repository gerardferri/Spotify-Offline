"""Production OAuth 2.0 and REST adapter for Google Drive.

Only the PC process handles these credentials.  The PWA talks to the personal
PC API and never receives Google access or refresh tokens.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import secrets
from typing import Any, Mapping
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"
GOOGLE_API_ORIGIN = "https://www.googleapis.com"
DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
DEFAULT_DRIVE_SCOPES = f"{DRIVE_READONLY_SCOPE} {DRIVE_FILE_SCOPE}"


class DriveConfigurationError(RuntimeError):
    pass


class GoogleApiError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class GoogleDriveClient:
    """Small dependency-free OAuth/HTTP client implementing the service ports."""

    def __init__(
        self,
        client_config_path: str | Path,
        token_path: str | Path,
        redirect_uri: str,
        *,
        scope: str = DEFAULT_DRIVE_SCOPES,
        timeout: float = 30.0,
    ) -> None:
        self.client_config_path = Path(client_config_path)
        self.token_path = Path(token_path)
        self.redirect_uri = redirect_uri
        self.scope = scope
        self.timeout = timeout
        self._pending_state: str | None = None
        self._code_verifier: str | None = None

    @property
    def configured(self) -> bool:
        return self.client_config_path.is_file()

    def is_connected(self) -> bool:
        token = self._load_token()
        return bool(token and (token.get("refresh_token") or token.get("access_token")))

    def authorization_url(self) -> str:
        config = self._client_config()
        self._pending_state = secrets.token_urlsafe(32)
        self._code_verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(self._code_verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")
        return AUTHORIZATION_ENDPOINT + "?" + urlencode(
            {
                "client_id": config["client_id"],
                "redirect_uri": self.redirect_uri,
                "response_type": "code",
                "scope": self.scope,
                "access_type": "offline",
                "prompt": "consent",
                "include_granted_scopes": "true",
                "state": self._pending_state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )

    def validate_state(self, state: str) -> bool:
        return bool(
            self._pending_state
            and state
            and secrets.compare_digest(self._pending_state, state)
        )

    def exchange_code(self, code: str) -> None:
        if not self._code_verifier:
            raise RuntimeError("No hay una autorización de Google pendiente.")
        config = self._client_config()
        token = self._post_form(
            TOKEN_ENDPOINT,
            {
                "client_id": config["client_id"],
                "client_secret": config.get("client_secret", ""),
                "code": code,
                "code_verifier": self._code_verifier,
                "grant_type": "authorization_code",
                "redirect_uri": self.redirect_uri,
            },
        )
        token["expires_at"] = _expires_at(token.get("expires_in"))
        self._save_token(token)
        self._pending_state = None
        self._code_verifier = None

    def disconnect(self) -> None:
        token = self._load_token() or {}
        revoke_token = token.get("refresh_token") or token.get("access_token")
        if revoke_token:
            try:
                request = Request(
                    REVOKE_ENDPOINT,
                    data=urlencode({"token": revoke_token}).encode("ascii"),
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    method="POST",
                )
                urlopen(request, timeout=self.timeout).close()
            except OSError:
                pass
        self.token_path.unlink(missing_ok=True)
        self._pending_state = None
        self._code_verifier = None

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        url = GOOGLE_API_ORIGIN + path
        if params:
            url += "?" + urlencode(
                {key: str(value).lower() if isinstance(value, bool) else value for key, value in params.items()}
            )
        body = None if json is None else _json_bytes(json)
        response = self._authorized_request(method, url, body=body)
        with response:
            payload = response.read()
        return {} if not payload else _decode_json(payload)

    def download(self, file_id: str, range_header: str | None = None) -> tuple[bytes, Mapping[str, str], int]:
        headers = {"Range": range_header} if range_header else None
        response = self._authorized_request(
            "GET",
            f"{GOOGLE_API_ORIGIN}/drive/v3/files/{file_id}?alt=media",
            extra_headers=headers,
        )
        with response:
            return response.read(), dict(response.headers.items()), int(response.status)

    def _authorized_request(
        self,
        method: str,
        url: str,
        *,
        body: bytes | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ):
        token = self._valid_token()
        headers = {"Authorization": f"Bearer {token['access_token']}"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        headers.update(extra_headers or {})
        request = Request(url, data=body, headers=headers, method=method)
        try:
            return urlopen(request, timeout=self.timeout)
        except HTTPError as exc:
            payload = exc.read()
            message = _google_error_message(payload) or f"Google Drive devolvió HTTP {exc.code}."
            raise GoogleApiError(exc.code, message) from exc

    def _valid_token(self) -> dict[str, Any]:
        token = self._load_token()
        if not token:
            raise RuntimeError("Google Drive no está conectado.")
        expires_at = token.get("expires_at")
        now = datetime.now(timezone.utc)
        if token.get("access_token") and expires_at:
            try:
                expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            except ValueError:
                expiry = now
            if expiry > now + timedelta(seconds=60):
                return token
        refresh_token = token.get("refresh_token")
        if not refresh_token:
            raise RuntimeError("La sesión de Google ha caducado; vuelve a conectarla.")
        config = self._client_config()
        refreshed = self._post_form(
            TOKEN_ENDPOINT,
            {
                "client_id": config["client_id"],
                "client_secret": config.get("client_secret", ""),
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        token.update(refreshed)
        token["refresh_token"] = refresh_token
        token["expires_at"] = _expires_at(token.get("expires_in"))
        self._save_token(token)
        return token

    def _client_config(self) -> dict[str, Any]:
        if not self.configured:
            raise DriveConfigurationError(
                f"Falta el archivo de credenciales de Google: {self.client_config_path}"
            )
        raw = _decode_json(self.client_config_path.read_bytes())
        config = raw.get("installed") or raw.get("web") or raw
        if not isinstance(config, dict) or not config.get("client_id"):
            raise DriveConfigurationError("El archivo de credenciales de Google no es válido.")
        return config

    def _post_form(self, url: str, values: Mapping[str, Any]) -> dict[str, Any]:
        request = Request(
            url,
            data=urlencode(values).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return _decode_json(response.read())
        except HTTPError as exc:
            payload = exc.read()
            raise GoogleApiError(
                exc.code,
                _google_error_message(payload) or "Google rechazó la autorización.",
            ) from exc

    def _load_token(self) -> dict[str, Any] | None:
        if not self.token_path.is_file():
            return None
        try:
            value = _decode_json(self.token_path.read_bytes())
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def _save_token(self, token: Mapping[str, Any]) -> None:
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.token_path.with_suffix(self.token_path.suffix + ".tmp")
        temporary.write_bytes(_json_bytes(token))
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        temporary.replace(self.token_path)


def _expires_at(seconds: Any) -> str:
    try:
        duration = max(60, int(seconds))
    except (TypeError, ValueError):
        duration = 3600
    return (datetime.now(timezone.utc) + timedelta(seconds=duration)).isoformat().replace("+00:00", "Z")


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _decode_json(payload: bytes) -> dict[str, Any]:
    value = json.loads(payload.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Google devolvió una respuesta inesperada.")
    return value


def _google_error_message(payload: bytes) -> str | None:
    try:
        value = _decode_json(payload)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    error = value.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error.get("error_description") or "") or None
    return str(error) if error else None
