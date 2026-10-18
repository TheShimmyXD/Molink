"""Cliente SSH de Molink sobre asyncssh.

Se conecta solo con la llave de la app y solo a un servidor cuya llave de
equipo ya conoce: no lee ~/.ssh (ni config, ni known_hosts, ni llaves) y no
usa el ssh-agent del sistema.

stream_command entrega la salida en vivo, trozo a trozo, y se cancela como
cualquier tarea de asyncio (task.cancel()): cierra el canal y el servidor
termina el comando en el otro equipo.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

import asyncssh

from services.service_ssh_server import KEEPALIVE_MISSES, KEEPALIVE_S

CLIENT_USERNAME = "molink"
READ_CHUNK = 4096
STDOUT = "stdout"
STDERR = "stderr"

# Recibe el nombre del flujo (STDOUT o STDERR) y el trozo de bytes recien llegado.
OutputCallback = Callable[[str, bytes], None]


@dataclass
class CommandResult:
    exit_status: int | None
    stdout: bytes
    stderr: bytes


def connect_peer(
    host: str, port: int, client_key: asyncssh.SSHKey, server_host_key: asyncssh.SSHKey
):
    """Conexion al otro equipo; se usa con `async with`."""
    return asyncssh.connect(
        host,
        port,
        username=CLIENT_USERNAME,
        client_keys=[client_key],
        known_hosts=([server_host_key], [], []),
        agent_path=None,
        config=None,
        preferred_auth="publickey",
        keepalive_interval=KEEPALIVE_S,
        keepalive_count_max=KEEPALIVE_MISSES,
    )


async def _forward(reader: asyncssh.SSHReader, name: str, on_output: OutputCallback) -> None:
    while chunk := await reader.read(READ_CHUNK):
        on_output(name, chunk)


async def stream_command(
    conn: asyncssh.SSHClientConnection,
    command: str,
    on_output: OutputCallback,
    stdin: bytes = b"",
) -> int | None:
    """Corre un comando sin PTY, pasa su salida en vivo y devuelve su codigo de salida.

    stdin se le escribe al comando y despues se cierra (fin de entrada); asi
    llega la contrasena de sudo sin pasar por la linea de comando. Si la tarea
    se cancela, cierra el canal antes de propagar la cancelacion.
    """
    process = await conn.create_process(command, encoding=None)
    try:
        if stdin:
            process.stdin.write(stdin)
        process.stdin.write_eof()
        await asyncio.gather(
            _forward(process.stdout, STDOUT, on_output),
            _forward(process.stderr, STDERR, on_output),
        )
        await process.wait_closed()
        return process.exit_status
    finally:
        process.close()


async def run_command(
    host: str,
    port: int,
    client_key: asyncssh.SSHKey,
    server_host_key: asyncssh.SSHKey,
    command: str,
) -> CommandResult:
    """Corre un comando en el otro equipo y devuelve su salida completa."""
    chunks: dict[str, list[bytes]] = {STDOUT: [], STDERR: []}
    async with connect_peer(host, port, client_key, server_host_key) as conn:
        status = await stream_command(conn, command, lambda name, data: chunks[name].append(data))
    return CommandResult(status, b"".join(chunks[STDOUT]), b"".join(chunks[STDERR]))
