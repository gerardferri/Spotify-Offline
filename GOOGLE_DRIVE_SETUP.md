# Google Drive para ordenador

YT-MP3 Studio detecta automáticamente una unidad ya vinculada mediante Google
Drive para ordenador. No necesita OAuth, credenciales de desarrollador ni una
API de pago.

En este equipo la unidad detectada es:

```text
F:\Mi unidad\YT-MP3 Studio
```

La carpeta `YT-MP3 Studio` se crea al realizar la primera sincronización.
Organiza dentro las canciones como quieras:

```text
YT-MP3 Studio/
├── Favoritas/
├── Rock/
└── Viajes/
```

Cada subcarpeta aparecerá automáticamente como playlist.

## Uso

1. Abre `ABRIR-YT-MP3-STUDIO-WEB.cmd`.
2. Entra en **Biblioteca > Google Drive**.
3. La aplicación detectará “Google Drive para ordenador” y sincronizará la
   carpeta automáticamente.
4. Abre una carpeta y pulsa **Guardar en iPhone** en las canciones que quieras
   conservar offline.

La web vuelve a sincronizar al abrirse, cada cinco minutos mientras permanece
abierta y cuando pulsas **Sincronizar**. Los audios no se copian automáticamente
al iPhone: abre una carpeta y pulsa **Guardar en iPhone** en las canciones que
quieras conservar offline.

La aplicación solo lee la carpeta musical mediante el disco virtual de Google.
No recibe contraseñas ni tokens y no modifica otras carpetas de Drive. El PC y
Google Drive para ordenador deben permanecer activos para recibir cambios.

La integración OAuth incluida queda como alternativa para equipos sin Google
Drive para ordenador. Esa modalidad sí requiere un proyecto de Google Cloud y
puede necesitar verificación si se distribuye públicamente.
