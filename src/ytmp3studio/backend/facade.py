from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

from PySide6.QtCore import QObject, QThreadPool, Signal

from ytmp3studio.backend.dependency_service import DependencyService
from ytmp3studio.backend.error_mapping import to_app_error
from ytmp3studio.backend.library_service import LibraryService
from ytmp3studio.backend.playlist_service import PlaylistService
from ytmp3studio.backend.queue_service import QueueService
from ytmp3studio.backend.search_service import SearchService
from ytmp3studio.backend.settings_service import SettingsService
from ytmp3studio.backend.workers import FunctionWorker
from ytmp3studio.domain.errors import AppError, ErrorCode, invalid_input

logger = logging.getLogger("ytmp3studio.facade")


class BackendFacade(QObject):
    initialized = Signal(object)
    search_started = Signal(str)
    search_succeeded = Signal(str, object)
    queue_snapshot = Signal(str, object)
    job_added = Signal(object)
    job_updated = Signal(object)
    job_progress = Signal(object)
    job_completed = Signal(object, object)
    library_snapshot = Signal(str, object, int)
    library_changed = Signal()
    library_folders_snapshot = Signal(str, object)
    library_folders_changed = Signal()
    playlists_snapshot = Signal(str, object)
    playlist_snapshot = Signal(str, object)
    playlists_changed = Signal()
    playlist_changed = Signal(str)
    exportify_imported = Signal(str, object)
    playlist_replacement_candidates = Signal(str, str, str, object)
    settings_changed = Signal(object)
    dependency_status = Signal(str, object)
    operation_failed = Signal(str, object)
    fatal_error = Signal(object)

    def __init__(
        self,
        database: Any,
        search_service: SearchService,
        queue_service: QueueService,
        library_service: LibraryService,
        settings_service: SettingsService,
        dependency_service: DependencyService,
        playlist_service: PlaylistService | None = None,
        thread_pool: QThreadPool | None = None,
    ) -> None:
        super().__init__()
        self._database = database
        self._search = search_service
        self._queue = queue_service
        self._library = library_service
        self._settings = settings_service
        self._dependencies = dependency_service
        self._playlists = playlist_service
        self._pool = thread_pool or QThreadPool(self)
        if thread_pool is None:
            self._pool.setMaxThreadCount(4)
        self._initialized = False
        self._initializing = False
        self._shutting_down = False
        self._lifecycle_lock = threading.RLock()
        self._queue.set_callbacks(
            on_added=self.job_added.emit,
            on_updated=self._job_updated,
            on_progress=self.job_progress.emit,
            on_completed=self._job_completed,
            on_library_changed=self.library_changed.emit,
        )

    def initialize(self) -> None:
        with self._lifecycle_lock:
            if self._initialized or self._initializing or self._shutting_down:
                return
            self._initializing = True

        def operation() -> dict[str, Any]:
            migrate = getattr(self._database, "migrate", None) or getattr(self._database, "initialize", None)
            if migrate:
                migrate()
            settings = self._settings.get()
            status = self._dependencies.check(settings)
            return {"settings": settings, "dependencies": status}

        def success(snapshot: dict[str, Any]) -> None:
            with self._lifecycle_lock:
                if self._shutting_down:
                    self._initializing = False
                    return
                self._queue.start(recover=True)
                snapshot["queue"] = self._queue.snapshot()
                self._initialized = True
                self._initializing = False
            self.initialized.emit(snapshot)

        self._run(
            "initialize",
            operation,
            success,
            fatal=True,
            failure_cleanup=self._initialization_failed,
        )

    def search(self, query: str, limit: int = 12) -> str:
        request_id = self._request_id()
        self.search_started.emit(request_id)
        self._run(request_id, lambda: self._search.search(query, limit), lambda results: self.search_succeeded.emit(request_id, results))
        return request_id

    def enqueue(self, video_ids: list[str], quality_kbps: int | None = None) -> str:
        request_id = self._request_id()
        self._run(request_id, lambda: self._queue.enqueue(video_ids, quality_kbps), lambda _jobs: None)
        return request_id

    def open_exportify(self) -> str:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        request_id = self._request_id()
        if not QDesktopServices.openUrl(QUrl("https://exportify.net/")):
            self.operation_failed.emit(
                request_id,
                AppError(ErrorCode.INTERNAL_ERROR, "No se pudo abrir Exportify."),
            )
        return request_id

    def import_exportify(self, path: str) -> str:
        service = self._require_playlists()
        request_id = self._request_id()

        def success(playlists: object) -> None:
            self.exportify_imported.emit(request_id, playlists)
            self.playlists_changed.emit()

        self._run(request_id, lambda: service.import_exportify(path), success)
        return request_id

    def list_playlists(self) -> str:
        service = self._require_playlists()
        request_id = self._request_id()
        self._run(
            request_id,
            service.list_playlists,
            lambda playlists: self.playlists_snapshot.emit(request_id, playlists),
        )
        return request_id

    def get_playlist(self, playlist_id: str) -> str:
        service = self._require_playlists()
        request_id = self._request_id()
        validated = self._validate_uuid(playlist_id, "playlist")
        self._run(
            request_id,
            lambda: service.get_playlist(validated),
            lambda playlist: self.playlist_snapshot.emit(request_id, playlist),
        )
        return request_id

    def download_playlist(self, playlist_id: str) -> str:
        return self._playlist_command(playlist_id, self._require_playlists().download_playlist)

    def retry_playlist_failures(self, playlist_id: str) -> str:
        return self._playlist_command(playlist_id, self._require_playlists().retry_failures)

    def stop_playlist_downloads(self, playlist_id: str) -> str:
        return self._playlist_command(playlist_id, self._require_playlists().stop_downloads)

    def replace_playlist_track(self, playlist_id: str, track_key: str) -> str:
        service = self._require_playlists()
        request_id = self._request_id()
        validated = self._validate_uuid(playlist_id, "playlist")
        self._run(
            request_id,
            lambda: service.replacement_candidates(validated, str(track_key)),
            lambda candidates: self.playlist_replacement_candidates.emit(
                request_id, validated, str(track_key), candidates
            ),
        )
        return request_id

    def confirm_playlist_replacement(
        self, playlist_id: str, track_key: str, video_id: str
    ) -> str:
        service = self._require_playlists()
        request_id = self._request_id()
        validated = self._validate_uuid(playlist_id, "playlist")
        self._run(
            request_id,
            lambda: service.queue_replacement(validated, str(track_key), str(video_id)),
            lambda _value: self.playlist_changed.emit(validated),
        )
        return request_id

    def choose_playlist_cover(self, playlist_id: str, path: str) -> str:
        service = self._require_playlists()
        request_id = self._request_id()
        validated = self._validate_uuid(playlist_id, "playlist")
        self._run(
            request_id,
            lambda: service.choose_cover(validated, path),
            lambda _value: self.playlist_changed.emit(validated),
        )
        return request_id

    def pause_job(self, job_id: str) -> str:
        return self._job_command(job_id, self._queue.pause)

    def resume_job(self, job_id: str) -> str:
        return self._job_command(job_id, self._queue.resume)

    def cancel_job(self, job_id: str) -> str:
        return self._job_command(job_id, self._queue.cancel)

    def retry_job(self, job_id: str) -> str:
        return self._job_command(job_id, self._queue.retry)

    def remove_job(self, job_id: str) -> str:
        return self._job_command(job_id, self._queue.remove)

    def list_queue(self) -> str:
        request_id = self._request_id()
        self._run(request_id, self._queue.snapshot, lambda jobs: self.queue_snapshot.emit(request_id, jobs))
        return request_id

    def list_library(self, filter_text: str = "", limit: int = 200, offset: int = 0, folder_id: str | None = None) -> str:
        request_id = self._request_id()

        def success(result: tuple[list[Any], int]) -> None:
            tracks, total = result
            self.library_snapshot.emit(request_id, tracks, total)

        def operation() -> tuple[list[Any], int]:
            validated_folder = folder_id
            if folder_id not in (None, ""):
                validated_folder = self._validate_uuid(folder_id, "carpeta")
            return self._library.list(filter_text, limit, offset, validated_folder)

        self._run(request_id, operation, success)
        return request_id

    def list_library_folders(self) -> str:
        request_id = self._request_id()
        self._run(
            request_id,
            self._library.list_folders,
            lambda folders: self.library_folders_snapshot.emit(request_id, folders),
        )
        return request_id

    def create_library_folder(self, name: str) -> str:
        request_id = self._request_id()
        self._run(
            request_id,
            lambda: self._library.create_folder(name),
            lambda _folder: self.library_folders_changed.emit(),
        )
        return request_id

    def rename_library_folder(self, folder_id: str, name: str) -> str:
        request_id = self._request_id()
        self._run(
            request_id,
            lambda: self._library.rename_folder(self._validate_uuid(folder_id, "carpeta"), name),
            lambda _folder: self.library_folders_changed.emit(),
        )
        return request_id

    def delete_library_folder(self, folder_id: str) -> str:
        request_id = self._request_id()

        def success(_value: object) -> None:
            self.library_folders_changed.emit()
            self.library_changed.emit()

        self._run(
            request_id,
            lambda: self._library.delete_folder(self._validate_uuid(folder_id, "carpeta")),
            success,
        )
        return request_id

    def assign_library_track_folder(self, track_id: str, folder_id: str | None) -> str:
        request_id = self._request_id()

        def operation() -> None:
            validated_track = self._validate_uuid(track_id, "pista")
            validated_folder = None if folder_id is None else self._validate_uuid(folder_id, "carpeta")
            self._library.assign_folder(validated_track, validated_folder)

        def success(_value: object) -> None:
            self.library_folders_changed.emit()
            self.library_changed.emit()

        self._run(request_id, operation, success)
        return request_id

    def remove_library_track(self, track_id: str, delete_file: bool = False) -> str:
        request_id = self._request_id()
        self._run(
            request_id,
            lambda: self._library.remove(self._validate_uuid(track_id, "pista"), delete_file),
            lambda _value: self.library_changed.emit(),
        )
        return request_id

    def reveal_library_track(self, track_id: str) -> str:
        request_id = self._request_id()
        self._run(
            request_id,
            lambda: self._library.reveal(self._validate_uuid(track_id, "pista")),
            lambda _value: None,
        )
        return request_id

    def get_settings(self) -> str:
        request_id = self._request_id()
        self._run(request_id, self._settings.get, lambda settings: self.settings_changed.emit(settings))
        return request_id

    def update_settings(self, patch: dict[str, Any]) -> str:
        request_id = self._request_id()
        self._run(request_id, lambda: self._settings.update(patch), lambda settings: self.settings_changed.emit(settings))
        return request_id

    def check_dependencies(self) -> str:
        request_id = self._request_id()
        self._run(
            request_id,
            lambda: self._dependencies.check(self._settings.get()),
            lambda status: self.dependency_status.emit(request_id, status),
        )
        return request_id

    def shutdown(self) -> None:
        with self._lifecycle_lock:
            if self._shutting_down:
                return
            self._shutting_down = True
        deadline = time.monotonic() + 5.0
        self._queue.shutdown(timeout=max(0.0, deadline - time.monotonic()))

        clear = getattr(self._pool, "clear", None)
        if clear is not None:
            clear()
        wait_for_done = getattr(self._pool, "waitForDone", None)
        if wait_for_done is not None:
            remaining_ms = max(0, round((deadline - time.monotonic()) * 1000))
            if not wait_for_done(remaining_ms):
                logger.warning("backend worker pool did not stop before shutdown deadline")

        close_database = getattr(self._database, "close", None)
        if close_database is not None:
            try:
                close_database()
            except Exception:
                logger.exception("database close barrier failed")

    def _job_command(self, job_id: str, command: Callable[[str], Any]) -> str:
        request_id = self._request_id()
        self._run(request_id, lambda: command(self._validate_uuid(job_id, "trabajo")), lambda _value: None)
        return request_id

    def _playlist_command(self, playlist_id: str, command: Callable[[str], Any]) -> str:
        request_id = self._request_id()
        validated = self._validate_uuid(playlist_id, "playlist")
        self._run(
            request_id,
            lambda: command(validated),
            lambda _value: self.playlist_changed.emit(validated),
        )
        return request_id

    def _require_playlists(self) -> PlaylistService:
        if self._playlists is None:
            raise AppError(ErrorCode.INVALID_STATE, "Las playlists no están disponibles.")
        return self._playlists

    def _job_updated(self, job: object) -> None:
        self.job_updated.emit(job)
        if self._playlists is None:
            return
        try:
            if self._playlists.on_job_updated(job):
                self.playlists_changed.emit()
        except Exception:
            logger.exception("could not update playlist state for job")

    def _job_completed(self, job: object, track: object) -> None:
        updated_track = track
        if self._playlists is not None:
            try:
                updated_track = self._playlists.on_job_completed(job, track)
                self.playlists_changed.emit()
            except Exception:
                logger.exception("could not finalize playlist projection for job")
        self.job_completed.emit(job, updated_track)

    def _run(
        self,
        request_id: str,
        operation: Callable[[], Any],
        success: Callable[[Any], None],
        *,
        fatal: bool = False,
        failure_cleanup: Callable[[], None] | None = None,
    ) -> None:
        with self._lifecycle_lock:
            shutting_down = self._shutting_down
        if shutting_down:
            if failure_cleanup:
                failure_cleanup()
            self.operation_failed.emit(request_id, AppError(ErrorCode.INVALID_STATE, "La aplicación se está cerrando."))
            return

        def succeeded(value: Any) -> None:
            with self._lifecycle_lock:
                if self._shutting_down:
                    return
            success(value)

        def failed(exc: BaseException) -> None:
            if failure_cleanup:
                failure_cleanup()
            with self._lifecycle_lock:
                if self._shutting_down:
                    return
            error = to_app_error(exc)
            logger.error(
                "request_id=%s code=%s message=%s technical=%s",
                request_id,
                error.code,
                error.user_message,
                error.technical_message,
                exc_info=not isinstance(exc, AppError),
            )
            (self.fatal_error if fatal else self.operation_failed).emit(*( [error] if fatal else [request_id, error] ))

        self._pool.start(FunctionWorker(operation, succeeded, failed))

    def _initialization_failed(self) -> None:
        with self._lifecycle_lock:
            self._initializing = False

    @staticmethod
    def _request_id() -> str:
        return str(uuid4())

    @staticmethod
    def _validate_uuid(value: str, label: str) -> str:
        try:
            UUID(value)
        except (TypeError, ValueError, AttributeError) as exc:
            raise invalid_input(f"El identificador de {label} no es válido.", str(value)) from exc
        return value
