from __future__ import annotations

from pathlib import Path

from ytmp3studio.backend.adapters.ffmpeg_adapter import FfmpegAdapter
from ytmp3studio.backend.adapters.media_files import MediaFiles
from ytmp3studio.backend.adapters.ytdlp_adapter import YtDlpAdapter
from ytmp3studio.backend.dependency_service import DependencyService
from ytmp3studio.backend.facade import BackendFacade
from ytmp3studio.backend.library_service import LibraryService
from ytmp3studio.backend.playlist_service import PlaylistService
from ytmp3studio.backend.logging_config import configure_logging, user_data_dir
from ytmp3studio.backend.queue_service import QueueService
from ytmp3studio.backend.search_service import SearchService
from ytmp3studio.backend.settings_service import SettingsService
from ytmp3studio.persistence.database import Database
from ytmp3studio.persistence.repositories import (
    DownloadJobRepository,
    HistoryRepository,
    LibraryRepository,
    SettingsRepository,
)
from ytmp3studio.persistence.playlist_repository import PlaylistRepository


def create_backend(
    database_path: str | Path | None = None,
    *,
    log_dir: str | Path | None = None,
) -> BackendFacade:
    """Compose the production backend without creating any UI widgets."""
    configure_logging(Path(log_dir) if log_dir is not None else None)
    database = Database(database_path or user_data_dir() / "ytmp3studio.db")
    jobs = DownloadJobRepository(database)
    library_repository = LibraryRepository(database)
    settings_repository = SettingsRepository(database)
    history = HistoryRepository(database)
    playlists_repository = PlaylistRepository(database)
    ffmpeg = FfmpegAdapter()
    media_provider = YtDlpAdapter(ffmpeg=ffmpeg, media_files=MediaFiles())
    queue = QueueService(
        jobs,
        library_repository,
        history,
        media_provider,
        settings_repository.get,
    )
    settings = SettingsService(settings_repository, queue.set_concurrency)
    search = SearchService(media_provider)
    playlists = PlaylistService(
        playlists_repository,
        library_repository,
        search,
        queue,
        settings_repository.get,
    )
    return BackendFacade(
        database=database,
        search_service=search,
        queue_service=queue,
        library_service=LibraryService(library_repository),
        settings_service=settings,
        dependency_service=DependencyService(media_provider, ffmpeg),
        playlist_service=playlists,
    )


def main() -> int:
    """Start the production Qt application."""
    import sys

    if "--smoke-test" in sys.argv:
        return _run_smoke_test()

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from ytmp3studio.ui.main_window import MainWindow
    from ytmp3studio.ui.theme import apply_theme

    application = QApplication.instance() or QApplication(sys.argv)
    application.setApplicationName("YT-MP3 Studio")
    application.setOrganizationName("YT-MP3 Studio")
    apply_theme(application, "system")
    backend = create_backend()
    application.aboutToQuit.connect(backend.shutdown)
    window = MainWindow(backend)
    window.show()
    QTimer.singleShot(0, backend.initialize)
    return application.exec()


def _run_smoke_test() -> int:
    """Exercise the frozen imports, Qt widgets and SQL resources, then exit.

    This deliberately avoids network access, user settings and the real
    library. It is used by ``scripts/verify.ps1`` after creating the bundle.
    """
    import logging
    import os
    import tempfile

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication

    from ytmp3studio.persistence.database import Database
    from ytmp3studio.ui.main_window import MainWindow

    application = QApplication.instance() or QApplication(
        ["YT-MP3 Studio", "--smoke-test"]
    )
    application.setApplicationName("YT-MP3 Studio")
    with tempfile.TemporaryDirectory(prefix="ytmp3studio-smoke-") as temp_dir:
        temp_path = Path(temp_dir)
        log_dir = temp_path / "logs"
        database_path = Path(temp_dir) / "smoke.db"
        Database(database_path).migrate()
        backend = create_backend(database_path, log_dir=log_dir)
        window = MainWindow(backend)
        try:
            window.close()
            backend.shutdown()
            window.deleteLater()
            application.processEvents()
        finally:
            # RotatingFileHandler keeps its file open on Windows. It must be
            # detached before TemporaryDirectory attempts to remove the log.
            logger = logging.getLogger("ytmp3studio")
            resolved_log_dir = log_dir.resolve()
            for handler in list(logger.handlers):
                filename = getattr(handler, "baseFilename", None)
                if filename is None:
                    continue
                try:
                    belongs_to_smoke = Path(filename).resolve().is_relative_to(
                        resolved_log_dir
                    )
                except (OSError, ValueError):
                    belongs_to_smoke = False
                if belongs_to_smoke:
                    logger.removeHandler(handler)
                    handler.close()
    application.quit()
    return 0
