from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROTOTYPE = PROJECT_ROOT / "prototype"


def test_pc_web_exposes_clear_download_entrypoints() -> None:
    html = (PROTOTYPE / "index.html").read_text(encoding="utf-8")
    javascript = (PROTOTYPE / "app.js").read_text(encoding="utf-8")
    css = (PROTOTYPE / "styles.css").read_text(encoding="utf-8")

    assert '<h1>Descargar música</h1>' in html
    assert 'id="desktopDownload"' in html
    assert 'id="libraryDownload"' in html
    assert 'data-page="search"' in html
    assert "$('#desktopDownload').onclick = $('#libraryDownload').onclick" in javascript
    assert "@media(min-width:1024px){.desktop-download{display:inline-flex}" in css
