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


def test_playlist_dialog_exposes_complete_editing_controls() -> None:
    html = (PROTOTYPE / "index.html").read_text(encoding="utf-8")
    parser = IdCollector()
    parser.feed(html)

    assert {
        "playPlaylist",
        "togglePlaylistRename",
        "playlistRenameInput",
        "savePlaylistName",
        "playlistTrackSelect",
        "addPlaylistTrack",
        "deletePlaylist",
        "playlistTracks",
    } <= parser.ids


def test_playlist_edits_are_persisted_and_keep_library_tracks() -> None:
    javascript = (PROTOTYPE / "app.js").read_text(encoding="utf-8")

    for function in (
        "addTrackToOpenPlaylist",
        "removeTrackFromPlaylist",
        "renameOpenPlaylist",
        "deleteOpenPlaylist",
        "playOpenPlaylist",
    ):
        assert f"function {function}" in javascript
    delete_body = javascript[javascript.index("async function deleteOpenPlaylist"):javascript.index("async function playOpenPlaylist")]
    assert "transaction.objectStore('playlists').delete(playlistId)" in delete_body
    assert "transaction.objectStore('tracks').delete" not in delete_body
    assert "Las canciones seguirán en tu biblioteca" in delete_body


def test_playlist_playback_uses_its_own_order() -> None:
    javascript = (PROTOTYPE / "app.js").read_text(encoding="utf-8")

    assert "function playbackTracks()" in javascript
    assert "play(queue[0], queue)" in javascript
    assert "sort((a, b) => (a.addedAt || '').localeCompare(b.addedAt || ''))" in javascript
