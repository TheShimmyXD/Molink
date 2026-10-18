# Changelog

Todos los cambios relevantes de Molink se registran aquí.
Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y versiones
[SemVer](https://semver.org/lang/es/): MAYOR.MENOR.PARCHE.

## [Sin publicar]

### Agregado
- Sello de Molink al inicio del README, en versión para tema claro y oscuro.

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
