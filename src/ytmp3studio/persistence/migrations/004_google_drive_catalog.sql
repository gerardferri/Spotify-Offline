CREATE TABLE drive_connection (
    id                  INTEGER PRIMARY KEY CHECK (id = 1),
    account_email       TEXT,
    account_name        TEXT,
    root_folder_id      TEXT,
    changes_token       TEXT,
    last_synced_at      TEXT,
    revision            INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    last_error           TEXT
);

CREATE TABLE drive_folders (
    file_id             TEXT PRIMARY KEY,
    parent_file_id      TEXT,
    name                TEXT NOT NULL,
    modified_time       TEXT,
    FOREIGN KEY (parent_file_id) REFERENCES drive_folders(file_id) ON DELETE CASCADE
);

CREATE INDEX idx_drive_folders_parent ON drive_folders(parent_file_id);

CREATE TABLE drive_tracks (
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

CREATE INDEX idx_drive_tracks_folder ON drive_tracks(folder_id, name COLLATE NOCASE);
