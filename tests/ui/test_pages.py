from __future__ import annotations

from dataclasses import replace

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from ytmp3studio.domain.errors import AppError, ErrorCode
from ytmp3studio.domain.models import DownloadJob, JobState, LibraryFolder, LibraryTrack, SearchResult, Settings
from ytmp3studio.ui.pages.library_page import LibraryPage
from ytmp3studio.ui.pages.queue_page import QueuePage
from ytmp3studio.ui.pages.search_page import SearchPage
from ytmp3studio.ui.pages.settings_page import SettingsPage


class FakeFacade(QObject):
    initialized = Signal(object)
    search_started = Signal(str)
    search_succeeded = Signal(str, object)
    queue_snapshot = Signal(str, object)
    job_added = Signal(object)
    job_updated = Signal(object)
    job_progress = Signal(object)
    job_completed = Signal(object, object)
    library_snapshot = Signal(str, object, int)
    library_changed = Signal()
    library_folders_snapshot = Signal(str, object)
    library_folders_changed = Signal()
    settings_changed = Signal(object)
    dependency_status = Signal(str, object)
    operation_failed = Signal(str, object)
    fatal_error = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple] = []
        self._counter = 0

    def _id(self, name: str) -> str:
        self._counter += 1
        return f"{name}-{self._counter}"

    def search(self, query: str, limit: int) -> str:
        request = self._id("search")
        self.calls.append(("search", query, limit))
        return request

    def enqueue(self, ids: list[str]) -> str:
        request = self._id("enqueue")
        self.calls.append(("enqueue", ids))
        return request

    def update_settings(self, patch: dict) -> str:
        request = self._id("settings")
        self.calls.append(("update_settings", patch))
        return request

    def check_dependencies(self) -> str:
        return self._id("dependencies")

    def remove_job(self, job_id: str) -> str:
        request = self._id("remove")
        self.calls.append(("remove_job", job_id))
        return request

    def list_library(self, filter_text: str, limit: int, offset: int, folder_id=None) -> str:
        request = self._id("library")
        self.calls.append(("list_library", filter_text, limit, offset, folder_id))
        return request

    def list_library_folders(self) -> str:
        request = self._id("folders")
        self.calls.append(("list_library_folders",))
        return request

    def create_library_folder(self, name: str) -> str:
        request = self._id("create-folder")
        self.calls.append(("create_library_folder", name))
        return request

    def assign_library_track_folder(self, track_id: str, folder_id: str | None) -> str:
        request = self._id("assign-folder")
        self.calls.append(("assign_library_track_folder", track_id, folder_id))
        return request

    def reveal_library_track(self, track_id: str) -> str:
        request = self._id("reveal")
        self.calls.append(("reveal_library_track", track_id))
        return request


@pytest.fixture(scope="module")
def qapp():
    application = QApplication.instance() or QApplication([])
    yield application
    application.processEvents()


def make_job(state: JobState = JobState.QUEUED) -> DownloadJob:
    return DownloadJob(
        id="00000000-0000-0000-0000-000000000001",
        video_id="video",
        source_url="https://youtube.invalid/watch?v=video",
        title="Una canción",
        channel="Canal",
        quality_kbps=192,
        output_dir="C:/Music",
        temp_dir="C:/Music/tmp",
        state=state,
        attempt_count=0,
        max_attempts=3,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )


def test_search_shows_multiple_results_and_enqueues_selection(qapp):
    facade = FakeFacade()
    page = SearchPage(facade)

    page.query.setText("música autorizada")
    page.start_search()
    request = page._latest_search
    facade.search_succeeded.emit(
        request,
        [
            SearchResult("a", "https://youtube.invalid/a", "Primera", "Canal 1", 61),
            SearchResult("b", "https://youtube.invalid/b", "Segunda", "Canal 2", None),
        ],
    )

    assert len(page._cards) == 2
    assert "1:01" in page._cards[0].meta.text()
    page._cards[0].check.setChecked(True)
    page._cards[1].check.setChecked(True)
    page.enqueue_selected()
    assert facade.calls[-1] == ("enqueue", ["a", "b"])

    request_id = next(iter(page._pending_enqueue))
    facade.job_added.emit(replace(make_job(), video_id="a"))
    assert request_id in page._pending_enqueue
    assert all(card.check.isChecked() for card in page._cards)
    facade.job_added.emit(replace(make_job(), video_id="b"))
    assert request_id not in page._pending_enqueue
    assert not any(card.check.isChecked() for card in page._cards)


def test_search_error_is_visible_and_unlocks_controls(qapp):
    facade = FakeFacade()
    page = SearchPage(facade)
    page.query.setText("fallo")
    page.start_search()

    facade.operation_failed.emit(page._latest_search, AppError(ErrorCode.NETWORK_ERROR, "Sin conexión", recoverable=True))

    assert not page.feedback.isHidden()
    assert page.feedback.text() == "Sin conexión"
    assert page.search_button.isEnabled()


def test_queue_remove_is_optimistic_but_restored_on_error(qapp):
    facade = FakeFacade()
    page = QueuePage(facade)
    job = make_job(JobState.COMPLETED)
    page.set_jobs([job])

    page._action(job.id, "remove")
    request = next(iter(page._pending))
    assert not page._rows

    facade.operation_failed.emit(request, AppError(ErrorCode.DATABASE_ERROR, "No se pudo quitar"))
    assert job.id in page._rows
    assert page.feedback.text() == "No se pudo quitar"


def test_settings_sends_complete_valid_patch(qapp, tmp_path):
    facade = FakeFacade()
    page = SettingsPage(facade)
    settings = Settings(str(tmp_path), quality_kbps=256, theme="dark", concurrency=3, max_retries=4, retry_base_seconds=7)
    page.set_settings(settings)

    page._save()

    name, patch = facade.calls[-1]
    assert name == "update_settings"
    assert patch == {
        "download_dir": str(tmp_path),
        "quality_kbps": 256,
        "theme": "dark",
        "concurrency": 3,
        "max_retries": 4,
        "retry_base_seconds": 7,
    }


def test_settings_google_drive_uses_a_dedicated_music_folder(qapp, tmp_path, monkeypatch):
    facade = FakeFacade()
    page = SettingsPage(facade)
    monkeypatch.setattr(
        "ytmp3studio.ui.pages.settings_page.QFileDialog.getExistingDirectory",
        lambda *_args: str(tmp_path),
    )

    page._choose_google_drive()

    assert page.download_dir.text() == str(tmp_path / "YT-MP3 Studio")
    assert page.saved.text() == "Google Drive seleccionado. Pulsa Guardar configuración."


def test_settings_google_drive_does_not_duplicate_dedicated_folder(qapp, tmp_path, monkeypatch):
    facade = FakeFacade()
    page = SettingsPage(facade)
    dedicated = tmp_path / "YT-MP3 Studio"
    dedicated.mkdir()
    monkeypatch.setattr(
        "ytmp3studio.ui.pages.settings_page.QFileDialog.getExistingDirectory",
        lambda *_args: str(dedicated),
    )

    page._choose_google_drive()

    assert page.download_dir.text() == str(dedicated)


def test_library_paginates_and_reveals_selected_track(qapp, tmp_path):
    facade = FakeFacade()
    page = LibraryPage(facade)
    audio = tmp_path / "track.mp3"
    audio.write_bytes(b"mp3")
    track = LibraryTrack(
        id="00000000-0000-0000-0000-000000000002",
        video_id="video",
        title="Track",
        channel="Channel",
        source_url="https://youtube.invalid/video",
        file_path=str(audio),
        file_size_bytes=3,
        quality_kbps=192,
        created_at="2026-01-01T00:00:00Z",
    )

    page.refresh()
    request = page._latest_request
    assert facade.calls[-1] == ("list_library", "", 100, 0, None)
    facade.library_snapshot.emit(request, [track], 150)
    page.table.selectRow(0)
    page._reveal_selected()
    assert facade.calls[-1] == ("reveal_library_track", track.id)

    page._next_page()
    assert facade.calls[-1] == ("list_library", "", 100, 100, None)


def test_library_filters_and_moves_tracks_to_folders(qapp, tmp_path):
    facade = FakeFacade()
    page = LibraryPage(facade)
    folder = LibraryFolder(
        "00000000-0000-0000-0000-000000000003", "Favoritas", "2026-01-01T00:00:00Z", 1
    )
    page.refresh_folders()
    facade.library_folders_snapshot.emit(page._latest_folders_request, [folder])
    assert page.folder_filter.findData(folder.id) >= 0

    audio = tmp_path / "folder-track.mp3"
    audio.write_bytes(b"mp3")
    track = LibraryTrack(
        id="00000000-0000-0000-0000-000000000004",
        video_id="folder-video",
        title="Track en carpeta",
        channel="Channel",
        source_url="https://youtube.invalid/folder-video",
        file_path=str(audio),
        file_size_bytes=3,
        quality_kbps=192,
        created_at="2026-01-01T00:00:00Z",
    )
    page.refresh()
    facade.library_snapshot.emit(page._latest_request, [track], 1)
    page.table.selectRow(0)
    page.move_target.setCurrentIndex(page.move_target.findData(folder.id))
    page._move_selected()
    assert facade.calls[-1] == ("assign_library_track_folder", track.id, folder.id)
