# Molink

Conecta dos equipos Linux de la misma red local. Se emparejan una vez con un
código de 6 dígitos y, desde cualquiera de los dos:

- **Consola:** corres comandos en el otro equipo y ves la salida en vivo
  (`cd`, historial, `Ctrl+C`, `clear`; `sudo` pide la contraseña en la ventana).
- **Chat:** mensajes y archivos en la misma conversación, con barra de avance.
  Lo que llega queda en `~/Descargas/Molink` (o `~/Downloads/Molink`).

Por debajo es SSH, pero con un servidor propio que vive solo mientras la app
está abierta: no hace falta instalar ni configurar `openssh-server`.

## Qué no toca

- No usa `sudo`, `systemctl` ni `ufw`, y no instala servicios.
- No toca `~/.ssh` ni el `sshd` del sistema.
- Solo acepta equipos emparejados (llave, nunca contraseña) y solo de la red local.
- Al cerrar la ventana el servidor se apaga y el puerto queda libre.
- Todo lo suyo vive en `~/.local/share/molink/` (carpeta 700, llaves 600).

## Requisitos

- Linux con escritorio (probado en Linux Mint y Ubuntu).
- Python 3.12 o superior con `venv` (en Debian/Ubuntu/Mint: `python3-venv`).
- Los dos equipos en la misma red local.

## Instalación

```bash
git clone https://github.com/TheShimmyXD/Molink.git
cd Molink
./install.sh
```

`install.sh` crea `.venv/` dentro de la carpeta, instala las dependencias y
deja Molink en el menú de aplicaciones. Hazlo en los dos equipos.

Para abrirlo sin el menú:

```bash
.venv/bin/python main.py
```

## Primer uso

1. Abre Molink en los dos equipos.
2. En uno, **Emparejar → Mostrar mi código**; en el otro, escribe ese código.
   El código dura 2 minutos y solo sirve una vez.
3. Listo: la línea al pie dice «Conectado a ...». Si la red se corta,
   reintenta sola cada 5 s.

## Si ufw está activo

Molink no abre puertos en el cortafuegos: eso lo decides tú. Mira si está activo:

```bash
sudo ufw status
```

Si dice `Status: active`, el equipo necesita dejar entrar estos puertos
**solo desde tu red local**:

| Puerto | Para qué |
|---|---|
| `47820/tcp` | El canal (consola y chat). Siempre. |
| `47821/tcp` | El emparejamiento, solo mientras se muestra el código. |

Tu red sale de `ip -4 route` (la línea sin `default`, por ejemplo
`192.168.1.0/24`). Con ella:

```bash
sudo ufw allow from 192.168.1.0/24 to any port 47820:47821 proto tcp
```

Para cerrarlos otra vez (la misma orden con `delete`):

```bash
sudo ufw delete allow from 192.168.1.0/24 to any port 47820:47821 proto tcp
```

La búsqueda del otro equipo usa mDNS (`5353/udp`); con la configuración por
defecto de ufw no necesita regla.

## Desinstalar

```bash
rm ~/.local/share/applications/Molink.desktop
rm ~/.local/share/icons/hicolor/256x256/apps/Molink.png
rm -r ~/.local/share/molink     # olvida la identidad y los emparejados
```

y borra la carpeta del proyecto. Si abriste el puerto en ufw, ciérralo como
arriba.

## Desarrollo

```bash
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/ruff format .      # formatea el código
.venv/bin/ruff check .       # revisa errores y estilo
.venv/bin/pytest             # ejecuta los tests
```

Sin ventana, `services/service_console.py` hace lo mismo desde la terminal
(`serve`, `pair`, `run`, `peers`; ver `--help`).

## Glosario de dominio

Términos del proyecto y su nombre en el código (el código va en inglés).

| Español | Inglés (código) |
|---|---|
| equipo | peer |
| emparejar | pair |
| emparejados | paired |
| enlace | link |
| carpeta de llegada | inbox |
| identidad | identity |

## Licencia

MIT. Ver `LICENSE`.
