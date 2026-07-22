"""Persistent local catalog for the user's dedicated Google Drive folder."""

from __future__ import annotations

from typing import Any

from ytmp3studio.backend.google_drive_service import DriveLibrarySnapshot

from .database import Database, utc_now


LOOSE_FOLDER_NAME = "Sin carpeta"


class DriveRepository:
    """Atomically replace and query the Drive catalog without storing OAuth tokens."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def replace_snapshot(
        self,
        snapshot: DriveLibrarySnapshot,
        *,
        account_email: str | None,
        account_name: str | None = None,
    ) -> dict[str, Any]:
        root = snapshot.root_folder
        folders = (root, *snapshot.folders)
        now = utc_now()
        with self.database.transaction() as connection:
            previous = connection.execute(
                "SELECT revision FROM drive_connection WHERE id = 1"
            ).fetchone()
            revision = (int(previous["revision"]) if previous else 0) + 1
            connection.execute("DELETE FROM drive_tracks")
            connection.execute("DELETE FROM drive_folders")
            for folder in folders:
                connection.execute(
                    """
                    INSERT INTO drive_folders(file_id, parent_file_id, name, modified_time)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        folder.id,
                        None if folder.id == root.id else folder.parent_id,
                        folder.name,
                        folder.modified_time,
                    ),
                )
            connection.executemany(
                """
                INSERT INTO drive_tracks(
                    file_id, folder_id, name, mime_type, size_bytes,
                    modified_time, web_view_link, checksum, local_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        track.id,
                        track.folder_id,
                        track.name,
                        track.mime_type,
                        track.size_bytes,
                        track.modified_time,
                        track.web_view_link,
                        track.checksum,
                        track.local_path,
                    )
                    for track in snapshot.tracks
                ),
            )
            connection.execute(
                """
                INSERT INTO drive_connection(
                    id, account_email, account_name, root_folder_id,
                    changes_token, last_synced_at, revision, last_error
                ) VALUES (1, ?, ?, ?, ?, ?, ?, NULL)
                ON CONFLICT(id) DO UPDATE SET
                    account_email = excluded.account_email,
                    account_name = excluded.account_name,
                    root_folder_id = excluded.root_folder_id,
                    changes_token = excluded.changes_token,
                    last_synced_at = excluded.last_synced_at,
                    revision = excluded.revision,
                    last_error = NULL
                """,
                (
                    account_email,
                    account_name,
                    root.id,
                    snapshot.changes_token,
                    now,
                    revision,
                ),
            )
        return self.status(connected=True)

    def status(self, *, connected: bool) -> dict[str, Any]:
        with self.database.connection() as connection:
            state = connection.execute(
                "SELECT * FROM drive_connection WHERE id = 1"
            ).fetchone()
            folders = connection.execute(
                """
                SELECT f.file_id, f.name, f.parent_file_id, COUNT(t.file_id) AS track_count
                FROM drive_folders f
                LEFT JOIN drive_tracks t ON t.folder_id = f.file_id
                WHERE f.parent_file_id IS NOT NULL
                GROUP BY f.file_id, f.name, f.parent_file_id
                ORDER BY CASEFOLD(f.name), f.file_id
                """
            ).fetchall()
            loose = connection.execute(
                """
                SELECT f.file_id, COUNT(t.file_id) AS track_count
                FROM drive_folders f
                LEFT JOIN drive_tracks t ON t.folder_id = f.file_id
                WHERE f.parent_file_id IS NULL
                GROUP BY f.file_id
                """
            ).fetchone()
            total = connection.execute("SELECT COUNT(*) FROM drive_tracks").fetchone()[0]
        listed = [
            {
                "id": row["file_id"],
                "name": row["name"],
                "parent_id": row["parent_file_id"],
                "track_count": int(row["track_count"]),
            }
            for row in folders
        ]
        # Tracks dropped straight into the linked folder still need a playlist.
        if loose is not None and int(loose["track_count"]):
            listed.insert(
                0,
                {
                    "id": loose["file_id"],
                    "name": LOOSE_FOLDER_NAME,
                    "parent_id": None,
                    "track_count": int(loose["track_count"]),
                },
            )
        return {
            "connected": bool(connected),
            "account_email": state["account_email"] if state else None,
            "account_name": state["account_name"] if state else None,
            "folder_name": "YT-MP3 Studio",
            "root_folder_id": state["root_folder_id"] if state else None,
            "last_sync_at": state["last_synced_at"] if state else None,
            "revision": int(state["revision"]) if state else 0,
            "track_count": int(total),
            "folders": listed,
            "error": state["last_error"] if state else None,
        }

    def list_tracks(self, folder_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM drive_tracks"
        params: tuple[str, ...] = ()
        if folder_id:
            query += " WHERE folder_id = ?"
            params = (folder_id,)
        query += " ORDER BY CASEFOLD(name), file_id"
        with self.database.connection() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def changes_token(self) -> str | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT changes_token FROM drive_connection WHERE id = 1"
            ).fetchone()
        return None if row is None else row["changes_token"]

    def record_error(self, message: str) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO drive_connection(id, last_error)
                VALUES (1, ?)
                ON CONFLICT(id) DO UPDATE SET last_error = excluded.last_error
                """,
                (message[:500],),
            )

    def clear(self) -> None:
        with self.database.transaction() as connection:
            connection.execute("DELETE FROM drive_connection")
            connection.execute("DELETE FROM drive_tracks")
            connection.execute("DELETE FROM drive_folders")
