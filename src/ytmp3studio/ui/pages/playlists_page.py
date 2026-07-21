from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QInputDialog, QListWidget, QListWidgetItem, QPushButton, QSplitter, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ytmp3studio.ui.widgets.common import FeedbackLabel, format_duration


def _value(item: object, name: str, default: Any = None) -> Any:
    return item.get(name, default) if isinstance(item, dict) else getattr(item, name, default)


def _track_value(entry: object, name: str, default: Any = None) -> Any:
    """Read both flat UI records and domain PlaylistEntry records."""
    direct = _value(entry, name, None)
    if direct is not None:
        return direct
    track = _value(entry, "track", None)
    item = _value(entry, "item", None)
    value = _value(track, name, None) if track is not None else None
    return value if value is not None else _value(item, name, default)


class PlaylistsPage(QWidget):
    """Import and synchronize Spotify playlists exported by Exportify."""

    def __init__(self, facade: object, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.facade = facade
        self._playlists: list[object] = []
        self._current: object | None = None
        self._detail_tracks: list[object] = []
        self._latest_list: str | None = None
        self._latest_detail: str | None = None
        self._pending: set[str] = set()
        self._pending_stop: dict[str, object] = {}

        eyebrow = QLabel("SPOTIFY · EXPORTIFY")
        eyebrow.setProperty("eyebrow", True)
        heading = QLabel("Playlists")
        heading.setProperty("heading", True)
        intro = QLabel("Importa el ZIP o los CSV de Exportify. La aplicación buscará las canciones y mantendrá cada playlist sincronizada.")
        intro.setWordWrap(True)
        intro.setProperty("muted", True)

        self.open_exportify_button = QPushButton("Abrir Exportify")
        self.open_exportify_button.setProperty("secondary", True)
        self.import_button = QPushButton("Importar ZIP o CSV")
        self.refresh_button = QPushButton("Actualizar lista")
        self.refresh_button.setProperty("secondary", True)
        actions = QHBoxLayout()
        actions.addWidget(self.open_exportify_button)
        actions.addWidget(self.import_button)
        actions.addStretch()
        actions.addWidget(self.refresh_button)
        self.feedback = FeedbackLabel()

        self.playlist_list = QListWidget()
        self.playlist_list.setAccessibleName("Playlists importadas")
        self.playlist_list.setMinimumWidth(245)
        list_panel = QFrame()
        list_panel.setObjectName("card")
        list_layout = QVBoxLayout(list_panel)
        list_layout.setContentsMargins(14, 14, 14, 14)
        list_title = QLabel("Tus playlists")
        list_title.setProperty("subheading", True)
        self.list_summary = QLabel("Todavía no hay playlists importadas.")
        self.list_summary.setProperty("muted", True)
        self.list_summary.setWordWrap(True)
        list_layout.addWidget(list_title)
        list_layout.addWidget(self.list_summary)
        list_layout.addWidget(self.playlist_list, 1)

        self.cover = QLabel("Sin\nportada")
        self.cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover.setFixedSize(116, 116)
        self.cover.setStyleSheet("border: 1px solid #52675c; border-radius: 8px;")
        self.detail_title = QLabel("Selecciona una playlist")
        self.detail_title.setProperty("subheading", True)
        self.detail_meta = QLabel("Aquí verás sus canciones y el estado de cada descarga.")
        self.detail_meta.setProperty("muted", True)
        self.detail_meta.setWordWrap(True)
        header_text = QVBoxLayout()
        header_text.addWidget(self.detail_title)
        header_text.addWidget(self.detail_meta)
        header_text.addStretch()
        detail_header = QHBoxLayout()
        detail_header.addWidget(self.cover)
        detail_header.addLayout(header_text, 1)

        self.download_button = QPushButton("Descargar / sincronizar")
        self.stop_button = QPushButton("Detener descargas")
        self.stop_button.setProperty("secondary", True)
        self.retry_button = QPushButton("Reintentar fallidas")
        self.retry_button.setProperty("secondary", True)
        self.cover_button = QPushButton("Elegir portada")
        self.cover_button.setProperty("secondary", True)
        self.replace_button = QPushButton("Cambiar versión")
        self.replace_button.setProperty("secondary", True)
        for button in (self.download_button, self.stop_button, self.retry_button, self.cover_button, self.replace_button):
            button.setEnabled(False)
        detail_actions = QHBoxLayout()
        for button in (self.download_button, self.stop_button, self.retry_button, self.replace_button, self.cover_button):
            detail_actions.addWidget(button)
        detail_actions.addStretch()

        self.tracks_table = QTableWidget(0, 4)
        self.tracks_table.setHorizontalHeaderLabels(["Artista", "Canción", "Duración", "Estado"])
        self.tracks_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tracks_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tracks_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tracks_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.tracks_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tracks_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tracks_table.setAlternatingRowColors(True)
        self.tracks_table.setAccessibleName("Canciones de la playlist")
        detail_panel = QFrame()
        detail_panel.setObjectName("card")
        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(16, 16, 16, 16)
        detail_layout.addLayout(detail_header)
        detail_layout.addLayout(detail_actions)
        detail_layout.addWidget(self.tracks_table, 1)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(list_panel)
        splitter.addWidget(detail_panel)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([270, 700])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(10)
        for widget in (eyebrow, heading, intro):
            layout.addWidget(widget)
        layout.addLayout(actions)
        layout.addWidget(self.feedback)
        layout.addWidget(splitter, 1)

        self.open_exportify_button.clicked.connect(self.open_exportify)
        self.import_button.clicked.connect(self.choose_import)
        self.refresh_button.clicked.connect(self.refresh)
        self.playlist_list.currentRowChanged.connect(self._selection_changed)
        self.download_button.clicked.connect(self.download_current)
        self.stop_button.clicked.connect(self.stop_current)
        self.retry_button.clicked.connect(self.retry_current)
        self.cover_button.clicked.connect(self.choose_cover)
        self.replace_button.clicked.connect(self.replace_selected)
        self.tracks_table.itemSelectionChanged.connect(self._track_selection_changed)
        self.tracks_table.itemDoubleClicked.connect(lambda _item: self.replace_selected())
        for name, slot in (
            ("playlists_snapshot", self._playlists_snapshot),
            ("playlist_snapshot", self._playlist_snapshot),
            ("playlist_detail", self._playlist_snapshot),
            ("playlists_changed", self.refresh),
            ("playlist_changed", self._playlist_changed),
            ("exportify_imported", self._import_completed),
            ("playlist_replacement_candidates", self._replacement_candidates),
            ("operation_failed", self._operation_failed),
        ):
            self._connect_optional(name, slot)
        self._update_capabilities()

    def _connect_optional(self, name: str, slot: object) -> None:
        signal = getattr(self.facade, name, None)
        if signal is not None and hasattr(signal, "connect"):
            signal.connect(slot)

    def _update_capabilities(self) -> None:
        can_import = hasattr(self.facade, "import_exportify")
        self.import_button.setEnabled(can_import)
        self.refresh_button.setEnabled(hasattr(self.facade, "list_playlists"))
        self.open_exportify_button.setEnabled(hasattr(self.facade, "open_exportify"))
        if not can_import:
            self.feedback.setText("La función de playlists aún no está disponible en este build.")
            self.feedback.setVisible(True)

    def open_exportify(self) -> None:
        method = getattr(self.facade, "open_exportify", None)
        if method:
            self._remember_pending(method())

    def choose_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Importar desde Exportify", "", "Exportify (*.zip *.csv);;Archivo ZIP (*.zip);;Archivo CSV (*.csv)")
        if path:
            self.import_path(path)

    def import_path(self, path: str) -> None:
        method = getattr(self.facade, "import_exportify", None)
        if not method:
            return
        self.feedback.clear()
        self.import_button.setEnabled(False)
        result = method(path)
        if isinstance(result, (list, tuple)):
            self.set_playlists(list(result))
            self.import_button.setEnabled(True)
        else:
            self._remember_pending(result)

    def refresh(self) -> None:
        method = getattr(self.facade, "list_playlists", None)
        if method:
            result = method()
            if isinstance(result, (list, tuple)):
                self.set_playlists(list(result))
            else:
                self._latest_list = result if isinstance(result, str) else None

    def set_playlists(self, playlists: list[object]) -> None:
        selected_id = self.current_playlist_id()
        self._playlists = playlists
        self.playlist_list.blockSignals(True)
        self.playlist_list.clear()
        selected_row = -1
        for row, playlist in enumerate(playlists):
            count = _value(playlist, "track_count", _value(playlist, "total_tracks", None))
            label = str(_value(playlist, "name", "Playlist")) + (f"  ·  {count}" if count is not None else "")
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, _value(playlist, "id"))
            self.playlist_list.addItem(item)
            if str(_value(playlist, "id")) == str(selected_id):
                selected_row = row
        self.playlist_list.blockSignals(False)
        count = len(playlists)
        self.list_summary.setText(f"{count} playlist{'s' if count != 1 else ''} importada{'s' if count != 1 else ''}.")
        if playlists:
            self.playlist_list.setCurrentRow(selected_row if selected_row >= 0 else 0)
        else:
            self._show_detail(None)

    def current_playlist_id(self) -> object | None:
        item = self.playlist_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _selection_changed(self, row: int) -> None:
        if not (0 <= row < len(self._playlists)):
            self._show_detail(None)
            return
        playlist = self._playlists[row]
        self._show_detail(playlist)
        method = getattr(self.facade, "get_playlist", None)
        playlist_id = _value(playlist, "id")
        if method and playlist_id is not None:
            result = method(playlist_id)
            if isinstance(result, (dict, tuple, list)) or hasattr(result, "tracks") or hasattr(result, "entries"):
                self._show_detail(result)
            else:
                self._latest_detail = result if isinstance(result, str) else None

    def _show_detail(self, playlist: object | None) -> None:
        self._current = playlist
        enabled = playlist is not None
        self.download_button.setEnabled(enabled and hasattr(self.facade, "download_playlist"))
        self._update_stop_button()
        self.cover_button.setEnabled(enabled and hasattr(self.facade, "choose_playlist_cover"))
        if playlist is None:
            self._detail_tracks = []
            self.detail_title.setText("Selecciona una playlist")
            self.detail_meta.setText("Aquí verás sus canciones y el estado de cada descarga.")
            self.tracks_table.setRowCount(0)
            self._set_cover(None)
            return
        if isinstance(playlist, (tuple, list)) and playlist:
            base = playlist[0]
            tracks = list(playlist[1] if len(playlist) > 1 else [])
        else:
            base = _value(playlist, "playlist", playlist)
            tracks = list(_value(playlist, "tracks", _value(playlist, "entries", [])) or [])
        self._detail_tracks = tracks
        self.detail_title.setText(str(_value(base, "name", "Playlist")))
        failed_states = {"failed", "error", "fallida"}
        complete_states = {"downloaded", "completed", "available", "descargada"}
        failed = sum(str(_track_value(track, "status", _track_value(track, "state", ""))).lower() in failed_states for track in tracks)
        downloaded = sum(str(_track_value(track, "status", _track_value(track, "state", ""))).lower() in complete_states for track in tracks)
        self.detail_meta.setText(f"{len(tracks)} canciones · {downloaded} descargadas" + (f" · {failed} pendientes de revisión" if failed else ""))
        self.retry_button.setEnabled(bool(failed) and hasattr(self.facade, "retry_playlist_failures"))
        self.tracks_table.setRowCount(len(tracks))
        for row, track in enumerate(tracks):
            artist = _track_value(track, "artist", _track_value(track, "artists", ""))
            if isinstance(artist, (list, tuple)):
                artist = ", ".join(str(value) for value in artist)
            duration = _track_value(track, "duration_seconds", None)
            duration_ms = _track_value(track, "duration_ms", None)
            if duration is None and isinstance(duration_ms, (int, float)):
                duration = duration_ms // 1000
            raw_status = _track_value(track, "status", _track_value(track, "state", "Pendiente"))
            status = str(raw_status).replace("_", " ").capitalize()
            values = (artist, _track_value(track, "title", _track_value(track, "name", "")), format_duration(duration), status)
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value or ""))
                item.setData(Qt.ItemDataRole.UserRole, _track_value(track, "track_key"))
                if str(raw_status).lower() in failed_states:
                    item.setForeground(Qt.GlobalColor.red)
                self.tracks_table.setItem(row, column, item)
        self._set_cover(_value(base, "cover_path", _value(base, "image_path", None)))
        self._track_selection_changed()

    def _set_cover(self, path: object | None) -> None:
        pixmap = QPixmap(str(path)) if path and Path(str(path)).is_file() else QPixmap()
        if pixmap.isNull():
            self.cover.setPixmap(QPixmap())
            self.cover.setText("Sin\nportada")
        else:
            self.cover.setText("")
            self.cover.setPixmap(pixmap.scaled(self.cover.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def download_current(self) -> None:
        self._call_current("download_playlist")

    def stop_current(self) -> None:
        playlist_id = self.current_playlist_id()
        method = getattr(self.facade, "stop_playlist_downloads", None)
        if playlist_id is None or method is None or self._is_stop_pending(playlist_id):
            return
        self.feedback.clear()
        result = method(playlist_id)
        if isinstance(result, str):
            self._pending.add(result)
            self._pending_stop[result] = playlist_id
        self._update_stop_button()

    def retry_current(self) -> None:
        self._call_current("retry_playlist_failures")

    def _is_stop_pending(self, playlist_id: object | None) -> bool:
        return playlist_id is not None and any(
            str(pending_id) == str(playlist_id)
            for pending_id in self._pending_stop.values()
        )

    def _update_stop_button(self) -> None:
        playlist_id = self.current_playlist_id()
        pending = self._is_stop_pending(playlist_id)
        self.stop_button.setText("Deteniendo..." if pending else "Detener descargas")
        self.stop_button.setEnabled(
            playlist_id is not None
            and hasattr(self.facade, "stop_playlist_downloads")
            and not pending
        )

    def _finish_stop_requests(self, playlist_id: object) -> None:
        completed = [
            request_id
            for request_id, pending_id in self._pending_stop.items()
            if str(pending_id) == str(playlist_id)
        ]
        for request_id in completed:
            self._pending_stop.pop(request_id, None)
            self._pending.discard(request_id)
        self._update_stop_button()

    def _track_selection_changed(self) -> None:
        row = self.tracks_table.currentRow()
        self.replace_button.setEnabled(
            0 <= row < len(self._detail_tracks) and hasattr(self.facade, "replace_playlist_track")
        )

    def replace_selected(self) -> None:
        row = self.tracks_table.currentRow()
        playlist_id = self.current_playlist_id()
        method = getattr(self.facade, "replace_playlist_track", None)
        if playlist_id is None or method is None or not (0 <= row < len(self._detail_tracks)):
            return
        track_key = _track_value(self._detail_tracks[row], "track_key")
        if track_key is not None:
            self.feedback.clear()
            self._remember_pending(method(playlist_id, track_key))

    def _replacement_candidates(
        self,
        request_id: str,
        playlist_id: str,
        track_key: str,
        candidates: object,
    ) -> None:
        self._pending.discard(request_id)
        values = list(candidates) if isinstance(candidates, (list, tuple)) else []
        if not values:
            self.feedback.setText("No se encontraron versiones alternativas.")
            self.feedback.setVisible(True)
            return
        labels = [
            f"{_value(item, 'title', 'Sin título')} — {_value(item, 'channel', '')} "
            f"({_value(item, 'score', 0):.0f}/100)"
            for item in values
        ]
        selected, accepted = QInputDialog.getItem(
            self,
            "Cambiar versión",
            "Elige el resultado de YouTube que sustituirá la canción en todas sus playlists:",
            labels,
            0,
            False,
        )
        if not accepted:
            return
        index = labels.index(selected)
        method = getattr(self.facade, "confirm_playlist_replacement", None)
        video_id = _value(values[index], "video_id")
        if method is not None and video_id:
            self._remember_pending(method(playlist_id, track_key, video_id))

    def _call_current(self, method_name: str) -> None:
        playlist_id = self.current_playlist_id()
        method = getattr(self.facade, method_name, None)
        if playlist_id is not None and method:
            self.feedback.clear()
            self._remember_pending(method(playlist_id))

    def choose_cover(self) -> None:
        playlist_id = self.current_playlist_id()
        method = getattr(self.facade, "choose_playlist_cover", None)
        if playlist_id is None or not method:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Elegir portada", "", "Imágenes (*.jpg *.jpeg *.png *.webp)")
        if path:
            self._remember_pending(method(playlist_id, path))

    def _remember_pending(self, result: object) -> None:
        if isinstance(result, str):
            self._pending.add(result)

    @staticmethod
    def _signal_payload(args: tuple[object, ...]) -> tuple[str | None, object | None]:
        if len(args) >= 2 and isinstance(args[0], str):
            return args[0], args[1]
        return None, args[-1] if args else None

    def _playlists_snapshot(self, *args: object) -> None:
        request_id, playlists = self._signal_payload(args)
        if self._latest_list and request_id and request_id != self._latest_list:
            return
        if isinstance(playlists, (list, tuple)):
            self.set_playlists(list(playlists))
        self.import_button.setEnabled(hasattr(self.facade, "import_exportify"))

    def _playlist_snapshot(self, *args: object) -> None:
        request_id, playlist = self._signal_payload(args)
        if self._latest_detail and request_id and request_id != self._latest_detail:
            return
        playlist_id = _value(playlist, "id") if playlist is not None else None
        if playlist is not None and (playlist_id is None or str(playlist_id) == str(self.current_playlist_id())):
            self._show_detail(playlist)

    def _playlist_changed(self, *args: object) -> None:
        if args:
            self._finish_stop_requests(args[-1])
        self.refresh()

    def _import_completed(self, *args: object) -> None:
        _, playlists = self._signal_payload(args)
        self.import_button.setEnabled(hasattr(self.facade, "import_exportify"))
        self.feedback.setText("Importación completada.")
        self.feedback.setVisible(True)
        if isinstance(playlists, (list, tuple)):
            self.set_playlists(list(playlists))
        else:
            self.refresh()

    def _operation_failed(self, request_id: str, error: object) -> None:
        if request_id not in self._pending and request_id not in {self._latest_list, self._latest_detail}:
            return
        self._pending.discard(request_id)
        self._pending_stop.pop(request_id, None)
        self._update_stop_button()
        self.import_button.setEnabled(hasattr(self.facade, "import_exportify"))
        self.feedback.show_error(error)
