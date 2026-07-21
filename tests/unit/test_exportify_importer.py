from __future__ import annotations

import io
import zipfile

from ytmp3studio.backend.importers.exportify import (
    ExportifyImporter,
    sanitize_playlist_name,
)


HEADER = "Track URI,Track Name,Artist Name(s),Album Name,Duration (ms)\n"


def test_imports_utf8_bom_csv_and_detects_real_exportify_columns(tmp_path):
    csv_path = tmp_path / "Verano.csv"
    csv_path.write_bytes(
        ("\ufeff" + HEADER + 'spotify:track:abc,"La Graciosa","Carlos Sadness","Tropical Jesus",205000\n').encode()
    )

    result = ExportifyImporter().import_file(csv_path)

    assert result.issues == ()
    assert result.track_count == 1
    playlist = result.playlists[0]
    assert playlist.name == "Verano"
    assert playlist.safe_name == "Verano"
    assert playlist.is_liked_songs is False
    assert playlist.tracks[0].spotify_id == "abc"
    assert playlist.tracks[0].artist_names == "Carlos Sadness"
    assert playlist.tracks[0].duration_ms == 205000


def test_imports_liked_songs_and_sanitizes_playlist_filename(tmp_path):
    csv_path = tmp_path / "Liked Songs.csv"
    csv_path.write_text(
        HEADER + "spotify:track:1,Song,Artist,Album,123\n", encoding="utf-8"
    )

    playlist = ExportifyImporter().import_file(csv_path).playlists[0]

    assert playlist.is_liked_songs is True
    assert sanitize_playlist_name('  Road: Trip? <2026>.  ') == "Road_ Trip_ _2026_"
    assert sanitize_playlist_name("CON") == "_CON"


def test_deduplicates_tracks_inside_playlist_but_not_across_playlists(tmp_path):
    zip_path = tmp_path / "spotify_playlists.zip"
    content = (
        HEADER
        + "spotify:track:same,Song,Artist,Album,1000\n"
        + "spotify:track:same,Song duplicate,Artist,Album,1000\n"
    )
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("One.csv", content)
        archive.writestr("folder/Two.csv", content.splitlines()[0] + "\n" + content.splitlines()[1] + "\n")

    result = ExportifyImporter().import_file(zip_path)

    assert len(result.playlists) == 2
    assert result.track_count == 2
    assert result.duplicate_count == 1
    assert [playlist.tracks[0].spotify_id for playlist in result.playlists] == ["same", "same"]


def test_bad_csv_in_zip_does_not_abort_other_playlists(tmp_path):
    zip_path = tmp_path / "export.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("Good.csv", HEADER + "spotify:track:1,Song,Artist,Album,123\n")
        archive.writestr("Bad.csv", "Track Name,Artist Name(s)\nSong,Artist\n")
        archive.writestr("Not UTF8.csv", b"\xff\xfe")
        archive.writestr("notes.txt", "ignored")

    result = ExportifyImporter().import_file(zip_path)

    assert [playlist.name for playlist in result.playlists] == ["Good"]
    assert len(result.issues) == 2
    assert {issue.source_file for issue in result.issues} == {"Bad.csv", "Not UTF8.csv"}


def test_row_errors_are_reported_without_dropping_valid_rows(tmp_path):
    csv_path = tmp_path / "Mixed.csv"
    csv_path.write_text(
        HEADER
        + "spotify:track:1,Valid,Artist,Album,not-a-number\n"
        + "spotify:track:2,,Artist,Album,200\n"
        + "spotify:track:3,Also valid,Artist,Album,300\n",
        encoding="utf-8",
    )

    result = ExportifyImporter().import_file(csv_path)

    assert result.track_count == 2
    assert result.playlists[0].tracks[0].duration_ms is None
    assert [(issue.row, issue.message) for issue in result.issues] == [
        (2, "Duración no válida ('not-a-number'); se importó sin duración."),
        (3, "Fila omitida: faltan el nombre de la canción o el artista."),
    ]


def test_accepts_semicolon_delimited_csv(tmp_path):
    csv_path = tmp_path / "Delimited.csv"
    csv_path.write_text(
        "Track URI;Track Name;Artist Name(s);Album Name;Duration ms\n"
        "spotify:track:1;Song;Artist;Album;100\n",
        encoding="utf-8",
    )

    result = ExportifyImporter().import_file(csv_path)

    assert result.issues == ()
    assert result.track_count == 1


def test_zip_without_csv_and_unsupported_file_are_clean_errors(tmp_path):
    zip_path = tmp_path / "empty.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("readme.txt", "nothing")

    empty = ExportifyImporter().import_file(zip_path)
    unsupported = ExportifyImporter().import_file(tmp_path / "playlists.json")

    assert empty.playlists == ()
    assert "no contiene archivos CSV" in empty.issues[0].message
    assert "Formato no compatible" in unsupported.issues[0].message
