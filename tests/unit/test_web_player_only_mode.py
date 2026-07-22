"""Served from a static host (GitHub Pages) there is no PC behind the app, so
every PC-dependent control must disappear instead of failing with a 404."""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROTOTYPE = PROJECT_ROOT / "prototype"


def test_player_only_mode_hides_every_control_that_needs_the_pc() -> None:
    javascript = (PROTOTYPE / "app.js").read_text(encoding="utf-8")

    assert "function applyPlayerOnlyMode()" in javascript
    for selector in ("#desktopDownload", "#libraryDownload", "#driveHub", "#serverBanner"):
        assert selector in javascript
    assert "'search', 'downloads'" in javascript
    assert ".drive-settings" in javascript
    assert "$('#playerOnlyNote').hidden = false" in javascript


def test_pc_detection_covers_localhost_and_private_wifi_addresses() -> None:
    javascript = (PROTOTYPE / "app.js").read_text(encoding="utf-8")

    assert "const PC_HOSTED" in javascript
    assert "'localhost', '127.0.0.1'" in javascript
    # RFC1918 ranges: 10/8, 172.16-31/12 and 192.168/16.
    assert "10\\.\\d+\\.\\d+\\.\\d+" in javascript
    assert "172\\.(1[6-9]|2\\d|3[01])" in javascript
    assert "192\\.168\\.\\d+\\.\\d+" in javascript


def test_the_pc_is_never_polled_without_a_pc_behind_the_app() -> None:
    javascript = (PROTOTYPE / "app.js").read_text(encoding="utf-8")
    start = javascript.index("async function init()")
    init_body = javascript[start:]

    assert "if (!PC_HOSTED) {" in init_body
    player_only, pc_mode = init_body.split("} else {", 1)
    # Polling and Drive/health calls belong only to the PC-hosted branch.
    for pc_only_call in ("updateServerBanner", "loadDriveStatus", "jobsTimer", "driveTimer"):
        assert pc_only_call not in player_only
        assert pc_only_call in pc_mode
    # The service worker still registers in both modes; that is what makes the
    # installed copy openable with the PC switched off.
    assert "serviceWorker" in init_body.split("}\n", 1)[0] or "serviceWorker" in init_body


def test_library_explains_how_to_add_music_without_the_pc() -> None:
    html = (PROTOTYPE / "index.html").read_text(encoding="utf-8")

    assert 'id="playerOnlyNote"' in html
    assert 'id="playerOnlyImport"' in html
    assert "Archivos" in html
    assert "Importar audio" in html


def test_api_calls_target_the_serving_origin() -> None:
    javascript = (PROTOTYPE / "app.js").read_text(encoding="utf-8")

    assert "fetch(`${location.origin}${path}`" in javascript
    # The removed Tailscale settings must not creep back in.
    for gone in ("serverToken", "serverUrl", "saveServerConfig"):
        assert gone not in javascript
