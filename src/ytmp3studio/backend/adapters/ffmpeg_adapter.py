"""Subprocess boundary for ffmpeg diagnostics and MP3 conversion."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import os
import errno
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from threading import Event
from typing import Any

from ytmp3studio.domain.errors import AppError, ErrorCode
from ytmp3studio.domain.models import DependencyItem, DependencyState


@dataclass(frozen=True, slots=True)
class ToolDiagnostic:
    available: bool
    path: str | None = None
    version: str | None = None
    detail: str | None = None


class FfmpegAdapter:
    def __init__(
        self,
        executable: str | Path | None = None,
        *,
        runner: Callable[..., Any] = subprocess.run,
        which: Callable[[str], str | None] = shutil.which,
    ) -> None:
        self._configured_executable = str(executable) if executable is not None else None
        self._runner = runner
        self._which = which

    def resolve_executable(self) -> str | None:
        if self._configured_executable:
            candidate = Path(self._configured_executable)
            if candidate.is_file():
                return str(candidate.resolve())
            # Also allow an injected command name such as "ffmpeg".
            return self._which(self._configured_executable)
        # In development this resolves to ``<repository>/tools``. In a
        # PyInstaller onedir bundle, ``sys._MEIPASS`` is the ``_internal``
        # directory where the spec places the optional binary.
        bundle_root = Path(
            getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[4])
        )
        for relative_path in (
            Path("tools") / "ffmpeg.exe",
            Path("bin") / "ffmpeg.exe",  # compatibility with older bundles
        ):
            bundled = bundle_root / relative_path
            if bundled.is_file():
                return str(bundled.resolve())
        return self._which("ffmpeg")

    def diagnose(self, timeout_seconds: float = 5.0) -> ToolDiagnostic:
        executable = self.resolve_executable()
        if not executable:
            return ToolDiagnostic(False, detail="ffmpeg no se encontró en el paquete ni en PATH")
        try:
            completed = self._runner(
                [executable, "-version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                check=False,
                creationflags=_no_window_flag(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return ToolDiagnostic(False, path=executable, detail=str(exc))
        output = f"{completed.stdout or ''}\n{completed.stderr or ''}".strip()
        version = _parse_ffmpeg_version(output)
        if completed.returncode != 0:
            return ToolDiagnostic(False, path=executable, version=version, detail=output)
        return ToolDiagnostic(True, path=executable, version=version)

    def check(self) -> DependencyItem:
        """Return the domain diagnostic consumed by ``DependencyService``."""
        diagnostic = self.diagnose()
        state = (
            DependencyState.OK
            if diagnostic.available
            else DependencyState.ERROR
            if diagnostic.path
            else DependencyState.MISSING
        )
        return DependencyItem(
            name="ffmpeg",
            state=state,
            version=diagnostic.version,
            path=diagnostic.path,
            message=diagnostic.detail,
        )

    def convert_to_mp3(
        self,
        source: str | Path,
        destination: str | Path,
        quality_kbps: int,
        *,
        timeout_seconds: float | None = None,
        stop_event: Event | None = None,
    ) -> Path:
        if quality_kbps not in (128, 192, 256, 320):
            raise ValueError("quality_kbps debe ser 128, 192, 256 o 320")
        executable = self.resolve_executable()
        if not executable:
            raise AppError(ErrorCode.FFMPEG_MISSING, "ffmpeg no está instalado.")
        source_path = Path(source)
        destination_path = Path(destination)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        command: Sequence[str] = (
            executable,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source_path),
            "-vn",
            "-codec:a",
            "libmp3lame",
            "-b:a",
            f"{quality_kbps}k",
            str(destination_path),
        )
        try:
            if stop_event is not None and self._runner is subprocess.run:
                completed = _run_cancellable(
                    command,
                    stop_event,
                    timeout_seconds=timeout_seconds,
                )
            else:
                completed = self._runner(
                    list(command),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout_seconds,
                    check=False,
                    creationflags=_no_window_flag(),
                )
        except AppError:
            raise
        except FileNotFoundError as exc:
            raise AppError(ErrorCode.FFMPEG_MISSING, "ffmpeg no está instalado.", str(exc)) from exc
        except (OSError, subprocess.SubprocessError) as exc:
            if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
                raise AppError(ErrorCode.DISK_FULL, "No hay espacio suficiente en el disco.", str(exc)) from exc
            if isinstance(exc, OSError) and exc.errno in {errno.EACCES, errno.EPERM}:
                raise AppError(ErrorCode.PERMISSION_DENIED, "No hay permiso para escribir el archivo.", str(exc)) from exc
            raise AppError(ErrorCode.FFMPEG_FAILED, "ffmpeg no pudo ejecutarse.", str(exc)) from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            lowered = detail.lower()
            if any(marker in lowered for marker in ("no space left", "disk full", "not enough space")):
                raise AppError(ErrorCode.DISK_FULL, "No hay espacio suficiente en el disco.", detail)
            if any(marker in lowered for marker in ("permission denied", "access is denied")):
                raise AppError(ErrorCode.PERMISSION_DENIED, "No hay permiso para escribir el archivo.", detail)
            raise AppError(ErrorCode.FFMPEG_FAILED, "ffmpeg no pudo convertir el audio.", detail)
        return destination_path


def _parse_ffmpeg_version(output: str) -> str | None:
    match = re.search(r"(?im)^ffmpeg version\s+([^\s]+)", output)
    return match.group(1) if match else None


def _no_window_flag() -> int:
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0


def _run_cancellable(
    command: Sequence[str],
    stop_event: Event,
    *,
    timeout_seconds: float | None,
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        list(command),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_no_window_flag(),
    )
    deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
    while process.poll() is None:
        if stop_event.wait(0.05):
            process.terminate()
            try:
                stdout, stderr = process.communicate(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
            raise AppError(
                ErrorCode.CANCELLED,
                "La conversion se ha detenido.",
                (stderr or stdout or "").strip() or None,
                True,
            )
        if deadline is not None and time.monotonic() >= deadline:
            process.terminate()
            try:
                process.communicate(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
            raise AppError(
                ErrorCode.FFMPEG_FAILED,
                "ffmpeg tardo demasiado en convertir el audio.",
                f"timeout={timeout_seconds}s",
            )
    stdout, stderr = process.communicate()
    return subprocess.CompletedProcess(list(command), process.returncode, stdout, stderr)
