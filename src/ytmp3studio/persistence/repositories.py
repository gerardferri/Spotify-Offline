"""Repository implementations over :mod:`sqlite3`.

Repositories return plain dictionaries by default.  A domain constructor may
be supplied as ``model_factory`` (for example ``DownloadJob.from_record``),
which keeps this layer independent from Qt and from concrete domain classes.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
import json
from pathlib import Path
import sqlite3
from typing import Any, TypeVar
from uuid import uuid4

from ytmp3studio.domain.models import DownloadJob, JobState, LibraryFolder, LibraryTrack, Settings

from .database import Database, utc_now


Record = dict[str, Any]
T = TypeVar("T")
ModelFactory = Callable[[Record], T]


DOWNLOAD_JOB_COLUMNS = (
    "id",
    "video_id",
    "source_url",
    "title",
    "channel",
    "thumbnail_url",
    "duration_seconds",
    "quality_kbps",
    "output_dir",
    "temp_dir",
    "state",
    "attempt_count",
    "max_attempts",
    "downloaded_bytes",
    "total_bytes",
    "progress_percent",
    "error_code",
    "error_message",
    "next_retry_at",
    "created_at",
    "started_at",
    "finished_at",
    "updated_at",
)

LIBRARY_TRACK_COLUMNS = (
    "id",
    "job_id",
    "video_id",
    "source_url",
    "title",
    "channel",
    "duration_seconds",
    "thumbnail_url",
    "file_path",
    "file_size_bytes",
    "quality_kbps",
    "created_at",
    "last_played_at",
)


class SettingsRepository:
    def __init__(self, database: Database):
        self.database = database

    def get_value(self, key: str, default: Any = None) -> Any:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT value_json FROM settings WHERE key = ?", (key,)
            ).fetchone()
        return default if row is None else json.loads(row["value_json"])

    def get(self) -> Settings:
        values = self.get_all()
        try:
            return Settings(**values)
        except TypeError as exc:
            raise ValueError("Stored settings do not match the domain schema") from exc

    def get_all(self) -> Record:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT key, value_json FROM settings ORDER BY key"
            ).fetchall()
        return {row["key"]: json.loads(row["value_json"]) for row in rows}

    all = get_all

    def set_value(
        self,
        key: str,
        value: Any,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        self.update_values({key: value}, connection=connection)

    def update_values(
        self,
        values: Mapping[str, Any],
        *,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        if not values:
            return
        now = utc_now()
        rows = [
            (str(key), json.dumps(value, ensure_ascii=False), now)
            for key, value in values.items()
        ]
        with _write_connection(self.database, connection) as active:
            active.executemany(
                """
                INSERT INTO settings(key, value_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                rows,
            )

    set_many = update_values

    def update(
        self,
        settings: Settings,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> Settings:
        self.update_values(asdict(settings), connection=connection)
        return settings


class DownloadJobRepository:
    def __init__(
        self,
        database: Database,
        model_factory: ModelFactory[T] | None = None,
    ):
        self.database = database
        self.model_factory = model_factory or _download_job_from_record

    def add(
        self,
        job: object,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> DownloadJob:
        record = _record(job)
        _require(record, DOWNLOAD_JOB_COLUMNS)
        values = [_db_value(record[column]) for column in DOWNLOAD_JOB_COLUMNS]
        placeholders = ", ".join("?" for _ in DOWNLOAD_JOB_COLUMNS)
        with _write_connection(self.database, connection) as active:
            active.execute(
                f"INSERT INTO download_jobs ({', '.join(DOWNLOAD_JOB_COLUMNS)}) "
                f"VALUES ({placeholders})",
                values,
            )

        return job  # type: ignore[return-value]

    create = add

    def update(
        self,
        job: object,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> DownloadJob:
        record = _record(job)
        _require(record, DOWNLOAD_JOB_COLUMNS)
        values = [_db_value(record[column]) for column in DOWNLOAD_JOB_COLUMNS]
        placeholders = ", ".join("?" for _ in DOWNLOAD_JOB_COLUMNS)
        updates = ", ".join(
            f"{column} = excluded.{column}"
            for column in DOWNLOAD_JOB_COLUMNS
            if column != "id"
        )
        with _write_connection(self.database, connection) as active:
            active.execute(
                f"INSERT INTO download_jobs ({', '.join(DOWNLOAD_JOB_COLUMNS)}) "
                f"VALUES ({placeholders}) ON CONFLICT(id) DO UPDATE SET {updates}",
                values,
            )

        return job  # type: ignore[return-value]

    save = update
    upsert = update

    def get(self, job_id: str) -> T | Record | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM download_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return None if row is None else self._result(row)

    get_by_id = get

    def list(
        self,
        states: Iterable[str | Enum] | None = None,
        *,
        include_terminal: bool = True,
    ) -> list[T | Record]:
        conditions: list[str] = []
        parameters: list[Any] = []
        if states is not None:
            normalized = [_db_value(state) for state in states]
            if not normalized:
                return []
            conditions.append("state IN (" + ", ".join("?" for _ in normalized) + ")")
            parameters.extend(normalized)
        if not include_terminal:
            conditions.append("state NOT IN ('completed', 'failed', 'cancelled')")
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM download_jobs"
                + where
                + " ORDER BY created_at ASC, id ASC",
                parameters,
            ).fetchall()
        return [self._result(row) for row in rows]

    list_all = list

    def update_fields(
        self,
        job_id: str,
        changes: Mapping[str, Any] | None = None,
        *,
        connection: sqlite3.Connection | None = None,
        **fields: Any,
    ) -> bool:
        updates = dict(changes or {})
        updates.update(fields)
        updates.pop("id", None)
        unknown = set(updates) - set(DOWNLOAD_JOB_COLUMNS)
        if unknown:
            raise ValueError(f"Unknown download job fields: {sorted(unknown)}")
        if not updates:
            return False
        if "updated_at" not in updates:
            updates["updated_at"] = utc_now()
        assignments = ", ".join(f"{name} = ?" for name in updates)
        values = [_db_value(value) for value in updates.values()]
        with _write_connection(self.database, connection) as active:
            cursor = active.execute(
                f"UPDATE download_jobs SET {assignments} WHERE id = ?",
                [*values, job_id],
            )
        return cursor.rowcount > 0

    def mark_active_interrupted(
        self, *, connection: sqlite3.Connection | None = None
    ) -> int:
        """Recover jobs left active by an unclean process shutdown."""

        now = utc_now()
        with _write_connection(self.database, connection) as active:
            cursor = active.execute(
                """
                UPDATE download_jobs
                SET state = 'interrupted', updated_at = ?,
                    error_code = COALESCE(error_code, 'DOWNLOAD_FAILED'),
                    error_message = COALESCE(
                        error_message, 'La descarga fue interrumpida al cerrar la aplicación.'
                    )
                WHERE state IN (
                    'resolving', 'downloading', 'converting', 'pausing', 'cancelling'
                )
                """,
                (now,),
            )
        return cursor.rowcount

    recover_interrupted = mark_active_interrupted

    def recover_interrupted(self) -> int:
        return self.mark_active_interrupted()

    def delete(
        self, job_id: str, *, connection: sqlite3.Connection | None = None
    ) -> None:
        with _write_connection(self.database, connection) as active:
            active.execute("DELETE FROM download_jobs WHERE id = ?", (job_id,))

    def delete_terminal(
        self, job_id: str, *, connection: sqlite3.Connection | None = None
    ) -> bool:
        with _write_connection(self.database, connection) as active:
            cursor = active.execute(
                """
                DELETE FROM download_jobs
                WHERE id = ? AND state IN ('completed', 'failed', 'cancelled')
                """,
                (job_id,),
            )
        return cursor.rowcount > 0

    def _result(self, row: sqlite3.Row) -> T | Record:
        record = dict(row)
        return record if self.model_factory is None else self.model_factory(record)


class LibraryRepository:
    def __init__(
        self,
        database: Database,
        model_factory: ModelFactory[T] | None = None,
    ):
        self.database = database
        self.model_factory = model_factory or _library_track_from_record

    def add(
        self,
        track: object,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> LibraryTrack:
        record = _record(track)
        _require(record, LIBRARY_TRACK_COLUMNS)
        values = [_db_value(record[column]) for column in LIBRARY_TRACK_COLUMNS]
        with _write_connection(self.database, connection) as active:
            active.execute(
                f"INSERT INTO library_tracks ({', '.join(LIBRARY_TRACK_COLUMNS)}) "
                f"VALUES ({', '.join('?' for _ in LIBRARY_TRACK_COLUMNS)})",
                values,
            )

        return track  # type: ignore[return-value]

    create = add

    def save(
        self,
        track: object,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> LibraryTrack:
        record = _record(track)
        _require(record, LIBRARY_TRACK_COLUMNS)
        values = [_db_value(record[column]) for column in LIBRARY_TRACK_COLUMNS]
        updates = ", ".join(
            f"{column} = excluded.{column}"
            for column in LIBRARY_TRACK_COLUMNS
            if column != "id"
        )
        with _write_connection(self.database, connection) as active:
            active.execute(
                f"INSERT INTO library_tracks ({', '.join(LIBRARY_TRACK_COLUMNS)}) "
                f"VALUES ({', '.join('?' for _ in LIBRARY_TRACK_COLUMNS)}) "
                f"ON CONFLICT(id) DO UPDATE SET {updates}",
                values,
            )

        return track  # type: ignore[return-value]

    upsert = save

    def get(self, track_id: str) -> T | Record | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM library_tracks WHERE id = ?", (track_id,)
            ).fetchone()
        return None if row is None else self._result(row)

    get_by_id = get

    def list(
        self,
        filter_text: str = "",
        limit: int = 200,
        offset: int = 0,
        folder_id: str | None = None,
    ) -> tuple[list[T | Record], int]:
        if limit < 1 or offset < 0:
            raise ValueError("limit must be positive and offset cannot be negative")
        pattern = filter_text.strip()
        conditions = ["""(
            INSTR(CASEFOLD(title), CASEFOLD(?)) > 0
            OR INSTR(CASEFOLD(COALESCE(channel, '')), CASEFOLD(?)) > 0
            OR INSTR(CASEFOLD(file_path), CASEFOLD(?)) > 0
        )"""]
        parameters: list[Any] = [pattern, pattern, pattern]
        if folder_id == "":
            conditions.append("folder_id IS NULL")
        elif folder_id is not None:
            conditions.append("folder_id = ?")
            parameters.append(folder_id)
        where = " WHERE " + " AND ".join(conditions)
        with self.database.connection() as connection:
            total = int(
                connection.execute(
                    "SELECT COUNT(*) FROM library_tracks " + where,
                    parameters,
                ).fetchone()[0]
            )
            rows = connection.execute(
                "SELECT * FROM library_tracks "
                + where
                + " ORDER BY created_at DESC, id ASC LIMIT ? OFFSET ?",
                (*parameters, limit, offset),
            ).fetchall()
        return [self._result(row) for row in rows], total

    def list_tracks(
        self, filter_text: str = "", *, limit: int = 200, offset: int = 0
    ) -> list[T | Record]:
        return self.list(filter_text, limit=limit, offset=offset)[0]

    def count(self, filter_text: str = "") -> int:
        return self.list(filter_text, limit=1)[1]

    def list_folders(self) -> list[LibraryFolder]:
        with self.database.connection() as connection:
            rows = connection.execute(
                """
                SELECT f.id, f.name, f.created_at, COUNT(t.id) AS track_count
                FROM library_folders AS f
                LEFT JOIN library_tracks AS t ON t.folder_id = f.id
                GROUP BY f.id, f.name, f.created_at
                ORDER BY CASEFOLD(f.name), f.id
                """
            ).fetchall()
        return [LibraryFolder(**dict(row)) for row in rows]

    def get_folder(self, folder_id: str) -> LibraryFolder | None:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT f.id, f.name, f.created_at, COUNT(t.id) AS track_count
                FROM library_folders AS f
                LEFT JOIN library_tracks AS t ON t.folder_id = f.id
                WHERE f.id = ?
                GROUP BY f.id, f.name, f.created_at
                """,
                (folder_id,),
            ).fetchone()
        return None if row is None else LibraryFolder(**dict(row))

    def get_folder_by_name(self, name: str) -> LibraryFolder | None:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT f.id, f.name, f.created_at, COUNT(t.id) AS track_count
                FROM library_folders AS f
                LEFT JOIN library_tracks AS t ON t.folder_id = f.id
                WHERE CASEFOLD(f.name) = CASEFOLD(?)
                GROUP BY f.id, f.name, f.created_at
                """,
                (name,),
            ).fetchone()
        return None if row is None else LibraryFolder(**dict(row))

    def create_folder(self, name: str) -> LibraryFolder:
        folder = LibraryFolder(str(uuid4()), name, utc_now())
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO library_folders(id, name, created_at) VALUES (?, ?, ?)",
                (folder.id, folder.name, folder.created_at),
            )
        return folder

    def rename_folder(self, folder_id: str, name: str) -> LibraryFolder:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE library_folders SET name = ? WHERE id = ?",
                (name, folder_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(folder_id)
        folder = self.get_folder(folder_id)
        if folder is None:
            raise KeyError(folder_id)
        return folder

    def delete_folder(self, folder_id: str) -> None:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM library_folders WHERE id = ?", (folder_id,)
            )
            if cursor.rowcount == 0:
                raise KeyError(folder_id)

    def assign_folder(self, track_id: str, folder_id: str | None) -> None:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE library_tracks SET folder_id = ? WHERE id = ?",
                (folder_id, track_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(track_id)

    def remove(
        self, track_id: str, *, connection: sqlite3.Connection | None = None
    ) -> None:
        with _write_connection(self.database, connection) as active:
            cursor = active.execute(
                "DELETE FROM library_tracks WHERE id = ?", (track_id,)
            )
        return None

    delete = remove

    def set_last_played(
        self,
        track_id: str,
        played_at: str | None = None,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> bool:
        with _write_connection(self.database, connection) as active:
            cursor = active.execute(
                "UPDATE library_tracks SET last_played_at = ? WHERE id = ?",
                (played_at or utc_now(), track_id),
            )
        return cursor.rowcount > 0

    def _result(self, row: sqlite3.Row) -> T | Record:
        record = dict(row)
        return record if self.model_factory is None else self.model_factory(record)


class HistoryRepository:
    def __init__(self, database: Database):
        self.database = database

    def add(
        self,
        job_id: str | None = None,
        video_id: str | None = None,
        event_type: str | Enum = "enqueued",
        detail: Any = None,
        *,
        created_at: str | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        detail_json = (
            None if detail is None else json.dumps(detail, ensure_ascii=False, default=str)
        )
        with _write_connection(self.database, connection) as active:
            cursor = active.execute(
                """
                INSERT INTO history_events(
                    job_id, video_id, event_type, detail_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    video_id,
                    _db_value(event_type),
                    detail_json,
                    created_at or utc_now(),
                ),
            )
        return None

    append = add

    def list(
        self,
        *,
        job_id: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[Record]:
        if limit < 1 or offset < 0:
            raise ValueError("limit must be positive and offset cannot be negative")
        where = " WHERE job_id = ?" if job_id is not None else ""
        parameters: list[Any] = [] if job_id is None else [job_id]
        parameters.extend((limit, offset))
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM history_events"
                + where
                + " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                parameters,
            ).fetchall()
        records: list[Record] = []
        for row in rows:
            record = dict(row)
            record["detail"] = (
                None
                if record["detail_json"] is None
                else json.loads(record["detail_json"])
            )
            records.append(record)
        return records


# Concise compatibility name matching ``JobRepositoryPort``.
JobRepository = DownloadJobRepository


@contextmanager
def _write_connection(
    database: Database, existing: sqlite3.Connection | None
):
    if existing is not None:
        yield existing
        return
    with database.transaction() as connection:
        yield connection


def _record(value: object) -> Record:
    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    try:
        return dict(vars(value))
    except TypeError as exc:
        raise TypeError("Expected a mapping, dataclass or object with attributes") from exc


def _require(record: Mapping[str, Any], columns: Sequence[str]) -> None:
    missing = [column for column in columns if column not in record]
    if missing:
        raise ValueError(f"Missing persistence fields: {', '.join(missing)}")


def _db_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    return value


def _download_job_from_record(record: Record) -> DownloadJob:
    values = dict(record)
    values["state"] = JobState(values["state"])
    # These transient progress fields are intentionally not part of the v1 DB.
    values.setdefault("speed_bps", None)
    values.setdefault("eta_seconds", None)
    return DownloadJob(**values)


def _library_track_from_record(record: Record) -> LibraryTrack:
    values = dict(record)
    values.setdefault("file_missing", False)
    return LibraryTrack(**values)
