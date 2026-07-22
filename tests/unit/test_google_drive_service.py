from __future__ import annotations

from collections import deque

import pytest

from ytmp3studio.backend.google_drive_service import (
    APP_FOLDER_NAME,
    FOLDER_MIME_TYPE,
    DriveFolder,
    DriveTrack,
    GoogleDriveService,
)


class FakeOAuth:
    def __init__(self, connected: bool = False) -> None:
        self.connected = connected
        self.exchanged: list[str] = []
        self.disconnected = False

    def is_connected(self) -> bool:
        return self.connected

    def authorization_url(self) -> str:
        return "https://accounts.google.test/oauth"

    def exchange_code(self, code: str) -> None:
        self.exchanged.append(code)
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False
        self.disconnected = True


class FakeHttp:
    def __init__(self, responses=()) -> None:
        self.responses = deque(responses)
        self.requests: list[tuple[str, str, dict, dict | None]] = []

    def request(self, method, path, *, params=None, json=None):
        self.requests.append((method, path, dict(params or {}), json))
        if not self.responses:
            raise AssertionError(f"Unexpected request: {method} {path}")
        return self.responses.popleft()


def drive_folder(file_id: str, name: str, parent: str = "root") -> dict:
    return {
        "id": file_id,
        "name": name,
        "mimeType": FOLDER_MIME_TYPE,
        "parents": [parent],
        "modifiedTime": "2026-07-22T10:00:00Z",
    }


def drive_track(
    file_id: str,
    name: str,
    parent: str,
    mime_type: str = "audio/mpeg",
) -> dict:
    return {
        "id": file_id,
        "name": name,
        "mimeType": mime_type,
        "parents": [parent],
        "size": "1234",
        "modifiedTime": "2026-07-22T11:00:00Z",
        "webViewLink": f"https://drive.google.test/{file_id}",
        "md5Checksum": "checksum",
    }


def test_disconnected_state_does_not_call_drive() -> None:
    http = FakeHttp()
    service = GoogleDriveService(FakeOAuth(), http)

    assert service.connection_state().connected is False
    assert service.authorization_url() == "https://accounts.google.test/oauth"
    assert http.requests == []


def test_connect_exchanges_code_creates_dedicated_folder_and_maps_account() -> None:
    oauth = FakeOAuth()
    http = FakeHttp(
        [
            {"files": []},
            drive_folder("app-root", APP_FOLDER_NAME),
            {"user": {"displayName": "Gerard", "emailAddress": "g@example.test"}},
        ]
    )

    state = GoogleDriveService(oauth, http).connect("  auth-code  ")

    assert oauth.exchanged == ["auth-code"]
    assert state.connected is True
    assert state.account_email == "g@example.test"
    assert state.account_name == "Gerard"
    assert state.app_folder_id == "app-root"
    create = http.requests[1]
    assert create[:2] == ("POST", "/drive/v3/files")
    assert create[3] == {
        "name": APP_FOLDER_NAME,
        "mimeType": FOLDER_MIME_TYPE,
        "parents": ["root"],
    }


def test_ensure_folder_reuses_existing_folder_and_escapes_custom_name() -> None:
    http = FakeHttp([{"files": [drive_folder("app-root", "Gerard's Music")]}])
    service = GoogleDriveService(FakeOAuth(True), http, "Gerard's Music")

    folder = service.ensure_app_folder()

    assert folder == DriveFolder(
        "app-root", "Gerard's Music", "root", "2026-07-22T10:00:00Z"
    )
    assert "Gerard\\'s Music" in http.requests[0][2]["q"]
    assert len(http.requests) == 1


def test_scan_recurses_subfolders_paginates_and_maps_only_audio() -> None:
    http = FakeHttp(
        [
            {"files": [drive_folder("root-id", APP_FOLDER_NAME)]},
            {
                "files": [
                    drive_folder("rock", "Rock", "root-id"),
                    drive_track("root-song", "Inicio.mp3", "root-id"),
                ],
                "nextPageToken": "files-page-2",
            },
            {
                "files": [
                    drive_track(
                        "extension-song",
                        "Grabacion.OPUS",
                        "root-id",
                        "application/octet-stream",
                    ),
                    {
                        "id": "cover",
                        "name": "cover.jpg",
                        "mimeType": "image/jpeg",
                        "parents": ["root-id"],
                    },
                ]
            },
            {"files": [drive_track("rock-song", "Rock.mp3", "rock")]},
            {"startPageToken": "changes-10"},
        ]
    )
    service = GoogleDriveService(FakeOAuth(True), http)

    snapshot = service.scan_library()

    assert snapshot.root_folder.id == "root-id"
    assert snapshot.folders == (
        DriveFolder("rock", "Rock", "root-id", "2026-07-22T10:00:00Z"),
    )
    assert [track.id for track in snapshot.tracks] == [
        "root-song",
        "extension-song",
        "rock-song",
    ]
    assert isinstance(snapshot.tracks[0], DriveTrack)
    assert snapshot.tracks[0].size_bytes == 1234
    assert snapshot.tracks[0].checksum == "checksum"
    assert snapshot.changes_token == "changes-10"
    assert http.requests[2][2]["pageToken"] == "files-page-2"


def test_incremental_changes_paginate_map_library_items_and_ignore_other_drive_files() -> None:
    # First scan establishes the IDs belonging to the dedicated app folder.
    http = FakeHttp(
        [
            {"files": [drive_folder("root-id", APP_FOLDER_NAME)]},
            {
                "files": [
                    drive_folder("old-folder", "Old", "root-id"),
                    drive_track("deleted-song", "Delete.mp3", "root-id"),
                ]
            },
            {"files": []},
            {"startPageToken": "changes-1"},
            {
                "changes": [
                    {
                        "fileId": "new-song",
                        "file": drive_track("new-song", "New.mp3", "new-folder"),
                    },
                    {
                        "fileId": "new-folder",
                        "file": drive_folder("new-folder", "New", "root-id"),
                    },
                    {"fileId": "deleted-song", "removed": True},
                ],
                "nextPageToken": "changes-2",
            },
            {
                "changes": [
                    {
                        "fileId": "foreign-song",
                        "file": drive_track("foreign-song", "Other.mp3", "foreign-root"),
                    },
                    {
                        "fileId": "old-folder",
                        "file": {
                            **drive_folder("old-folder", "Old", "root-id"),
                            "trashed": True,
                        },
                    },
                ],
                "newStartPageToken": "changes-3",
            },
        ]
    )
    service = GoogleDriveService(FakeOAuth(True), http)
    service.scan_library()

    page = service.list_changes("changes-1")

    assert page.next_token == "changes-3"
    assert [(change.file_id, change.removed) for change in page.changes] == [
        ("new-song", False),
        ("new-folder", False),
        ("deleted-song", True),
        ("old-folder", True),
    ]
    assert page.changes[0].track is not None
    assert page.changes[0].track.folder_id == "new-folder"
    assert page.changes[1].folder is not None
    change_requests = [request for request in http.requests if request[1].endswith("/changes")]
    assert [request[2]["pageToken"] for request in change_requests] == [
        "changes-1",
        "changes-2",
    ]


def test_disconnect_clears_state_and_requires_reconnection() -> None:
    oauth = FakeOAuth(True)
    http = FakeHttp([{"files": [drive_folder("root-id", APP_FOLDER_NAME)]}])
    service = GoogleDriveService(oauth, http)
    service.ensure_app_folder()

    service.disconnect()

    assert oauth.disconnected is True
    assert service.connection_state().connected is False
    with pytest.raises(RuntimeError, match="not connected"):
        service.ensure_app_folder()


def test_change_moved_outside_dedicated_folder_is_reported_as_removed() -> None:
    http = FakeHttp(
        [
            {"files": [drive_folder("root-id", APP_FOLDER_NAME)]},
            {"files": [drive_track("song", "Song.mp3", "root-id")]},
            {"startPageToken": "token-1"},
            {
                "changes": [
                    {
                        "fileId": "song",
                        "file": drive_track("song", "Song.mp3", "outside-folder"),
                    }
                ],
                "newStartPageToken": "token-2",
            },
        ]
    )
    service = GoogleDriveService(FakeOAuth(True), http)
    service.scan_library()

    changes = service.list_changes("token-1")

    assert changes.next_token == "token-2"
    assert len(changes.changes) == 1
    assert changes.changes[0].file_id == "song"
    assert changes.changes[0].removed is True


@pytest.mark.parametrize("value", ["", "   "])
def test_connection_and_changes_tokens_cannot_be_empty(value: str) -> None:
    service = GoogleDriveService(FakeOAuth(True), FakeHttp())

    with pytest.raises(ValueError):
        service.connect(value)
    with pytest.raises(ValueError):
        service.list_changes(value)
