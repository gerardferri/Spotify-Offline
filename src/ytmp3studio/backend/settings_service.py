from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Callable

from ytmp3studio.domain.errors import AppError, ErrorCode, invalid_input
from ytmp3studio.domain.models import Settings
from ytmp3studio.domain.ports import SettingsRepositoryPort
from ytmp3studio.backend.adapters.media_files import MediaFiles


class SettingsService:
    ALLOWED = frozenset(asdict(Settings(download_dir=".")).keys())

    def __init__(
        self,
        repository: SettingsRepositoryPort,
        concurrency_changed: Callable[[int], None] | None = None,
    ) -> None:
        self._repository = repository
        self._concurrency_changed = concurrency_changed

    def get(self) -> Settings:
        return self._repository.get()

    def update(self, patch: dict[str, Any]) -> Settings:
        if not isinstance(patch, dict) or not patch:
            raise invalid_input("No hay cambios de configuración que guardar.")
        unknown = set(patch) - self.ALLOWED
        if unknown:
            raise invalid_input("Hay opciones de configuración desconocidas.", str(sorted(unknown)))
        current = self.get()
        try:
            candidate = replace(current, **patch)
        except (TypeError, ValueError) as exc:
            raise invalid_input("La configuración no es válida.", str(exc)) from exc
        self.validate(candidate)
        saved = self._repository.update(candidate)
        if saved.concurrency != current.concurrency and self._concurrency_changed:
            self._concurrency_changed(saved.concurrency)
        return saved

    @staticmethod
    def validate(settings: Settings, *, create_dir: bool = True) -> None:
        if settings.quality_kbps not in {128, 192, 256, 320}:
            raise invalid_input("La calidad debe ser 128, 192, 256 o 320 kbps.")
        if settings.theme not in {"system", "light", "dark"}:
            raise invalid_input("El tema debe ser sistema, claro u oscuro.")
        if not 1 <= settings.concurrency <= 4:
            raise invalid_input("La concurrencia debe estar entre 1 y 4.")
        if not 0 <= settings.max_retries <= 5:
            raise invalid_input("Los reintentos deben estar entre 0 y 5.")
        if not 1 <= settings.retry_base_seconds <= 60:
            raise invalid_input("La espera base debe estar entre 1 y 60 segundos.")
        path = Path(settings.download_dir).expanduser()
        try:
            if create_dir:
                path.mkdir(parents=True, exist_ok=True)
        except PermissionError as exc:
            raise AppError(
                ErrorCode.PERMISSION_DENIED,
                "No se puede crear la carpeta de descargas.",
                str(exc),
                False,
                "Elige otra carpeta con permisos de escritura.",
            ) from exc
        if create_dir:
            try:
                MediaFiles.ensure_writable_directory(path)
            except OSError as exc:
                raise AppError(
                    ErrorCode.PERMISSION_DENIED,
                    "La carpeta de descargas no permite escribir.",
                    str(exc),
                    False,
                    "Elige otra carpeta con permisos de escritura.",
                ) from exc
