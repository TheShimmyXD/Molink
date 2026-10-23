from __future__ import annotations

import argparse
import logging
import sys

from logging_config import setup_logging

logger = logging.getLogger(__name__)


def install_launcher() -> None:
    """Instala el acceso de Molink en el menu del escritorio o en el menu Inicio."""
    from PySide6.QtWidgets import QApplication

    from logic._00_logic_launcher import ICON_SIZE
    from managers.launcher import install_launcher as write_launcher
    from ui.blocks.logo import seal_pixmap

    # QPixmap necesita una QApplication viva; se guarda en una variable para que no se libere.
    app = QApplication.instance() or QApplication([])
    try:
        write_launcher(seal_pixmap(ICON_SIZE, pixel_ratio=1.0))
    except OSError as exc:
        logger.error("%s", exc)
        sys.exit(1)
    finally:
        del app


def main() -> None:
    parser = argparse.ArgumentParser(prog="molink")
    parser.add_argument(
        "--install-launcher",
        action="store_true",
        help="instala el acceso de Molink en el menu (Linux) o en el menu Inicio (Windows)",
    )
    args = parser.parse_args()
    setup_logging()
    if args.install_launcher:
        install_launcher()
        return
    # Import diferido: el logging queda configurado antes de cargar Qt y los módulos.
    from ui._00_ui_main import run_app

    run_app()


if __name__ == "__main__":
    main()
