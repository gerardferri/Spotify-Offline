from __future__ import annotations

from http.client import HTTPConnection
import json
from pathlib import Path
from threading import Thread

import pytest

from ytmp3studio.domain.models import LibraryTrack
from ytmp3studio.mobile_server import (
    MobileApiServer,
    _is_private_lan_host,
    _parse_range,
    build_parser,
    load_or_create_token,
    main,
)


TOKEN = "a-secure-personal-token-with-24-chars"
ORIGIN = "https://gerardferri.github.io"
PWA_DIRECTORY = Path(__file__).resolve().parents[2] / "prototype"


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

    def drive_status(self):
        return {
            "connected": True,
            "configured": True,
            "account_email": "me@example.test",
            "folder_name": "YT-MP3 Studio",
            "last_sync_at": "2026-07-22T12:00:00Z",
            "syncing": False,
            "folders": [{"id": "rock", "name": "Rock", "track_count": 1}],
            "track_count": 1,
        }

    def drive_authorization_url(self):
        return "https://accounts.google.test/oauth"

    def sync_drive(self):
        return self.drive_status()

    def disconnect_drive(self):
        return {**self.drive_status(), "connected": False}

    def drive_tracks(self, folder_id=None):
        return [{"file_id": "drive-track", "folder_id": folder_id, "name": "Drive.mp3"}]

    def download_drive_track(self, file_id, range_header=None):
        assert file_id == "drive-track"
        return b"drive-audio", {"Content-Type": "audio/mpeg"}, 200


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


def test_drive_catalog_sync_tracks_and_audio(api):
    status, payload = request(api, "GET", "/api/drive/status")
    assert status.status == 200
    assert json.loads(payload)["drive"]["account_email"] == "me@example.test"

    synced, payload = request(api, "POST", "/api/drive/sync")
    assert synced.status == 200
    assert json.loads(payload)["drive"]["track_count"] == 1

    tracks, payload = request(api, "GET", "/api/drive/folders/rock/tracks")
    assert tracks.status == 200
    assert json.loads(payload)["tracks"][0]["file_id"] == "drive-track"

    audio, data = request(api, "GET", "/api/drive/files/drive-track/audio")
    assert audio.status == 200
    assert data == b"drive-audio"


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


@pytest.mark.parametrize(
    "hostname, expected",
    [
        ("192.168.1.50", True),
        ("10.0.0.5", True),
        ("172.20.4.9", True),
        ("172.15.0.1", False),
        ("172.32.0.1", False),
        ("8.8.8.8", False),
        ("127.0.0.1", False),
        ("not-an-ip", False),
        ("", False),
    ],
)
def test_is_private_lan_host(hostname, expected):
    assert _is_private_lan_host(hostname) is expected


def test_lan_flag_without_web_is_rejected():
    with pytest.raises(SystemExit):
        main(["--lan"])


def test_lan_flag_defaults_host_to_all_interfaces():
    args = build_parser().parse_args(["--web", "--lan"])
    assert args.lan is True
    assert args.host == "127.0.0.1"  # main() promotes this to 0.0.0.0 when --lan is set


def test_local_web_serves_pwa_and_allows_only_its_same_origin_without_token(tmp_path):
    audio_path = tmp_path / "test.mp3"
    audio_path.write_bytes(b"0123456789")
    server = MobileApiServer(
        ("127.0.0.1", 0),
        FakeBackend(audio_path),
        TOKEN,
        {ORIGIN},
        static_dir=PWA_DIRECTORY,
        allow_local_web_without_token=True,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        local_origin = f"http://127.0.0.1:{server.server_port}"
        page, html = request(server.server_address, "GET", "/", token=None, headers={"Origin": local_origin})
        assert page.status == 200
        assert page.getheader("Content-Type") == "text/html"
        assert b"YT-MP3 Studio" in html

        health, payload = request(
            server.server_address,
            "GET",
            "/api/health",
            token=None,
            headers={"Origin": "", "Host": f"127.0.0.1:{server.server_port}"},
        )
        assert health.status == 200
        assert json.loads(payload)["ok"] is True

        connect, payload = request(
            server.server_address,
            "POST",
            "/api/drive/connect",
            token=None,
            headers={"Origin": local_origin},
        )
        assert connect.status == 200
        assert json.loads(payload)["authorization_url"].startswith("https://accounts.google.test/")

        remote, _payload = request(
            server.server_address,
            "GET",
            "/api/health",
            token=None,
            headers={"Host": "desktop.example.test"},
        )
        assert remote.status == 401
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_lan_phone_reaches_local_web_without_a_token(tmp_path):
    """Same-WiFi devices (e.g. an iPhone at a private IP) must be trusted like the PC itself."""
    audio_path = tmp_path / "test.mp3"
    audio_path.write_bytes(b"0123456789")
    server = MobileApiServer(
        ("127.0.0.1", 0),
        FakeBackend(audio_path),
        TOKEN,
        {ORIGIN},
        static_dir=PWA_DIRECTORY,
        allow_local_web_without_token=True,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        lan_host = f"192.168.1.50:{server.server_port}"
        health, payload = request(
            server.server_address,
            "GET",
            "/api/health",
            token=None,
            headers={"Origin": f"http://{lan_host}", "Host": lan_host},
        )
        assert health.status == 200
        assert json.loads(payload)["ok"] is True

        mismatched_host = f"192.168.1.50:{server.server_port + 1}"
        health, _payload = request(
            server.server_address,
            "GET",
            "/api/health",
            token=None,
            headers={"Origin": f"http://{lan_host}", "Host": mismatched_host},
        )
        assert health.status == 401

        public_host = f"8.8.8.8:{server.server_port}"
        health, _payload = request(
            server.server_address,
            "GET",
            "/api/health",
            token=None,
            headers={"Origin": f"http://{public_host}", "Host": public_host},
        )
        assert health.status == 403  # a public-IP origin is rejected by CORS before auth runs
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_lan_access_is_still_blocked_without_the_wifi_flag(tmp_path):
    audio_path = tmp_path / "test.mp3"
    audio_path.write_bytes(b"0123456789")
    server = MobileApiServer(
        ("127.0.0.1", 0),
        FakeBackend(audio_path),
        TOKEN,
        {ORIGIN},
        static_dir=PWA_DIRECTORY,
        allow_local_web_without_token=False,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        health, _payload = request(
            server.server_address,
            "GET",
            "/api/health",
            token=None,
            headers={"Host": f"192.168.1.50:{server.server_port}"},
        )
        assert health.status == 401
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
