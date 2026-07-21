from __future__ import annotations

from types import SimpleNamespace

import pytest

from ytmp3studio.backend.adapters.ytdlp_adapter import YtDlpAdapter
from ytmp3studio.domain.errors import AppError, ErrorCode
from ytmp3studio.domain.models import DependencyState


class FakeYdl:
    def __init__(self, options, payload=None, error=None):
        self.options = options
        self.payload = payload
        self.error = error

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def extract_info(self, query, download=False):
        if self.error:
            raise self.error
        return self.payload


def factory_for(payload=None, error=None):
    return lambda options: FakeYdl(options, payload, error)


def test_search_returns_multiple_normalized_results_and_skips_bad_entries():
    payload = {"entries": [
        {"id": "a", "title": "  Uno  ", "uploader": "Canal", "duration": 12.8},
        None,
        {"title": "sin id"},
        {"id": "b", "title": None, "channel": None, "is_live": True,
         "thumbnails": [{"url": "small"}, {"url": "large"}]},
    ]}
    results = YtDlpAdapter(factory_for(payload)).search("música", 4)
    assert [item.video_id for item in results] == ["a", "b"]
    assert results[0].webpage_url == "https://www.youtube.com/watch?v=a"
    assert results[0].duration_seconds == 12
    assert results[1].title == "Sin título"
    assert results[1].channel == "Canal desconocido"
    assert results[1].thumbnail_url == "large"
    assert results[1].is_live is True


@pytest.mark.parametrize("payload", [{}, {"entries": []}, None])
def test_search_empty_payload_is_empty(payload):
    assert YtDlpAdapter(factory_for(payload)).search("algo") == []


def test_search_global_network_error_is_explicit_and_recoverable():
    adapter = YtDlpAdapter(factory_for(error=RuntimeError("HTTP Error 503")))
    with pytest.raises(AppError) as raised:
        adapter.search("algo")
    assert raised.value.code == ErrorCode.NETWORK_ERROR
    assert raised.value.recoverable is True


def test_search_validates_arguments_before_adapter_call():
    adapter = YtDlpAdapter(factory_for({}))
    with pytest.raises(ValueError):
        adapter.search("  ")
    with pytest.raises(ValueError):
        adapter.search("x", 51)


def test_search_unknown_extractor_failure_uses_search_error():
    adapter = YtDlpAdapter(factory_for(error=RuntimeError("extractor exploded")))
    with pytest.raises(AppError) as raised:
        adapter.search("algo")
    assert raised.value.code == ErrorCode.SEARCH_FAILED


def test_ytdlp_diagnostic_reports_installed_version(monkeypatch):
    modules = {
        "yt_dlp": SimpleNamespace(),
        "yt_dlp.version": SimpleNamespace(__version__="2026.07.01"),
    }
    monkeypatch.setattr(
        "ytmp3studio.backend.adapters.ytdlp_adapter.importlib.import_module",
        lambda name: modules[name],
    )
    status = YtDlpAdapter(factory_for({})).diagnose()
    assert status.available is True
    assert status.version == "2026.07.01"
    assert YtDlpAdapter(factory_for({})).check().state == DependencyState.OK


def test_ytdlp_diagnostic_reports_missing(monkeypatch):
    def missing(_):
        raise ModuleNotFoundError("No module named yt_dlp")

    monkeypatch.setattr(
        "ytmp3studio.backend.adapters.ytdlp_adapter.importlib.import_module", missing
    )
    status = YtDlpAdapter(factory_for({})).diagnose()
    assert status.available is False
    assert "yt_dlp" in (status.detail or "")
