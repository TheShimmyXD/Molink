from __future__ import annotations

import logging
import sys
from collections.abc import Callable

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from config import AppConfig, load_app_config, save_app_config
from logic._00_logic_main import MainLogic
from ui._00_ui_connection import ConnectionBar
from ui._00_ui_sidebar import COLLAPSED_WIDTH, NavSidebar
from ui.blocks.icons import set_icon_font
from ui.blocks.logo import app_icon
from ui.theme import (
    ThemeFonts,
    apply_theme,
    next_theme,
    resolve_theme,
)

logger = logging.getLogger(__name__)

WINDOW_TITLE = "Molink"
APP_NAME = "Molink"
# Medido en las maquetas de la pantalla de emparejar: cabe sin crecer.
WINDOW_SIZE = (660, 400)
MIN_SIZE = (600, 380)
THEME_GLYPHS = {"light": "sun", "dark": "moon"}
THEME_TIPS = {
    "light": "Tema: claro",
    "dark": "Tema: oscuro",
}


class MainWindow(QWidget):
    """
    Ventana principal: barra lateral plegable (sello, modulos, tema) y area de trabajo.

    Es la RAIZ DE COMPOSICION de la aplicacion: carga letras, iconos y tema, y
    construye cada modulo inyectandole su coordinador. Ninguna UI de modulo crea
    gestores ni servicios.
    """

    def __init__(
        self,
        config: AppConfig,
        is_admin: bool = False,
        save_config: Callable[[AppConfig], bool] = save_app_config,
        pair_coordinator: Callable[[], QObject] | None = None,
        console_coordinator: Callable[[], QObject] | None = None,
        chat_coordinator: Callable[[], QObject] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._save_config = save_config  # capturas y pruebas pasan uno que no escribe
        # Capturas y pruebas pasan coordinadores sin red: emparejar es la primera pantalla.
        make_pair = pair_coordinator or self._app_pair_coordinator
        self._console_coordinator = console_coordinator or self._app_console_coordinator
        make_chat = chat_coordinator or self._app_chat_coordinator
        self._network_loop = None  # bucle asyncio de la red, se crea al primer uso
        self._link = None  # enlace que comparten las pantallas, al primer uso
        self.logic = MainLogic(is_admin=is_admin)
        self._pages: dict[str, QWidget] = {}
        self._nav_buttons: dict[str, QPushButton] = {}
        self._fonts = self._load_assets()
        self._apply_theme()

        self.setWindowTitle(WINDOW_TITLE)
        self.setWindowIcon(app_icon())
        self._build_ui()
        self._build_navigation()
        self._configure_geometry()
        # Emparejar es el dueno del enlace: su estado va a la linea del pie desde el arranque.
        self._pair = make_pair()
        self._pair.connection_changed.connect(self.connection_bar.show_line)
        self.connection_bar.retry_requested.connect(self._pair.start)
        self.connection_bar.show_line(self._pair.connection())
        # El Chat escucha desde el arranque: lo que llega pinta el punto del boton.
        self._chat = make_chat()
        self._chat.badge_changed.connect(self._show_chat_badge)
        self._chat.start()

        default_id = self.logic.get_default_module_id()
        if default_id:
            self._load_module(default_id)

    # -- Tema e identidad --------------------------------------

    @staticmethod
    def _load_assets() -> ThemeFonts:
        # Imports diferidos: los gestores leen archivos y la UI no.
        from managers.app_fonts import load_app_fonts
        from managers.icon_font import load_icon_font

        set_icon_font(*load_icon_font())
        return ThemeFonts(*load_app_fonts())

    def _apply_theme(self) -> None:
        app = QApplication.instance()
        colors = resolve_theme(self._config.theme)
        apply_theme(app, self._fonts, colors)

    def _cycle_theme(self) -> None:
        self._config.theme = next_theme(self._config.theme)
        self._save_config(self._config)
        self._apply_theme()
        self._refresh_sidebar()

    def _refresh_sidebar(self) -> None:
        self.sidebar.refresh_theme()
        theme = self._config.theme
        self.sidebar.set_item("theme", THEME_TIPS[theme], THEME_GLYPHS[theme])

    # -- Construccion de la interfaz ---------------------------

    def _configure_geometry(self) -> None:
        self.setMinimumSize(*MIN_SIZE)
        self.resize(*WINDOW_SIZE)
        screen = QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            frame = self.frameGeometry()
            frame.moveCenter(area.center())
            self.move(frame.topLeft())

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # La barra no va en el layout: desplegada pasa por encima del area de
        # trabajo. En el layout queda un hueco del ancho de la barra plegada.
        self.sidebar = NavSidebar(self)
        self.sidebar.module_chosen.connect(self._load_module)
        theme = self._config.theme
        self.theme_button = self.sidebar.add_action(
            "theme", THEME_TIPS[theme], THEME_GLYPHS[theme], self._cycle_theme
        )
        sidebar_slot = QWidget()
        sidebar_slot.setFixedWidth(COLLAPSED_WIDTH)

        # A la derecha, el modulo abierto y bajo el la linea de la conexion.
        self.workspace_stack = QStackedWidget()
        self.connection_bar = ConnectionBar()
        work = QVBoxLayout()
        work.setContentsMargins(0, 0, 0, 0)
        work.setSpacing(0)
        work.addWidget(self.workspace_stack, 1)
        work.addWidget(self.connection_bar)
        root.addWidget(sidebar_slot)
        root.addLayout(work, 1)

    def _build_navigation(self) -> None:
        items = self.logic.get_navigation_items()
        if len(items) < 2:
            return  # con un solo modulo la barra solo lleva el sello y el tema
        for item in items:
            button = self.sidebar.add_module(
                item.module_id, item.label, item.icon or "square", item.description
            )
            self._nav_buttons[item.module_id] = button

    # -- Navegacion --------------------------------------------

    def _load_module(self, module_id: str) -> None:
        payload = self.logic.open_module(module_id)
        if not payload["ok"]:
            logger.warning("Modulo desconocido: %s", module_id)
            return
        if module_id in self._nav_buttons:
            self._nav_buttons[module_id].setChecked(True)
        page = self._pages.get(module_id)
        if page is None:
            page = self._create_module_widget(module_id)
            self._pages[module_id] = page
            self.workspace_stack.addWidget(page)
        self.workspace_stack.setCurrentWidget(page)

    def _create_module_widget(self, module_id: str) -> QWidget:
        # Los imports van dentro de cada rama: un modulo se carga solo al abrirlo.
        # new_module.py agrega ramas antes del marcador.

        if module_id == "pair":
            from modules.mod_02_pair.ui._02_ui_pair import PairWidget

            return PairWidget(coordinator=self._pair)

        if module_id == "console":
            from modules.mod_03_console.ui._03_ui_console import ConsoleWidget

            return ConsoleWidget(coordinator=self._console_coordinator())

        if module_id == "chat":
            from modules.mod_05_chat.ui._05_ui_chat import ChatWidget

            return ChatWidget(coordinator=self._chat)

        # [python-programmer:module-factory]

        labels = {item.module_id: item.label for item in self.logic.get_navigation_items()}
        placeholder = QLabel(f"{labels.get(module_id, module_id)}: próximamente.")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return placeholder

    def _app_pair_coordinator(self) -> QObject:
        from modules.mod_02_pair._02_coordinator import PairCoordinator

        return PairCoordinator.for_app(self._get_network_loop(), self._get_link(), parent=self)

    def _app_console_coordinator(self) -> QObject:
        from modules.mod_03_console._03_coordinator import ConsoleCoordinator

        return ConsoleCoordinator.for_app(self._get_network_loop(), self._get_link(), parent=self)

    def _app_chat_coordinator(self) -> QObject:
        from modules.mod_05_chat._05_coordinator import ChatCoordinator

        return ChatCoordinator.for_app(self._get_network_loop(), self._get_link(), parent=self)

    def _show_chat_badge(self, badge: dict) -> None:
        unread = badge["unread"]
        lines = [f"{unread} sin leer"] if unread else []
        if badge["tooltip"]:
            lines.append(badge["tooltip"])
        self.sidebar.set_badge("chat", bool(unread) or badge["busy"], "\n".join(lines))

    def _get_link(self):
        """El de la app: identidad de ~/.local/share/molink; la IP la pone Emparejar."""
        if self._link is None:
            from services.service_identity import load_or_create_identity
            from services.service_link import LinkSession, LinkSettings
            from services.service_transfer import default_inbox

            settings = LinkSettings("", inbox=default_inbox())
            self._link = LinkSession(load_or_create_identity(), settings)
        return self._link

    def _get_network_loop(self):
        if self._network_loop is None:
            from core.async_loop import AsyncLoop

            self._network_loop = AsyncLoop()
        return self._network_loop

    def resizeEvent(self, event) -> None:  # noqa: N802 (nombre impuesto por Qt)
        super().resizeEvent(event)
        self.sidebar.place(0, 0, self.height())

    # -- Cierre ------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802 (nombre impuesto por Qt)
        # Cada pagina de modulo libera sus hilos y conexiones en su propio closeEvent.
        # Al reves de como se abrieron: Emparejar, la primera, cierra el enlace al final.
        # El Chat no es de ninguna pagina: se cierra antes que todas.
        self._chat.close()
        for page in reversed(self._pages.values()):
            page.close()
        if self._network_loop is not None:
            self._network_loop.stop()
            self._network_loop = None
        super().closeEvent(event)


# -- Punto de entrada ------------------------------------------


def run_app() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setDesktopFileName(APP_NAME)
    window = MainWindow(config=load_app_config())
    window.show()
    sys.exit(app.exec())
