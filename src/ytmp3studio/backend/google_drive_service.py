"""Google Drive library synchronization without coupling to an HTTP SDK.

The service deliberately depends on two small injected ports.  Production code
can implement them with any OAuth and HTTP library, while unit tests remain
fully local and deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Mapping, Protocol, Sequence


DRIVE_API = "/drive/v3"
APP_FOLDER_NAME = "YT-MP3 Studio"
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
_AUDIO_EXTENSIONS = frozenset(
    {".aac", ".flac", ".m4a", ".mp3", ".oga", ".ogg", ".opus", ".wav", ".webm"}
)
_FILE_FIELDS = (
    "id,name,mimeType,size,modifiedTime,parents,webViewLink,md5Checksum,trashed"
)


class OAuthPort(Protocol):
    """Authorization boundary used by :class:`GoogleDriveService`."""

    def is_connected(self) -> bool: ...

    def authorization_url(self) -> str: ...

    def exchange_code(self, code: str) -> None: ...

    def disconnect(self) -> None: ...


class DriveHttpPort(Protocol):
    """Minimal authenticated HTTP boundary.

    ``path`` is relative to the Google APIs host.  The adapter is responsible
    for attaching and refreshing the OAuth access token.
    """

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class DriveConnectionState:
    connected: bool
    account_email: str | None = None
    account_name: str | None = None
    app_folder_id: str | None = None


@dataclass(frozen=True, slots=True)
class DriveFolder:
    id: str
    name: str
    parent_id: str
    modified_time: str | None = None


@dataclass(frozen=True, slots=True)
class DriveTrack:
    id: str
    name: str
    folder_id: str
    mime_type: str
    size_bytes: int | None = None
    modified_time: str | None = None
    web_view_link: str | None = None
    checksum: str | None = None


@dataclass(frozen=True, slots=True)
class DriveLibrarySnapshot:
    root_folder: DriveFolder
    folders: tuple[DriveFolder, ...]
    tracks: tuple[DriveTrack, ...]
    changes_token: str


@dataclass(frozen=True, slots=True)
class DriveChange:
    file_id: str
    removed: bool
    folder: DriveFolder | None = None
    track: DriveTrack | None = None


@dataclass(frozen=True, slots=True)
class DriveChangesPage:
    changes: tuple[DriveChange, ...]
    next_token: str


class GoogleDriveService:
    """Connect a dedicated Drive folder and map its contents to app DTOs."""

    def __init__(
        self,
        oauth: OAuthPort,
        http: DriveHttpPort,
        app_folder_name: str = APP_FOLDER_NAME,
    ) -> None:
        self._oauth = oauth
        self._http = http
        self._app_folder_name = app_folder_name.strip() or APP_FOLDER_NAME
        self._root_folder: DriveFolder | None = None
        self._known_folder_ids: set[str] = set()
        self._known_item_ids: set[str] = set()

    def connection_state(self) -> DriveConnectionState:
        if not self._oauth.is_connected():
            return DriveConnectionState(connected=False)
        about = self._http.request(
            "GET",
            f"{DRIVE_API}/about",
            params={"fields": "user(displayName,emailAddress)"},
        )
        user = _mapping(about.get("user"))
        return DriveConnectionState(
            connected=True,
            account_email=_optional_string(user.get("emailAddress")),
            account_name=_optional_string(user.get("displayName")),
            app_folder_id=self._root_folder.id if self._root_folder else None,
        )

    def authorization_url(self) -> str:
        return self._oauth.authorization_url()

    def connect(self, authorization_code: str) -> DriveConnectionState:
        code = authorization_code.strip()
        if not code:
            raise ValueError("Google authorization code cannot be empty")
        self._oauth.exchange_code(code)
        root = self.ensure_app_folder()
        state = self.connection_state()
        return DriveConnectionState(
            connected=state.connected,
            account_email=state.account_email,
            account_name=state.account_name,
            app_folder_id=root.id,
        )

    def disconnect(self) -> None:
        self._oauth.disconnect()
        self._root_folder = None
        self._known_folder_ids.clear()
        self._known_item_ids.clear()

    def ensure_app_folder(self) -> DriveFolder:
        self._require_connection()
        if self._root_folder is not None:
            return self._root_folder

        escaped_name = self._app_folder_name.replace("\\", "\\\\").replace("'", "\\'")
        response = self._http.request(
            "GET",
            f"{DRIVE_API}/files",
            params={
                "q": (
                    f"name = '{escaped_name}' and mimeType = '{FOLDER_MIME_TYPE}' "
                    "and 'root' in parents and trashed = false"
                ),
                "spaces": "drive",
                "pageSize": 1,
                "fields": f"files({_FILE_FIELDS})",
            },
        )
        files = _sequence(response.get("files"))
        if files:
            root = _folder_from_file(_mapping(files[0]), expected_parent="root")
        else:
            created = self._http.request(
                "POST",
                f"{DRIVE_API}/files",
                params={"fields": _FILE_FIELDS},
                json={
                    "name": self._app_folder_name,
                    "mimeType": FOLDER_MIME_TYPE,
                    "parents": ["root"],
                },
            )
            root = _folder_from_file(created, expected_parent="root")

        self._root_folder = root
        self._known_folder_ids = {root.id}
        self._known_item_ids.add(root.id)
        return root

    def scan_library(self) -> DriveLibrarySnapshot:
        root = self.ensure_app_folder()
        folders: list[DriveFolder] = []
        tracks: list[DriveTrack] = []
        pending = [root]
        visited = {root.id}

        while pending:
            parent = pending.pop(0)
            for item in self._list_children(parent.id):
                mime_type = _string(item, "mimeType")
                if mime_type == FOLDER_MIME_TYPE:
                    folder = _folder_from_file(item, expected_parent=parent.id)
                    if folder.id not in visited:
                        visited.add(folder.id)
                        folders.append(folder)
                        pending.append(folder)
                    continue
                if _is_audio(item):
                    tracks.append(_track_from_file(item, expected_parent=parent.id))

        changes_token = self._start_changes_token()
        self._known_folder_ids = visited
        self._known_item_ids = visited | {track.id for track in tracks}
        return DriveLibrarySnapshot(
            root_folder=root,
            folders=tuple(folders),
            tracks=tuple(tracks),
            changes_token=changes_token,
        )

    def list_changes(self, changes_token: str) -> DriveChangesPage:
        token = changes_token.strip()
        if not token:
            raise ValueError("Google Drive changes token cannot be empty")
        self._require_connection()
        root = self.ensure_app_folder()

        raw_changes: list[Mapping[str, Any]] = []
        page_token = token
        final_token: str | None = None
        while page_token:
            response = self._http.request(
                "GET",
                f"{DRIVE_API}/changes",
                params={
                    "pageToken": page_token,
                    "spaces": "drive",
                    "includeRemoved": "true",
                    "fields": (
                        "nextPageToken,newStartPageToken,"
                        f"changes(fileId,removed,file({_FILE_FIELDS}))"
                    ),
                },
            )
            raw_changes.extend(_mapping(change) for change in _sequence(response.get("changes")))
            next_page = _optional_string(response.get("nextPageToken"))
            if next_page:
                page_token = next_page
            else:
                final_token = _optional_string(response.get("newStartPageToken")) or page_token
                page_token = ""

        # Register folders first so descendants returned in the same batch can
        # be recognized even if Drive puts child changes before their parents.
        pending_folders = [
            _mapping(change.get("file"))
            for change in raw_changes
            if not change.get("removed")
            and _mapping(change.get("file")).get("mimeType") == FOLDER_MIME_TYPE
            and not _mapping(change.get("file")).get("trashed")
        ]
        while pending_folders:
            unresolved: list[Mapping[str, Any]] = []
            found_parent = False
            for item in pending_folders:
                if any(parent in self._known_folder_ids for parent in _parents(item)):
                    self._known_folder_ids.add(_string(item, "id"))
                    found_parent = True
                else:
                    unresolved.append(item)
            if not found_parent:
                break
            pending_folders = unresolved

        mapped: list[DriveChange] = []
        for change in raw_changes:
            file_id = _optional_string(change.get("fileId"))
            if not file_id:
                continue
            item = _mapping(change.get("file"))
            removed = bool(change.get("removed")) or bool(item.get("trashed"))
            if removed:
                if file_id in self._known_item_ids:
                    mapped.append(DriveChange(file_id=file_id, removed=True))
                    self._known_item_ids.discard(file_id)
                    self._known_folder_ids.discard(file_id)
                continue

            parents = _parents(item)
            parent = next((value for value in parents if value in self._known_folder_ids), None)
            if parent is None and file_id != root.id:
                if file_id in self._known_item_ids:
                    mapped.append(DriveChange(file_id=file_id, removed=True))
                    self._known_item_ids.discard(file_id)
                    self._known_folder_ids.discard(file_id)
                continue
            mime_type = _string(item, "mimeType")
            if mime_type == FOLDER_MIME_TYPE:
                folder = _folder_from_file(item, expected_parent=parent or "root")
                self._known_folder_ids.add(folder.id)
                self._known_item_ids.add(folder.id)
                mapped.append(DriveChange(file_id=file_id, removed=False, folder=folder))
            elif _is_audio(item):
                track = _track_from_file(item, expected_parent=parent or root.id)
                self._known_item_ids.add(track.id)
                mapped.append(DriveChange(file_id=file_id, removed=False, track=track))
            elif file_id in self._known_item_ids:
                # An audio file can cease to belong to the library after being
                # converted to an unsupported type, without being trashed.
                mapped.append(DriveChange(file_id=file_id, removed=True))
                self._known_item_ids.discard(file_id)

        return DriveChangesPage(changes=tuple(mapped), next_token=final_token or token)

    def _list_children(self, parent_id: str) -> list[Mapping[str, Any]]:
        items: list[Mapping[str, Any]] = []
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {
                "q": f"'{parent_id}' in parents and trashed = false",
                "spaces": "drive",
                "pageSize": 1000,
                "fields": f"nextPageToken,files({_FILE_FIELDS})",
            }
            if page_token:
                params["pageToken"] = page_token
            response = self._http.request("GET", f"{DRIVE_API}/files", params=params)
            items.extend(_mapping(item) for item in _sequence(response.get("files")))
            page_token = _optional_string(response.get("nextPageToken"))
            if not page_token:
                return items

    def _start_changes_token(self) -> str:
        response = self._http.request(
            "GET",
            f"{DRIVE_API}/changes/startPageToken",
            params={"spaces": "drive", "fields": "startPageToken"},
        )
        return _string(response, "startPageToken")

    def _require_connection(self) -> None:
        if not self._oauth.is_connected():
            raise RuntimeError("Google Drive is not connected")


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else ()


def _string(source: Mapping[str, Any], key: str) -> str:
    value = _optional_string(source.get(key))
    if value is None:
        raise ValueError(f"Google Drive response is missing {key!r}")
    return value


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _parents(item: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(value for value in _sequence(item.get("parents")) if isinstance(value, str))


def _folder_from_file(item: Mapping[str, Any], expected_parent: str) -> DriveFolder:
    parents = _parents(item)
    return DriveFolder(
        id=_string(item, "id"),
        name=_string(item, "name"),
        parent_id=parents[0] if parents else expected_parent,
        modified_time=_optional_string(item.get("modifiedTime")),
    )


def _track_from_file(item: Mapping[str, Any], expected_parent: str) -> DriveTrack:
    raw_size = item.get("size")
    try:
        size = int(raw_size) if raw_size is not None else None
    except (TypeError, ValueError):
        size = None
    parents = _parents(item)
    return DriveTrack(
        id=_string(item, "id"),
        name=_string(item, "name"),
        folder_id=parents[0] if parents else expected_parent,
        mime_type=_string(item, "mimeType"),
        size_bytes=size,
        modified_time=_optional_string(item.get("modifiedTime")),
        web_view_link=_optional_string(item.get("webViewLink")),
        checksum=_optional_string(item.get("md5Checksum")),
    )


def _is_audio(item: Mapping[str, Any]) -> bool:
    mime_type = _optional_string(item.get("mimeType")) or ""
    if mime_type.startswith("audio/"):
        return True
    name = _optional_string(item.get("name")) or ""
    return PurePosixPath(name.casefold()).suffix in _AUDIO_EXTENSIONS
