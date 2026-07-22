from __future__ import annotations

from ytmp3studio.backend.google_drive_service import (
    DriveFolder,
    DriveLibrarySnapshot,
    DriveTrack,
)
from ytmp3studio.persistence.database import Database
from ytmp3studio.persistence.drive_repository import DriveRepository


def snapshot(token: str = "changes-1") -> DriveLibrarySnapshot:
    root = DriveFolder("root-drive", "YT-MP3 Studio", "root")
    rock = DriveFolder("folder-rock", "Rock", root.id)
    return DriveLibrarySnapshot(
        root_folder=root,
        folders=(rock,),
        tracks=(
            DriveTrack("track-1", "Song.mp3", rock.id, "audio/mpeg", 123),
        ),
        changes_token=token,
    )


def test_drive_snapshot_is_atomic_queryable_and_revisioned(tmp_path) -> None:
    database = Database(tmp_path / "drive.db")
    assert database.migrate() == [1, 2, 3, 4]
    repository = DriveRepository(database)

    first = repository.replace_snapshot(
        snapshot(), account_email="me@example.test", account_name="Gerard"
    )
    second = repository.replace_snapshot(
        snapshot("changes-2"), account_email="me@example.test", account_name="Gerard"
    )

    assert first["revision"] == 1
    assert second["revision"] == 2
    assert second["track_count"] == 1
    assert second["folders"] == [
        {"id": "folder-rock", "name": "Rock", "parent_id": "root-drive", "track_count": 1}
    ]
    assert repository.changes_token() == "changes-2"
    assert repository.list_tracks("folder-rock")[0]["file_id"] == "track-1"


def test_drive_disconnect_clears_catalog_without_touching_other_tables(tmp_path) -> None:
    database = Database(tmp_path / "drive.db")
    database.migrate()
    repository = DriveRepository(database)
    repository.replace_snapshot(snapshot(), account_email="me@example.test")

    repository.clear()

    assert repository.status(connected=False)["track_count"] == 0
    assert repository.list_tracks() == []
