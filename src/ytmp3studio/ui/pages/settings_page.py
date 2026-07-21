from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget

from ytmp3studio.ui.widgets.common import FeedbackLabel


class SettingsPage(QWidget):
    theme_selected = Signal(str)

    def __init__(self, facade: object, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.facade = facade
        self._pending_save: str | None = None
        self._pending_dependencies: str | None = None
        self._loading = False

        self.download_dir = QLineEdit()
        self.download_dir.setAccessibleName("Carpeta de descargas")
        browse = QPushButton("Elegir…")
        browse.setProperty("secondary", True)
        self.google_drive = QPushButton("Elegir carpeta de Google Drive…")
        self.google_drive.setAccessibleName("Elegir carpeta de Google Drive")
        folder_row = QHBoxLayout()
        folder_row.addWidget(self.download_dir, 1)
        folder_row.addWidget(browse)
        self.quality = QComboBox()
        for value in (128, 192, 256, 320):
            self.quality.addItem(f"{value} kbps", value)
        self.theme = QComboBox()
        self.theme.addItem("Sistema", "system")
        self.theme.addItem("Claro", "light")
        self.theme.addItem("Oscuro", "dark")
        self.concurrency = QSpinBox()
        self.concurrency.setRange(1, 4)
        self.concurrency.setToolTip("Número máximo de descargas simultáneas")
        self.retries = QSpinBox()
        self.retries.setRange(0, 5)
        self.retry_base = QSpinBox()
        self.retry_base.setRange(1, 60)
        self.retry_base.setSuffix(" s")
        self.feedback = FeedbackLabel()
        self.saved = QLabel("")
        self.saved.setProperty("muted", True)
        self.dependencies = QLabel("Diagnóstico pendiente")
        self.dependencies.setWordWrap(True)
        self.dependencies.setProperty("muted", True)
        self.check = QPushButton("Comprobar herramientas")
        self.check.setProperty("secondary", True)
        self.save = QPushButton("Guardar configuración")

        preferences = QFrame()
        preferences.setObjectName("settingsCard")
        preferences_layout = QVBoxLayout(preferences)
        preferences_layout.setContentsMargins(18, 16, 18, 18)
        preferences_layout.setSpacing(12)
        preferences_title = QLabel("Preferencias de descarga")
        preferences_title.setProperty("subheading", True)
        preferences_hint = QLabel("Elige dónde guardar tus MP3 y la calidad que prefieres.")
        preferences_hint.setProperty("muted", True)
        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)
        form.addRow("Carpeta de descargas", folder_row)
        form.addRow("Calidad MP3", self.quality)
        form.addRow("Tema", self.theme)
        preferences_layout.addWidget(preferences_title)
        preferences_layout.addWidget(preferences_hint)
        preferences_layout.addLayout(form)

        drive = QFrame()
        drive.setObjectName("driveCard")
        drive_layout = QVBoxLayout(drive)
        drive_layout.setContentsMargins(18, 16, 18, 18)
        drive_layout.setSpacing(8)
        drive_title = QLabel("Lleva tu música al iPhone con Google Drive")
        drive_title.setProperty("subheading", True)
        drive_intro = QLabel(
            "1. Elige aquí tu carpeta Mi unidad.  2. Descarga música y espera a que Drive la sincronice.  "
            "3. En el iPhone, importa las canciones desde Archivos."
        )
        drive_intro.setWordWrap(True)
        drive_intro.setProperty("muted", True)
        self.drive_status = QLabel("Google Drive para ordenador debe estar instalado y con tu sesión iniciada.")
        self.drive_status.setWordWrap(True)
        self.drive_status.setProperty("muted", True)
        drive_actions = QHBoxLayout()
        drive_actions.addWidget(self.google_drive)
        drive_actions.addStretch()
        drive_layout.addWidget(drive_title)
        drive_layout.addWidget(drive_intro)
        drive_layout.addWidget(self.drive_status)
        drive_layout.addLayout(drive_actions)

        self.advanced_toggle = QPushButton("Mostrar opciones avanzadas")
        self.advanced_toggle.setProperty("secondary", True)
        self.advanced_toggle.setCheckable(True)
        self.advanced = QFrame()
        self.advanced.setObjectName("settingsCard")
        advanced_layout = QFormLayout(self.advanced)
        advanced_layout.setContentsMargins(18, 16, 18, 16)
        advanced_layout.setHorizontalSpacing(18)
        advanced_layout.setVerticalSpacing(12)
        advanced_layout.addRow("Descargas simultáneas", self.concurrency)
        advanced_layout.addRow("Reintentos automáticos", self.retries)
        advanced_layout.addRow("Espera base", self.retry_base)
        self.advanced.hide()

        tools = QFrame()
        tools.setObjectName("settingsCard")
        tools_layout = QVBoxLayout(tools)
        tools_layout.setContentsMargins(18, 16, 18, 16)
        tools_title = QLabel("Estado de herramientas")
        tools_title.setProperty("subheading", True)
        tools_layout.addWidget(tools_title)
        tools_layout.addWidget(self.dependencies)
        buttons = QHBoxLayout()
        buttons.addWidget(self.check)
        buttons.addStretch()
        buttons.addWidget(self.save)
        eyebrow = QLabel("AJUSTES")
        eyebrow.setProperty("eyebrow", True)
        heading = QLabel("Configuración")
        heading.setProperty("heading", True)
        intro = QLabel("Personaliza cómo se descarga y organiza tu música.")
        intro.setProperty("muted", True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(10)
        layout.addWidget(eyebrow)
        layout.addWidget(heading)
        layout.addWidget(intro)
        layout.addSpacing(6)
        layout.addWidget(drive)
        layout.addWidget(preferences)
        layout.addWidget(self.advanced_toggle, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.advanced)
        layout.addWidget(self.feedback)
        layout.addWidget(self.saved)
        layout.addWidget(tools)
        layout.addLayout(buttons)
        layout.addStretch()

        browse.clicked.connect(self._browse)
        self.google_drive.clicked.connect(self._choose_google_drive)
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        self.save.clicked.connect(self._save)
        self.check.clicked.connect(self._check_dependencies)
        facade.settings_changed.connect(self.set_settings)
        facade.dependency_status.connect(self.set_dependency_status)
        facade.operation_failed.connect(self._operation_failed)

    def set_settings(self, settings: object) -> None:
        self._loading = True
        self.download_dir.setText(settings.download_dir)
        self.quality.setCurrentIndex(max(0, self.quality.findData(settings.quality_kbps)))
        self.theme.setCurrentIndex(max(0, self.theme.findData(settings.theme)))
        self.concurrency.setValue(settings.concurrency)
        self.retries.setValue(settings.max_retries)
        self.retry_base.setValue(settings.retry_base_seconds)
        self._loading = False
        self.save.setEnabled(True)
        if self._pending_save:
            self.saved.setText("Configuración guardada.")
            self._pending_save = None
        self.theme_selected.emit(settings.theme)

    def set_dependency_status(self, request_id: str, status: object) -> None:
        if self._pending_dependencies and request_id != self._pending_dependencies:
            return
        self._pending_dependencies = None
        self.check.setEnabled(True)
        ytdlp = status.ytdlp
        ffmpeg = status.ffmpeg
        writable = "correcta" if status.download_dir_writable else "sin permiso de escritura"
        self.dependencies.setText(
            f"yt-dlp: {ytdlp.state.value} {ytdlp.version or ''}\n"
            f"ffmpeg: {ffmpeg.state.value} {ffmpeg.version or ''}\n"
            f"Carpeta: {writable}"
        )
        self.dependencies.setToolTip("\n".join(filter(None, [ytdlp.message, ffmpeg.message, status.download_dir])))

    def _browse(self) -> None:
        initial = self.download_dir.text() if Path(self.download_dir.text()).exists() else str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "Elegir carpeta de descargas", initial)
        if path:
            self.download_dir.setText(path)

    def _choose_google_drive(self) -> None:
        initial = self.download_dir.text() if Path(self.download_dir.text()).exists() else str(Path.home())
        root = QFileDialog.getExistingDirectory(
            self,
            "Selecciona la carpeta 'Mi unidad' de Google Drive",
            initial,
        )
        if root:
            selected = Path(root)
            target = selected if selected.name.casefold() == "yt-mp3 studio" else selected / "YT-MP3 Studio"
            self.download_dir.setText(str(target))
            self.feedback.clear()
            self.drive_status.setText(f"Carpeta preparada: {target}")
            self.saved.setText("Google Drive seleccionado. Pulsa Guardar configuración.")

    def _toggle_advanced(self, visible: bool) -> None:
        self.advanced.setVisible(visible)
        self.advanced_toggle.setText("Ocultar opciones avanzadas" if visible else "Mostrar opciones avanzadas")

    def _save(self) -> None:
        path = self.download_dir.text().strip()
        self.feedback.clear()
        self.saved.clear()
        if not path:
            self.feedback.show_error("Elige una carpeta de descargas.")
            return
        patch = {
            "download_dir": path,
            "quality_kbps": self.quality.currentData(),
            "theme": self.theme.currentData(),
            "concurrency": self.concurrency.value(),
            "max_retries": self.retries.value(),
            "retry_base_seconds": self.retry_base.value(),
        }
        self.save.setEnabled(False)
        self._pending_save = self.facade.update_settings(patch)

    def _check_dependencies(self) -> None:
        self.check.setEnabled(False)
        self.dependencies.setText("Comprobando…")
        self._pending_dependencies = self.facade.check_dependencies()

    def _operation_failed(self, request_id: str, error: object) -> None:
        if request_id == self._pending_save:
            self._pending_save = None
            self.save.setEnabled(True)
            self.feedback.show_error(error)
        elif request_id == self._pending_dependencies:
            self._pending_dependencies = None
            self.check.setEnabled(True)
            self.feedback.show_error(error)
