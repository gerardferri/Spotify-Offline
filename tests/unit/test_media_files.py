from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from ytmp3studio.backend.adapters.media_files import MediaFiles


@pytest.mark.parametrize(("raw", "expected"), [
    ('  canción: \\ rara?  ', "canción_ _ rara_"),
    ("CON", "_CON"),
    ("...", "Sin título"),
    ("", "Sin título"),
])
def test_safe_stem(raw, expected):
    assert MediaFiles.safe_stem(raw) == expected


def test_unique_destination_uses_windows_style_collision_number(tmp_path: Path):
    (tmp_path / "Tema.mp3").touch()
    (tmp_path / "Tema (2).mp3").touch()
    assert MediaFiles.unique_destination(tmp_path, "Tema").name == "Tema (3).mp3"


def test_job_temp_requires_uuid_and_cleanup_is_scoped(tmp_path: Path):
    first = str(uuid4())
    second = str(uuid4())
    first_dir = MediaFiles.ensure_job_temp_dir(tmp_path, first)
    second_dir = MediaFiles.ensure_job_temp_dir(tmp_path, second)
    (first_dir / "download.part").write_bytes(b"partial")
    (second_dir / "keep.part").write_bytes(b"keep")

    assert MediaFiles.cleanup_job_temp(tmp_path, first) is True
    assert not first_dir.exists()
    assert (second_dir / "keep.part").exists()
    with pytest.raises(ValueError):
        MediaFiles.job_temp_dir(tmp_path, "../outside")


def test_publish_atomic_moves_completed_file(tmp_path: Path):
    source = tmp_path / ".ytmp3studio-tmp" / str(uuid4()) / "final.tmp.mp3"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"mp3")
    destination = tmp_path / "Tema.mp3"
    assert MediaFiles.publish_atomic(source, destination) == destination
    assert destination.read_bytes() == b"mp3"
    assert not source.exists()


def test_cleanup_temp_accepts_persisted_job_temp_but_rejects_arbitrary_path(tmp_path: Path):
    temp_dir = MediaFiles.ensure_job_temp_dir(tmp_path, str(uuid4()))
    (temp_dir / "source.part").touch()
    assert MediaFiles.cleanup_temp(temp_dir) is True
    assert not temp_dir.exists()
    arbitrary = tmp_path / str(uuid4())
    arbitrary.mkdir()
    with pytest.raises(ValueError):
        MediaFiles.cleanup_temp(arbitrary)
    assert arbitrary.exists()


def test_publish_unique_chooses_collision_and_preserves_existing_file(tmp_path: Path):
    existing = tmp_path / "Tema.mp3"
    existing.write_bytes(b"old")
    temporary = tmp_path / "new.tmp"
    temporary.write_bytes(b"new")
    published = MediaFiles.publish_unique(temporary, tmp_path, "Tema")
    assert published.name == "Tema (2).mp3"
    assert published.read_bytes() == b"new"
    assert existing.read_bytes() == b"old"
