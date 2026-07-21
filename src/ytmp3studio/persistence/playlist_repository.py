"""Persistence for playlists imported from Exportify.

The repository deliberately owns the synchronization transaction: callers
never observe a playlist whose metadata and membership came from different
CSV imports.
"""

from __future__ import annotations

from collections.abc import Sequence
import sqlite3
from uuid import uuid4

from ytmp3studio.domain.models import (
    Playlist,
    PlaylistEntry,
    PlaylistImportError,
    PlaylistItem,
    PlaylistSyncResult,
    PlaylistTrackState,
    SpotifyTrack,
)

from .database import Database, utc_now


class PlaylistRepository:
    def __init__(self, database: Database):
        self.database = database

    def upsert_playlist(
        self, playlist: Playlist, *, connection: sqlite3.Connection | None = None
    ) -> Playlist:
        if not playlist.source_key.strip():
            raise ValueError("playlist source_key cannot be empty")
        if not playlist.name.strip():
            raise ValueError("playlist name cannot be empty")
        if connection is None:
            with self.database.transaction() as active:
                playlist_id = self._upsert_playlist(active, playlist)
        else:
            playlist_id = self._upsert_playlist(connection, playlist)
            row = connection.execute(
                self._playlist_select() + " WHERE p.id = ?", (playlist_id,)
            ).fetchone()
            if row is None:  # pragma: no cover - same-transaction invariant
                raise RuntimeError("playlist disappeared after upsert")
            return self._playlist(row)
        result = self.get(playlist_id)
        if result is None:  # pragma: no cover - protects against external DB mutation
            raise RuntimeError("playlist disappeared after upsert")
        return result

    save_playlist = upsert_playlist

    def get(self, playlist_id: str) -> Playlist | None:
        return self._get_one("p.id = ?", (playlist_id,))

    def get_by_source_key(self, source_key: str) -> Playlist | None:
        return self._get_one("p.source_key = ?", (source_key,))

    def get_by_spotify_uri(self, spotify_uri: str) -> Playlist | None:
        return self._get_one("p.spotify_uri = ?", (spotify_uri,))

    def list(self) -> list[Playlist]:
        with self.database.connection() as connection:
            rows = connection.execute(self._playlist_select() + " ORDER BY CASEFOLD(p.name), p.id").fetchall()
        return [self._playlist(row) for row in rows]

    list_all = list
    list_playlists = list

    def sync_playlist(
        self,
        playlist: Playlist,
        tracks: Sequence[SpotifyTrack],
        *,
        default_state: PlaylistTrackState = PlaylistTrackState.PENDING,
    ) -> PlaylistSyncResult:
        """Replace membership with one Exportify snapshot while retaining state.

        Track identity first uses ``track_key`` and then Spotify URI. Reimported
        items retain their download/error state; new items start in
        ``default_state``. Duplicate identities in one snapshot are rejected,
        because one playlist/track association has exactly one position.
        """

        now = utc_now()
        with self.database.transaction() as connection:
            playlist_id = self._upsert_playlist(connection, playlist)
            canonical_keys: list[str] = []
            for track in tracks:
                canonical_keys.append(self._upsert_track(connection, track))
            if len(set(canonical_keys)) != len(canonical_keys):
                raise ValueError("a playlist snapshot contains duplicate track identities")

            existing = {
                row["track_key"]: row
                for row in connection.execute(
                    "SELECT * FROM playlist_items WHERE playlist_id = ?",
                    (playlist_id,),
                )
            }
            incoming = set(canonical_keys)
            removed = len(set(existing) - incoming)
            retained = len(set(existing) & incoming)
            added = len(incoming - set(existing))

            if canonical_keys:
                connection.execute(
                    "DELETE FROM playlist_items WHERE playlist_id = ? AND track_key NOT IN ("
                    + ", ".join("?" for _ in canonical_keys)
                    + ")",
                    (playlist_id, *canonical_keys),
                )
            else:
                connection.execute(
                    "DELETE FROM playlist_items WHERE playlist_id = ?", (playlist_id,)
                )
            # Avoid transient UNIQUE(position) collisions when tracks reorder.
            connection.execute(
                "UPDATE playlist_items SET position = position + 1000000000 WHERE playlist_id = ?",
                (playlist_id,),
            )
            for position, track_key in enumerate(canonical_keys):
                prior = existing.get(track_key)
                connection.execute(
                    """
                    INSERT INTO playlist_items(
                        playlist_id, track_key, position, state, added_at,
                        error_code, error_message, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(playlist_id, track_key) DO UPDATE SET
                        position = excluded.position,
                        updated_at = excluded.updated_at
                    """,
                    (
                        playlist_id,
                        track_key,
                        position,
                        default_state.value if prior is None else prior["state"],
                        None if prior is None else prior["added_at"],
                        None if prior is None else prior["error_code"],
                        None if prior is None else prior["error_message"],
                        now,
                    ),
                )
            connection.execute(
                "UPDATE playlists SET last_synced_at = ?, updated_at = ? WHERE id = ?",
                (now, now, playlist_id),
            )

        return PlaylistSyncResult(playlist_id, added, retained, removed, len(canonical_keys))

    sync = sync_playlist

    def list_entries(self, playlist_id: str) -> list[PlaylistEntry]:
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT i.playlist_id, i.track_key, i.position, i.state, i.added_at,
                       i.error_code, i.error_message, i.updated_at AS item_updated_at,
                       t.spotify_uri, t.title, t.artist, t.album, t.duration_ms,
                       t.isrc, t.album_image_url, t.library_track_id,
                       t.current_job_id,
                       t.created_at, t.updated_at
                FROM playlist_items AS i
                JOIN spotify_tracks AS t ON t.track_key = i.track_key
                WHERE i.playlist_id = ?
                ORDER BY i.position
                """,
                (playlist_id,),
            ).fetchall()
        return [self._entry(row) for row in rows]

    def get_track(self, track_key: str) -> SpotifyTrack | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM spotify_tracks WHERE track_key = ?", (track_key,)
            ).fetchone()
        return None if row is None else SpotifyTrack(**dict(row))

    def update_item_state(
        self,
        playlist_id: str,
        track_key: str,
        state: PlaylistTrackState,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> bool:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE playlist_items
                SET state = ?, error_code = ?, error_message = ?, updated_at = ?
                WHERE playlist_id = ? AND track_key = ?
                """,
                (state.value, error_code, error_message, utc_now(), playlist_id, track_key),
            )
        return cursor.rowcount > 0

    def link_library_track(self, track_key: str, library_track_id: str | None) -> bool:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE spotify_tracks SET library_track_id = ?, updated_at = ? WHERE track_key = ?",
                (library_track_id, utc_now(), track_key),
            )
        return cursor.rowcount > 0

    def bind_job(self, track_key: str, job_id: str) -> bool:
        """Bind one shared Spotify track to a download and queue all occurrences."""

        now = utc_now()
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE spotify_tracks SET current_job_id = ?, updated_at = ? WHERE track_key = ?",
                (job_id, now, track_key),
            )
            if cursor.rowcount:
                connection.execute(
                    """
                    UPDATE playlist_items SET state = 'queued', error_code = NULL,
                        error_message = NULL, updated_at = ? WHERE track_key = ?
                    """,
                    (now, track_key),
                )
        return cursor.rowcount > 0

    def complete_job(self, job_id: str, library_track_id: str) -> bool:
        """Attach the downloaded file and complete every playlist occurrence."""

        now = utc_now()
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT track_key FROM spotify_tracks WHERE current_job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                return False
            track_key = row["track_key"]
            connection.execute(
                """
                UPDATE spotify_tracks SET library_track_id = ?, current_job_id = NULL,
                    updated_at = ? WHERE track_key = ?
                """,
                (library_track_id, now, track_key),
            )
            connection.execute(
                """
                UPDATE playlist_items SET state = 'downloaded', error_code = NULL,
                    error_message = NULL, updated_at = ? WHERE track_key = ?
                """,
                (now, track_key),
            )
        return True

    def mark_failed(self, job_id: str, error_code: str, error_message: str) -> bool:
        now = utc_now()
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT track_key FROM spotify_tracks WHERE current_job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                return False
            track_key = row["track_key"]
            connection.execute(
                "UPDATE spotify_tracks SET current_job_id = NULL, updated_at = ? WHERE track_key = ?",
                (now, track_key),
            )
            connection.execute(
                """
                UPDATE playlist_items SET state = 'failed', error_code = ?,
                    error_message = ?, updated_at = ? WHERE track_key = ?
                """,
                (error_code, error_message, now, track_key),
            )
        return True

    def release_job(
        self,
        job_id: str,
        *,
        state: PlaylistTrackState = PlaylistTrackState.PENDING,
    ) -> bool:
        """Detach a cancelled job and make all its playlist items selectable again."""

        now = utc_now()
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT track_key FROM spotify_tracks WHERE current_job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                return False
            track_key = row["track_key"]
            connection.execute(
                "UPDATE spotify_tracks SET current_job_id = NULL, updated_at = ? WHERE track_key = ?",
                (now, track_key),
            )
            connection.execute(
                """
                UPDATE playlist_items SET state = ?, error_code = NULL,
                    error_message = NULL, updated_at = ?
                WHERE track_key = ? AND state = 'queued'
                """,
                (state.value, now, track_key),
            )
        return True

    def update_state(
        self,
        track_key: str,
        state: PlaylistTrackState,
        *,
        playlist_id: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> int:
        """Update one track in one playlist, or all playlists when ID is omitted."""

        where = "track_key = ?"
        parameters: list[object] = [track_key]
        if playlist_id is not None:
            where += " AND playlist_id = ?"
            parameters.append(playlist_id)
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE playlist_items SET state = ?, error_code = ?, error_message = ?, "
                "updated_at = ? WHERE " + where,
                (state.value, error_code, error_message, utc_now(), *parameters),
            )
        return cursor.rowcount

    def update_cover(
        self,
        playlist_id: str,
        *,
        url: str | None,
        path: str | None,
        etag: str | None = None,
        updated_at: str | None = None,
    ) -> bool:
        timestamp = updated_at or utc_now()
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE playlists SET cover_url = ?, cover_path = ?, cover_etag = ?,
                    cover_updated_at = ?, updated_at = ? WHERE id = ?
                """,
                (url, path, etag, timestamp, timestamp, playlist_id),
            )
        return cursor.rowcount > 0

    set_cover = update_cover

    def add_error(
        self,
        error_code: str,
        message: str,
        *,
        playlist_id: str | None = None,
        row_number: int | None = None,
        track_key: str | None = None,
        detail: str | None = None,
    ) -> PlaylistImportError:
        created_at = utc_now()
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO playlist_import_errors(
                    playlist_id, row_number, track_key, error_code,
                    message, detail, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (playlist_id, row_number, track_key, error_code, message, detail, created_at),
            )
            error_id = int(cursor.lastrowid)
        return PlaylistImportError(
            error_id, playlist_id, error_code, message, created_at,
            row_number, track_key, detail,
        )

    def list_errors(
        self, *, playlist_id: str | None = None, unresolved_only: bool = False
    ) -> list[PlaylistImportError]:
        conditions: list[str] = []
        parameters: list[object] = []
        if playlist_id is not None:
            conditions.append("playlist_id = ?")
            parameters.append(playlist_id)
        if unresolved_only:
            conditions.append("resolved_at IS NULL")
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM playlist_import_errors" + where + " ORDER BY id", parameters
            ).fetchall()
        return [PlaylistImportError(**dict(row)) for row in rows]

    def resolve_error(self, error_id: int, *, resolved_at: str | None = None) -> bool:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE playlist_import_errors SET resolved_at = ? WHERE id = ?",
                (resolved_at or utc_now(), error_id),
            )
        return cursor.rowcount > 0

    def delete(self, playlist_id: str) -> bool:
        with self.database.transaction() as connection:
            cursor = connection.execute("DELETE FROM playlists WHERE id = ?", (playlist_id,))
        return cursor.rowcount > 0

    def _upsert_playlist(self, connection: sqlite3.Connection, playlist: Playlist) -> str:
        row = connection.execute(
            """
            SELECT id FROM playlists
            WHERE source_key = ? OR (spotify_uri IS NOT NULL AND spotify_uri = ?)
            ORDER BY CASE WHEN source_key = ? THEN 0 ELSE 1 END LIMIT 1
            """,
            (playlist.source_key, playlist.spotify_uri, playlist.source_key),
        ).fetchone()
        playlist_id = playlist.id if row is None else row["id"]
        if row is None:
            connection.execute(
                """
                INSERT INTO playlists(
                    id, source_key, spotify_uri, name, description, owner,
                    is_liked_songs, cover_url, cover_path, cover_etag,
                    cover_updated_at, last_synced_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    playlist_id, playlist.source_key, playlist.spotify_uri, playlist.name,
                    playlist.description, playlist.owner, int(playlist.is_liked_songs),
                    playlist.cover_url, playlist.cover_path, playlist.cover_etag,
                    playlist.cover_updated_at, playlist.last_synced_at,
                    playlist.created_at, playlist.updated_at,
                ),
            )
        else:
            connection.execute(
                """
                UPDATE playlists SET source_key = ?, spotify_uri = ?, name = ?,
                    description = ?, owner = ?, is_liked_songs = ?,
                    cover_url = COALESCE(?, cover_url),
                    cover_path = COALESCE(?, cover_path),
                    cover_etag = COALESCE(?, cover_etag),
                    cover_updated_at = COALESCE(?, cover_updated_at),
                    last_synced_at = COALESCE(?, last_synced_at), updated_at = ?
                WHERE id = ?
                """,
                (
                    playlist.source_key, playlist.spotify_uri, playlist.name,
                    playlist.description, playlist.owner, int(playlist.is_liked_songs),
                    playlist.cover_url, playlist.cover_path, playlist.cover_etag,
                    playlist.cover_updated_at, playlist.last_synced_at,
                    playlist.updated_at, playlist_id,
                ),
            )
        return playlist_id

    @staticmethod
    def _upsert_track(connection: sqlite3.Connection, track: SpotifyTrack) -> str:
        if not track.track_key.strip():
            raise ValueError("track_key cannot be empty")
        row = connection.execute(
            """
            SELECT track_key FROM spotify_tracks
            WHERE track_key = ? OR (spotify_uri IS NOT NULL AND spotify_uri = ?)
            ORDER BY CASE WHEN track_key = ? THEN 0 ELSE 1 END LIMIT 1
            """,
            (track.track_key, track.spotify_uri, track.track_key),
        ).fetchone()
        canonical_key = track.track_key if row is None else row["track_key"]
        if row is None:
            connection.execute(
                """
                INSERT INTO spotify_tracks(
                    track_key, spotify_uri, title, artist, album, duration_ms,
                    isrc, album_image_url, library_track_id, current_job_id,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    canonical_key, track.spotify_uri, track.title, track.artist,
                    track.album, track.duration_ms, track.isrc, track.album_image_url,
                    track.library_track_id, track.current_job_id,
                    track.created_at, track.updated_at,
                ),
            )
        else:
            connection.execute(
                """
                UPDATE spotify_tracks SET spotify_uri = ?, title = ?, artist = ?,
                    album = ?, duration_ms = ?, isrc = ?, album_image_url = ?,
                    library_track_id = COALESCE(?, library_track_id), updated_at = ?
                WHERE track_key = ?
                """,
                (
                    track.spotify_uri, track.title, track.artist, track.album,
                    track.duration_ms, track.isrc, track.album_image_url,
                    track.library_track_id, track.updated_at, canonical_key,
                ),
            )
        return canonical_key

    def _get_one(self, where: str, parameters: tuple[object, ...]) -> Playlist | None:
        with self.database.connection() as connection:
            row = connection.execute(self._playlist_select() + " WHERE " + where, parameters).fetchone()
        return None if row is None else self._playlist(row)

    @staticmethod
    def _playlist_select() -> str:
        return """
            SELECT p.*, (
                SELECT COUNT(*) FROM playlist_items AS i WHERE i.playlist_id = p.id
            ) AS track_count
            FROM playlists AS p
        """

    @staticmethod
    def _playlist(row: sqlite3.Row) -> Playlist:
        values = dict(row)
        values["is_liked_songs"] = bool(values["is_liked_songs"])
        return Playlist(**values)

    @staticmethod
    def _entry(row: sqlite3.Row) -> PlaylistEntry:
        values = dict(row)
        item = PlaylistItem(
            playlist_id=values["playlist_id"], track_key=values["track_key"],
            position=values["position"], state=PlaylistTrackState(values["state"]),
            added_at=values["added_at"], error_code=values["error_code"],
            error_message=values["error_message"], updated_at=values["item_updated_at"],
        )
        track = SpotifyTrack(
            track_key=values["track_key"], spotify_uri=values["spotify_uri"],
            title=values["title"], artist=values["artist"], album=values["album"],
            duration_ms=values["duration_ms"], isrc=values["isrc"],
            album_image_url=values["album_image_url"],
            library_track_id=values["library_track_id"],
            current_job_id=values["current_job_id"],
            created_at=values["created_at"], updated_at=values["updated_at"],
        )
        return PlaylistEntry(item, track)


def new_playlist(source_key: str, name: str, **metadata: object) -> Playlist:
    """Convenience constructor for importers that do not own an ID policy."""

    now = utc_now()
    return Playlist(str(uuid4()), source_key, name, now, now, **metadata)
