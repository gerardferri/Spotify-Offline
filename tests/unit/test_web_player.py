from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROTOTYPE = PROJECT_ROOT / "prototype"


class IdCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if attributes.get("id"):
            self.ids.append(str(attributes["id"]))


def test_web_player_has_unique_complete_control_contract() -> None:
    html = (PROTOTYPE / "index.html").read_text(encoding="utf-8")
    parser = IdCollector()
    parser.feed(html)

    expected = {
        "player",
        "playerCover",
        "playerTitle",
        "playerArtist",
        "playerShuffle",
        "playerPrevious",
        "playerPlay",
        "playerPlayIcon",
        "playerNext",
        "playerRepeat",
        "progress",
        "elapsed",
        "duration",
    }
    assert expected <= set(parser.ids)
    assert len(parser.ids) == len(set(parser.ids))
    assert 'aria-pressed="false"' in html
    assert 'step="0.1"' in html


def test_web_player_wires_playback_modes_seeking_and_media_session() -> None:
    javascript = (PROTOTYPE / "app.js").read_text(encoding="utf-8")

    for handler in (
        "$('#playerShuffle').onclick = toggleShuffle",
        "$('#playerRepeat').onclick = toggleRepeat",
        "$('#playerPrevious').onclick = previous",
        "$('#playerNext').onclick = () => next()",
        "$('#progress').oninput = event => seekTo",
        "audio.onended = () => next(true)",
    ):
        assert handler in javascript

    for media_action in ("seekbackward", "seekforward", "seekto", "nexttrack", "previoustrack"):
        assert f"setActionHandler('{media_action}'" in javascript


def test_web_player_has_desktop_and_mobile_layouts() -> None:
    css = (PROTOTYPE / "styles.css").read_text(encoding="utf-8")

    assert ".player-main{display:contents}" in css
    assert "@media(min-width:1024px){.player" in css
    assert "@media(max-width:560px){.player" in css
    assert ".player-control.is-active{color:var(--accent)}" in css
    assert "bottom:calc(var(--bottom-nav-height,76px) + 18px)" in css
    assert "touch-action:pan-y" in css
    assert "syncPlayerClearance" in (PROTOTYPE / "app.js").read_text(encoding="utf-8")
    assert ".icon-play" in css
    assert ".icon-pause" in css
