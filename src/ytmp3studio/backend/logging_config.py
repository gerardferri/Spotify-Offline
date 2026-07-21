from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from time import gmtime


def user_data_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base / "YT-MP3 Studio"


def configure_logging(log_dir: Path | None = None) -> Path:
    directory = log_dir or user_data_dir() / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    log_path = directory / "app.log"
    root = logging.getLogger("ytmp3studio")
    root.setLevel(logging.INFO)
    resolved_log_path = log_path.resolve()
    if any(
        isinstance(item, RotatingFileHandler)
        and Path(item.baseFilename).resolve() == resolved_log_path
        for item in root.handlers
    ):
        return log_path

    handler = RotatingFileHandler(
        log_path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)sZ %(levelname)s [%(threadName)s] %(name)s %(message)s",
            "%Y-%m-%dT%H:%M:%S",
        )
    )
    handler.formatter.converter = gmtime  # type: ignore[union-attr]
    root.addHandler(handler)
    return log_path
