"""SQLite connection management and schema migrations.

Connections are deliberately short lived.  Every operation obtains its own
connection so a connection is never shared between Qt worker threads.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp using the canonical ``Z`` suffix."""

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


class Database:
    """Owns database configuration, migrations and transaction boundaries."""

    def __init__(self, path: str | Path, migrations_dir: str | Path | None = None):
        self.path = Path(path).expanduser().resolve()
        self.migrations_dir = (
            Path(migrations_dir)
            if migrations_dir is not None
            else Path(__file__).with_name("migrations")
        )

    def connect(self) -> sqlite3.Connection:
        """Open and configure a new connection for the calling thread."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            self.path,
            timeout=5.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.create_function("CASEFOLD", 1, _casefold, deterministic=True)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self, *, immediate: bool = True) -> Iterator[sqlite3.Connection]:
        """Run a short transaction and reliably rollback on any exception."""

        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            try:
                yield connection
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()

    def migrate(self) -> list[int]:
        """Apply pending numbered SQL migrations and return applied versions."""

        migration_files = sorted(self.migrations_dir.glob("[0-9][0-9][0-9]_*.sql"))
        applied_now: list[int] = []
        with self.connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            applied = {
                int(row[0])
                for row in connection.execute("SELECT version FROM schema_migrations")
            }
            for migration_file in migration_files:
                try:
                    version = int(migration_file.name.split("_", 1)[0])
                except (ValueError, IndexError) as exc:
                    raise ValueError(
                        f"Invalid migration filename: {migration_file.name}"
                    ) from exc
                if version in applied:
                    continue
                script = migration_file.read_text(encoding="utf-8")
                try:
                    connection.executescript(
                        "BEGIN IMMEDIATE;\n"
                        + script
                        + "\nINSERT INTO schema_migrations(version, applied_at) VALUES ("
                        + str(version)
                        + ", "
                        + _sql_literal(utc_now())
                        + ");\nCOMMIT;"
                    )
                except BaseException:
                    if connection.in_transaction:
                        connection.rollback()
                    raise
                applied_now.append(version)

        self._ensure_default_settings()
        return applied_now

    def _ensure_default_settings(self) -> None:
        default_download_dir = Path.home() / "Music" / "YT-MP3 Studio"
        defaults: dict[str, Any] = {
            "download_dir": str(default_download_dir),
            "quality_kbps": 192,
            "theme": "system",
            "concurrency": 2,
            "max_retries": 2,
            "retry_base_seconds": 2,
        }
        now = utc_now()
        with self.transaction() as connection:
            connection.executemany(
                """
                INSERT OR IGNORE INTO settings(key, value_json, updated_at)
                VALUES (?, ?, ?)
                """,
                ((key, json.dumps(value), now) for key, value in defaults.items()),
            )

    def close(self) -> None:
        """Checkpoint WAL using a short-lived final barrier connection.

        Repositories never retain SQLite connections. This explicit boundary
        also makes the database file immediately movable/deletable on Windows.
        """
        if not self.path.exists():
            return
        with self.connection() as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()


def _sql_literal(value: str) -> str:
    """Quote a trusted scalar for the migration wrapper."""

    return "'" + value.replace("'", "''") + "'"


def _casefold(value: Any) -> str:
    return "" if value is None else str(value).casefold()
