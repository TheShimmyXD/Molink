from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from paths import LOG_DIR

# Formato legible: hora, nivel, módulo y mensaje.
_FORMAT = "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Archivo rotativo: 1 MB por archivo, se conservan 5 copias.
_LOG_FILE = LOG_DIR / "app.log"
_MAX_BYTES = 1_000_000
_BACKUP_COUNT = 5

# Bibliotecas que en INFO escriben lo que pasa por el canal (asyncssh: el comando
# remoto). Ningun log lleva contenido del canal: se quedan en WARNING.
QUIET_LOGGERS = ("asyncssh",)

_configured = False


def setup_logging(level: int = logging.INFO, *, to_file: bool = True, force: bool = False) -> None:
    """
    Configura el logging raíz una sola vez.

    Parameters
    ----------
    level   : nivel del logger raíz (por defecto INFO).
    to_file : además de la consola, escribe en resources/logs/app.log (rotativo).
    force   : reconfigura aunque ya se haya inicializado.
    """
    global _configured
    if _configured and not force:
        return

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    file_error: OSError | None = None
    if to_file:
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            handlers.append(
                RotatingFileHandler(
                    _LOG_FILE, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
                )
            )
        except OSError as exc:
            # Sin permisos de escritura: se continúa solo con la consola y se avisa
            # cuando el logging ya esté configurado.
            file_error = exc

    logging.basicConfig(
        level=level, format=_FORMAT, datefmt=_DATE_FORMAT, handlers=handlers, force=force
    )
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(max(level, logging.WARNING))
    _configured = True
    if file_error is not None:
        logging.getLogger(__name__).warning("Log solo en consola: %s", file_error)


def level_from_debug(debug: bool) -> int:
    """Mapea la bandera `debug` de los servicios a un nivel de logging."""
    return logging.DEBUG if debug else logging.INFO
