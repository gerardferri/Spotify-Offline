from __future__ import annotations

from http.client import HTTPConnection
import json
from pathlib import Path
from threading import Thread

import pytest

from ytmp3studio.domain.models import LibraryTrack
from ytmp3studio.mobile_server import MobileApiServer, _parse_range, load_or_create_token


TOKEN = "a-secure-personal-token-with-24-chars"
ORIGIN = "https://gerardferri.github.io"


class FakeBackend:
    def __init__(self, audio_path: Path) -> None:
        self.audio_path = audio_path

    def search(self, query: str, limit: int):
        return [{"video_id": "abc", "title": query, "channel": "Canal", "duration_seconds": 42}][:limit]

    def enqueue(self, video_id: str, quality_kbps: int | None):
        return [{"id": "job-1", "video_id": video_id, "quality_kbps": quality_kbps, "state": "queued"}]

    def queue_snapshot(self):
        return [{"id": "job-1", "state": "completed", "track_id": "track-1"}]

    def get_track(self, track_id: str):
        if track_id != "track-1":
            return None
        return LibraryTrack(
            id="track-1",
            job_id="job-1",
            video_id="abc",
            title="Prueba",
            channel="Canal",
            source_url="https://example.test/watch?v=abc",
            file_path=str(self.audio_path),
            file_size_bytes=self.audio_path.stat().st_size,
            quality_kbps=192,
            created_at="2026-01-01T00:00:00Z",
        )


@pytest.fixture
def api(tmp_path):
    audio_path = tmp_path / "test.mp3"
    audio_path.write_bytes(b"0123456789")
    server = MobileApiServer(("127.0.0.1", 0), FakeBackend(audio_path), TOKEN, {ORIGIN})
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def request(api, method: str, path: str, *, token: str | None = TOKEN, body=None, headers=None):
    connection = HTTPConnection(*api, timeout=3)
    request_headers = {"Origin": ORIGIN, **(headers or {})}
    if token:
        request_headers["Authorization"] = f"Bearer {token}"
    encoded = None
    if body is not None:
        encoded = json.dumps(body).encode()
        request_headers["Content-Type"] = "application/json"
        request_headers["Content-Length"] = str(len(encoded))
    connection.request(method, path, body=encoded, headers=request_headers)
    response = connection.getresponse()
    data = response.read()
    connection.close()
    return response, data


def test_health_requires_token_and_allows_configured_origin(api):
    response, data = request(api, "GET", "/api/health")
    assert response.status == 200
    assert response.getheader("Access-Control-Allow-Origin") == ORIGIN
    assert json.loads(data)["ok"] is True

    denied, payload = request(api, "GET", "/api/health", token="wrong")
    assert denied.status == 401
    assert json.loads(payload)["error"]["code"] == "UNAUTHORIZED"


def test_search_enqueue_and_queue_snapshot(api):
    search, payload = request(api, "GET", "/api/search?q=Hola&limit=5")
    assert search.status == 200
    assert json.loads(payload)["results"][0]["title"] == "Hola"

    queued, payload = request(
        api,
        "POST",
        "/api/jobs",
        body={"video_id": "abc", "quality_kbps": 192},
    )
    assert queued.status == 202
    assert json.loads(payload)["jobs"][0]["video_id"] == "abc"

    snapshot, payload = request(api, "GET", "/api/jobs")
    assert snapshot.status == 200
    assert json.loads(payload)["jobs"][0]["track_id"] == "track-1"


def test_audio_supports_byte_ranges(api):
    response, data = request(
        api,
        "GET",
        "/api/tracks/track-1/audio",
        headers={"Range": "bytes=2-5"},
    )
    assert response.status == 206
    assert response.getheader("Content-Range") == "bytes 2-5/10"
    assert data == b"2345"


@pytest.mark.parametrize(
    ("header", "size", "expected"),
    [
        (None, 10, (0, 9, False)),
        ("bytes=3-", 10, (3, 9, True)),
        ("bytes=-4", 10, (6, 9, True)),
    ],
)
def test_parse_range(header, size, expected):
    assert _parse_range(header, size) == expected


def test_explicit_token_must_be_long_enough():
    with pytest.raises(ValueError):
        load_or_create_token("short")
