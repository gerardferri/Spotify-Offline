from __future__ import annotations

import errno
import sqlite3

from ytmp3studio.domain.errors import AppError, ErrorCode, internal_error


def to_app_error(exc: BaseException) -> AppError:
    if isinstance(exc, AppError):
        return exc
    if isinstance(exc, sqlite3.Error):
        return AppError(
            ErrorCode.DATABASE_ERROR,
            "No se pudieron guardar o leer los datos locales.",
            f"{type(exc).__name__}: {exc}",
            True,
            "Reinicia la aplicación. Si continúa, revisa el archivo de log.",
        )
    if isinstance(exc, PermissionError):
        return AppError(
            ErrorCode.PERMISSION_DENIED,
            "No hay permisos suficientes para completar la operación.",
            str(exc),
            False,
            "Elige una carpeta con permisos de escritura.",
        )
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        return AppError(
            ErrorCode.DISK_FULL,
            "No hay espacio suficiente en el disco.",
            str(exc),
            False,
            "Libera espacio y vuelve a intentarlo.",
        )
    return internal_error(exc)

