#!/usr/bin/env bash
# Instala Molink en Linux: entorno virtual, dependencias y acceso en el menu.
# No usa sudo ni toca el sistema: todo queda en esta carpeta y en ~/.local/share.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
if ! "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
    echo "Molink necesita Python 3.12 o superior ($PYTHON no sirve)." >&2
    echo "Puedes indicar otro con: PYTHON=python3.12 ./install.sh" >&2
    exit 1
fi

if ! "$PYTHON" -m venv .venv; then
    echo "No se pudo crear el entorno virtual." >&2
    echo "En Debian/Ubuntu/Mint instala el paquete python3-venv y vuelve a intentarlo." >&2
    exit 1
fi

.venv/bin/python -m pip install --upgrade pip
# Solo instala las dependencias de pyproject.toml; el codigo corre desde esta carpeta.
.venv/bin/python -m pip install .
.venv/bin/python main.py --install-launcher

# Qt 6 necesita libxcb-cursor0 para abrir ventanas en X11; solo se avisa.
if command -v ldconfig >/dev/null && ! ldconfig -p | grep -q "libxcb-cursor.so.0"; then
    echo
    echo "Aviso: falta libxcb-cursor0. Si la ventana no abre, instalalo con:"
    echo "  sudo apt install libxcb-cursor0"
fi

echo
echo "Listo. Abre Molink desde el menu de aplicaciones o con:"
echo "  .venv/bin/python main.py"
echo "Si ufw esta activo, el README explica como abrir y cerrar el puerto 47820."
