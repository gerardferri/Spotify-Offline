from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROTOTYPE = PROJECT_ROOT / "prototype"


class ElementCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        element_id = dict(attrs).get("id")
        if element_id:
            self.ids.add(str(element_id))


def test_drive_panel_exposes_every_connection_state_and_action() -> None:
    html = (PROTOTYPE / "index.html").read_text(encoding="utf-8")
    parser = ElementCollector()
    parser.feed(html)

    assert {
        "driveHub",
        "driveStatus",
        "driveLoading",
        "driveDisconnected",
        "driveConnected",
        "driveError",
        "driveConnect",
        "driveSync",
        "driveDisconnect",
        "driveRetry",
        "driveFolderList",
        "driveLastSync",
    } <= parser.ids
    assert 'aria-busy="true"' in html
    assert "Nunca vemos ni guardamos tu contraseña" in html


def test_drive_frontend_consumes_canonical_api_contract() -> None:
    javascript = (PROTOTYPE / "app.js").read_text(encoding="utf-8")

    for endpoint in (
        "/api/drive/status",
        "/api/drive/connect",
        "/api/drive/sync",
        "/api/drive/disconnect",
        "/api/drive/folders/",
        "/api/drive/files/",
    ):
        assert endpoint in javascript

    assert "payload?.drive" in javascript
    assert "payload.authorization_url" in javascript
    assert "account_email" in javascript
    assert "driveSnapshot.mode === 'desktop'" in javascript
    assert "google-client-secret.json" in javascript
    assert "last_sync_at" in javascript
    assert "track_count" in javascript
    assert "driveSnapshot.folders" in javascript
    assert "autoSync: true" in javascript
    assert "300000" in javascript
    assert "Google Drive se vincula y sincroniza de forma segura en el PC" in javascript


def test_drive_folders_are_reflected_as_remote_playlists() -> None:
    javascript = (PROTOTYPE / "app.js").read_text(encoding="utf-8")
    css = (PROTOTYPE / "styles.css").read_text(encoding="utf-8")

    assert "drive-playlist" in javascript
    assert "data-drive-folder-id" in javascript
    assert "focusDriveFolder" in javascript
    assert ".drive-folder-list" in css
    assert ".drive-hub[data-state=connected]" in css
    assert "@media(max-width:620px)" in css
