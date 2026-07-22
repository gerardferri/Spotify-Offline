from __future__ import annotations

from dataclasses import replace
import sqlite3

import pytest

from ytmp3studio.domain.models import (
    DownloadJob,
    JobState,
    LibraryTrack,
    Playlist,
    PlaylistTrackState,
    SpotifyTrack,
)
from ytmp3studio.persistence.database import Database
from ytmp3studio.persistence.playlist_repository import PlaylistRepository
from ytmp3studio.persistence.repositories import DownloadJobRepository, LibraryRepository


NOW = "2026-07-20T12:00:00.000Z"


@pytest.fixture
def repository(tmp_path):
    database = Database(tmp_path / "playlists.db")
    assert database.migrate() == [1, 2, 3, 4, 5]
    return PlaylistRepository(database)


def playlist(identifier="playlist-1", source_key="Road Trip"):
    return Playlist(
        id=identifier,
        source_key=source_key,
        spotify_uri=f"spotify:playlist:{identifier}",
        name=source_key,
        created_at=NOW,
        updated_at=NOW,
    )


def track(key: str, uri: str | None = None, title: str | None = None):
    return SpotifyTrack(
        track_key=key,
        spotify_uri=uri or f"spotify:track:{key}",
        title=title or f"Song {key}",
        artist="Artist",
        album="Album",
        duration_ms=180_000,
        isrc=f"ISRC{key}",
        album_image_url="https://img.example/album.jpg",
        created_at=NOW,
        updated_at=NOW,
    )


def job(identifier: str):
    return DownloadJob(
        id=identifier,
        video_id=identifier,
        source_url=f"https://youtube.example/{identifier}",
        title="Matched song",
        channel="Official",
        quality_kbps=192,
        output_dir="C:/Music",
        temp_dir="C:/Temp",
        state=JobState.QUEUED,
        attempt_count=0,
        max_attempts=2,
        created_at=NOW,
        updated_at=NOW,
    )


def test_sync_roundtrip_reorders_and_retains_item_state(repository):
    original = playlist()
    first, second, third = track("a"), track("b"), track("c")

    result = repository.sync_playlist(original, [first, second])
    assert (result.added, result.retained, result.removed, result.total) == (2, 0, 0, 2)
    assert repository.get(original.id).track_count == 2
    assert [entry.track.track_key for entry in repository.list_entries(original.id)] == ["a", "b"]

    assert repository.update_item_state(
        original.id,
        "a",
        PlaylistTrackState.FAILED,
        error_code="NO_MATCH",
        error_message="No reliable YouTube result",
    )
    result = repository.sync_playlist(original, [second, first, third])
    assert (result.added, result.retained, result.removed) == (1, 2, 0)
    entries = repository.list_entries(original.id)
    assert [entry.track.track_key for entry in entries] == ["b", "a", "c"]
    assert entries[1].item.state is PlaylistTrackState.FAILED
    assert entries[1].item.error_code == "NO_MATCH"

    result = repository.sync_playlist(original, [third])
    assert (result.added, result.retained, result.removed, result.total) == (0, 1, 2, 1)


def test_spotify_uri_is_canonical_identity_across_changed_track_keys(repository):
    value = playlist()
    repository.sync_playlist(value, [track("csv-key", "spotify:track:stable")])
    renamed_key = track("new-generated-key", "spotify:track:stable", "Updated title")

    result = repository.sync_playlist(value, [renamed_key])

    assert (result.added, result.retained, result.removed) == (0, 1, 0)
    entry = repository.list_entries(value.id)[0]
    assert entry.track.track_key == "csv-key"
    assert entry.track.title == "Updated title"


def test_one_track_can_belong_to_multiple_playlists_without_duplication(repository):
    shared = track("shared")
    first = playlist("one", "One")
    second = playlist("two", "Two")
    repository.sync_playlist(first, [shared])
    repository.sync_playlist(second, [shared])

    assert repository.list_entries(first.id)[0].track == repository.list_entries(second.id)[0].track
    with repository.database.connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM spotify_tracks").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM playlist_items").fetchone()[0] == 2


def test_cover_metadata_and_import_errors_are_persisted(repository):
    value = playlist()
    repository.upsert_playlist(value)
    assert repository.update_cover(
        value.id,
        url="https://img.example/playlist.jpg",
        path="C:/Music/Road Trip/cover.jpg",
        etag="cover-v1",
        updated_at=NOW,
    )
    error = repository.add_error(
        "CSV_ROW_INVALID",
        "Missing track title",
        playlist_id=value.id,
        row_number=7,
        detail="Title column was empty",
    )

    stored = repository.get(value.id)
    assert stored.cover_path.endswith("cover.jpg")
    assert stored.cover_etag == "cover-v1"
    assert repository.list_errors(playlist_id=value.id, unresolved_only=True) == [error]
    assert repository.resolve_error(error.id, resolved_at=NOW)
    assert repository.list_errors(playlist_id=value.id, unresolved_only=True) == []


def test_empty_sync_and_duplicate_snapshot_are_atomic(repository):
    value = playlist()
    one = track("one")
    repository.sync_playlist(value, [one])
    duplicate_uri = replace(one, track_key="other-key")

    with pytest.raises(ValueError, match="duplicate track identities"):
        repository.sync_playlist(value, [one, duplicate_uri])
    assert [entry.track.track_key for entry in repository.list_entries(value.id)] == ["one"]

    result = repository.sync_playlist(value, [])
    assert (result.removed, result.total) == (1, 0)
    assert repository.list_entries(value.id) == []


def test_library_link_honors_foreign_key(repository):
    value = playlist()
    repository.sync_playlist(value, [track("one")])
    with pytest.raises(sqlite3.IntegrityError):
        repository.link_library_track("one", "missing-library-row")


def test_cancelled_job_is_released_back_to_pending(repository, tmp_path):
    from ytmp3studio.domain.models import DownloadJob, JobState
    from ytmp3studio.persistence.repositories import DownloadJobRepository

    value = playlist()
    repository.sync_playlist(value, [track("one")])
    now = NOW
    job = DownloadJob(
        "00000000-0000-0000-0000-000000000001", "video", "https://youtube.test/video",
        "Song", "Artist", 192, str(tmp_path),
        str(tmp_path / ".ytmp3studio-tmp" / "00000000-0000-0000-0000-000000000001"),
        JobState.QUEUED, 0, 1, now, now,
    )
    DownloadJobRepository(repository.database).add(job)
    assert repository.bind_job("one", job.id)

    assert repository.release_job(job.id)
    entry = repository.list_entries(value.id)[0]
    assert entry.item.state is PlaylistTrackState.PENDING
    assert entry.track.current_job_id is None


def test_job_binding_completion_and_failure_update_every_playlist(repository):
    shared = track("shared")
    first, second = playlist("one", "One"), playlist("two", "Two")
    repository.sync_playlist(first, [shared])
    repository.sync_playlist(second, [shared])
    jobs = DownloadJobRepository(repository.database)
    jobs.add(job("job-ok"))

    assert repository.bind_job("shared", "job-ok")
    assert {repository.list_entries(value.id)[0].item.state for value in (first, second)} == {
        PlaylistTrackState.QUEUED
    }
    library_track = LibraryTrack(
        id="library-1",
        job_id="job-ok",
        video_id="job-ok",
        source_url="https://youtube.example/job-ok",
        title="Matched song",
        channel="Official",
        file_path="C:/Music/Artist - Song.mp3",
        file_size_bytes=100,
        quality_kbps=192,
        created_at=NOW,
    )
    LibraryRepository(repository.database).add(library_track)
    assert repository.complete_job("job-ok", library_track.id)
    assert repository.get_track("shared").library_track_id == library_track.id
    assert {repository.list_entries(value.id)[0].item.state for value in (first, second)} == {
        PlaylistTrackState.DOWNLOADED
    }

    jobs.add(job("job-bad"))
    assert repository.bind_job("shared", "job-bad")
    assert repository.mark_failed("job-bad", "NO_MATCH", "No reliable match")
    entries = [repository.list_entries(value.id)[0] for value in (first, second)]
    assert {entry.item.state for entry in entries} == {PlaylistTrackState.FAILED}
    assert {entry.item.error_code for entry in entries} == {"NO_MATCH"}
