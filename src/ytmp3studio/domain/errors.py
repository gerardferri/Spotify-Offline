from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ErrorCode(StrEnum):
    INVALID_INPUT = "INVALID_INPUT"
    SEARCH_FAILED = "SEARCH_FAILED"
    NETWORK_ERROR = "NETWORK_ERROR"
    VIDEO_UNAVAILABLE = "VIDEO_UNAVAILABLE"
    AGE_OR_LOGIN_REQUIRED = "AGE_OR_LOGIN_REQUIRED"
    LIVE_NOT_SUPPORTED = "LIVE_NOT_SUPPORTED"
    YTDLP_MISSING = "YTDLP_MISSING"
    YTDLP_OUTDATED = "YTDLP_OUTDATED"
    FFMPEG_MISSING = "FFMPEG_MISSING"
    FFMPEG_FAILED = "FFMPEG_FAILED"
    DOWNLOAD_FAILED = "DOWNLOAD_FAILED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    DISK_FULL = "DISK_FULL"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    DATABASE_ERROR = "DATABASE_ERROR"
    INVALID_STATE = "INVALID_STATE"
    CANCELLED = "CANCELLED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass(frozen=True, slots=True)
class AppError(Exception):
    code: ErrorCode | str
    user_message: str
    technical_message: str | None = None
    recoverable: bool = False
    suggested_action: str | None = None

    def __post_init__(self) -> None:
        Exception.__init__(self, self.user_message)

    def __str__(self) -> str:
        return self.user_message


def invalid_input(message: str, technical: str | None = None) -> AppError:
    return AppError(ErrorCode.INVALID_INPUT, message, technical, False)


def internal_error(exc: BaseException) -> AppError:
    return AppError(
        ErrorCode.INTERNAL_ERROR,
        "Se produjo un error interno.",
        f"{type(exc).__name__}: {exc}",
        False,
    )

