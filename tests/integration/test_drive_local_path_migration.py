"""Regression: migration 004 was edited after being applied, so real databases
created before that edit lacked drive_tracks.local_path and every Drive sync
crashed. Fresh-database tests could never catch it."""

from __future__ import annotations

import sqlite3

from ytmp3studio.backend.google_drive_service import (
    DriveFolder,
    DriveLibrarySnapshot,
    DriveTrack,
)
from ytmp3studio.persistence.database import Database
from ytmp3studio.persistence.drive_repository import DriveRepository


def _database_as_shipped_before_local_path(path) -> None:
    """Recreate the exact schema a user upgrading from 004 already has on disk."""
    connection = sqlite3.connect(str(path))
    connection.executescript(
        """
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        );
        INSERT INTO schema_migrations(version, applied_at) VALUES
            (1, '2026-07-20T09:00:34.514Z'),
            (2, '2026-07-20T10:32:39.596Z'),
            (3, '2026-07-20T13:32:11.667Z'),
            (4, '2026-07-22T09:53:47.499Z');

        CREATE TABLE settings (
            key         TEXT PRIMARY KEY,
            value_json  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );

        CREATE TABLE drive_connection (
            id                  INTEGER PRIMARY KEY CHECK (id = 1),
            account_email       TEXT,
            account_name        TEXT,
            root_folder_id      TEXT,
            changes_token       TEXT,
            last_synced_at      TEXT,
            revision            INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
            last_error          TEXT
        );

        CREATE TABLE drive_folders (
            file_id             TEXT PRIMARY KEY,
            parent_file_id      TEXT,
            name                TEXT NOT NULL,
            modified_time       TEXT,
            FOREIGN KEY (parent_file_id) REFERENCES drive_folders(file_id) ON DELETE CASCADE
        );
        CREATE INDEX idx_drive_folders_parent ON drive_folders(parent_file_id);

        -- The shape that shipped in 004: no local_path column.
        CREATE TABLE drive_tracks (
            file_id             TEXT PRIMARY KEY,
            folder_id           TEXT NOT NULL REFERENCES drive_folders(file_id) ON DELETE CASCADE,
            name                TEXT NOT NULL,
            mime_type           TEXT NOT NULL,
            size_bytes          INTEGER CHECK (size_bytes IS NULL OR size_bytes >= 0),
            modified_time       TEXT,
            web_view_link       TEXT,
            checksum            TEXT
        );
        CREATE INDEX idx_drive_tracks_folder ON drive_tracks(folder_id, name COLLATE NOCASE);

        INSERT INTO drive_folders(file_id, parent_file_id, name) VALUES
            ('root-drive', NULL, 'YT-MP3 Studio'),
            ('folder-rock', 'root-drive', 'Rock');
        INSERT INTO drive_tracks(file_id, folder_id, name, mime_type, size_bytes)
            VALUES ('track-old', 'folder-rock', 'Antigua.mp3', 'audio/mpeg', 111);
        """
    )
    connection.commit()
    connection.close()


def test_upgrading_an_existing_database_adds_local_path(tmp_path) -> None:
    path = tmp_path / "ytmp3studio.db"
    _database_as_shipped_before_local_path(path)
    database = Database(path)

    assert database.migrate() == [5]

    with database.connection() as connection:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(drive_tracks)")]
    assert "local_path" in columns
    database.close()


def test_existing_catalog_rows_survive_the_upgrade(tmp_path) -> None:
    path = tmp_path / "ytmp3studio.db"
    _database_as_shipped_before_local_path(path)
    database = Database(path)

    database.migrate()

    rows = DriveRepository(database).list_tracks("folder-rock")
    assert [row["file_id"] for row in rows] == ["track-old"]
    assert rows[0]["local_path"] is None
    database.close()


def test_drive_sync_no_longer_crashes_after_the_upgrade(tmp_path) -> None:
    path = tmp_path / "ytmp3studio.db"
    _database_as_shipped_before_local_path(path)
    database = Database(path)
    database.migrate()
    repository = DriveRepository(database)
    root = DriveFolder("root-drive", "YT-MP3 Studio", "root")
    descargas = DriveFolder("folder-descargas", "Descargas", root.id)

    status = repository.replace_snapshot(
        DriveLibrarySnapshot(
            root_folder=root,
            folders=(descargas,),
            tracks=(
                DriveTrack(
                    "track-new",
                    "Cancion.mp3",
                    descargas.id,
                    "audio/mpeg",
                    222,
                    local_path=r"F:\Mi unidad\YT-MP3 Studio\Descargas\Cancion.mp3",
                ),
            ),
            changes_token="changes-after-upgrade",
        ),
        account_email=None,
        account_name="Google Drive para ordenador",
    )

    assert status["error"] is None
    assert status["track_count"] == 1
    assert repository.list_tracks("folder-descargas")[0]["local_path"].endswith("Cancion.mp3")
    database.close()


def test_a_brand_new_database_is_unaffected(tmp_path) -> None:
    database = Database(tmp_path / "fresh.db")

    assert database.migrate() == [1, 2, 3, 4, 5]

    with database.connection() as connection:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(drive_tracks)")]
    assert "local_path" in columns
    database.close()
