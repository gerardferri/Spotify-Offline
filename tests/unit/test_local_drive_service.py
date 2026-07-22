from __future__ import annotations

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
