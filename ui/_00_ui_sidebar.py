"""Barra de modulos plegable.

Plegada solo muestra los iconos (52 px); al acercar el raton se despliega por
encima del area de trabajo con los rotulos, sin mover el contenido, y se pliega
al alejarlo. Arriba va el sello; abajo, tras el hueco, las acciones (el tema).
La ventana principal la coloca (``place``) y le pide los botones.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGraphicsDropShadowEffect,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.blocks.icons import glyph_icon
from ui.blocks.logo import seal_pixmap
from ui.theme import Kind, Tone, set_kind, shadow_color, sidebar_palette, tone_color

COLLAPSED_WIDTH = 52
EXPANDED_WIDTH = 180
ICON_SIZE = 22
BUTTON_HEIGHT = 40
LOGO_SIZE = 34
LOGO_HEIGHT = 40
APP_NAME = "Molink"
# Pausas para que pasar el raton de largo no despliegue ni pliegue la barra.
EXPAND_DELAY_MS = 120
COLLAPSE_DELAY_MS = 300
ANIMATION_MS = 140
# El icono queda en el mismo sitio plegada o desplegada: (52 - 2*6 - 22) / 2 = 9
# (el relleno de 9 px de los botones esta en el tema).


class NavSidebar(QFrame):
    """Un boton por modulo, con icono; ``module_chosen(id)`` al pulsar uno."""

    module_chosen = Signal(str)

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        # Fondo propio: desplegada tapa el area de trabajo.
        self.setAutoFillBackground(True)
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(16)
        self._shadow.setOffset(2, 0)
        self.setGraphicsEffect(self._shadow)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(6, 12, 6, 10)
        self._layout.setSpacing(6)
        # El sello, centrado sobre los iconos plegada: (52 - 2*6) / 2 = 20 px del borde.
        self.logo = QLabel()
        self.logo.setFixedSize(COLLAPSED_WIDTH - 12, LOGO_HEIGHT)
        self.logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo.setToolTip(APP_NAME)
        self.logo.setAccessibleName(APP_NAME)
        self._layout.addWidget(self.logo)
        self._layout.addSpacing(6)
        self._layout.addStretch(1)
        # Modulos tras el sello y su espacio; acciones despues del hueco.
        self._top_count = 2
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        self._labels: dict[str, str] = {}
        self._icons: dict[str, str] = {}
        self._tips: dict[str, str] = {}
        self._badges: set[str] = set()
        self.expanded = False
        self._wanted = False
        # Despues de los atributos: el tema y la paleta repintan los iconos.
        set_kind(self, Kind.SIDEBAR)
        self.refresh_theme()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._apply_wanted)
        self._animation = QPropertyAnimation(self, b"geometry", self)
        self._animation.setDuration(ANIMATION_MS)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.finished.connect(self._on_animation_finished)
        self.resize(COLLAPSED_WIDTH, parent.height())

    # -- API publica -------------------------------------------

    def add_module(self, module_id: str, label: str, icon: str, tooltip: str) -> QPushButton:
        button = self._new_button(module_id, label, icon, tooltip)
        button.setCheckable(True)
        self._group.addButton(button)
        button.clicked.connect(lambda _=False, mid=module_id: self.module_chosen.emit(mid))
        self._layout.insertWidget(self._top_count, button)
        self._top_count += 1
        return button

    def add_action(
        self, action_id: str, label: str, icon: str, callback: Callable[[], None]
    ) -> QPushButton:
        """Boton de abajo que no cambia de modulo (p. ej. el tema)."""
        button = self._new_button(action_id, label, icon, label)
        button.clicked.connect(lambda _=False: callback())
        self._layout.addWidget(button)
        return button

    def set_item(self, item_id: str, label: str, icon: str) -> None:
        """Cambia rotulo, ayuda e icono de un boton (el del tema al rotar)."""
        if item_id not in self.buttons:
            return
        self._labels[item_id] = label
        self._icons[item_id] = icon
        self._tips[item_id] = label
        self.buttons[item_id].setToolTip(label)
        self.buttons[item_id].setAccessibleName(label)
        self._paint_button(item_id)

    def set_badge(self, item_id: str, marked: bool, note: str = "") -> None:
        """Punto en el icono si hay algo pendiente; ``note`` se suma a la ayuda."""
        if item_id not in self.buttons:
            return
        if marked:
            self._badges.add(item_id)
        else:
            self._badges.discard(item_id)
        tip = self._tips[item_id]
        self.buttons[item_id].setToolTip(f"{tip}\n{note}" if note else tip)
        self._paint_button(item_id)

    def refresh_theme(self) -> None:
        """Colores del tema aplicado: fondo, sombra, sello e iconos."""
        self.setPalette(sidebar_palette(self.palette()))
        self._shadow.setColor(shadow_color())
        self.logo.setPixmap(seal_pixmap(LOGO_SIZE, on_dark=True))
        for item_id in self.buttons:
            self._paint_button(item_id)

    def place(self, x: int, y: int, height: int) -> None:
        """La coloca en la ventana; el ancho es el del estado (plegada o desplegada)."""
        self._animation.stop()
        width = EXPANDED_WIDTH if self.expanded else COLLAPSED_WIDTH
        self.setGeometry(x, y, width, height)
        self.raise_()

    def set_expanded(self, expanded: bool) -> None:
        self._wanted = expanded
        self._timer.stop()
        self._apply_wanted()

    # -- Eventos -----------------------------------------------

    def enterEvent(self, event) -> None:  # noqa: N802 (nombre impuesto por Qt)
        self._schedule(True, EXPAND_DELAY_MS)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 (nombre impuesto por Qt)
        self._schedule(False, COLLAPSE_DELAY_MS)
        super().leaveEvent(event)

    def changeEvent(self, event) -> None:  # noqa: N802 (nombre impuesto por Qt)
        # Tema claro u oscuro: los iconos se vuelven a dibujar con los colores nuevos.
        if event.type() == QEvent.Type.PaletteChange:
            for item_id in self.buttons:
                self._paint_button(item_id)
        super().changeEvent(event)

    # -- Ayudantes ---------------------------------------------

    def _new_button(self, item_id: str, label: str, icon: str, tooltip: str) -> QPushButton:
        button = QPushButton()
        button.setToolTip(tooltip)
        button.setAccessibleName(label)
        button.setMinimumHeight(BUTTON_HEIGHT)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.buttons[item_id] = button
        self._labels[item_id] = label
        self._icons[item_id] = icon
        self._tips[item_id] = tooltip
        self._paint_button(item_id)
        return button

    def _schedule(self, expanded: bool, delay_ms: int) -> None:
        self._wanted = expanded
        self._timer.start(delay_ms)

    def _apply_wanted(self) -> None:
        if self._wanted == self.expanded:
            return
        self.expanded = self._wanted
        if self.expanded:
            self.raise_()
            for item_id in self.buttons:
                self._paint_button(item_id)
        start = self.geometry()
        width = EXPANDED_WIDTH if self.expanded else COLLAPSED_WIDTH
        self._animation.stop()
        self._animation.setStartValue(start)
        self._animation.setEndValue(QRect(start.x(), start.y(), width, start.height()))
        self._animation.start()

    def _on_animation_finished(self) -> None:
        # Los rotulos se quitan al terminar de plegarse, no antes (no saltan).
        if not self.expanded:
            for item_id in self.buttons:
                self._paint_button(item_id)

    def _paint_button(self, item_id: str) -> None:
        button = self.buttons[item_id]
        running = getattr(self, "_animation", None)
        animating = running is not None and running.state() == QPropertyAnimation.State.Running
        button.setText(f"  {self._labels[item_id]}" if self.expanded or animating else "")
        # La paleta propia de la barra, no la del boton: la hoja de estilo, al pulir el
        # marco, le devuelve el texto de la app y los iconos quedaban apagados.
        palette = sidebar_palette(self.palette())
        dot = tone_color(Tone.WARNING) if item_id in self._badges else None
        button.setIcon(glyph_icon(self._icons[item_id], palette, ICON_SIZE, dot))
        button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
