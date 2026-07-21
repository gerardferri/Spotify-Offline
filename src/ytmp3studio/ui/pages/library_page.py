from __future__ import annotations

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ytmp3studio.ui.widgets.common import FeedbackLabel, format_duration


class LibraryPage(QWidget):
    play_requested = Signal(object)
    PAGE_SIZE = 100

    def __init__(self, facade: object, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.facade = facade
        self._latest_request: str | None = None
        self._latest_folders_request: str | None = None
        self._pending_remove: set[str] = set()
        self._pending_reveal: set[str] = set()
        self._pending_folder_operations: set[str] = set()
        self._tracks: list[object] = []
        self._folders: dict[str, object] = {}
        self._offset = 0
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(300)

        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filtrar por título, canal o archivo")
        self.filter.setClearButtonEnabled(True)
        self.filter.setAccessibleName("Filtrar biblioteca")
        self.feedback = FeedbackLabel()
        self.summary = QLabel("Cargando biblioteca…")
        self.summary.setProperty("muted", True)
        self.folder_filter = QComboBox()
        self.folder_filter.setAccessibleName("Filtrar por carpeta")
        self.folder_filter.addItem("Todas las canciones", None)
        self.folder_filter.addItem("Sin carpeta", "")
        self.new_folder = QPushButton("Nueva carpeta")
        self.rename_folder = QPushButton("Renombrar")
        self.delete_folder = QPushButton("Eliminar")
        for button in (self.rename_folder, self.delete_folder):
            button.setProperty("secondary", True)
            button.setEnabled(False)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Título", "Canal", "Carpeta", "Duración", "Calidad", "Estado"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setAccessibleName("Biblioteca de audio")
        self.play = QPushButton("Reproducir")
        self.reveal = QPushButton("Mostrar en el Explorador")
        self.reveal.setProperty("secondary", True)
        self.remove = QPushButton("Quitar de biblioteca")
        self.remove.setProperty("secondary", True)
        self.delete_file = QCheckBox("Borrar también el archivo")
        self.move_target = QComboBox()
        self.move_target.setAccessibleName("Carpeta de destino")
        self.move_target.addItem("Sin carpeta", None)
        self.move = QPushButton("Mover")
        self.move.setProperty("secondary", True)
        self.move.setEnabled(False)
        self.play.setEnabled(False)
        self.reveal.setEnabled(False)
        self.remove.setEnabled(False)
        self.previous = QPushButton("Anterior")
        self.previous.setProperty("secondary", True)
        self.next = QPushButton("Siguiente")
        self.next.setProperty("secondary", True)
        self.previous.setEnabled(False)
        self.next.setEnabled(False)

        action_panel = QFrame()
        action_panel.setObjectName("card")
        actions = QHBoxLayout(action_panel)
        actions.setContentsMargins(12, 10, 12, 10)
        actions.addWidget(self.delete_file)
        actions.addSpacing(12)
        actions.addWidget(QLabel("Mover a"))
        actions.addWidget(self.move_target)
        actions.addWidget(self.move)
        actions.addStretch()
        actions.addWidget(self.reveal)
        actions.addWidget(self.remove)
        actions.addWidget(self.play)
        pagination = QHBoxLayout()
        pagination.addStretch()
        pagination.addWidget(self.previous)
        pagination.addWidget(self.next)
        eyebrow = QLabel("TU COLECCIÓN")
        eyebrow.setProperty("eyebrow", True)
        heading = QLabel("Biblioteca")
        heading.setProperty("heading", True)
        intro = QLabel("Toda tu música descargada, disponible sin conexión.")
        intro.setProperty("muted", True)
        filter_row = QHBoxLayout()
        filter_label = QLabel("⌕")
        filter_label.setProperty("accent", True)
        filter_label.setStyleSheet("font-size: 20px; font-weight: 700;")
        filter_row.addWidget(filter_label)
        filter_row.addWidget(self.filter, 1)
        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("Carpeta"))
        folder_row.addWidget(self.folder_filter, 1)
        folder_row.addWidget(self.new_folder)
        folder_row.addWidget(self.rename_folder)
        folder_row.addWidget(self.delete_folder)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(10)
        layout.addWidget(eyebrow)
        layout.addWidget(heading)
        layout.addWidget(intro)
        layout.addSpacing(6)
        layout.addLayout(folder_row)
        layout.addLayout(filter_row)
        layout.addWidget(self.feedback)
        layout.addWidget(self.summary)
        layout.addWidget(self.table, 1)
        layout.addLayout(pagination)
        layout.addWidget(action_panel)

        self.filter.textChanged.connect(self._filter_changed)
        self.folder_filter.currentIndexChanged.connect(self._folder_filter_changed)
        self._filter_timer.timeout.connect(self.refresh)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.itemDoubleClicked.connect(lambda _item: self._play_selected())
        self.play.clicked.connect(self._play_selected)
        self.reveal.clicked.connect(self._reveal_selected)
        self.remove.clicked.connect(self._remove_selected)
        self.move.clicked.connect(self._move_selected)
        self.new_folder.clicked.connect(self._create_folder)
        self.rename_folder.clicked.connect(self._rename_folder)
        self.delete_folder.clicked.connect(self._delete_folder)
        self.previous.clicked.connect(self._previous_page)
        self.next.clicked.connect(self._next_page)
        facade.library_snapshot.connect(self._snapshot)
        facade.library_changed.connect(self.refresh)
        facade.library_folders_snapshot.connect(self._folders_snapshot)
        facade.library_folders_changed.connect(self._folders_changed)
        facade.operation_failed.connect(self._operation_failed)

    def refresh(self) -> None:
        self.feedback.clear()
        self.summary.setText("Cargando biblioteca…")
        self._latest_request = self.facade.list_library(
            self.filter.text().strip(), self.PAGE_SIZE, self._offset, self.folder_filter.currentData()
        )

    def refresh_folders(self) -> None:
        self._latest_folders_request = self.facade.list_library_folders()

    def _folders_snapshot(self, request_id: str, folders: list[object]) -> None:
        if request_id != self._latest_folders_request:
            return
        selected_filter = self.folder_filter.currentData()
        selected_target = self.move_target.currentData()
        self._folders = {folder.id: folder for folder in folders}
        self.folder_filter.blockSignals(True)
        self.folder_filter.clear()
        self.folder_filter.addItem("Todas las canciones", None)
        self.folder_filter.addItem("Sin carpeta", "")
        self.move_target.clear()
        self.move_target.addItem("Sin carpeta", None)
        for folder in folders:
            self.folder_filter.addItem(f"{folder.name}  ({folder.track_count})", folder.id)
            self.move_target.addItem(folder.name, folder.id)
        filter_index = self.folder_filter.findData(selected_filter)
        self.folder_filter.setCurrentIndex(max(0, filter_index))
        target_index = self.move_target.findData(selected_target)
        self.move_target.setCurrentIndex(max(0, target_index))
        self.folder_filter.blockSignals(False)
        self._folder_controls_changed()

    def _folders_changed(self) -> None:
        self._pending_folder_operations.clear()
        self.refresh_folders()
        self.refresh()

    def _snapshot(self, request_id: str, tracks: list[object], total: int) -> None:
        if request_id != self._latest_request:
            return
        if total and self._offset >= total:
            self._offset = ((total - 1) // self.PAGE_SIZE) * self.PAGE_SIZE
            self.refresh()
            return
        self._tracks = tracks
        self.table.setRowCount(len(tracks))
        for row, track in enumerate(tracks):
            folder = self._folders.get(getattr(track, "folder_id", None))
            values = [track.title, track.channel, getattr(folder, "name", "Sin carpeta"), format_duration(track.duration_seconds), f"{track.quality_kbps} kbps", "Archivo no encontrado" if track.file_missing else "Disponible"]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if track.file_missing:
                    item.setForeground(Qt.GlobalColor.red)
                item.setToolTip(track.file_path if column == 0 else value)
                self.table.setItem(row, column, item)
        suffix = "" if total <= 200 else " (se muestran los primeros 200)"
        self.summary.setText(f"{total} pista{'s' if total != 1 else ''}{suffix}" if total else "La biblioteca está vacía.")
        if total:
            first = self._offset + 1
            last = self._offset + len(tracks)
            self.summary.setText(
                f"{total} pista{'s' if total != 1 else ''} - mostrando {first}-{last}"
            )
        self.previous.setEnabled(self._offset > 0)
        self.next.setEnabled(self._offset + len(tracks) < total)
        self._selection_changed()

    def _selected(self) -> object | None:
        row = self.table.currentRow()
        return self._tracks[row] if 0 <= row < len(self._tracks) else None

    def _selection_changed(self) -> None:
        track = self._selected()
        self.play.setEnabled(bool(track and not track.file_missing))
        self.reveal.setEnabled(bool(track and not track.file_missing))
        self.remove.setEnabled(track is not None)
        self.move.setEnabled(track is not None)

    def _play_selected(self) -> None:
        track = self._selected()
        if track and not track.file_missing:
            self.play_requested.emit(track)

    def _reveal_selected(self) -> None:
        track = self._selected()
        if track and not track.file_missing:
            request_id = self.facade.reveal_library_track(track.id)
            self._pending_reveal.add(request_id)

    def _filter_changed(self) -> None:
        self._offset = 0
        self._filter_timer.start()

    def _folder_filter_changed(self) -> None:
        self._offset = 0
        self._folder_controls_changed()
        self.refresh()

    def _folder_controls_changed(self) -> None:
        editable = self.folder_filter.currentData() not in (None, "")
        self.rename_folder.setEnabled(editable)
        self.delete_folder.setEnabled(editable)

    def _create_folder(self) -> None:
        name, accepted = QInputDialog.getText(self, "Nueva carpeta", "Nombre de la carpeta")
        if accepted:
            self._start_folder_operation(self.facade.create_library_folder(name))

    def _rename_folder(self) -> None:
        folder_id = self.folder_filter.currentData()
        folder = self._folders.get(folder_id)
        if folder is None:
            return
        name, accepted = QInputDialog.getText(self, "Renombrar carpeta", "Nuevo nombre", text=folder.name)
        if accepted:
            self._start_folder_operation(self.facade.rename_library_folder(folder_id, name))

    def _delete_folder(self) -> None:
        folder_id = self.folder_filter.currentData()
        folder = self._folders.get(folder_id)
        if folder is None:
            return
        answer = QMessageBox.question(
            self,
            "Eliminar carpeta",
            f"¿Eliminar la carpeta “{folder.name}”?\n\nSus canciones pasarán a Sin carpeta. Los archivos MP3 no se borrarán.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._start_folder_operation(self.facade.delete_library_folder(folder_id))

    def _move_selected(self) -> None:
        track = self._selected()
        if track is None:
            return
        self._start_folder_operation(
            self.facade.assign_library_track_folder(track.id, self.move_target.currentData())
        )

    def _start_folder_operation(self, request_id: str) -> None:
        self.feedback.clear()
        self._pending_folder_operations.add(request_id)

    def _previous_page(self) -> None:
        self._offset = max(0, self._offset - self.PAGE_SIZE)
        self.refresh()

    def _next_page(self) -> None:
        self._offset += self.PAGE_SIZE
        self.refresh()

    def _remove_selected(self) -> None:
        track = self._selected()
        if not track:
            return
        delete = self.delete_file.isChecked()
        detail = "Se borrará también el archivo de audio. Esta acción no se puede deshacer." if delete else "El archivo de audio se conservará."
        answer = QMessageBox.question(self, "Quitar pista", f"¿Quitar “{track.title}” de la biblioteca?\n\n{detail}")
        if answer != QMessageBox.StandardButton.Yes:
            return
        request_id = self.facade.remove_library_track(track.id, delete)
        self._pending_remove.add(request_id)

    def _operation_failed(self, request_id: str, error: object) -> None:
        if (
            request_id == self._latest_request
            or request_id in self._pending_remove
            or request_id in self._pending_reveal
            or request_id in self._pending_folder_operations
        ):
            self._pending_remove.discard(request_id)
            self._pending_reveal.discard(request_id)
            self._pending_folder_operations.discard(request_id)
            self.summary.setText("")
            self.feedback.show_error(error)
