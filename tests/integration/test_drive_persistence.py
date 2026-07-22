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


def test_loose_tracks_in_the_linked_folder_get_their_own_playlist(tmp_path) -> None:
    database = Database(tmp_path / "drive.db")
    database.migrate()
    repository = DriveRepository(database)
    root = DriveFolder("root-drive", "YT-MP3 Studio", "root")
    rock = DriveFolder("folder-rock", "Rock", root.id)

    status = repository.replace_snapshot(
        DriveLibrarySnapshot(
            root_folder=root,
            folders=(rock,),
            tracks=(
                DriveTrack("track-1", "Song.mp3", rock.id, "audio/mpeg", 123),
                DriveTrack("track-2", "Suelta.mp3", root.id, "audio/mpeg", 456),
            ),
            changes_token="changes-loose",
        ),
        account_email=None,
        account_name="Google Drive para ordenador",
    )

    assert [folder["name"] for folder in status["folders"]] == ["Sin carpeta", "Rock"]
    assert status["folders"][0] == {
        "id": "root-drive",
        "name": "Sin carpeta",
        "parent_id": None,
        "track_count": 1,
    }
    assert [track["file_id"] for track in repository.list_tracks("root-drive")] == ["track-2"]


def test_empty_root_is_not_listed_as_a_playlist(tmp_path) -> None:
    database = Database(tmp_path / "drive.db")
    database.migrate()
    repository = DriveRepository(database)

    status = repository.replace_snapshot(
        snapshot(), account_email=None, account_name="Google Drive para ordenador"
    )

    assert [folder["name"] for folder in status["folders"]] == ["Rock"]


def test_drive_disconnect_clears_catalog_without_touching_other_tables(tmp_path) -> None:
    database = Database(tmp_path / "drive.db")
    database.migrate()
    repository = DriveRepository(database)
    repository.replace_snapshot(snapshot(), account_email="me@example.test")

    repository.clear()

    assert repository.status(connected=False)["track_count"] == 0
    assert repository.list_tracks() == []
