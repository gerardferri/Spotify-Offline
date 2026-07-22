-- Migration 004 was edited in place after it had already been applied, so
-- databases created before that edit never got drive_tracks.local_path and
-- every Drive sync failed with "table drive_tracks has no column named
-- local_path". Rebuild the table copying only the columns both shapes share,
-- so this runs correctly whether or not local_path is already present.

CREATE TABLE drive_tracks_migrated (
    file_id             TEXT PRIMARY KEY,
    folder_id           TEXT NOT NULL REFERENCES drive_folders(file_id) ON DELETE CASCADE,
    name                TEXT NOT NULL,
    mime_type           TEXT NOT NULL,
    size_bytes          INTEGER CHECK (size_bytes IS NULL OR size_bytes >= 0),
    modified_time       TEXT,
    web_view_link       TEXT,
    checksum            TEXT,
    local_path          TEXT
);

INSERT INTO drive_tracks_migrated(
    file_id, folder_id, name, mime_type, size_bytes, modified_time, web_view_link, checksum
)
SELECT file_id, folder_id, name, mime_type, size_bytes, modified_time, web_view_link, checksum
FROM drive_tracks;

DROP INDEX IF EXISTS idx_drive_tracks_folder;
DROP TABLE drive_tracks;
ALTER TABLE drive_tracks_migrated RENAME TO drive_tracks;

CREATE INDEX idx_drive_tracks_folder ON drive_tracks(folder_id, name COLLATE NOCASE);
