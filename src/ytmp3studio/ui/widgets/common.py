from __future__ import annotations

from PySide6.QtCore import QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QStyle,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt


def format_duration(seconds: int | None) -> str:
    if seconds is None or seconds < 0:
        return "Duración desconocida"
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def format_rate(value: float | None) -> str:
    if value is None:
        return ""
    units = ("B/s", "KB/s", "MB/s", "GB/s")
    index = 0
    while value >= 1024 and index < len(units) - 1:
        value /= 1024
        index += 1
    return f"{value:.1f} {units[index]}"


class FeedbackLabel(QLabel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWordWrap(True)
        self.setProperty("error", True)
        self.hide()

    def show_error(self, error: object) -> None:
        message = getattr(error, "user_message", str(error))
        action = getattr(error, "suggested_action", None)
        self.setText(f"{message} {action or ''}".strip())
        self.show()

    def clear(self) -> None:
        self.hide()
        self.setText("")


class PlayerBar(QFrame):
    playback_error = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("player")
        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._audio.setVolume(0.7)
        self._player.setAudioOutput(self._audio)

        self.cover = QLabel("♫")
        self.cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover.setFixedSize(52, 52)
        self.cover.setProperty("accent", True)
        self.cover.setStyleSheet("background: #20372a; border-radius: 8px; font-size: 22px; font-weight: 800;")
        self.title = QLabel("Nada en reproducción")
        self.title.setStyleSheet("font-weight: 700;")
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.artist = QLabel("Elige una pista de tu biblioteca")
        self.artist.setProperty("muted", True)
        self.play = QPushButton()
        self.play.setProperty("playerControl", True)
        self.play.setAccessibleName("Reproducir o pausar")
        self.play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setAccessibleName("Posición de reproducción")
        self.seek.setRange(0, 0)
        self.time = QLabel("0:00")
        self.time.setProperty("muted", True)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setAccessibleName("Volumen")
        self.volume.setRange(0, 100)
        self.volume.setValue(70)
        self.volume.setMaximumWidth(110)

        row = QHBoxLayout(self)
        row.setContentsMargins(14, 11, 14, 11)
        row.setSpacing(12)
        row.addWidget(self.cover)
        metadata = QVBoxLayout()
        metadata.setSpacing(2)
        metadata.addWidget(self.title)
        metadata.addWidget(self.artist)
        row.addLayout(metadata, 2)
        row.addWidget(self.play)
        transport = QVBoxLayout()
        transport.setSpacing(2)
        controls = QHBoxLayout()
        self.elapsed = QLabel("0:00")
        self.elapsed.setProperty("muted", True)
        controls.addWidget(self.elapsed)
        controls.addWidget(self.seek, 1)
        controls.addWidget(self.time)
        transport.addLayout(controls)
        row.addLayout(transport, 4)
        volume_label = QLabel("VOL")
        volume_label.setProperty("eyebrow", True)
        row.addWidget(volume_label)
        row.addWidget(self.volume)

        self.play.clicked.connect(self.toggle)
        self.seek.sliderMoved.connect(self._player.setPosition)
        self.volume.valueChanged.connect(lambda value: self._audio.setVolume(value / 100))
        self._player.durationChanged.connect(lambda value: self.seek.setRange(0, value))
        self._player.positionChanged.connect(self._position_changed)
        self._player.playbackStateChanged.connect(self._state_changed)
        self._player.errorOccurred.connect(lambda _code, message: self.playback_error.emit(message or "No se pudo reproducir el archivo."))

    def play_track(self, track: object) -> None:
        self.title.setText(getattr(track, "title", "Sin título"))
        self.artist.setText(getattr(track, "channel", "Biblioteca local"))
        self._player.setSource(QUrl.fromLocalFile(getattr(track, "file_path")))
        self._player.play()

    def toggle(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        elif not self._player.source().isEmpty():
            self._player.play()

    def _state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        icon = QStyle.StandardPixmap.SP_MediaPause if state == QMediaPlayer.PlaybackState.PlayingState else QStyle.StandardPixmap.SP_MediaPlay
        self.play.setIcon(self.style().standardIcon(icon))

    def _position_changed(self, value: int) -> None:
        if not self.seek.isSliderDown():
            self.seek.setValue(value)
        self.elapsed.setText(format_duration(value // 1000))
        self.time.setText(format_duration(self._player.duration() // 1000))
