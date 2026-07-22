from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sqlite3

import pytest

from ytmp3studio.domain.models import DownloadJob, JobState, LibraryTrack, Settings
from ytmp3studio.persistence.database import Database
from ytmp3studio.persistence.repositories import (
    DownloadJobRepository,
    HistoryRepository,
    LibraryRepository,
    SettingsRepository,
)


@pytest.fixture
def database(tmp_path):
    database = Database(tmp_path / "app.db")
    assert database.migrate() == [1, 2, 3, 4]
    return database


def make_job(identifier: str = "job-1", state: JobState = JobState.QUEUED):
    return DownloadJob(
        id=identifier,
        video_id="abc123",
        source_url="https://www.youtube.com/watch?v=abc123",
        title="Una canción",
        channel="Un canal",
        quality_kbps=192,
        output_dir="C:/Music",
        temp_dir=f"C:/Music/.ytmp3studio-tmp/{identifier}",
        state=state,
        attempt_count=0,
        max_attempts=3,
        created_at="2026-07-20T10:00:00.000Z",
        updated_at="2026-07-20T10:00:00.000Z",
    )


def make_track(identifier: str = "track-1", job_id: str | None = None):
    return LibraryTrack(
        id=identifier,
        job_id=job_id,
        video_id="abc123",
        source_url="https://www.youtube.com/watch?v=abc123",
        title="Canción de prueba",
        channel="Canal único",
        file_path=f"C:/Music/{identifier}.mp3",
        file_size_bytes=1234,
        quality_kbps=192,
        created_at="2026-07-20T10:10:00.000Z",
    )


def test_empty_database_migrates_idempotently_and_enables_pragmas(database):
    assert database.migrate() == []

    with database.connection() as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        assert [row[0] for row in connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()] == [1, 2, 3, 4]

    settings = SettingsRepository(database).get()
    assert settings.quality_kbps == 192
    assert settings.theme == "system"
    assert settings.concurrency == 2
    assert settings.download_dir.endswith("YT-MP3 Studio")


def test_job_crud_enum_roundtrip_and_recovery(database):
    repository = DownloadJobRepository(database)
    queued = make_job()
    assert repository.add(queued) == queued
    assert repository.get(queued.id) == queued

    downloading = replace(queued, state=JobState.DOWNLOADING)
    assert repository.update(downloading) == downloading
    assert repository.recover_interrupted() == 1

    recovered = repository.get(queued.id)
    assert recovered is not None
    assert recovered.state is JobState.INTERRUPTED
    assert recovered.error_code == "DOWNLOAD_FAILED"
    assert repository.list() == [recovered]

    repository.delete(queued.id)
    assert repository.get(queued.id) is None


def test_job_partial_update_rejects_unknown_columns(database):
    repository = DownloadJobRepository(database)
    repository.add(make_job())
    assert repository.update_fields("job-1", {"progress_percent": 42.5})
    assert repository.get("job-1").progress_percent == 42.5

    with pytest.raises(ValueError, match="Unknown download job fields"):
        repository.update_fields("job-1", {"surprise": True})


def test_library_filter_pagination_history_and_foreign_key(database):
    jobs = DownloadJobRepository(database)
    library = LibraryRepository(database)
    history = HistoryRepository(database)
    jobs.add(make_job())
    track = make_track(job_id="job-1")
    assert library.add(track) == track

    tracks, total = library.list("ÚNICO", 20, 0)
    assert tracks == [track]
    assert total == 1
    assert library.list("no existe", 20, 0) == ([], 0)

    history.add("job-1", "abc123", "completed", {"track_id": track.id})
    assert history.list(job_id="job-1")[0]["detail"] == {"track_id": track.id}

    jobs.delete("job-1")
    assert library.get(track.id).job_id is None
    assert history.list()[0]["job_id"] is None


def test_settings_roundtrip_is_atomic(database):
    repository = SettingsRepository(database)
    changed = replace(
        repository.get(), quality_kbps=320, theme="dark", concurrency=4
    )
    assert repository.update(changed) == changed
    assert repository.get() == changed

    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as connection:
            repository.update_values({"theme": "light"}, connection=connection)
            connection.execute(
                "INSERT INTO settings(key, value_json, updated_at) VALUES (?, ?, ?)",
                ("theme", '"system"', "2026-07-20T10:00:00.000Z"),
            )

    assert repository.get().theme == "dark"


def test_library_unique_file_path_rolls_back_transaction(database):
    repository = LibraryRepository(database)
    first = make_track("first")
    duplicate = replace(make_track("second"), file_path=first.file_path)

    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as connection:
            repository.add(first, connection=connection)
            repository.add(duplicate, connection=connection)

    assert repository.list("", 20, 0) == ([], 0)


def test_library_folders_organize_tracks_without_moving_files(database):
    repository = LibraryRepository(database)
    track = make_track("folder-track")
    repository.add(track)
    folder = repository.create_folder("Favoritas")

    repository.assign_folder(track.id, folder.id)
    assigned = repository.get(track.id)
    assert assigned.folder_id == folder.id
    assert repository.list("", 20, 0, folder.id)[0] == [assigned]
    assert repository.list("", 20, 0, "") == ([], 0)
    assert repository.list_folders()[0].track_count == 1

    renamed = repository.rename_folder(folder.id, "Para estudiar")
    assert renamed.name == "Para estudiar"
    repository.delete_folder(folder.id)
    assert repository.get(track.id).folder_id is None
    assert repository.get(track.id).file_path == track.file_path


def test_close_checkpoint_releases_database_files_on_windows(tmp_path):
    database = Database(tmp_path / "closable.db")
    database.migrate()
    SettingsRepository(database).get()

    database.close()

    moved = tmp_path / "moved.db"
    database.path.replace(moved)
    assert moved.is_file()
    assert not Path(str(database.path) + "-wal").exists()
    assert not Path(str(database.path) + "-shm").exists()
