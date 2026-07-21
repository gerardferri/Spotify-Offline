CREATE TABLE library_folders (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL COLLATE NOCASE UNIQUE,
    created_at  TEXT NOT NULL
);

ALTER TABLE library_tracks ADD COLUMN folder_id TEXT
    REFERENCES library_folders(id) ON DELETE SET NULL;

CREATE INDEX idx_library_tracks_folder ON library_tracks(folder_id);
CREATE INDEX idx_library_folders_name ON library_folders(name COLLATE NOCASE);
