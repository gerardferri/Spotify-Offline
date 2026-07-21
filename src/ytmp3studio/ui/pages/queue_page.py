from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QProgressBar, QPushButton, QVBoxLayout, QWidget

from ytmp3studio.domain.models import JobState
from ytmp3studio.ui.widgets.common import FeedbackLabel, format_duration, format_rate


STATE_LABELS = {
    JobState.QUEUED: "En cola", JobState.RESOLVING: "Preparando", JobState.DOWNLOADING: "Descargando",
    JobState.CONVERTING: "Convirtiendo", JobState.PAUSING: "Pausando", JobState.PAUSED: "Pausado",
    JobState.CANCELLING: "Cancelando", JobState.CANCELLED: "Cancelado", JobState.COMPLETED: "Completado",
    JobState.FAILED: "Fallido", JobState.INTERRUPTED: "Interrumpido",
}
RECOVERABLE = {"NETWORK_ERROR", "SEARCH_FAILED", "DOWNLOAD_FAILED", "YTDLP_OUTDATED"}


class QueueRow(QFrame):
    action = Signal(str, str)

    def __init__(self, job: object, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.job = job
        self.title = QLabel()
        self.title.setWordWrap(True)
        self.meta = QLabel()
        self.meta.setProperty("muted", True)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.detail = QLabel()
        self.detail.setProperty("muted", True)
        self.error = QLabel()
        self.error.setProperty("error", True)
        self.error.setWordWrap(True)
        self.actions = QHBoxLayout()
        self._action_buttons: list[QPushButton] = []

        body = QVBoxLayout(self)
        body.setContentsMargins(14, 12, 14, 12)
        body.setSpacing(7)
        body.addWidget(self.title)
        body.addWidget(self.meta)
        body.addWidget(self.progress)
        body.addWidget(self.detail)
        body.addWidget(self.error)
        body.addLayout(self.actions)
        self.update_job(job)

    def update_job(self, job: object) -> None:
        self.job = job
        self.title.setText(job.title or "Sin título")
        self.meta.setText(f"{job.channel} · {STATE_LABELS.get(job.state, str(job.state))} · {job.quality_kbps} kbps")
        if job.progress_percent is None:
            if job.state in {JobState.RESOLVING, JobState.DOWNLOADING, JobState.CONVERTING}:
                self.progress.setRange(0, 0)
            else:
                self.progress.setRange(0, 1000)
                self.progress.setValue(1000 if job.state == JobState.COMPLETED else 0)
        else:
            self.progress.setRange(0, 1000)
            self.progress.setValue(round(job.progress_percent * 10))
        self.detail.setText(self._progress_text(job.speed_bps, job.eta_seconds, job.duration_seconds))
        self.error.setText(job.error_message or "")
        self.error.setVisible(bool(job.error_message))
        self._build_actions()

    def update_progress(self, progress: object) -> None:
        if progress.percent is None:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, 1000)
            self.progress.setValue(round(progress.percent * 10))
        self.detail.setText(self._progress_text(progress.speed_bps, progress.eta_seconds, self.job.duration_seconds, progress.phase))

    @staticmethod
    def _progress_text(speed: float | None, eta: int | None, duration: int | None, phase: str | None = None) -> str:
        pieces = [phase.capitalize()] if phase else []
        if speed:
            pieces.append(format_rate(speed))
        if eta is not None:
            pieces.append(f"quedan {format_duration(eta)}")
        if not pieces and duration is not None:
            pieces.append(format_duration(duration))
        return " · ".join(pieces)

    def _build_actions(self) -> None:
        self._action_buttons.clear()
        while self.actions.count():
            item = self.actions.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        state = self.job.state
        commands: list[tuple[str, str]] = []
        if state in {JobState.QUEUED, JobState.RESOLVING, JobState.DOWNLOADING, JobState.CONVERTING}:
            commands.append(("Pausar", "pause"))
        if state in {JobState.PAUSED, JobState.INTERRUPTED}:
            commands.append(("Reanudar", "resume"))
        if state == JobState.FAILED and self.job.error_code in RECOVERABLE:
            commands.append(("Reintentar", "retry"))
        if state in {JobState.QUEUED, JobState.RESOLVING, JobState.DOWNLOADING, JobState.CONVERTING, JobState.PAUSING, JobState.PAUSED, JobState.INTERRUPTED}:
            commands.append(("Cancelar", "cancel"))
        if state in {JobState.CANCELLED, JobState.COMPLETED, JobState.FAILED}:
            commands.append(("Quitar", "remove"))
        self.actions.addStretch()
        for text, command in commands:
            button = QPushButton(text)
            button.setProperty("secondary", True)
            button.setAccessibleName(f"{text}: {self.job.title}")
            button.clicked.connect(lambda _checked=False, cmd=command: self.action.emit(self.job.id, cmd))
            self.actions.addWidget(button)
            self._action_buttons.append(button)

    def set_actions_enabled(self, enabled: bool) -> None:
        for button in self._action_buttons:
            button.setEnabled(enabled)


class QueuePage(QWidget):
    def __init__(self, facade: object, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.facade = facade
        self._rows: dict[str, tuple[QListWidgetItem, QueueRow]] = {}
        self._pending: dict[str, str] = {}
        self._optimistically_removed: dict[str, object] = {}
        self.feedback = FeedbackLabel()
        self.empty = QLabel("La cola está vacía.")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setProperty("muted", True)
        self.list = QListWidget()
        self.list.setSpacing(8)
        self.list.setFrameShape(QFrame.Shape.NoFrame)
        self.list.setAccessibleName("Cola de descargas")
        eyebrow = QLabel("ACTIVIDAD")
        eyebrow.setProperty("eyebrow", True)
        heading = QLabel("Cola de descargas")
        heading.setProperty("heading", True)
        intro = QLabel("Sigue el progreso y gestiona tus descargas en curso.")
        intro.setProperty("muted", True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(10)
        layout.addWidget(eyebrow)
        layout.addWidget(heading)
        layout.addWidget(intro)
        layout.addSpacing(6)
        layout.addWidget(self.feedback)
        layout.addWidget(self.empty)
        layout.addWidget(self.list, 1)

        facade.job_added.connect(self.upsert_job)
        facade.job_updated.connect(self.upsert_job)
        facade.job_progress.connect(self.update_progress)
        facade.job_completed.connect(lambda job, _track: self.upsert_job(job))
        facade.operation_failed.connect(self._operation_failed)

    def set_jobs(self, jobs: list[object]) -> None:
        self.list.clear()
        self._rows.clear()
        for job in jobs:
            self.upsert_job(job)
        self._show_empty()

    def upsert_job(self, job: object) -> None:
        completed_requests = [
            request_id
            for request_id, pending_job_id in self._pending.items()
            if pending_job_id == job.id
        ]
        for request_id in completed_requests:
            self._pending.pop(request_id, None)
            self._optimistically_removed.pop(request_id, None)
        existing = self._rows.get(job.id)
        if existing:
            existing[1].update_job(job)
            existing[0].setSizeHint(existing[1].sizeHint())
        else:
            row = QueueRow(job)
            row.action.connect(self._action)
            item = QListWidgetItem()
            item.setSizeHint(row.sizeHint())
            self.list.addItem(item)
            self.list.setItemWidget(item, row)
            self._rows[job.id] = (item, row)
        self._show_empty()

    def update_progress(self, progress: object) -> None:
        row = self._rows.get(progress.job_id)
        if row:
            row[1].update_progress(progress)

    def _action(self, job_id: str, command: str) -> None:
        removed_job = None
        existing = self._rows.get(job_id)
        if existing:
            existing[1].set_actions_enabled(False)
        if command == "remove" and job_id in self._rows:
            item, row = self._rows.pop(job_id)
            removed_job = row.job
            self.list.takeItem(self.list.row(item))
            row.deleteLater()
            self._show_empty()
        request_id = getattr(self.facade, f"{command}_job")(job_id)
        self._pending[request_id] = job_id
        if removed_job is not None:
            self._optimistically_removed[request_id] = removed_job

    def _operation_failed(self, request_id: str, error: object) -> None:
        if request_id in self._pending:
            job_id = self._pending.pop(request_id)
            removed = self._optimistically_removed.pop(request_id, None)
            if removed is not None:
                self.upsert_job(removed)
            elif job_id in self._rows:
                self._rows[job_id][1].set_actions_enabled(True)
            self.feedback.show_error(error)

    def _show_empty(self) -> None:
        self.empty.setVisible(not self._rows)
