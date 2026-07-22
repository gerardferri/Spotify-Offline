from __future__ import annotations

import os
import zipfile

import pytest

from ytmp3studio.backend.local_drive_service import (
    EXPORTS_FOLDER_NAME,
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


def test_refresh_zip_exports_creates_archives_with_direct_audio_only(tmp_path) -> None:
    root = tmp_path / "Mi unidad" / "YT-MP3 Studio"
    rock = root / "Rock"
    empty = root / "Vacía"
    nested = rock / "Anidada"
    nested.mkdir(parents=True)
    empty.mkdir()
    (rock / "canción.mp3").write_bytes(b"mp3")
    (rock / "Tema.flac").write_bytes(b"flac")
    (rock / "cover.jpg").write_bytes(b"image")
    (nested / "Oculta.ogg").write_bytes(b"nested")
    service = LocalGoogleDriveService(root)

    assert service.refresh_zip_exports() == ["Rock"]

    rock_zip = service.exports_root / "Rock.zip"
    assert rock_zip.is_file()
    assert not (service.exports_root / "Vacía.zip").exists()
    with zipfile.ZipFile(rock_zip) as archive:
        assert sorted(archive.namelist()) == ["Tema.flac", "canción.mp3"]


def test_refresh_zip_exports_does_not_rewrite_unchanged_archive(tmp_path) -> None:
    root = tmp_path / "Mi unidad" / "YT-MP3 Studio"
    playlist = root / "Favoritas"
    playlist.mkdir(parents=True)
    (playlist / "Tema.mp3").write_bytes(b"audio")
    service = LocalGoogleDriveService(root)
    service.refresh_zip_exports()
    zip_path = service.exports_root / "Favoritas.zip"
    original_mtime = zip_path.stat().st_mtime_ns

    assert service.refresh_zip_exports() == []
    assert zip_path.stat().st_mtime_ns == original_mtime


def test_refresh_zip_exports_updates_archive_when_audio_is_added(tmp_path) -> None:
    root = tmp_path / "Mi unidad" / "YT-MP3 Studio"
    playlist = root / "Favoritas"
    playlist.mkdir(parents=True)
    (playlist / "Uno.mp3").write_bytes(b"one")
    service = LocalGoogleDriveService(root)
    service.refresh_zip_exports()
    zip_path = service.exports_root / "Favoritas.zip"
    old_zip_mtime = zip_path.stat().st_mtime
    new_track = playlist / "Dos.ogg"
    new_track.write_bytes(b"two")
    os.utime(new_track, (old_zip_mtime + 2, old_zip_mtime + 2))

    assert service.refresh_zip_exports() == ["Favoritas"]
    with zipfile.ZipFile(zip_path) as archive:
        assert sorted(archive.namelist()) == ["Dos.ogg", "Uno.mp3"]


def test_refresh_zip_exports_removes_archive_for_emptied_folder(tmp_path) -> None:
    root = tmp_path / "Mi unidad" / "YT-MP3 Studio"
    playlist = root / "Favoritas"
    playlist.mkdir(parents=True)
    track = playlist / "Tema.mp3"
    track.write_bytes(b"audio")
    service = LocalGoogleDriveService(root)
    service.refresh_zip_exports()
    zip_path = service.exports_root / "Favoritas.zip"
    track.unlink()

    assert service.refresh_zip_exports() == []
    assert not zip_path.exists()


def test_exports_folder_is_hidden_and_reserved(tmp_path) -> None:
    root = tmp_path / "Mi unidad" / "YT-MP3 Studio"
    exports = root / EXPORTS_FOLDER_NAME
    exports.mkdir(parents=True)
    service = LocalGoogleDriveService(root)

    assert EXPORTS_FOLDER_NAME not in service.list_folders()
    with pytest.raises(ValueError, match="reservada"):
        service.resolve_folder(EXPORTS_FOLDER_NAME)


@pytest.mark.parametrize(
    "name", ["../fuera", "..\\fuera", "..", "/absoluta", "C:\\Musica", "CON"]
)
def test_zip_path_for_invalid_name_returns_none(name, tmp_path) -> None:
    root = tmp_path / "Mi unidad" / "YT-MP3 Studio"

    assert LocalGoogleDriveService(root).zip_path_for(name) is None


def test_zip_path_for_returns_none_before_archive_exists(tmp_path) -> None:
    root = tmp_path / "Mi unidad" / "YT-MP3 Studio"
    (root / "Favoritas").mkdir(parents=True)

    assert LocalGoogleDriveService(root).zip_path_for("Favoritas") is None


def test_zip_path_for_returns_existing_archive(tmp_path) -> None:
    root = tmp_path / "Mi unidad" / "YT-MP3 Studio"
    playlist = root / "Favoritas"
    playlist.mkdir(parents=True)
    (playlist / "Tema.mp3").write_bytes(b"audio")
    service = LocalGoogleDriveService(root)
    service.refresh_zip_exports()

    zip_path = service.zip_path_for("Favoritas")

    assert zip_path == service.exports_root / "Favoritas.zip"
    assert zip_path is not None and zip_path.exists()


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
