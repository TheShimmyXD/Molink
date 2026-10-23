<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/logo-dark.png">
    <img src="docs/logo-light.png" alt="Sello de Molink" width="128">
  </picture>
</p>

# Molink

Conecta dos equipos de la misma red local (Linux con Linux, o Linux con
Windows 11). Se emparejan una vez con un código de 6 dígitos y, desde
cualquiera de los dos:

- **Consola:** corres comandos en el otro equipo y ves la salida en vivo
  (`cd`, historial, `Ctrl+C`, `clear`; `sudo` pide la contraseña en la ventana).
  Hacia Windows los comandos corren en PowerShell.
- **Chat:** mensajes y archivos en la misma conversación, con barra de avance.
  Lo que llega queda en `~/Descargas/Molink` (o `~/Downloads/Molink`).

Por debajo es SSH, pero con un servidor propio que vive solo mientras la app
está abierta: no hace falta instalar ni configurar `openssh-server`.

## Qué no toca

- No usa `sudo`, `systemctl` ni `ufw`, y no instala servicios.
- No toca `~/.ssh` ni el `sshd` del sistema.
- Solo acepta equipos emparejados (llave, nunca contraseña) y solo de la red local.
- Al cerrar la ventana el servidor se apaga y el puerto queda libre.
- Todo lo suyo vive en `~/.local/share/molink/` (carpeta 700, llaves 600); en
  Windows, en `%LOCALAPPDATA%\Molink`. Tampoco pide administrador.

## Requisitos

- Linux con escritorio (probado en Linux Mint y Ubuntu) o Windows 11.
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

### En Windows 11

En PowerShell (sin administrador), con [Git](https://git-scm.com) y Python 3.12
o superior de [python.org](https://www.python.org):

```powershell
git clone https://github.com/TheShimmyXD/Molink.git
cd Molink
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

`-ExecutionPolicy Bypass` vale solo para esa orden: Windows no deja correr
guiones descargados por defecto y así no hace falta cambiar su política.
Si tu `python` es otro más viejo (por ejemplo, el de Anaconda), el instalador
se detiene; indícale el de python.org antes de correrlo:

```powershell
$env:PYTHON = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
```

`install.ps1` crea `.venv\` dentro de la carpeta, instala las dependencias y
deja Molink en el menú Inicio. Para abrirlo sin el menú:

```powershell
.venv\Scripts\pythonw.exe main.py
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

## Cortafuegos de Windows

La primera vez que Molink abre el puerto, Windows pregunta si deja entrar a
Python. Marca solo **Redes privadas** y acepta. La red de casa tiene que estar
como privada: en una red pública Windows bloquea todo lo que entra. Míralo con:

```powershell
Get-NetConnectionProfile
```

(`NetworkCategory : Private`). Si dice `Public`, cámbiala en PowerShell
**como administrador** (con el nombre de tu conexión, `Ethernet` o `Wi-Fi`):

```powershell
Set-NetConnectionProfile -InterfaceAlias "Ethernet" -NetworkCategory Private
```

Si cerraste el aviso o el otro equipo no te encuentra, abre solo lo que usa
Molink y solo para la red local con dos reglas propias, también como
administrador: los puertos del canal y del emparejamiento, y mDNS para la
búsqueda (la regla «mDNS (UDP de entrada)» que trae Windows es solo para el
propio Windows, no para Python):

```powershell
New-NetFirewallRule -DisplayName "Molink" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 47820,47821 -RemoteAddress LocalSubnet -Profile Private
New-NetFirewallRule -DisplayName "Molink mDNS" -Direction Inbound -Action Allow -Protocol UDP -LocalPort 5353 -RemoteAddress LocalSubnet -Profile Private
```

Con ellas ya no hacen falta las reglas que crea el aviso, que dejan entrar a
cualquier programa de Python por cualquier puerto. Si aceptaste el aviso para
redes públicas, puedes desactivarlas (`Enable-NetFirewallRule` las vuelve a
activar):

```powershell
Get-NetFirewallApplicationFilter | Where-Object { $_.Program -like "*\Python3*\python*.exe" } | Get-NetFirewallRule | Disable-NetFirewallRule
```

Para quitar las reglas de Molink:

```powershell
Remove-NetFirewallRule -DisplayName "Molink", "Molink mDNS"
```

## Desinstalar

```bash
rm ~/.local/share/applications/Molink.desktop
rm ~/.local/share/icons/hicolor/256x256/apps/Molink.png
rm -r ~/.local/share/molink     # olvida la identidad y los emparejados
```

y borra la carpeta del proyecto. Si abriste el puerto en ufw, ciérralo como
arriba.

En Windows, en PowerShell:

```powershell
Remove-Item "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Molink.lnk"
Remove-Item -Recurse "$env:LOCALAPPDATA\Molink"   # identidad, emparejados e icono
```

y borra la carpeta del proyecto. Si creaste las reglas del cortafuegos,
quítalas como arriba.

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
