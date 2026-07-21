from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt, QTimer, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ytmp3studio.ui.widgets.common import FeedbackLabel, format_duration


class ResultCard(QFrame):
    def __init__(self, result: object, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.result = result
        self.setObjectName("card")
        self.check = QCheckBox()
        self.check.setAccessibleName(f"Seleccionar {result.title}")
        self.thumbnail = QLabel("Sin\nminiatura")
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail.setFixedSize(116, 68)
        self.thumbnail.setProperty("muted", True)
        self.thumbnail.setStyleSheet("background: #203027; border-radius: 8px;")
        title = QLabel(result.title)
        title.setStyleSheet("font-size: 15px; font-weight: 700;")
        title.setWordWrap(True)
        title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.meta = QLabel(f"{result.channel}  ·  {format_duration(result.duration_seconds)}")
        self.meta.setProperty("muted", True)
        if result.is_live:
            unsupported = QLabel("Directo no compatible")
            unsupported.setProperty("error", True)
            self.check.setEnabled(False)
        else:
            unsupported = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 14, 10)
        layout.setSpacing(12)
        layout.addWidget(self.check)
        layout.addWidget(self.thumbnail)
        text = QVBoxLayout()
        text.addWidget(title)
        text.addWidget(self.meta)
        if unsupported:
            text.addWidget(unsupported)
        text.addStretch()
        layout.addLayout(text, 1)


class SearchPage(QWidget):
    def __init__(self, facade: object, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.facade = facade
        self._latest_search: str | None = None
        self._pending_enqueue: dict[str, set[str]] = {}
        self._cards: list[ResultCard] = []
        self._network = QNetworkAccessManager(self)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(450)

        eyebrow = QLabel("DESCUBRIR")
        eyebrow.setProperty("eyebrow", True)
        heading = QLabel("Encuentra tu próxima canción")
        heading.setProperty("heading", True)
        intro = QLabel("Busca por título, artista o pega un enlace de YouTube.")
        intro.setProperty("muted", True)
        self.query = QLineEdit()
        self.query.setPlaceholderText("Título, artista o URL de YouTube")
        self.query.setAccessibleName("Consulta de búsqueda")
        self.query.setClearButtonEnabled(True)
        self.search_button = QPushButton("Buscar")
        self.search_button.setShortcut("Return")
        self.search_button.setAccessibleName("Buscar en YouTube")
        self.feedback = FeedbackLabel()
        self.state = QLabel("Escribe algo para empezar.")
        self.state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.state.setProperty("muted", True)
        self.results = QListWidget()
        self.results.setSpacing(8)
        self.results.setFrameShape(QFrame.Shape.NoFrame)
        self.results.setAccessibleName("Resultados de búsqueda")
        self.enqueue = QPushButton("Añadir a la cola")
        self.enqueue.setEnabled(False)

        search_panel = QFrame()
        search_panel.setObjectName("card")
        controls = QHBoxLayout()
        controls.setContentsMargins(12, 12, 12, 12)
        controls.setSpacing(10)
        controls.addWidget(self.query, 1)
        controls.addWidget(self.search_button)
        search_panel.setLayout(controls)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(10)
        layout.addWidget(eyebrow)
        layout.addWidget(heading)
        layout.addWidget(intro)
        layout.addSpacing(6)
        layout.addWidget(search_panel)
        layout.addWidget(self.feedback)
        layout.addWidget(self.state)
        layout.addWidget(self.results, 1)
        layout.addWidget(self.enqueue, alignment=Qt.AlignmentFlag.AlignRight)

        self.search_button.clicked.connect(self.start_search)
        self.query.returnPressed.connect(self.start_search)
        self.query.textEdited.connect(lambda: self._search_timer.start())
        self._search_timer.timeout.connect(self._debounced_search)
        self.enqueue.clicked.connect(self.enqueue_selected)
        facade.search_succeeded.connect(self._search_succeeded)
        facade.operation_failed.connect(self._operation_failed)
        facade.job_added.connect(self._job_added)

    def start_search(self) -> None:
        self._search_timer.stop()
        query = self.query.text().strip()
        self.feedback.clear()
        if not query:
            self.feedback.show_error("Escribe una consulta antes de buscar.")
            return
        self._set_loading(True)
        self.state.setText("Buscando…")
        self.state.show()
        self._latest_search = self.facade.search(query, 12)

    def _set_loading(self, loading: bool) -> None:
        self.search_button.setEnabled(not loading)

    def _debounced_search(self) -> None:
        if self.query.text().strip():
            self.start_search()

    def _search_succeeded(self, request_id: str, results: list[object]) -> None:
        if request_id != self._latest_search:
            return
        self._set_loading(False)
        self._clear_results()
        if not results:
            self.state.setText("No se encontraron resultados. Prueba con otros términos.")
            self.state.show()
            return
        self.state.hide()
        for result in results:
            card = ResultCard(result)
            card.check.toggled.connect(self._selection_changed)
            item = QListWidgetItem()
            item.setSizeHint(card.sizeHint())
            self.results.addItem(item)
            self.results.setItemWidget(item, card)
            self._cards.append(card)
            if result.thumbnail_url:
                self._load_thumbnail(result.thumbnail_url, card.thumbnail)
        self._selection_changed()

    def _clear_results(self) -> None:
        self.results.clear()
        self._cards.clear()
        self.enqueue.setEnabled(False)

    def _selection_changed(self) -> None:
        self.enqueue.setEnabled(any(card.check.isChecked() for card in self._cards))

    def enqueue_selected(self) -> None:
        ids = [card.result.video_id for card in self._cards if card.check.isChecked()]
        if not ids:
            return
        request_id = self.facade.enqueue(ids)
        self._pending_enqueue[request_id] = set(ids)
        self.enqueue.setEnabled(False)
        self.state.setText("Añadiendo a la cola…")
        self.state.show()

    def _job_added(self, job: object) -> None:
        if not self._pending_enqueue:
            return
        completed_request = None
        for request_id, remaining in self._pending_enqueue.items():
            remaining.discard(getattr(job, "video_id", ""))
            if not remaining:
                completed_request = request_id
                break
        if completed_request is None:
            return
        self._pending_enqueue.pop(completed_request, None)
        for card in self._cards:
            card.check.setChecked(False)
        self.state.setText("Selección añadida a la cola.")
        self.state.show()

    def _operation_failed(self, request_id: str, error: object) -> None:
        if request_id == self._latest_search:
            self._set_loading(False)
            self.state.hide()
            self.feedback.show_error(error)
        elif request_id in self._pending_enqueue:
            self._pending_enqueue.pop(request_id, None)
            self._selection_changed()
            self.state.hide()
            self.feedback.show_error(error)

    def _load_thumbnail(self, url: str, label: QLabel) -> None:
        reply = self._network.get(QNetworkRequest(QUrl(url)))
        reply.setProperty("target", label)
        reply.finished.connect(lambda: self._thumbnail_finished(reply))

    @staticmethod
    def _thumbnail_finished(reply: QNetworkReply) -> None:
        label = reply.property("target")
        if label and reply.error() == QNetworkReply.NetworkError.NoError:
            pixmap = QPixmap()
            if pixmap.loadFromData(QByteArray(reply.readAll())):
                label.setPixmap(pixmap.scaled(label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                label.setText("")
        reply.deleteLater()
