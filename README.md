# YT-MP3 Studio

Aplicación de escritorio para Windows que busca varios resultados en YouTube, permite seleccionar vídeos y administra su descarga y conversión a MP3. Incluye cola persistente con pausa, reanudación, cancelación y reintentos; biblioteca local organizada mediante carpetas, importación de playlists exportadas por Exportify, reproductor integrado y temas claro/oscuro.

## Playlists de Spotify mediante Exportify

La pantalla **Playlists** no necesita la contraseña ni un token de Spotify:

1. Pulsa **Abrir Exportify**, inicia sesión en Spotify y usa **Export All**.
2. Pulsa **Importar ZIP o CSV** y selecciona `spotify_playlists.zip`.
3. Revisa las playlists y pulsa **Descargar / sincronizar**.

La aplicación busca primero `Canción + Artista` y examina una tanda pequeña de resultados. Solo amplía el número de candidatos cuando esa primera búsqueda no contiene una coincidencia fiable. Compara título, cantante y duración, y descarta automáticamente coincidencias poco fiables o variantes no solicitadas como directos, karaoke, covers o remixes. Los fallos no detienen el lote y quedan en `errores.csv`.

Los audios se guardan una sola vez en `Audio`; las carpetas bajo `Playlists` usan enlaces físicos NTFS para mostrar el mismo archivo sin duplicar espacio. `playlist.m3u8` conserva el orden original. Una nueva importación sincroniza la lista, conserva lo ya descargado y pone en cola solo lo pendiente. **Detener descargas** cancela los trabajos pendientes o activos de esa playlist y devuelve sus canciones a estado pendiente para poder reanudarlas después. **Cambiar versión** busca alternativas distintas a la descarga actual para que el usuario elija cuál sustituirá el archivo en todas las playlists que comparten la canción.

Exportify no incluye las portadas en el ZIP. Para conservar la imagen exacta, selecciona **Elegir portada** en cada playlist; se normaliza y guarda como `cover.jpg`.

## Requisitos

- Windows 10/11 de 64 bits.
- Python 3.11 o posterior para desarrollo (el instalador no requiere Python).
- `ffmpeg`: para desarrollo puede estar en `PATH` o en `tools\ffmpeg.exe`. El build incluye automáticamente ese archivo opcional si existe; no lo descarga.
- Conexión a Internet para búsquedas y descargas.

`yt-dlp` se instala como dependencia Python y queda incluido en el bundle. Ni la aplicación ni los scripts actualizan `yt-dlp` o `ffmpeg` automáticamente.

## Instalación para usuarios

Ejecuta `YT-MP3-Studio-0.1.0-Setup.exe` y sigue el asistente. Es una instalación por usuario en `%LOCALAPPDATA%\Programs\YT-MP3 Studio` y no requiere permisos de administrador.

Si el instalador fue construido sin `tools\ffmpeg.exe`, instala `ffmpeg` por tu cuenta y asegúrate de que `ffmpeg.exe` esté accesible mediante `PATH`. La pantalla Configuración muestra el estado detectado de ambas dependencias.

Los datos no se guardan dentro de la instalación:

- Base de datos: `%LOCALAPPDATA%\YT-MP3 Studio\ytmp3studio.db`
- Logs: `%LOCALAPPDATA%\YT-MP3 Studio\logs\app.log`
- Música: la carpeta elegida en Configuración; por defecto, `%USERPROFILE%\Music\YT-MP3 Studio`

Desinstalar el programa conserva la biblioteca, la base de datos, los logs y los MP3 del usuario.

## Aplicación web local para PC

Puedes usar YT-MP3 Studio en el navegador sin instalar ni abrir el archivo `.exe`: haz doble clic en `ABRIR-YT-MP3-STUDIO-WEB.cmd`. Se abrirá `http://127.0.0.1:8766` y esa ventana debe mantenerse abierta mientras uses la aplicación.

La web usa el mismo motor de búsqueda, cola, descargas y biblioteca que la aplicación Windows. El servidor se limita a `127.0.0.1`, así que solo es accesible desde ese mismo PC: no se abre ningún puerto del router ni se publica tu biblioteca en GitHub. Requiere el repositorio y Python/dependencias instalados (por ejemplo, la carpeta `.venv` de desarrollo).

### Usar la web desde el iPhone en la misma WiFi

Si quieres abrir la misma web desde el iPhone (u otro dispositivo) sin salir de tu red doméstica, usa `ABRIR-YT-MP3-STUDIO-WIFI.cmd` en lugar del anterior. Al arrancar, la consola muestra una dirección del tipo `http://192.168.1.x:8766`; ábrela en Safari desde el iPhone conectado a la misma WiFi. No pide clave.

Este modo hace visible el servidor a **cualquier dispositivo de tu red doméstica**, no solo al iPhone: no lo actives en WiFis compartidas con desconocidos (por ejemplo, redes de invitados o lugares públicos). Sigue sin abrir ningún puerto del router.

## iPhone: PWA y Google Drive

La carpeta `prototype/` contiene una PWA instalable desde Safari. La aplicación de Windows busca, descarga y convierte contenido autorizado. La web puede vincular Google Drive desde el PC, convertir las subcarpetas de `YT-MP3 Studio` en playlists y copiar al iPhone las canciones elegidas para reproducirlas sin conexión.

Para instalar la PWA:

1. En GitHub, selecciona **Settings > Pages > GitHub Actions**. El flujo `.github/workflows/deploy-pwa.yml` publica `prototype/` en cada cambio de `main`.
2. Abre `https://gerardferri.github.io/Spotify-Offline/` con Safari.
3. Pulsa **Compartir > Añadir a pantalla de inicio**.

### Sincronizar la música con Google Drive

La aplicación detecta Google Drive para ordenador y lee su carpeta local sincronizada. No necesita credenciales de desarrollador, OAuth ni una API de pago. Consulta [GOOGLE_DRIVE_SETUP.md](GOOGLE_DRIVE_SETUP.md).

1. Abre la web local y entra en **Biblioteca > Google Drive**.
2. La primera sincronización crea o reutiliza `Mi unidad\YT-MP3 Studio`.
3. Añade carpetas y canciones dentro de `YT-MP3 Studio` en Drive.
4. La aplicación sincroniza al abrirse, periódicamente mientras está activa y al pulsar **Sincronizar**.
5. Cada subcarpeta aparece como playlist. Abre una y pulsa **Guardar en iPhone** para conservar canciones offline.

Los MP3 se almacenan en Google Drive y, al guardarlos, se copia una versión a IndexedDB dentro del iPhone. No se suben a GitHub. Safari controla la cuota y puede borrar los datos al limpiar el sitio, así que conviene exportar copias periódicas; estas contienen metadatos y playlists, pero no el audio.

La PWA también funciona como web local completa del PC mediante `ABRIR-YT-MP3-STUDIO-WEB.cmd`; ya no hace falta ejecutar un servidor estático aparte. El service worker solo se registra en un origen seguro o en `localhost`.

## Desarrollo

Desde PowerShell, en la raíz del repositorio:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,build]"
python -m ytmp3studio
```

Como alternativa reproducible para esta versión:

```powershell
python -m pip install -r requirements.lock
$env:PYTHONPATH = "$PWD\src"
python -m ytmp3studio
```

## Tests

La suite normal es determinista y no usa YouTube ni descarga contenido:

```powershell
python -m pytest
```

Las comprobaciones externas, si se añaden o habilitan, se ejecutan manualmente:

```powershell
python -m pytest -m external
```

## Build de producción

El build debe hacerse en Windows. Instala las dependencias y ejecuta:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build.ps1
```

El script ejecuta los tests, crea el bundle PyInstaller `onedir`, comprueba que contiene las migraciones SQLite y lanza un smoke test no interactivo del ejecutable. El resultado queda en:

```text
dist\YT-MP3 Studio\YT-MP3 Studio.exe
```

Para distribuir `ffmpeg` dentro del bundle, coloca previamente un binario compatible y cuya licencia permita la redistribución en:

```text
tools\ffmpeg.exe
```

El script no descarga binarios. Si el archivo no existe, muestra una advertencia y genera igualmente el bundle; en ejecución se buscará `ffmpeg` en `PATH`.

Puedes repetir solo la verificación sobre un bundle existente con:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify.ps1
```

## Generar el instalador

Instala Inno Setup 6 y asegúrate de que `ISCC.exe` esté en `PATH` o en su ubicación estándar. Después ejecuta:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build.ps1 -Installer
```

El instalador se genera en:

```text
dist\installer\YT-MP3-Studio-0.1.0-Setup.exe
```

Antes de publicar, prueba el instalador en una máquina Windows limpia: arranque, diagnóstico de dependencias, búsqueda, una descarga breve de contenido autorizado, reproducción, persistencia tras reinicio y desinstalación.

## Limitaciones conocidas

Consulta [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md). La versión 1 es solo para Windows y MP3; no admite autenticación/cookies, vídeos privados o restringidos por edad ni directos. Las playlists se importan mediante CSV/ZIP de Exportify, no desde una URL de YouTube. YouTube puede cambiar sus extractores y las actualizaciones de herramientas son manuales.

## Aviso legal

Descarga y convierte únicamente contenido propio, de dominio público o para el que tengas autorización. Eres responsable de cumplir los derechos de autor, las condiciones de YouTube y la legislación aplicable. YT-MP3 Studio no elude DRM ni controles de acceso y no está afiliado a YouTube o Google.
