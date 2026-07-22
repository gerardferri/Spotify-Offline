from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import pytest

from ytmp3studio.backend.google_drive_client import (
    DRIVE_FILE_SCOPE,
    DRIVE_READONLY_SCOPE,
    DriveConfigurationError,
    GoogleDriveClient,
)


def write_client(path) -> None:
    path.write_text(
        json.dumps({"installed": {"client_id": "client.apps.googleusercontent.com", "client_secret": "secret"}}),
        encoding="utf-8",
    )


def test_authorization_url_uses_offline_pkce_readonly_and_state(tmp_path) -> None:
    config = tmp_path / "client.json"
    write_client(config)
    client = GoogleDriveClient(config, tmp_path / "token.json", "http://127.0.0.1:8766/api/drive/callback")

    url = client.authorization_url()
    query = parse_qs(urlsplit(url).query)

    assert set(query["scope"][0].split()) == {DRIVE_READONLY_SCOPE, DRIVE_FILE_SCOPE}
    assert query["access_type"] == ["offline"]
    assert query["code_challenge_method"] == ["S256"]
    assert client.validate_state(query["state"][0]) is True
    assert client.validate_state("wrong") is False


def test_missing_client_credentials_has_actionable_error(tmp_path) -> None:
    client = GoogleDriveClient(tmp_path / "missing.json", tmp_path / "token.json", "http://localhost/callback")
    assert client.configured is False
    with pytest.raises(DriveConfigurationError, match="Falta el archivo"):
        client.authorization_url()


def test_connected_state_comes_from_separate_token_file(tmp_path) -> None:
    config = tmp_path / "client.json"
    write_client(config)
    token = tmp_path / "token.json"
    client = GoogleDriveClient(config, token, "http://localhost/callback")
    assert client.is_connected() is False
    token.write_text('{"refresh_token":"refresh"}', encoding="utf-8")
    assert client.is_connected() is True
