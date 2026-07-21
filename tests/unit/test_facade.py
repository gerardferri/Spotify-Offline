from __future__ import annotations

import time

from ytmp3studio.backend.facade import BackendFacade
from ytmp3studio.backend.search_service import SearchService
from ytmp3studio.domain.errors import ErrorCode
from ytmp3studio.domain.models import SearchResult, Settings


class ImmediatePool:
    def start(self, worker):
        worker.run()


class SearchProvider:
    def search(self, query, limit):
        return [SearchResult("one", "https://youtube.test/one", query)]


class Queue:
    def set_callbacks(self, **callbacks):
        self.callbacks = callbacks

    def shutdown(self, timeout=5):
        pass


class Stub:
    pass


def facade():
    return BackendFacade(
        database=Stub(),
        search_service=SearchService(SearchProvider()),
        queue_service=Queue(),
        library_service=Stub(),
        settings_service=Stub(),
        dependency_service=Stub(),
        thread_pool=ImmediatePool(),
    )


def test_search_signal_is_correlated_with_returned_request_id():
    backend = facade()
    started = []
    succeeded = []
    backend.search_started.connect(lambda request_id: started.append(request_id))
    backend.search_succeeded.connect(lambda request_id, results: succeeded.append((request_id, results)))

    request_id = backend.search("query", 5)

    assert started == [request_id]
    assert succeeded[0][0] == request_id
    assert len(succeeded[0][1]) == 1


def test_invalid_search_emits_explicit_correlated_error():
    backend = facade()
    failures = []
    backend.operation_failed.connect(lambda request_id, error: failures.append((request_id, error)))

    request_id = backend.search("   ")

    assert failures[0][0] == request_id
    assert failures[0][1].code == ErrorCode.INVALID_INPUT


def test_shutdown_during_initialization_cannot_restart_queue(tmp_path):
    class SlowDatabase:
        def __init__(self):
            self.closed = False

        def migrate(self):
            time.sleep(0.05)

        def close(self):
            self.closed = True

    class LifecycleQueue(Queue):
        def __init__(self):
            self.start_calls = 0
            self.shutdown_calls = 0

        def start(self, recover=True):
            self.start_calls += 1

        def snapshot(self):
            return []

        def shutdown(self, timeout=5):
            self.shutdown_calls += 1

    class SettingsService:
        def get(self):
            return Settings(str(tmp_path))

    class Dependencies:
        def check(self, _settings):
            return object()

    database = SlowDatabase()
    queue = LifecycleQueue()
    backend = BackendFacade(
        database=database,
        search_service=SearchService(SearchProvider()),
        queue_service=queue,
        library_service=Stub(),
        settings_service=SettingsService(),
        dependency_service=Dependencies(),
    )

    backend.initialize()
    backend.initialize()
    backend.shutdown()

    assert queue.start_calls == 0
    assert queue.shutdown_calls == 1
    assert database.closed is True
    assert backend._initialized is False
