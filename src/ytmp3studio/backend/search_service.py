from __future__ import annotations

from ytmp3studio.domain.errors import AppError, ErrorCode, invalid_input
from ytmp3studio.domain.models import SearchResult
from ytmp3studio.domain.ports import MediaProvider


class SearchService:
    def __init__(self, provider: MediaProvider) -> None:
        self._provider = provider

    def search(self, query: str, limit: int = 12) -> list[SearchResult]:
        normalized = query.strip()
        if not normalized:
            raise invalid_input("Escribe algo para buscar.")
        if not 1 <= limit <= 50:
            raise invalid_input("El límite debe estar entre 1 y 50.", f"limit={limit}")
        try:
            return self._provider.search(normalized, limit)
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                ErrorCode.SEARCH_FAILED,
                "No se pudo completar la búsqueda.",
                f"{type(exc).__name__}: {exc}",
                True,
                "Comprueba la conexión e inténtalo de nuevo.",
            ) from exc

