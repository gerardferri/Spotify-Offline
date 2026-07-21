from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from ytmp3studio.backend.playlist_service import PlaylistService
from ytmp3studio.backend.search_service import SearchService
from ytmp3studio.domain.models import (
    DownloadJob, JobState, LibraryTrack, SearchResult, Settings,
)
from ytmp3studio.persistence.database import Database, utc_now
from ytmp3studio.persistence.playlist_repository import PlaylistRepository
from ytmp3studio.persistence.repositories import DownloadJobRepository, LibraryRepository


class SearchProvider:
    def __init__(self):
        self.calls = []

    def search(self, query, limit):
        self.calls.append((query, limit))
        return [SearchResult("video-1", "https://youtube.test/video-1", "Artist - Song (Official Audio)", "Artist - Topic", 180)]


class Queue:
    def __init__(self, repository, output):
        self.repository = repository
        self.output = output

    def enqueue(self, video_ids, quality_kbps=None):
        now = utc_now()
        jobs = []
        for video_id in video_ids:
            identifier = str(uuid4())
            job = DownloadJob(
                identifier, video_id, f"https://youtube.test/{video_id}",
                "Artist - Song (Official Audio)", "Artist - Topic", 192,
                str(self.output), str(self.output / ".ytmp3studio-tmp" / identifier),
                JobState.QUEUED, 0, 1, now, now, duration_seconds=180,
            )
            self.repository.add(job)
            jobs.append(job)
        return jobs

    def cancel(self, job_id):
        job = self.repository.get(job_id)
        cancelled = replace(job, state=JobState.CANCELLED)
        self.repository.update(cancelled)
        return cancelled


def make_service(tmp_path):
    database = Database(tmp_path / "test.db")
    database.migrate()
    jobs = DownloadJobRepository(database)
    library = LibraryRepository(database)
    queue = Queue(jobs, tmp_path / "Music")
    provider = SearchProvider()
    service = PlaylistService(
        PlaylistRepository(database), library, SearchService(provider),
        queue, lambda: Settings(str(tmp_path / "Music")),
    )
    service._test_search_provider = provider
    return service, jobs, library


def test_import_match_complete_and_project_hardlink(tmp_path):
    csv_path = tmp_path / "Road_Trip.csv"
    csv_path.write_text(
        "Track URI,Track Name,Album Name,Artist Name(s),Duration (ms)\n"
        "spotify:track:abc,Song,Album,Artist,180000\n",
        encoding="utf-8",
    )
    service, jobs, library = make_service(tmp_path)

    playlists = service.import_exportify(str(csv_path))
    assert playlists[0]["name"] == "Road Trip"
    result = service.download_playlist(playlists[0]["id"])
    assert result == {"queued": 1, "failed": 0, "skipped": 0}
    assert service._test_search_provider.calls == [("Song Artist", 5)]

    job = jobs.list()[0]
    downloaded = tmp_path / "Music" / "youtube-title.mp3"
    downloaded.parent.mkdir(parents=True, exist_ok=True)
    downloaded.write_bytes(b"fake mp3")
    local = LibraryTrack(
        str(uuid4()), job.video_id, job.title, job.channel, job.source_url,
        str(downloaded), downloaded.stat().st_size, 192, utc_now(), job_id=job.id,
        duration_seconds=180,
    )
    library.add(local)
    completed = replace(job, state=JobState.COMPLETED)

    updated = service.on_job_completed(completed, local)

    assert Path(updated.file_path).is_file()
    projected = tmp_path / "Music" / "Playlists" / "Road Trip" / "Artist - Song.mp3"
    assert projected.is_file()
    assert projected.read_bytes() == b"fake mp3"
    detail = service.get_playlist(playlists[0]["id"])
    assert detail["tracks"][0]["status"] == "downloaded"


def test_no_reliable_match_is_reported_without_stopping(tmp_path):
    class BadProvider:
        def __init__(self):
            self.calls = []

        def search(self, query, limit):
            self.calls.append((query, limit))
            return [SearchResult("bad", "https://youtube.test/bad", "Song karaoke", "Karaoke", 300)]

    service, _, _ = make_service(tmp_path)
    provider = BadProvider()
    service._search = SearchService(provider)
    csv_path = tmp_path / "List.csv"
    csv_path.write_text(
        "Track URI,Track Name,Album Name,Artist Name(s),Duration (ms)\n"
        "spotify:track:abc,Song,Album,Artist,180000\n",
        encoding="utf-8",
    )
    playlist = service.import_exportify(str(csv_path))[0]

    result = service.download_playlist(playlist["id"])

    assert result["failed"] == 1
    assert provider.calls == [("Song Artist", 5), ("Song Artist", 20)]
    assert service.get_playlist(playlist["id"])["tracks"][0]["status"] == "failed"
    assert (tmp_path / "Music" / "Playlists" / "List" / "errores.csv").is_file()


def test_expands_candidates_only_after_first_pass_has_no_match(tmp_path):
    class ExpandingProvider:
        def __init__(self):
            self.calls = []

        def search(self, query, limit):
            self.calls.append((query, limit))
            if limit == 5:
                return []
            return [SearchResult("good", "https://youtube.test/good", "Artist - Song", "Artist - Topic", 180)]

    service, _, _ = make_service(tmp_path)
    provider = ExpandingProvider()
    service._search = SearchService(provider)
    csv_path = tmp_path / "List.csv"
    csv_path.write_text(
        "Track URI,Track Name,Album Name,Artist Name(s),Duration (ms)\n"
        "spotify:track:abc,Song,Album,Artist,180000\n",
        encoding="utf-8",
    )
    playlist = service.import_exportify(str(csv_path))[0]

    result = service.download_playlist(playlist["id"])

    assert result["queued"] == 1
    assert provider.calls == [("Song Artist", 5), ("Song Artist", 20)]


def test_replacement_candidates_can_be_chosen_explicitly(tmp_path):
    service, jobs, _ = make_service(tmp_path)
    csv_path = tmp_path / "List.csv"
    csv_path.write_text(
        "Track URI,Track Name,Album Name,Artist Name(s),Duration (ms)\n"
        "spotify:track:abc,Song,Album,Artist,180000\n",
        encoding="utf-8",
    )
    playlist = service.import_exportify(str(csv_path))[0]
    track_key = service.get_playlist(playlist["id"])["tracks"][0]["track_key"]

    candidates = service.replacement_candidates(playlist["id"], track_key)
    result = service.queue_replacement(
        playlist["id"], track_key, candidates[0]["video_id"]
    )

    assert result["queued"] == 1
    assert len(jobs.list()) == 1


def test_stopping_playlist_cancels_jobs_and_leaves_tracks_pending(tmp_path):
    service, jobs, _ = make_service(tmp_path)
    csv_path = tmp_path / "List.csv"
    csv_path.write_text(
        "Track URI,Track Name,Album Name,Artist Name(s),Duration (ms)\n"
        "spotify:track:abc,Song,Album,Artist,180000\n",
        encoding="utf-8",
    )
    playlist = service.import_exportify(str(csv_path))[0]
    service.download_playlist(playlist["id"])

    result = service.stop_downloads(playlist["id"])

    assert result["stopped"] == 1
    assert jobs.list()[0].state is JobState.CANCELLED
    assert service.get_playlist(playlist["id"])["tracks"][0]["status"] == "pending"
