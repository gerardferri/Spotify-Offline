"""The interface must not promise things the architecture does not deliver."""

from __future__ import annotations

from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROTOTYPE = PROJECT_ROOT / "prototype"


@pytest.fixture(scope="module")
def web_text() -> str:
    return (PROTOTYPE / "index.html").read_text(encoding="utf-8") + (
        PROTOTYPE / "app.js"
    ).read_text(encoding="utf-8")


def test_the_app_never_claims_the_connection_is_encrypted(web_text: str) -> None:
    """Over plain HTTP on the LAN it is not, and saying so would mislead the user."""

    for claim in ("cifrada", "cifrado", "cifra tu"):
        assert claim not in web_text.casefold()


def test_no_leftover_references_to_the_removed_server_settings(web_text: str) -> None:
    for gone in ("Tailscale", "serverToken", "serverUrl", "Clave mostrada por el PC"):
        assert gone not in web_text


def test_shared_screens_do_not_assume_the_device_is_an_iphone(web_text: str) -> None:
    """The same markup is served to the PC browser and to the phone."""

    assert "este iPhone" not in web_text


def test_spanish_plural_of_cancion_drops_its_accent(web_text: str) -> None:
    """"canciónes" is misspelled; the shared songs() helper must be used instead."""

    assert "canciónes" not in web_text
    assert "function songs(count)" in web_text


def test_readme_documents_the_two_hosting_modes() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

    assert "modo reproductor" in readme.casefold()
    assert "webkitdirectory" in readme
    assert "ABRIR-YT-MP3-STUDIO-WIFI.cmd" in readme
