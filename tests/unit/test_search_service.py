from __future__ import annotations

import pytest

from ytmp3studio.backend.search_service import SearchService
from ytmp3studio.domain.errors import AppError, ErrorCode
from ytmp3studio.domain.models import SearchResult


class Provider:
    def __init__(self, results=None, error=None):
        self.results = results or []
        self.error = error
        self.calls = []

    def search(self, query, limit):
        self.calls.append((query, limit))
        if self.error:
            raise self.error
        return self.results[:limit]


def test_search_returns_multiple_results_in_provider_order():
    expected = [
        SearchResult(str(i), f"https://youtube.test/watch?v={i}", f"Title {i}")
        for i in range(3)
    ]
    provider = Provider(expected)

    assert SearchService(provider).search("  música  ", 3) == expected
    assert provider.calls == [("música", 3)]


@pytest.mark.parametrize("query,limit", [("", 12), ("ok", 0), ("ok", 51)])
def test_search_rejects_invalid_input(query, limit):
    with pytest.raises(AppError) as caught:
        SearchService(Provider()).search(query, limit)
    assert caught.value.code == ErrorCode.INVALID_INPUT


def test_search_maps_unexpected_global_failure():
    with pytest.raises(AppError) as caught:
        SearchService(Provider(error=RuntimeError("extractor exploded"))).search("query")
    assert caught.value.code == ErrorCode.SEARCH_FAILED
    assert caught.value.recoverable is True
    assert "extractor exploded" in (caught.value.technical_message or "")

