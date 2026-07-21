from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QStackedWidget, QVBoxLayout, QWidget

from ytmp3studio.ui.pages.library_page import LibraryPage
from ytmp3studio.ui.pages.playlists_page import PlaylistsPage
from ytmp3studio.ui.pages.queue_page import QueuePage
from ytmp3studio.ui.pages.search_page import SearchPage
from ytmp3studio.ui.pages.settings_page import SettingsPage
from ytmp3studio.ui.theme import apply_theme
from ytmp3studio.ui.widgets.common import PlayerBar


class MainWindow(QMainWindow):
    def __init__(self, facade: object, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.facade = facade
        self.setObjectName("mainWindow")
        self.setWindowTitle("YT-MP3 Studio — Tu música sin conexión")
        self.resize(1280, 820)
        self.setMinimumSize(900, 620)

        brand_mark = QLabel("●")
        brand_mark.setObjectName("brandMark")
        brand_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_mark.setFixedSize(36, 36)
        brand_mark.setProperty("accent", True)
        brand_name = QLabel("YT-MP3 Studio")
        brand_name.setObjectName("brandName")
        brand = QHBoxLayout()
        brand.setSpacing(10)
        brand.addWidget(brand_mark)
        brand.addWidget(brand_name)
        brand.addStretch()
        brand_caption = QLabel("TU MÚSICA, SIN CONEXIÓN")
        brand_caption.setProperty("eyebrow", True)

        navigation_label = QLabel("NAVEGACIÓN")
        navigation_label.setObjectName("sidebarSectionLabel")

        self.navigation = QListWidget()
        self.navigation.setObjectName("navigation")
        self.navigation.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.navigation.setAccessibleName("Navegación principal")
        navigation_entries = (
            ("⌕   Buscar", "Busca música o pega un enlace", "Ctrl+1"),
            ("↓   Cola", "Consulta tus descargas", "Ctrl+2"),
            ("♫   Playlists", "Importa y sincroniza playlists", "Ctrl+3"),
            ("▦   Biblioteca", "Escucha tu música descargada", "Ctrl+4"),
            ("⚙   Configuración", "Ajusta carpeta, calidad y tema", "Ctrl+5"),
        )
        for label, description, shortcut in navigation_entries:
            item = QListWidgetItem(label)
            item.setSizeHint(QSize(0, 46))
            item.setToolTip(f"{description}  ·  {shortcut}")
            self.navigation.addItem(item)

        profile = QFrame()
        profile.setObjectName("profileCard")
        profile_layout = QVBoxLayout(profile)
        profile_layout.setContentsMargins(12, 10, 12, 10)
        profile_layout.setSpacing(2)
        profile_title = QLabel("●  Modo local")
        profile_title.setObjectName("localStatus")
        profile_detail = QLabel("Privado y sin anuncios")
        profile_detail.setProperty("muted", True)
        profile_layout.addWidget(profile_title)
        profile_layout.addWidget(profile_detail)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(236)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(16, 22, 16, 16)
        sidebar_layout.setSpacing(8)
        sidebar_layout.addLayout(brand)
        sidebar_layout.addWidget(brand_caption)
        sidebar_layout.addSpacing(24)
        sidebar_layout.addWidget(navigation_label)
        sidebar_layout.addSpacing(2)
        sidebar_layout.addWidget(self.navigation, 1)
        sidebar_layout.addWidget(profile)

        self.search_page = SearchPage(facade)
        self.queue_page = QueuePage(facade)
        self.playlists_page = PlaylistsPage(facade)
        self.library_page = LibraryPage(facade)
        self.settings_page = SettingsPage(facade)
        self.pages = QStackedWidget()
        for page in (self.search_page, self.queue_page, self.playlists_page, self.library_page, self.settings_page):
            self.pages.addWidget(page)
        self.player = PlayerBar()
        self.legal = QLabel("Descarga únicamente contenido para el que tengas derechos o permiso.")
        self.legal.setProperty("muted", True)
        self.legal.setAlignment(Qt.AlignmentFlag.AlignCenter)

        content = QVBoxLayout()
        content.setContentsMargins(30, 26, 30, 14)
        content.setSpacing(14)
        content.addWidget(self.pages, 1)
        content.addWidget(self.player)
        content.addWidget(self.legal)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(sidebar)
        body.addLayout(content, 1)
        central = QWidget()
        central.setObjectName("appShell")
        central.setLayout(body)
        self.setCentralWidget(central)

        self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.navigation.setCurrentRow(0)
        self.library_page.play_requested.connect(self.player.play_track)
        self.player.playback_error.connect(lambda message: self.statusBar().showMessage(message, 8000))
        self.settings_page.theme_selected.connect(self._apply_theme)
        facade.initialized.connect(self._initialized)
        facade.operation_failed.connect(self._global_error)
        facade.fatal_error.connect(self._fatal_error)

        for index, sequence in enumerate(("Ctrl+1", "Ctrl+2", "Ctrl+3", "Ctrl+4", "Ctrl+5")):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(lambda value=index: self.navigation.setCurrentRow(value))

    def _initialized(self, snapshot: dict[str, object]) -> None:
        self.queue_page.set_jobs(snapshot.get("queue", []))
        settings = snapshot.get("settings")
        if settings:
            self.settings_page.set_settings(settings)
        dependencies = snapshot.get("dependencies")
        if dependencies:
            self.settings_page.set_dependency_status("", dependencies)
            if not dependencies.operational:
                self.statusBar().showMessage("Hay herramientas sin configurar. Revisa Configuración.", 12000)
        self.library_page.refresh_folders()
        self.library_page.refresh()
        self.playlists_page.refresh()

    def _global_error(self, _request_id: str, error: object) -> None:
        message = getattr(error, "user_message", str(error))
        action = getattr(error, "suggested_action", None)
        self.statusBar().showMessage(f"{message} {action or ''}".strip(), 10000)

    def _fatal_error(self, error: object) -> None:
        message = getattr(error, "user_message", str(error))
        action = getattr(error, "suggested_action", None)
        QMessageBox.critical(self, "No se pudo iniciar YT-MP3 Studio", f"{message}\n\n{action or ''}".strip())
        self.close()

    @staticmethod
    def _apply_theme(theme: str) -> None:
        app = QApplication.instance()
        if app:
            apply_theme(app, theme)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API
        self.facade.shutdown()
        event.accept()
