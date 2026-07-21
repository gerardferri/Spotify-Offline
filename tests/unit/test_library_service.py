from __future__ import annotations

import pytest

from ytmp3studio.backend.library_service import LibraryService
from ytmp3studio.domain.errors import AppError, ErrorCode
from ytmp3studio.domain.models import LibraryFolder, LibraryTrack


class Repository:
    def __init__(self, track=None):
        self.track = track

    def get(self, track_id):
        return self.track if self.track and self.track.id == track_id else None


def make_track(tmp_path):
    path = tmp_path / "track.mp3"
    path.write_bytes(b"mp3")
    return LibraryTrack(
        id="track-id",
        video_id="video-id",
        title="Track",
        channel="Channel",
        source_url="https://youtube.invalid/video-id",
        file_path=str(path),
        file_size_bytes=3,
        quality_kbps=192,
        created_at="2026-01-01T00:00:00Z",
    )


def test_reveal_uses_backend_boundary_for_existing_file(tmp_path):
    track = make_track(tmp_path)
    revealed = []
    LibraryService(Repository(track), revealed.append).reveal(track.id)
    assert revealed == [(tmp_path / "track.mp3").resolve()]


def test_reveal_reports_missing_file_explicitly(tmp_path):
    track = make_track(tmp_path)
    (tmp_path / "track.mp3").unlink()
    with pytest.raises(AppError) as raised:
        LibraryService(Repository(track), lambda _path: None).reveal(track.id)
    assert raised.value.code == ErrorCode.FILE_NOT_FOUND


class FolderRepository(Repository):
    def __init__(self, track=None):
        super().__init__(track)
        self.folders = []
        self.assigned = None

    def list_folders(self):
        return self.folders

    def create_folder(self, name):
        folder = LibraryFolder("folder-id", name, "2026-01-01T00:00:00Z")
        self.folders.append(folder)
        return folder

    def get_folder(self, folder_id):
        return next((folder for folder in self.folders if folder.id == folder_id), None)

    def assign_folder(self, track_id, folder_id):
        self.assigned = (track_id, folder_id)


def test_folder_names_are_normalized_and_unique(tmp_path):
    repository = FolderRepository(make_track(tmp_path))
    service = LibraryService(repository)
    assert service.create_folder("  Para   estudiar ").name == "Para estudiar"

    with pytest.raises(AppError) as raised:
        service.create_folder("PARA ESTUDIAR")
    assert raised.value.code == ErrorCode.INVALID_INPUT


def test_assign_folder_keeps_track_file_untouched(tmp_path):
    track = make_track(tmp_path)
    repository = FolderRepository(track)
    folder = repository.create_folder("Favoritas")

    LibraryService(repository).assign_folder(track.id, folder.id)

    assert repository.assigned == (track.id, folder.id)
    assert (tmp_path / "track.mp3").is_file()
