from __future__ import annotations

from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from ytmp3studio.backend.adapters.ffmpeg_adapter import FfmpegAdapter
from ytmp3studio.domain.errors import AppError, ErrorCode
from ytmp3studio.domain.models import DependencyState


def completed(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def test_diagnostic_reports_missing_without_spawning_process():
    adapter = FfmpegAdapter(which=lambda _: None)
    status = adapter.diagnose()
    assert status.available is False
    assert status.path is None
    assert adapter.check().state == DependencyState.MISSING


def test_resolver_prefers_optional_repository_tool(monkeypatch, tmp_path: Path):
    executable = tmp_path / "tools" / "ffmpeg.exe"
    executable.parent.mkdir()
    executable.touch()
    monkeypatch.setattr(
        "ytmp3studio.backend.adapters.ffmpeg_adapter.__file__",
        str(tmp_path / "src" / "ytmp3studio" / "backend" / "adapters" / "ffmpeg_adapter.py"),
    )
    adapter = FfmpegAdapter(which=lambda _: "C:/path/ffmpeg.exe")
    assert adapter.resolve_executable() == str(executable.resolve())


def test_diagnostic_parses_version():
    calls = []
    adapter = FfmpegAdapter(
        which=lambda _: "C:/tools/ffmpeg.exe",
        runner=lambda *args, **kwargs: calls.append((args, kwargs)) or completed(
            stdout="ffmpeg version 7.1-full_build Copyright"
        ),
    )
    status = adapter.diagnose()
    assert status.available is True
    assert status.version == "7.1-full_build"
    assert calls[0][0][0][-1] == "-version"


def test_check_distinguishes_broken_executable_from_missing():
    adapter = FfmpegAdapter(
        which=lambda _: "C:/tools/ffmpeg.exe",
        runner=lambda *_, **__: completed(1, stderr="failed to start"),
    )
    assert adapter.check().state == DependencyState.ERROR


def test_convert_maps_nonzero_exit_and_keeps_stderr(tmp_path: Path):
    adapter = FfmpegAdapter(
        which=lambda _: "ffmpeg",
        runner=lambda *_, **__: completed(1, stderr="invalid input"),
    )
    with pytest.raises(AppError) as raised:
        adapter.convert_to_mp3(tmp_path / "in.webm", tmp_path / "out.mp3", 192)
    assert raised.value.code == ErrorCode.FFMPEG_FAILED
    assert raised.value.technical_message == "invalid input"


def test_convert_builds_expected_bitrate_command(tmp_path: Path):
    seen = []
    adapter = FfmpegAdapter(
        which=lambda _: "ffmpeg",
        runner=lambda command, **kwargs: seen.append(command) or completed(),
    )
    target = adapter.convert_to_mp3(tmp_path / "in.webm", tmp_path / "out.mp3", 320)
    assert target == tmp_path / "out.mp3"
    assert seen[0][seen[0].index("-b:a") + 1] == "320k"


def test_convert_maps_disk_full_to_non_retryable_domain_error(tmp_path: Path):
    adapter = FfmpegAdapter(
        which=lambda _: "ffmpeg",
        runner=lambda *_, **__: completed(1, stderr="No space left on device"),
    )
    with pytest.raises(AppError) as raised:
        adapter.convert_to_mp3(tmp_path / "in.webm", tmp_path / "out.mp3", 192)
    assert raised.value.code == ErrorCode.DISK_FULL
    assert raised.value.recoverable is False


def test_convert_terminates_process_when_shutdown_is_requested(monkeypatch, tmp_path):
    class Process:
        def __init__(self):
            self.returncode = None
            self.terminated = False

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = -15

        def kill(self):
            self.returncode = -9

        def communicate(self, timeout=None):
            return "", "stopped"

    process = Process()
    monkeypatch.setattr(
        "ytmp3studio.backend.adapters.ffmpeg_adapter.subprocess.Popen",
        lambda *args, **kwargs: process,
    )
    stop = Event()
    stop.set()
    adapter = FfmpegAdapter(which=lambda _: "ffmpeg")

    with pytest.raises(AppError) as raised:
        adapter.convert_to_mp3(
            tmp_path / "in.webm",
            tmp_path / "out.mp3",
            192,
            stop_event=stop,
        )

    assert raised.value.code == ErrorCode.CANCELLED
    assert process.terminated is True
