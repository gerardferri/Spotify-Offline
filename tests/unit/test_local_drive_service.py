from __future__ import annotations

import pytest

from ytmp3studio.backend.local_drive_service import (
    LocalGoogleDriveService,
    detect_google_drive,
)


def test_local_drive_scans_subfolders_and_audio_only(tmp_path) -> None:
    root = tmp_path / "Mi unidad" / "YT-MP3 Studio"
    rock = root / "Rock"
    rock.mkdir(parents=True)
    (root / "Inicio.mp3").write_bytes(b"root")
    (rock / "Tema.flac").write_bytes(b"rock")
    (rock / "cover.jpg").write_bytes(b"image")

    snapshot = LocalGoogleDriveService(root).scan_library()

    assert snapshot.root_folder.name == "YT-MP3 Studio"
    assert [folder.name for folder in snapshot.folders] == ["Descargas", "Rock"]
    assert [track.name for track in snapshot.tracks] == ["Inicio.mp3", "Tema.flac"]
    assert all(track.local_path for track in snapshot.tracks)
    assert len(snapshot.changes_token) == 64


def test_local_file_identity_survives_rename(tmp_path) -> None:
    root = tmp_path / "Mi unidad" / "YT-MP3 Studio"
    root.mkdir(parents=True)
    original = root / "Antes.mp3"
    original.write_bytes(b"audio")
    service = LocalGoogleDriveService(root)
    first_id = service.scan_library().tracks[0].id

    original.rename(root / "Después.mp3")

    assert service.scan_library().tracks[0].id == first_id


def test_downloads_folder_is_created_inside_the_linked_drive_folder(tmp_path) -> None:
    root = tmp_path / "Mi unidad" / "YT-MP3 Studio"
    root.parent.mkdir(parents=True)
    service = LocalGoogleDriveService(root)

    target = service.ensure_downloads_folder()

    assert target == root / "Descargas"
    assert target.is_dir()


def test_scan_publishes_downloads_folder_even_on_a_brand_new_drive(tmp_path) -> None:
    root = tmp_path / "Mi unidad" / "YT-MP3 Studio"
    root.parent.mkdir(parents=True)

    snapshot = LocalGoogleDriveService(root).scan_library()

    assert [folder.name for folder in snapshot.folders] == ["Descargas"]


def test_environment_override_detects_prelinked_drive(monkeypatch, tmp_path) -> None:
    root = tmp_path / "Mi unidad" / "YT-MP3 Studio"
    root.parent.mkdir(parents=True)
    monkeypatch.setenv("YTMP3_GOOGLE_DRIVE_ROOT", str(root))

    location = detect_google_drive()

    assert location is not None
    assert location.music_root == root


def test_list_folders_returns_visible_direct_subfolders_casefold_sorted(tmp_path) -> None:
    root = tmp_path / "Mi unidad" / "YT-MP3 Studio"
    root.mkdir(parents=True)
    for name in ("zeta", "Álbum", "beta", ".oculta"):
        (root / name).mkdir()
    (root / "canción.mp3").write_bytes(b"audio")

    assert LocalGoogleDriveService(root).list_folders() == ["beta", "zeta", "Álbum"]


def test_list_folders_returns_empty_when_music_root_does_not_exist(tmp_path) -> None:
    root = tmp_path / "Mi unidad" / "YT-MP3 Studio"

    assert LocalGoogleDriveService(root).list_folders() == []


@pytest.mark.parametrize("name", [None, "", "   "])
def test_resolve_folder_uses_downloads_as_default(name, tmp_path) -> None:
    root = tmp_path / "Mi unidad" / "YT-MP3 Studio"
    service = LocalGoogleDriveService(root)

    target = service.resolve_folder(name)

    assert target == (root / "Descargas").resolve()
    assert target.is_dir()


def test_resolve_folder_creates_valid_subfolder(tmp_path) -> None:
    root = tmp_path / "Mi unidad" / "YT-MP3 Studio"

    target = LocalGoogleDriveService(root).resolve_folder(" Favoritas ")

    assert target == (root / "Favoritas").resolve()
    assert target.is_dir()


@pytest.mark.parametrize(
    "name",
    [
        "../fuera",
        "..\\fuera",
        "..",
        "/absoluta",
        "\\absoluta",
        "C:\\Musica",
        "C:",
        "CON",
        "prn.txt",
        "AUX",
        "NUL",
        "COM1",
        "com9.mp3",
        "LPT1",
        "lpt9.txt",
        "menor<",
        "mayor>",
        'comillas"',
        "barra|",
        "pregunta?",
        "asterisco*",
        "dos:puntos",
    ],
)
def test_resolve_folder_rejects_traversal_and_invalid_windows_names(
    name, tmp_path
) -> None:
    root = tmp_path / "Mi unidad" / "YT-MP3 Studio"

    with pytest.raises(ValueError, match="carpeta"):
        LocalGoogleDriveService(root).resolve_folder(name)


@pytest.mark.parametrize(
    "name",
    [
        "a\x00b",
        "a\x08b",
        "a\nb",
        "a\tb",
        "x" * 101,
    ],
)
def test_resolve_folder_rejects_names_the_filesystem_would_choke_on(name, tmp_path) -> None:
    """These used to escape validation and surface as an opaque OSError/500."""

    root = tmp_path / "Mi unidad" / "YT-MP3 Studio"

    with pytest.raises(ValueError, match="carpeta"):
        LocalGoogleDriveService(root).resolve_folder(name)


def test_resolve_folder_accepts_a_name_at_the_length_limit(tmp_path) -> None:
    root = tmp_path / "Mi unidad" / "YT-MP3 Studio"

    target = LocalGoogleDriveService(root).resolve_folder("x" * 100)

    assert target.name == "x" * 100
    assert target.is_dir()
