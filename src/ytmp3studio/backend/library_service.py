from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import subprocess
from typing import Callable

from ytmp3studio.domain.errors import AppError, ErrorCode, invalid_input
from ytmp3studio.domain.models import LibraryFolder, LibraryTrack
from ytmp3studio.domain.ports import LibraryRepositoryPort


class LibraryService:
    def __init__(
        self,
        repository: LibraryRepositoryPort,
        reveal_file: Callable[[Path], None] | None = None,
    ) -> None:
        self._repository = repository
        self._reveal_file = reveal_file or _reveal_in_explorer

    def list(self, filter_text: str = "", limit: int = 200, offset: int = 0, folder_id: str | None = None) -> tuple[list[LibraryTrack], int]:
        if not 1 <= limit <= 500 or offset < 0:
            raise invalid_input("La paginación de biblioteca no es válida.")
        tracks, total = self._repository.list(filter_text.strip(), limit, offset, folder_id)
        reconciled = [replace(t, file_missing=not Path(t.file_path).is_file()) for t in tracks]
        return reconciled, total

    def list_folders(self) -> list[LibraryFolder]:
        return self._repository.list_folders()

    def create_folder(self, name: str) -> LibraryFolder:
        normalized = self._validate_folder_name(name)
        self._ensure_unique_folder_name(normalized)
        return self._repository.create_folder(normalized)

    def rename_folder(self, folder_id: str, name: str) -> LibraryFolder:
        folder = self._repository.get_folder(folder_id)
        if folder is None:
            raise AppError(ErrorCode.FILE_NOT_FOUND, "La carpeta ya no existe.")
        normalized = self._validate_folder_name(name)
        self._ensure_unique_folder_name(normalized, except_id=folder_id)
        return self._repository.rename_folder(folder_id, normalized)

    def delete_folder(self, folder_id: str) -> None:
        if self._repository.get_folder(folder_id) is None:
            raise AppError(ErrorCode.FILE_NOT_FOUND, "La carpeta ya no existe.")
        self._repository.delete_folder(folder_id)

    def assign_folder(self, track_id: str, folder_id: str | None) -> None:
        if self._repository.get(track_id) is None:
            raise AppError(ErrorCode.FILE_NOT_FOUND, "La pista ya no existe en la biblioteca.")
        if folder_id is not None and self._repository.get_folder(folder_id) is None:
            raise AppError(ErrorCode.FILE_NOT_FOUND, "La carpeta ya no existe.")
        self._repository.assign_folder(track_id, folder_id)

    @staticmethod
    def _validate_folder_name(name: str) -> str:
        normalized = " ".join(name.strip().split())
        if not normalized:
            raise invalid_input("Escribe un nombre para la carpeta.")
        if len(normalized) > 60:
            raise invalid_input("El nombre de la carpeta no puede superar 60 caracteres.")
        return normalized

    def _ensure_unique_folder_name(self, name: str, except_id: str | None = None) -> None:
        duplicate = next(
            (folder for folder in self._repository.list_folders() if folder.name.casefold() == name.casefold()),
            None,
        )
        if duplicate is not None and duplicate.id != except_id:
            raise invalid_input("Ya existe una carpeta con ese nombre.")

    def remove(self, track_id: str, delete_file: bool = False) -> None:
        track = self._repository.get(track_id)
        if track is None:
            raise AppError(ErrorCode.FILE_NOT_FOUND, "La pista ya no existe en la biblioteca.")
        if delete_file:
            path = Path(track.file_path)
            try:
                if path.exists():
                    path.unlink()
            except PermissionError as exc:
                raise AppError(
                    ErrorCode.PERMISSION_DENIED,
                    "No se pudo borrar el archivo de audio.",
                    str(exc),
                    False,
                ) from exc
        self._repository.remove(track_id)

    def reveal(self, track_id: str) -> None:
        track = self._repository.get(track_id)
        if track is None:
            raise AppError(ErrorCode.FILE_NOT_FOUND, "La pista ya no existe en la biblioteca.")
        path = Path(track.file_path)
        if not path.is_file():
            raise AppError(
                ErrorCode.FILE_NOT_FOUND,
                "El archivo de audio ya no existe.",
                str(path),
                False,
            )
        try:
            self._reveal_file(path.resolve())
        except OSError as exc:
            raise AppError(
                ErrorCode.FILE_NOT_FOUND,
                "No se pudo abrir el Explorador de archivos.",
                str(exc),
                False,
            ) from exc


def _reveal_in_explorer(path: Path) -> None:
    if os.name != "nt":
        raise OSError("Reveal is only supported by the Windows build")
    subprocess.Popen(
        ["explorer.exe", f"/select,{path}"],
        close_fds=True,
        creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
    )
