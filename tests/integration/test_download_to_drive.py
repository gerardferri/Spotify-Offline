"""The finished MP3 must land in Drive and show up as a playlist without waiting."""

from __future__ import annotations

from pathlib import Path
import time

import pytest

from ytmp3studio.backend.local_drive_service import LocalGoogleDriveService
from ytmp3studio.mobile_server import MobileBackend


class OfflineDriveClient:
    """Stand-in for the OAuth client: the desktop mount is the preferred mode."""

    configured = False

    def is_connected(self) -> bool:
        return False


@pytest.fixture
def backend(tmp_path):
    music_root = tmp_path / "Mi unidad" / "YT-MP3 Studio"
    music_root.parent.mkdir(parents=True)
    instance = MobileBackend(
        database_path=tmp_path / "ytmp3studio.db",
        drive_client=OfflineDriveClient(),
        local_drive_service=LocalGoogleDriveService(music_root),
    )
    try:
        yield instance
    finally:
        instance.close()


def test_downloads_are_written_into_the_synced_drive_folder(backend, tmp_path) -> None:
    expected = tmp_path / "Mi unidad" / "YT-MP3 Studio" / "Descargas"

    assert Path(backend.download_dir()) == expected
    assert expected.is_dir()
    assert backend.drive_status()["downloads_folder_name"] == "Descargas"
    assert backend.drive_status()["download_dir"] == str(expected)


def test_a_folder_chosen_by_the_user_is_never_overwritten(tmp_path) -> None:
    music_root = tmp_path / "Mi unidad" / "YT-MP3 Studio"
    music_root.parent.mkdir(parents=True)
    chosen = tmp_path / "Mi musica"
    instance = MobileBackend(
        database_path=tmp_path / "ytmp3studio.db",
        drive_client=OfflineDriveClient(),
        local_drive_service=LocalGoogleDriveService(music_root),
    )
    instance.settings.set_value("download_dir", str(chosen))
    instance.close()

    reopened = MobileBackend(
        database_path=tmp_path / "ytmp3studio.db",
        drive_client=OfflineDriveClient(),
        local_drive_service=LocalGoogleDriveService(music_root),
    )
    try:
        assert Path(reopened.download_dir()) == chosen
    finally:
        reopened.close()


def test_sync_drive_response_reports_zip_availability_per_folder(backend, tmp_path) -> None:
    """Regression: sync_drive() used to return drive_repository's raw dict, which
    never carries has_zip - the button would vanish right after pressing Sync."""

    folder = tmp_path / "Mi unidad" / "YT-MP3 Studio" / "Con musica"
    folder.mkdir(parents=True)
    (folder / "Tema.mp3").write_bytes(b"audio")
    empty_folder = tmp_path / "Mi unidad" / "YT-MP3 Studio" / "Vacia"
    empty_folder.mkdir()

    status = backend.sync_drive()

    by_name = {item["name"]: item for item in status["folders"]}
    assert by_name["Con musica"]["has_zip"] is True
    assert by_name["Vacia"]["has_zip"] is False


def test_finishing_a_download_refreshes_the_drive_catalog(backend, tmp_path) -> None:
    downloads = tmp_path / "Mi unidad" / "YT-MP3 Studio" / "Descargas"
    (downloads / "Cancion nueva.mp3").write_bytes(b"audio")

    backend._on_download_completed(None, None)

    deadline = time.monotonic() + 5
    names: list[str] = []
    while time.monotonic() < deadline:
        names = [track["name"] for track in backend.drive_tracks()]
        if names:
            break
        time.sleep(0.05)

    assert names == ["Cancion nueva.mp3"]
    folders = backend.drive_status()["folders"]
    assert [folder["name"] for folder in folders] == ["Descargas"]
    assert folders[0]["track_count"] == 1
