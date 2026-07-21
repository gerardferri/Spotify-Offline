CREATE TABLE settings (
    key            TEXT PRIMARY KEY,
    value_json     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE TABLE download_jobs (
    id                 TEXT PRIMARY KEY,
    video_id           TEXT NOT NULL,
    source_url         TEXT NOT NULL,
    title              TEXT,
    channel            TEXT,
    thumbnail_url      TEXT,
    duration_seconds   INTEGER CHECK (duration_seconds IS NULL OR duration_seconds >= 0),
    quality_kbps       INTEGER NOT NULL CHECK (quality_kbps IN (128, 192, 256, 320)),
    output_dir         TEXT NOT NULL,
    temp_dir           TEXT NOT NULL,
    state              TEXT NOT NULL CHECK (state IN (
                           'queued','resolving','downloading','converting',
                           'pausing','paused','cancelling','cancelled',
                           'completed','failed','interrupted')),
    attempt_count      INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts       INTEGER NOT NULL CHECK (max_attempts >= 1),
    downloaded_bytes   INTEGER CHECK (downloaded_bytes IS NULL OR downloaded_bytes >= 0),
    total_bytes        INTEGER CHECK (total_bytes IS NULL OR total_bytes >= 0),
    progress_percent   REAL CHECK (progress_percent IS NULL OR
                                    (progress_percent >= 0 AND progress_percent <= 100)),
    error_code         TEXT,
    error_message      TEXT,
    next_retry_at      TEXT,
    created_at         TEXT NOT NULL,
    started_at         TEXT,
    finished_at        TEXT,
    updated_at         TEXT NOT NULL
);

CREATE INDEX idx_download_jobs_state_created
    ON download_jobs(state, created_at);
CREATE INDEX idx_download_jobs_video_id
    ON download_jobs(video_id);

CREATE TABLE library_tracks (
    id                 TEXT PRIMARY KEY,
    job_id             TEXT UNIQUE,
    video_id           TEXT NOT NULL,
    source_url         TEXT NOT NULL,
    title              TEXT NOT NULL,
    channel            TEXT,
    duration_seconds   INTEGER CHECK (duration_seconds IS NULL OR duration_seconds >= 0),
    thumbnail_url      TEXT,
    file_path          TEXT NOT NULL UNIQUE,
    file_size_bytes    INTEGER NOT NULL CHECK (file_size_bytes >= 0),
    quality_kbps       INTEGER NOT NULL,
    created_at         TEXT NOT NULL,
    last_played_at     TEXT,
    FOREIGN KEY (job_id) REFERENCES download_jobs(id) ON DELETE SET NULL
);

CREATE INDEX idx_library_tracks_title ON library_tracks(title COLLATE NOCASE);
CREATE INDEX idx_library_tracks_channel ON library_tracks(channel COLLATE NOCASE);
CREATE INDEX idx_library_tracks_video_id ON library_tracks(video_id);

CREATE TABLE history_events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id         TEXT,
    video_id       TEXT,
    event_type     TEXT NOT NULL CHECK (event_type IN (
                       'enqueued','started','paused','resumed','retry_scheduled',
                       'completed','failed','cancelled','removed')),
    detail_json    TEXT,
    created_at     TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES download_jobs(id) ON DELETE SET NULL
);

CREATE INDEX idx_history_events_created ON history_events(created_at DESC);
CREATE INDEX idx_history_events_job ON history_events(job_id);
