from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from ytmp3studio.ui.pages.playlists_page import PlaylistsPage


class PlaylistFacade(QObject):
    playlists_snapshot = Signal(str, object)
    playlist_snapshot = Signal(str, object)
    operation_failed = Signal(str, object)

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple] = []

    def list_playlists(self) -> str:
        self.calls.append(("list_playlists",))
        return "list-1"

    def get_playlist(self, playlist_id: str) -> str:
        self.calls.append(("get_playlist", playlist_id))
        return "detail-1"

    def import_exportify(self, path: str) -> str:
        self.calls.append(("import_exportify", path))
        return "import-1"

    def download_playlist(self, playlist_id: str) -> str:
        self.calls.append(("download_playlist", playlist_id))
        return "download-1"

    def stop_playlist_downloads(self, playlist_id: str) -> str:
        self.calls.append(("stop_playlist_downloads", playlist_id))
        return "stop-1"

    def retry_playlist_failures(self, playlist_id: str) -> str:
        self.calls.append(("retry_playlist_failures", playlist_id))
        return "retry-1"

    def choose_playlist_cover(self, playlist_id: str, path: str) -> str:
        self.calls.append(("choose_playlist_cover", playlist_id, path))
        return "cover-1"

    def open_exportify(self) -> str:
        self.calls.append(("open_exportify",))
        return "open-1"


def test_playlist_page_imports_lists_and_downloads(tmp_path):
    app = QApplication.instance() or QApplication([])
    facade = PlaylistFacade()
    page = PlaylistsPage(facade)
    export = tmp_path / "spotify_playlists.zip"
    export.write_bytes(b"zip")

    page.import_path(str(export))
    assert facade.calls[-1] == ("import_exportify", str(export))

    page.refresh()
    facade.playlists_snapshot.emit("list-1", [{"id": "p1", "name": "Favoritas", "track_count": 2}])
    assert page.playlist_list.count() == 1
    assert facade.calls[-1] == ("get_playlist", "p1")

    facade.playlist_snapshot.emit(
        "detail-1",
        {
            "id": "p1",
            "name": "Favoritas",
            "tracks": [
                {"artist": "Artista", "title": "Canción", "duration_ms": 61000, "status": "downloaded"},
                {"artist": "Otro", "title": "Pendiente", "status": "failed"},
            ],
        },
    )
    assert page.tracks_table.rowCount() == 2
    assert page.retry_button.isEnabled()
    page.download_current()
    assert facade.calls[-1] == ("download_playlist", "p1")
    app.processEvents()


def test_playlist_page_stops_downloads_and_tracks_pending_request():
    app = QApplication.instance() or QApplication([])
    facade = PlaylistFacade()
    page = PlaylistsPage(facade)
    page.set_playlists([{"id": "p1", "name": "Favoritas", "track_count": 1}])

    assert page.stop_button.isEnabled()
    page.stop_button.click()

    assert facade.calls[-1] == ("stop_playlist_downloads", "p1")
    assert not page.stop_button.isEnabled()
    assert page.stop_button.text() == "Deteniendo..."

    page._playlist_changed("p1")
    assert page.stop_button.isEnabled()
    assert page.stop_button.text() == "Detener descargas"
    app.processEvents()


def test_playlist_page_restores_stop_button_when_request_fails():
    app = QApplication.instance() or QApplication([])
    facade = PlaylistFacade()
    page = PlaylistsPage(facade)
    page.set_playlists([{"id": "p1", "name": "Favoritas", "track_count": 1}])
    page.stop_button.click()

    facade.operation_failed.emit("stop-1", RuntimeError("No se pudo detener"))

    assert page.stop_button.isEnabled()
    assert page.stop_button.text() == "Detener descargas"
    app.processEvents()


def test_playlist_page_is_safe_without_playlist_backend():
    app = QApplication.instance() or QApplication([])
    page = PlaylistsPage(QObject())
    page.refresh()
    page.open_exportify()
    assert not page.import_button.isEnabled()
    assert not page.stop_button.isEnabled()
    app.processEvents()
