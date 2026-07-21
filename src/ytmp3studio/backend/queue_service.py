from __future__ import annotations

import logging
import random
import shutil
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable
from uuid import uuid4

from ytmp3studio.domain.errors import AppError, ErrorCode, invalid_input
from ytmp3studio.backend.error_mapping import to_app_error
from ytmp3studio.domain.models import DownloadJob, JobState, LibraryTrack, Progress, Settings
from ytmp3studio.domain.ports import (
    HistoryRepositoryPort,
    JobRepositoryPort,
    LibraryRepositoryPort,
    MediaProvider,
)

logger = logging.getLogger("ytmp3studio.queue")


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


RECOVERABLE_CODES = {
    ErrorCode.NETWORK_ERROR.value,
    ErrorCode.SEARCH_FAILED.value,
    ErrorCode.DOWNLOAD_FAILED.value,
    ErrorCode.YTDLP_OUTDATED.value,
}


class QueueService:
    """Persistent FIFO scheduler. Callbacks may run on worker threads."""

    def __init__(
        self,
        jobs: JobRepositoryPort,
        library: LibraryRepositoryPort,
        history: HistoryRepositoryPort,
        provider: MediaProvider,
        settings_getter: Callable[[], Settings],
        *,
        on_added: Callable[[DownloadJob], None] | None = None,
        on_updated: Callable[[DownloadJob], None] | None = None,
        on_progress: Callable[[Progress], None] | None = None,
        on_completed: Callable[[DownloadJob, LibraryTrack], None] | None = None,
        on_library_changed: Callable[[], None] | None = None,
        random_uniform: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self._jobs = jobs
        self._library = library
        self._history = history
        self._provider = provider
        self._settings_getter = settings_getter
        self._on_added = on_added or (lambda _job: None)
        self._on_updated = on_updated or (lambda _job: None)
        self._on_progress = on_progress or (lambda _progress: None)
        self._on_completed = on_completed or (lambda _job, _track: None)
        self._on_library_changed = on_library_changed or (lambda: None)
        self._random_uniform = random_uniform
        self._lock = threading.RLock()
        self._wake = threading.Condition(self._lock)
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="download")
        self._active: dict[str, tuple[Future[None], threading.Event]] = {}
        self._requested_action: dict[str, str] = {}
        self._last_progress_emit: dict[str, float] = {}
        self._running = False
        self._accepting = True
        self._concurrency = 2
        self._scheduler: threading.Thread | None = None
        self._closed = False

    def set_callbacks(
        self,
        *,
        on_added: Callable[[DownloadJob], None] | None = None,
        on_updated: Callable[[DownloadJob], None] | None = None,
        on_progress: Callable[[Progress], None] | None = None,
        on_completed: Callable[[DownloadJob, LibraryTrack], None] | None = None,
        on_library_changed: Callable[[], None] | None = None,
    ) -> None:
        """Bind facade signal emitters before the scheduler is started."""
        with self._lock:
            if on_added is not None:
                self._on_added = on_added
            if on_updated is not None:
                self._on_updated = on_updated
            if on_progress is not None:
                self._on_progress = on_progress
            if on_completed is not None:
                self._on_completed = on_completed
            if on_library_changed is not None:
                self._on_library_changed = on_library_changed

    def start(self, recover: bool = True) -> None:
        with self._lock:
            if self._running:
                return
            if self._closed:
                raise AppError(ErrorCode.INVALID_STATE, "La cola ya se ha cerrado.")
            if recover:
                count = self._jobs.recover_interrupted()
                if count:
                    logger.warning("recovered_interrupted count=%s", count)
            self._concurrency = self._settings_getter().concurrency
            self._running = True
            self._accepting = True
            self._scheduler = threading.Thread(
                target=self._scheduler_loop, name="queue-scheduler", daemon=True
            )
            self._scheduler.start()

    def shutdown(self, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + max(0.0, timeout)
        with self._wake:
            if self._closed:
                return
            self._accepting = False
            self._running = False
            self._closed = True
            for job_id, (_future, event) in self._active.items():
                self._requested_action[job_id] = "interrupt"
                event.set()
            self._wake.notify_all()
        if self._scheduler:
            self._scheduler.join(max(0.0, deadline - time.monotonic()))

        with self._lock:
            futures = [future for future, _event in self._active.values()]
        if futures:
            wait(futures, timeout=max(0.0, deadline - time.monotonic()))
        self._executor.shutdown(wait=False, cancel_futures=True)

        with self._lock:
            active_ids = list(self._active)
        for job_id in active_ids:
            try:
                job = self._require(job_id)
                if job.state in {
                    JobState.RESOLVING,
                    JobState.DOWNLOADING,
                    JobState.CONVERTING,
                    JobState.PAUSING,
                    JobState.CANCELLING,
                }:
                    self._transition(
                        job,
                        JobState.INTERRUPTED,
                        error_code=ErrorCode.CANCELLED.value,
                        error_message="La descarga se interrumpi\u00f3 al cerrar la aplicaci\u00f3n.",
                    )
            except Exception:
                logger.exception("job_id=%s could not persist shutdown interruption", job_id)

    def set_concurrency(self, value: int) -> None:
        if not 1 <= value <= 4:
            raise invalid_input("La concurrencia debe estar entre 1 y 4.")
        with self._wake:
            self._concurrency = value
            self._wake.notify_all()

    def enqueue(self, video_ids: Iterable[str], quality_kbps: int | None = None) -> list[DownloadJob]:
        ids = list(dict.fromkeys(item.strip() for item in video_ids if isinstance(item, str) and item.strip()))
        if not ids:
            raise invalid_input("Selecciona al menos un vídeo.")
        if quality_kbps is not None and quality_kbps not in {128, 192, 256, 320}:
            raise invalid_input("La calidad no es válida.")
        with self._lock:
            if not self._accepting:
                raise AppError(ErrorCode.INVALID_STATE, "La aplicación se está cerrando.")
        settings = self._settings_getter()
        metadata_items = []
        for video_id in ids:
            metadata = self._provider.resolve(video_id)
            if metadata.is_live:
                raise AppError(ErrorCode.LIVE_NOT_SUPPORTED, "Los directos no son compatibles.")
            metadata_items.append(metadata)

        result: list[DownloadJob] = []
        for metadata in metadata_items:
            identifier = str(uuid4())
            now = utc_now()
            output_dir = str(Path(settings.download_dir).expanduser())
            job = DownloadJob(
                id=identifier,
                video_id=metadata.video_id,
                source_url=metadata.webpage_url,
                title=metadata.title,
                channel=metadata.channel,
                thumbnail_url=metadata.thumbnail_url,
                duration_seconds=metadata.duration_seconds,
                quality_kbps=quality_kbps or settings.quality_kbps,
                output_dir=output_dir,
                temp_dir=str(Path(output_dir) / ".ytmp3studio-tmp" / identifier),
                state=JobState.QUEUED,
                attempt_count=0,
                max_attempts=settings.max_retries + 1,
                created_at=now,
                updated_at=now,
            )
            result.append(job)

        with self._lock:
            if not self._accepting:
                raise AppError(
                    ErrorCode.INVALID_STATE,
                    "La aplicaci\u00f3n se est\u00e1 cerrando.",
                )
            saved_jobs = self._persist_enqueued(result)

        for saved in saved_jobs:
            logger.info("job_id=%s transition=<new>->queued", saved.id)
            self._on_added(saved)
        with self._wake:
            self._wake.notify_all()
        return saved_jobs

    def snapshot(self) -> list[DownloadJob]:
        return self._jobs.list()

    def pause(self, job_id: str) -> DownloadJob:
        with self._wake:
            job = self._require(job_id)
            if job.state == JobState.QUEUED:
                return self._transition(job, JobState.PAUSED, history_event="paused")
            if job.state in {JobState.RESOLVING, JobState.DOWNLOADING, JobState.CONVERTING}:
                updated = self._transition(job, JobState.PAUSING)
                self._requested_action[job_id] = "pause"
                active = self._active.get(job_id)
                if active:
                    active[1].set()
                return updated
            raise self._invalid_transition(job, "pausar")

    def resume(self, job_id: str) -> DownloadJob:
        with self._wake:
            job = self._require(job_id)
            if job.state not in {JobState.PAUSED, JobState.INTERRUPTED}:
                raise self._invalid_transition(job, "reanudar")
            updated = self._transition(
                job,
                JobState.QUEUED,
                history_event="resumed",
                next_retry_at=None,
                error_code=None,
                error_message=None,
            )
            self._wake.notify_all()
            return updated

    def cancel(self, job_id: str) -> DownloadJob:
        with self._wake:
            job = self._require(job_id)
            if job.state in {JobState.QUEUED, JobState.PAUSED, JobState.INTERRUPTED}:
                updated = self._transition(job, JobState.CANCELLED, history_event="cancelled", finished_at=utc_now())
                self._cleanup_temp(updated)
                return updated
            if job.state in {JobState.RESOLVING, JobState.DOWNLOADING, JobState.CONVERTING, JobState.PAUSING}:
                updated = self._transition(job, JobState.CANCELLING)
                self._requested_action[job_id] = "cancel"
                active = self._active.get(job_id)
                if active:
                    active[1].set()
                return updated
            raise self._invalid_transition(job, "cancelar")

    def retry(self, job_id: str) -> DownloadJob:
        with self._wake:
            job = self._require(job_id)
            allowed_failed = job.state == JobState.FAILED and job.error_code in RECOVERABLE_CODES
            if not (allowed_failed or job.state == JobState.INTERRUPTED):
                raise self._invalid_transition(job, "reintentar")
            updated = self._transition(
                job,
                JobState.QUEUED,
                history_event="resumed",
                attempt_count=0,
                next_retry_at=None,
                error_code=None,
                error_message=None,
                finished_at=None,
            )
            self._wake.notify_all()
            return updated

    def remove(self, job_id: str) -> None:
        with self._lock:
            job = self._require(job_id)
            if not job.state.terminal:
                raise self._invalid_transition(job, "eliminar")
            self._history.add(job.id, job.video_id, "removed")
            self._jobs.delete(job.id)

    def _scheduler_loop(self) -> None:
        while True:
            with self._wake:
                if not self._running:
                    return
                self._dispatch_available()
                self._wake.wait(timeout=0.1)

    def _dispatch_available(self) -> None:
        capacity = self._concurrency - len(self._active)
        if capacity <= 0:
            return
        now = datetime.now(UTC)
        queued = [
            job for job in self._jobs.list()
            if job.state == JobState.QUEUED
            and (job.next_retry_at is None or parse_utc(job.next_retry_at) <= now)
            and job.id not in self._active
        ]
        for job in queued[:capacity]:
            stop = threading.Event()
            future = self._executor.submit(self._run_job, job.id, stop)
            self._active[job.id] = (future, stop)
            future.add_done_callback(lambda _future, job_id=job.id: self._worker_done(job_id))

    def _worker_done(self, job_id: str) -> None:
        with self._wake:
            self._active.pop(job_id, None)
            self._requested_action.pop(job_id, None)
            self._wake.notify_all()

    def _run_job(self, job_id: str, stop_event: threading.Event) -> None:
        job = self._require(job_id)
        try:
            job = self._transition(
                job,
                JobState.RESOLVING,
                attempt_count=job.attempt_count + 1,
                started_at=job.started_at or utc_now(),
                next_retry_at=None,
            )
            self._history.add(job.id, job.video_id, "started", {"attempt": job.attempt_count})
            if stop_event.is_set():
                raise AppError(ErrorCode.CANCELLED, "Operación detenida.")
            job = self._transition(job, JobState.DOWNLOADING)
            final_path = self._provider.download(
                job, lambda progress: self._handle_progress(job_id, progress), stop_event
            )
            if stop_event.is_set():
                raise AppError(
                    ErrorCode.CANCELLED,
                    "Operacion detenida durante el cierre.",
                    recoverable=True,
                )
            current = self._require(job_id)
            if not Path(final_path).is_file():
                raise AppError(
                    ErrorCode.FILE_NOT_FOUND,
                    "La conversión terminó sin crear el archivo MP3.",
                    str(final_path),
                    False,
                )
            track = LibraryTrack(
                id=str(uuid4()),
                job_id=current.id,
                video_id=current.video_id,
                title=current.title,
                channel=current.channel,
                duration_seconds=current.duration_seconds,
                thumbnail_url=current.thumbnail_url,
                source_url=current.source_url,
                file_path=str(final_path),
                file_size_bytes=Path(final_path).stat().st_size,
                quality_kbps=current.quality_kbps,
                created_at=utc_now(),
            )
            completed = replace(
                current,
                state=JobState.COMPLETED,
                updated_at=utc_now(),
                progress_percent=100.0,
                finished_at=utc_now(),
                error_code=None,
                error_message=None,
            )
            completed, saved_track = self._persist_completion(completed, track)
            logger.info("job_id=%s transition=%s->completed", current.id, current.state.value)
            self._on_updated(completed)
            self._on_completed(completed, saved_track)
            self._on_library_changed()
        except AppError as exc:
            self._handle_worker_error(job_id, exc)
        except Exception as exc:
            logger.exception("job_id=%s unhandled worker failure", job_id)
            self._handle_worker_error(job_id, to_app_error(exc))

    def _handle_progress(self, job_id: str, progress: Progress) -> None:
        with self._lock:
            job = self._require(job_id)
            desired = JobState.CONVERTING if progress.phase == "converting" else JobState.DOWNLOADING
            if job.state not in {JobState.PAUSING, JobState.CANCELLING} and job.state != desired:
                job = self._transition(job, desired)
            now_mono = time.monotonic()
            last = self._last_progress_emit.get(job_id, 0.0)
            if now_mono - last < 0.2 and progress.percent not in {0.0, 100.0}:
                return
            self._last_progress_emit[job_id] = now_mono
            persisted = replace(
                job,
                downloaded_bytes=progress.downloaded_bytes,
                total_bytes=progress.total_bytes,
                progress_percent=progress.percent,
                speed_bps=progress.speed_bps,
                eta_seconds=progress.eta_seconds,
                updated_at=utc_now(),
            )
            self._jobs.update(persisted)
            self._on_progress(progress)

    def _handle_worker_error(self, job_id: str, error: AppError) -> None:
        with self._wake:
            job = self._require(job_id)
            action = self._requested_action.get(job_id)
            if action == "pause":
                self._transition(job, JobState.PAUSED, history_event="paused")
                return
            if action == "cancel":
                cancelled = self._transition(
                    job, JobState.CANCELLED, history_event="cancelled", finished_at=utc_now()
                )
                self._cleanup_temp(cancelled)
                return
            if action == "interrupt":
                self._transition(job, JobState.INTERRUPTED, error_code=error.code.value if isinstance(error.code, ErrorCode) else str(error.code), error_message=error.user_message)
                return
            code = error.code.value if isinstance(error.code, ErrorCode) else str(error.code)
            if error.recoverable and job.attempt_count < job.max_attempts:
                settings = self._settings_getter()
                base = min(300.0, settings.retry_base_seconds * (2 ** max(0, job.attempt_count - 1)))
                delay = min(300.0, base + self._random_uniform(0.0, min(1.0, base * 0.1)))
                retry_at = (datetime.now(UTC) + timedelta(seconds=delay)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
                updated = self._transition(
                    job,
                    JobState.QUEUED,
                    error_code=code,
                    error_message=error.user_message,
                    next_retry_at=retry_at,
                )
                self._history.add(updated.id, updated.video_id, "retry_scheduled", {"next_retry_at": retry_at})
                logger.warning("job_id=%s retry_scheduled attempt=%s at=%s code=%s", job.id, job.attempt_count, retry_at, code)
                self._wake.notify_all()
                return
            failed = self._transition(
                job,
                JobState.FAILED,
                error_code=code,
                error_message=error.user_message,
                finished_at=utc_now(),
            )
            self._history.add(failed.id, failed.video_id, "failed", {"code": code})
            if not error.recoverable:
                self._cleanup_temp(failed)

    def _transition(self, job: DownloadJob, state: JobState, history_event: str | None = None, **changes: object) -> DownloadJob:
        updated = replace(job, state=state, updated_at=utc_now(), **changes)
        saved = self._jobs.update(updated)
        logger.info("job_id=%s transition=%s->%s", job.id, job.state.value, state.value)
        if history_event:
            self._history.add(saved.id, saved.video_id, history_event)
        self._on_updated(saved)
        return saved

    def _require(self, job_id: str) -> DownloadJob:
        job = self._jobs.get(job_id)
        if job is None:
            raise AppError(ErrorCode.INVALID_INPUT, "El trabajo no existe.", job_id)
        return job

    def _persist_completion(
        self, job: DownloadJob, track: LibraryTrack
    ) -> tuple[DownloadJob, LibraryTrack]:
        """Commit library, terminal state and history as one SQLite transaction.

        In-memory/test repositories have no transaction object and use the same
        ordered fallback while production repositories share ``Database``.
        """
        database = getattr(self._jobs, "database", None)
        if (
            database is not None
            and database is getattr(self._library, "database", None)
            and database is getattr(self._history, "database", None)
            and hasattr(database, "transaction")
        ):
            with database.transaction() as connection:
                saved_track = self._library.add(track, connection=connection)  # type: ignore[call-arg]
                saved_job = self._jobs.update(job, connection=connection)  # type: ignore[call-arg]
                self._history.add(
                    job.id,
                    job.video_id,
                    "completed",
                    connection=connection,  # type: ignore[call-arg]
                )
            return saved_job, saved_track
        saved_track = self._library.add(track)
        saved_job = self._jobs.update(job)
        self._history.add(job.id, job.video_id, "completed")
        return saved_job, saved_track

    def _persist_enqueued(self, jobs: list[DownloadJob]) -> list[DownloadJob]:
        """Persist an enqueue batch and its history atomically in production."""
        database = getattr(self._jobs, "database", None)
        if (
            database is not None
            and database is getattr(self._history, "database", None)
            and hasattr(database, "transaction")
        ):
            saved: list[DownloadJob] = []
            with database.transaction() as connection:
                for job in jobs:
                    saved_job = self._jobs.add(job, connection=connection)  # type: ignore[call-arg]
                    self._history.add(
                        saved_job.id,
                        saved_job.video_id,
                        "enqueued",
                        connection=connection,  # type: ignore[call-arg]
                    )
                    saved.append(saved_job)
            return saved

        saved = []
        for job in jobs:
            saved_job = self._jobs.add(job)
            self._history.add(saved_job.id, saved_job.video_id, "enqueued")
            saved.append(saved_job)
        return saved

    @staticmethod
    def _invalid_transition(job: DownloadJob, action: str) -> AppError:
        return AppError(
            ErrorCode.INVALID_STATE,
            f"No se puede {action} este trabajo en su estado actual.",
            f"job_id={job.id} state={job.state.value}",
            False,
        )

    @staticmethod
    def _cleanup_temp(job: DownloadJob) -> None:
        temp = Path(job.temp_dir)
        if temp.name != job.id or temp.parent.name != ".ytmp3studio-tmp":
            logger.error("job_id=%s refused unsafe temp cleanup path=%s", job.id, temp)
            return
        try:
            if temp.is_dir():
                shutil.rmtree(temp)
        except OSError:
            logger.exception("job_id=%s temp cleanup failed path=%s", job.id, temp)
