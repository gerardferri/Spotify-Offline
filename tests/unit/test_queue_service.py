from __future__ import annotations

import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from ytmp3studio.backend.queue_service import QueueService
from ytmp3studio.domain.errors import AppError, ErrorCode
from ytmp3studio.domain.models import JobState, Progress, SearchResult, Settings


def wait_until(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not reached")


class Jobs:
    def __init__(self):
        self.data = {}
        self.lock = threading.Lock()

    def add(self, job):
        with self.lock:
            self.data[job.id] = job
        return job

    update = add

    def get(self, job_id):
        with self.lock:
            return self.data.get(job_id)

    def list(self):
        with self.lock:
            return sorted(self.data.values(), key=lambda job: (job.created_at, job.id))

    def delete(self, job_id):
        with self.lock:
            self.data.pop(job_id)

    def recover_interrupted(self):
        count = 0
        with self.lock:
            for identifier, job in list(self.data.items()):
                if job.state in {JobState.DOWNLOADING, JobState.CONVERTING, JobState.PAUSING}:
                    self.data[identifier] = replace(job, state=JobState.INTERRUPTED)
                    count += 1
        return count


class Library:
    def __init__(self):
        self.data = {}

    def add(self, track):
        self.data[track.id] = track
        return track


class History:
    def __init__(self):
        self.events = []

    def add(self, job_id, video_id, event_type, detail=None):
        self.events.append((job_id, video_id, event_type, detail))


class Provider:
    def __init__(self, root: Path, *, gate=None, failures=None):
        self.root = root
        self.gate = gate
        self.failures = list(failures or [])
        self.active = 0
        self.max_active = 0
        self.calls = 0
        self.lock = threading.Lock()

    def resolve(self, video_id):
        return SearchResult(video_id, f"https://youtube.test/{video_id}", f"Song {video_id}", "Channel")

    def download(self, job, progress, stop_event):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.calls += 1
            call = self.calls
        try:
            part = Path(job.temp_dir) / "source.part"
            part.parent.mkdir(parents=True, exist_ok=True)
            part.write_bytes(b"partial")
            progress(Progress(job.id, "downloading", 7, 10, 70.0))
            if self.gate:
                while not self.gate.is_set():
                    if stop_event.wait(0.01):
                        raise AppError(ErrorCode.CANCELLED, "detenido", recoverable=True)
            if stop_event.is_set():
                raise AppError(ErrorCode.CANCELLED, "detenido", recoverable=True)
            if call <= len(self.failures) and self.failures[call - 1]:
                raise self.failures[call - 1]
            progress(Progress(job.id, "converting"))
            final = Path(job.output_dir) / f"{job.id}.mp3"
            final.write_bytes(b"mp3")
            return final
        finally:
            with self.lock:
                self.active -= 1


def make_queue(tmp_path, provider, *, concurrency=2, retries=2):
    jobs, library, history = Jobs(), Library(), History()
    settings = Settings(str(tmp_path), concurrency=concurrency, max_retries=retries, retry_base_seconds=0)
    queue = QueueService(
        jobs, library, history, provider, lambda: settings, random_uniform=lambda _a, _b: 0.0
    )
    queue.start()
    return queue, jobs, library, history


def test_fifo_completion_and_library_persistence(tmp_path):
    provider = Provider(tmp_path)
    queue, jobs, library, history = make_queue(tmp_path, provider, concurrency=1)
    try:
        created = queue.enqueue(["a", "b", "c"])
        wait_until(lambda: all(jobs.get(job.id).state == JobState.COMPLETED for job in created))
        assert len(library.data) == 3
        assert [event[2] for event in history.events].count("completed") == 3
        assert all(jobs.get(job.id).progress_percent == 100 for job in created)
    finally:
        queue.shutdown()


def test_configurable_concurrency_caps_active_downloads(tmp_path):
    gate = threading.Event()
    provider = Provider(tmp_path, gate=gate)
    queue, jobs, _library, _history = make_queue(tmp_path, provider, concurrency=2)
    try:
        created = queue.enqueue(["a", "b", "c", "d"])
        wait_until(lambda: provider.active == 2)
        assert provider.max_active == 2
        gate.set()
        wait_until(lambda: all(jobs.get(job.id).state == JobState.COMPLETED for job in created))
    finally:
        gate.set()
        queue.shutdown()


def test_pause_preserves_partial_resume_completes_and_cancel_cleans(tmp_path):
    gate = threading.Event()
    provider = Provider(tmp_path, gate=gate)
    queue, jobs, _library, _history = make_queue(tmp_path, provider, concurrency=1)
    try:
        job = queue.enqueue(["pause-me"])[0]
        wait_until(lambda: jobs.get(job.id).state == JobState.DOWNLOADING)
        queue.pause(job.id)
        wait_until(lambda: jobs.get(job.id).state == JobState.PAUSED)
        assert (Path(job.temp_dir) / "source.part").exists()

        gate.set()
        queue.resume(job.id)
        wait_until(lambda: jobs.get(job.id).state == JobState.COMPLETED)

        gate.clear()
        cancelled = queue.enqueue(["cancel-me"])[0]
        wait_until(lambda: jobs.get(cancelled.id).state == JobState.DOWNLOADING)
        queue.cancel(cancelled.id)
        wait_until(lambda: jobs.get(cancelled.id).state == JobState.CANCELLED)
        assert not Path(cancelled.temp_dir).exists()
    finally:
        gate.set()
        queue.shutdown()


def test_recoverable_error_retries_but_permanent_error_does_not(tmp_path):
    transient = AppError(ErrorCode.NETWORK_ERROR, "red", recoverable=True)
    provider = Provider(tmp_path, failures=[transient])
    queue, jobs, _library, history = make_queue(tmp_path, provider, concurrency=1, retries=1)
    try:
        job = queue.enqueue(["retry"])[0]
        wait_until(lambda: jobs.get(job.id).state == JobState.COMPLETED)
        assert jobs.get(job.id).attempt_count == 2
        assert any(event[2] == "retry_scheduled" for event in history.events)
    finally:
        queue.shutdown()

    permanent = AppError(ErrorCode.VIDEO_UNAVAILABLE, "no disponible", recoverable=False)
    provider2 = Provider(tmp_path, failures=[permanent])
    queue2, jobs2, _library2, _history2 = make_queue(tmp_path, provider2, concurrency=1, retries=3)
    try:
        job2 = queue2.enqueue(["fail"])[0]
        wait_until(lambda: jobs2.get(job2.id).state == JobState.FAILED)
        assert provider2.calls == 1
        with pytest.raises(AppError) as caught:
            queue2.retry(job2.id)
        assert caught.value.code == ErrorCode.INVALID_STATE
    finally:
        queue2.shutdown()


def test_enqueue_resolves_entire_batch_before_persisting(tmp_path):
    class FailingResolveProvider(Provider):
        def resolve(self, video_id):
            if video_id == "bad":
                raise AppError(ErrorCode.VIDEO_UNAVAILABLE, "not available")
            return super().resolve(video_id)

    provider = FailingResolveProvider(tmp_path)
    queue, jobs, _library, history = make_queue(tmp_path, provider, concurrency=1)
    try:
        with pytest.raises(AppError):
            queue.enqueue(["good", "bad"])
        assert jobs.list() == []
        assert history.events == []
    finally:
        queue.shutdown()


def test_shutdown_is_bounded_and_persists_interrupted_state(tmp_path):
    release = threading.Event()

    class NonCooperativeProvider(Provider):
        def download(self, job, progress, stop_event):
            with self.lock:
                self.active += 1
            try:
                progress(Progress(job.id, "downloading", 1, 10, 10.0))
                release.wait(2.0)  # deliberately ignores stop_event
                final = Path(job.output_dir) / f"{job.id}.mp3"
                final.write_bytes(b"mp3")
                return final
            finally:
                with self.lock:
                    self.active -= 1

    provider = NonCooperativeProvider(tmp_path)
    queue, jobs, _library, _history = make_queue(tmp_path, provider, concurrency=1)
    job = queue.enqueue(["slow"])[0]
    wait_until(lambda: jobs.get(job.id).state == JobState.DOWNLOADING)

    started = time.monotonic()
    queue.shutdown(timeout=0.05)
    elapsed = time.monotonic() - started
    try:
        assert elapsed < 0.5
        assert jobs.get(job.id).state == JobState.INTERRUPTED
    finally:
        release.set()
        wait_until(lambda: provider.active == 0)
    assert jobs.get(job.id).state == JobState.INTERRUPTED
