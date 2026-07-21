CREATE TABLE playlists (
    id                  TEXT PRIMARY KEY,
    source_key          TEXT NOT NULL UNIQUE,
    spotify_uri         TEXT,
    name                TEXT NOT NULL,
    description         TEXT,
    owner               TEXT,
    is_liked_songs      INTEGER NOT NULL DEFAULT 0 CHECK (is_liked_songs IN (0, 1)),
    cover_url           TEXT,
    cover_path          TEXT,
    cover_etag          TEXT,
    cover_updated_at    TEXT,
    last_synced_at      TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE UNIQUE INDEX idx_playlists_spotify_uri
    ON playlists(spotify_uri) WHERE spotify_uri IS NOT NULL;
CREATE INDEX idx_playlists_name ON playlists(name COLLATE NOCASE);

CREATE TABLE spotify_tracks (
    track_key           TEXT PRIMARY KEY,
    spotify_uri         TEXT,
    title               TEXT NOT NULL,
    artist              TEXT NOT NULL,
    album               TEXT,
    duration_ms         INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0),
    isrc                TEXT,
    album_image_url     TEXT,
    library_track_id    TEXT REFERENCES library_tracks(id) ON DELETE SET NULL,
    current_job_id      TEXT UNIQUE REFERENCES download_jobs(id) ON DELETE SET NULL,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE UNIQUE INDEX idx_spotify_tracks_uri
    ON spotify_tracks(spotify_uri) WHERE spotify_uri IS NOT NULL;
CREATE INDEX idx_spotify_tracks_isrc ON spotify_tracks(isrc);
CREATE INDEX idx_spotify_tracks_title_artist
    ON spotify_tracks(title COLLATE NOCASE, artist COLLATE NOCASE);

CREATE TABLE playlist_items (
    playlist_id         TEXT NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    track_key           TEXT NOT NULL REFERENCES spotify_tracks(track_key) ON DELETE RESTRICT,
    position            INTEGER NOT NULL CHECK (position >= 0),
    state               TEXT NOT NULL DEFAULT 'pending' CHECK (state IN (
                            'pending','queued','downloaded','failed','unavailable')),
    added_at            TEXT,
    error_code          TEXT,
    error_message       TEXT,
    updated_at          TEXT NOT NULL,
    PRIMARY KEY (playlist_id, track_key),
    UNIQUE (playlist_id, position)
);

CREATE INDEX idx_playlist_items_track ON playlist_items(track_key);
CREATE INDEX idx_playlist_items_state ON playlist_items(playlist_id, state);

CREATE TABLE playlist_import_errors (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id         TEXT REFERENCES playlists(id) ON DELETE CASCADE,
    row_number          INTEGER CHECK (row_number IS NULL OR row_number >= 1),
    track_key           TEXT,
    error_code          TEXT NOT NULL,
    message             TEXT NOT NULL,
    detail              TEXT,
    created_at          TEXT NOT NULL,
    resolved_at         TEXT
);

CREATE INDEX idx_playlist_import_errors_playlist
    ON playlist_import_errors(playlist_id, resolved_at, id);
