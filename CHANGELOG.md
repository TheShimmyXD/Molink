# Changelog

Todos los cambios relevantes de Molink se registran aquí.
Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y versiones
[SemVer](https://semver.org/lang/es/): MAYOR.MENOR.PARCHE.

## [Sin publicar]

## [0.2.0] - 2026-10-23

### Agregado
- Windows 11: Molink conecta un equipo Linux con uno Windows 11, con chat, archivos y
  consola en los dos sentidos. Probado entre una laptop Linux y un PC con Windows 11.
- Datos en `%LOCALAPPDATA%\Molink` y descargas en `~\Downloads\Molink`; interfaces de red
  con ifaddr; el anuncio dice el sistema de cada equipo (`os`). Un equipo con 0.1.0 se
  toma como Linux.
- Hacia Windows, la consola corre en PowerShell: carpeta de trabajo, historial, salida en
  UTF-8 y el código de salida como en `sh`; Cancelar termina todo el árbol de procesos.
  `sudo` no aplica en Windows y la consola lo explica.
- `install.ps1`: entorno virtual, dependencias y acceso directo en el menú Inicio, sin
  administrador. README con la sección de Windows y su cortafuegos.
- Sello de Molink al inicio del README, en versión para tema claro y oscuro.

### Corregido
- En Windows llegaban mal los archivos: el servidor SFTP no convertía las rutas `/C:/...`.
- El `.ps1` temporal de un comando se borra al terminar, también si tenía un error.
- Los iconos de la interfaz no se veían en Windows: la fuente Phosphor va en TTF.

## [0.1.0] - 2026-10-18

Primera versión pública.

### Agregado
- Servidor SSH propio (asyncssh) que vive solo con la app abierta: solo llaves
  emparejadas y solo la red local, sin `sudo` ni `openssh-server`.
- Emparejamiento con un código de 6 dígitos (SPAKE2), que dura 2 minutos y sirve una vez,
  y búsqueda del otro equipo en la red local (mDNS).
- Consola: comandos en el otro equipo con salida en vivo, `cd`, historial, `Ctrl+C`,
  `clear` y `sudo` con la contraseña en la ventana.
- Chat con archivos en la misma conversación y barra de avance; lo recibido queda en
  `~/Descargas/Molink`.
- Línea de conexión al pie de la ventana y reconexión sola cada 5 s si la red se corta.
- Temas claro y oscuro.
- `install.sh`: entorno virtual, dependencias y lanzador en el menú de aplicaciones.
