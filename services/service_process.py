"""Lanza y termina los comandos que llegan por el canal, segun el sistema.

En Linux corren con sh en su propio grupo de procesos; al cancelar se manda
SIGTERM al grupo y, si no sale, SIGKILL. En Windows corren en PowerShell
desde un .ps1 temporal (con -EncodedCommand los errores llegarian en XML),
que se borra solo al arrancar (con un error de sintaxis no arranca: release
lo borra al terminar); al cancelar, taskkill termina todo el arbol.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import tempfile
from pathlib import Path

from logic._00_logic_platform import (
    WINDOWS_FLAGS,
    is_windows,
    powershell_file_args,
    powershell_script,
    taskkill_args,
)

# Tiempo que se le da a un comando cancelado para salir antes de SIGKILL.
TERM_GRACE_S = 2.0

# pid -> .ps1 de cada comando de Windows, hasta que release lo suelte.
_scripts: dict[int, Path] = {}

_PIPES = {
    "stdin": asyncio.subprocess.PIPE,
    "stdout": asyncio.subprocess.PIPE,
    "stderr": asyncio.subprocess.PIPE,
}


def write_script(command: str, folder: str | None = None) -> Path:
    """Guarda el guion de PowerShell en un .ps1 temporal (UTF-8 con BOM, el que lee 5.1)."""
    fd, name = tempfile.mkstemp(prefix="molink-", suffix=".ps1", dir=folder)
    with os.fdopen(fd, "w", encoding="utf-8-sig", newline="\r\n") as file:
        file.write(powershell_script(command))
    return Path(name)


async def spawn(command: str) -> asyncio.subprocess.Process:
    """Lanza command con el shell del sistema: sh en Linux, PowerShell en Windows."""
    if not is_windows():
        return await asyncio.create_subprocess_shell(command, start_new_session=True, **_PIPES)
    script = write_script(command)
    try:
        child = await asyncio.create_subprocess_exec(
            *powershell_file_args(str(script)), creationflags=WINDOWS_FLAGS, **_PIPES
        )
    except OSError:
        script.unlink(missing_ok=True)
        raise
    _scripts[child.pid] = script
    return child


def release(child: asyncio.subprocess.Process) -> None:
    """Borra el .ps1 del comando si quedo (el guion no llego a correr); ya salio."""
    script = _scripts.pop(child.pid, None)
    if script is not None:
        with contextlib.suppress(OSError):
            script.unlink(missing_ok=True)


async def terminate(child: asyncio.subprocess.Process) -> None:
    """Termina el comando y todo lo que lanzo; vuelve cuando ya salio."""
    if is_windows():
        with contextlib.suppress(OSError):
            killer = await asyncio.create_subprocess_exec(
                *taskkill_args(child.pid),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                creationflags=WINDOWS_FLAGS,
            )
            await killer.wait()
        await child.wait()
        return
    for signum in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(child.pid, signum)
        except ProcessLookupError:
            break
        try:
            await asyncio.wait_for(child.wait(), TERM_GRACE_S)
            break
        except TimeoutError:
            continue
    await child.wait()
