from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MainState(StrEnum):
    INIT = "INIT"  # construyendo la navegación
    NAVIGATION_READY = "NAVIGATION_READY"  # menú listo, sin módulo abierto
    MODULE_ACTIVE = "MODULE_ACTIVE"  # un módulo visible
    MODULE_NOT_FOUND = "MODULE_NOT_FOUND"  # se pidió un id inexistente


@dataclass(frozen=True, slots=True)
class NavigationItem:
    module_id: str
    label: str
    description: str
    admin_only: bool = False
    icon: str = ""  # nombre en Phosphor para la barra lateral


# Registro de módulos, en el orden en que aparecen en el menú.
# new_module.py agrega entradas antes del marcador.
NAVIGATION_ITEMS: tuple[NavigationItem, ...] = (
    NavigationItem(
        module_id="pair",
        label="Emparejar",
        description="Emparejar este equipo con otro de la red local",
        icon="link",
    ),
    NavigationItem(
        module_id="console",
        label="Consola",
        description="Correr comandos en el otro equipo",
        icon="terminal-window",
    ),
    NavigationItem(
        module_id="chat",
        label="Chat",
        description="Mensajes y archivos entre los dos equipos",
        icon="chat-circle-text",
    ),
    # [python-programmer:navigation]
)


class MainLogic:
    """
    MÁQUINA DE ESTADOS - VENTANA PRINCIPAL Y NAVEGACIÓN

    INIT
        -> __init__()                      -> NAVIGATION_READY

    NAVIGATION_READY / MODULE_ACTIVE
        -> open_module(id) [existe]        -> MODULE_ACTIVE
        -> open_module(id) [no existe]     -> MODULE_NOT_FOUND

    MODULE_NOT_FOUND
        -> open_module(id) [existe]        -> MODULE_ACTIVE

    REGLAS
    - Sin PySide6.
    - Los módulos marcados admin_only solo se registran si is_admin=True.
    """

    def __init__(self, is_admin: bool = False) -> None:
        self.state = MainState.INIT
        self.active_module_id = ""
        self._items = [item for item in NAVIGATION_ITEMS if is_admin or not item.admin_only]
        self.state = MainState.NAVIGATION_READY

    # -- API pública -------------------------------------------

    def get_navigation_items(self) -> list[NavigationItem]:
        return list(self._items)

    def get_default_module_id(self) -> str:
        return self._items[0].module_id if self._items else ""

    def open_module(self, module_id: str) -> dict:
        module_id = (module_id or "").strip()
        item = next((i for i in self._items if i.module_id == module_id), None)
        if item is None:
            self.state = MainState.MODULE_NOT_FOUND
            return {
                "ok": False,
                "state": self.state.value,
                "module_id": "",
                "title": "Módulo no encontrado",
                "description": "No existe un módulo registrado con ese identificador.",
            }
        self.active_module_id = item.module_id
        self.state = MainState.MODULE_ACTIVE
        return {
            "ok": True,
            "state": self.state.value,
            "module_id": item.module_id,
            "title": item.label,
            "description": item.description,
        }
