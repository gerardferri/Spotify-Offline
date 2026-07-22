from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROTOTYPE = PROJECT_ROOT / "prototype"


class IdCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        identifier = dict(attrs).get("id")
        if identifier:
            self.ids.add(identifier)


def test_exportify_import_controls_exist_in_the_playlist_page() -> None:
    parser = IdCollector()
    parser.feed((PROTOTYPE / "index.html").read_text(encoding="utf-8"))

    assert {
        "spotifyImport",
        "spotifyDrop",
        "spotifyFile",
        "spotifyImportStatus",
        "spotifyServerList",
    } <= parser.ids


def test_exportify_flow_is_loopback_only_and_starts_all_downloads() -> None:
    javascript = (PROTOTYPE / "app.js").read_text(encoding="utf-8")

    assert "const PC_LOOPBACK" in javascript
    assert "if (PC_LOOPBACK)" in javascript
    assert "/api/playlists/import?filename=" in javascript
    assert "/api/playlists/download-all" in javascript
    assert "importSpotifyFile(event.dataTransfer.files[0])" in javascript

