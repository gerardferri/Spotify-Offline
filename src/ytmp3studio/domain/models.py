from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class JobState(StrEnum):
    QUEUED = "queued"
    RESOLVING = "resolving"
    DOWNLOADING = "downloading"
    CONVERTING = "converting"
    PAUSING = "pausing"
    PAUSED = "paused"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"

    @property
    def terminal(self) -> bool:
        return self in {self.CANCELLED, self.COMPLETED, self.FAILED}


@dataclass(frozen=True, slots=True)
class SearchResult:
    video_id: str
    webpage_url: str
    title: str
    channel: str = "Canal desconocido"
    duration_seconds: int | None = None
    thumbnail_url: str | None = None
    availability: str | None = None
    is_live: bool = False


@dataclass(frozen=True, slots=True)
class DownloadRequest:
    video_id: str
    quality_kbps: int | None = None


@dataclass(frozen=True, slots=True)
class DownloadJob:
    id: str
    video_id: str
    source_url: str
    title: str
    channel: str
    quality_kbps: int
    output_dir: str
    temp_dir: str
    state: JobState
    attempt_count: int
    max_attempts: int
    created_at: str
    updated_at: str
    thumbnail_url: str | None = None
    duration_seconds: int | None = None
    progress_percent: float | None = None
    downloaded_bytes: int | None = None
    total_bytes: int | None = None
    speed_bps: float | None = None
    eta_seconds: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    next_retry_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


@dataclass(frozen=True, slots=True)
class Progress:
    job_id: str
    phase: str
    downloaded_bytes: int | None = None
    total_bytes: int | None = None
    percent: float | None = None
    speed_bps: float | None = None
    eta_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class LibraryTrack:
    id: str
    video_id: str
    title: str
    channel: str
    source_url: str
    file_path: str
    file_size_bytes: int
    quality_kbps: int
    created_at: str
    job_id: str | None = None
    duration_seconds: int | None = None
    thumbnail_url: str | None = None
    last_played_at: str | None = None
    file_missing: bool = False
    folder_id: str | None = None


@dataclass(frozen=True, slots=True)
class LibraryFolder:
    id: str
    name: str
    created_at: str
    track_count: int = 0


class PlaylistTrackState(StrEnum):
    """Lifecycle of one imported track inside a playlist."""

    PENDING = "pending"
    QUEUED = "queued"
    DOWNLOADED = "downloaded"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class Playlist:
    id: str
    source_key: str
    name: str
    created_at: str
    updated_at: str
    spotify_uri: str | None = None
    description: str | None = None
    owner: str | None = None
    is_liked_songs: bool = False
    cover_url: str | None = None
    cover_path: str | None = None
    cover_etag: str | None = None
    cover_updated_at: str | None = None
    last_synced_at: str | None = None
    track_count: int = 0


@dataclass(frozen=True, slots=True)
class SpotifyTrack:
    """Spotify/Exportify metadata; ``track_key`` is the stable local identity."""

    track_key: str
    title: str
    artist: str
    created_at: str
    updated_at: str
    spotify_uri: str | None = None
    album: str | None = None
    duration_ms: int | None = None
    isrc: str | None = None
    album_image_url: str | None = None
    library_track_id: str | None = None
    current_job_id: str | None = None


@dataclass(frozen=True, slots=True)
class PlaylistItem:
    playlist_id: str
    track_key: str
    position: int
    state: PlaylistTrackState
    added_at: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True, slots=True)
class PlaylistEntry:
    """A playlist association together with the imported track metadata."""

    item: PlaylistItem
    track: SpotifyTrack


@dataclass(frozen=True, slots=True)
class PlaylistImportError:
    id: int
    playlist_id: str | None
    error_code: str
    message: str
    created_at: str
    row_number: int | None = None
    track_key: str | None = None
    detail: str | None = None
    resolved_at: str | None = None


@dataclass(frozen=True, slots=True)
class PlaylistSyncResult:
    playlist_id: str
    added: int
    retained: int
    removed: int
    total: int


@dataclass(frozen=True, slots=True)
class Settings:
    download_dir: str
    quality_kbps: int = 192
    theme: str = "system"
    concurrency: int = 2
    max_retries: int = 2
    retry_base_seconds: int = 2


class DependencyState(StrEnum):
    OK = "ok"
    MISSING = "missing"
    OUTDATED = "outdated"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class DependencyItem:
    name: str
    state: DependencyState
    version: str | None = None
    path: str | None = None
    message: str | None = None

    @property
    def operational(self) -> bool:
        return self.state == DependencyState.OK


@dataclass(frozen=True, slots=True)
class DependencyStatus:
    ytdlp: DependencyItem
    ffmpeg: DependencyItem
    download_dir_writable: bool
    download_dir: str
    checked_at: str

    @property
    def operational(self) -> bool:
        return self.ytdlp.operational and self.ffmpeg.operational and self.download_dir_writable


def default_download_dir() -> str:
    return str(Path.home() / "Music" / "YT-MP3 Studio")
