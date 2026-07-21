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

## Biblioteca offline para iPhone (PWA)

La carpeta `prototype/` contiene una aplicaciÃ³n web instalable e independiente de la aplicaciÃ³n de Windows. Es una biblioteca personal: importa archivos de audio desde **Archivos**, guarda una copia dentro del almacenamiento local de Safari y permite reproducirlos sin conexiÃ³n. No busca ni descarga contenido de Internet.

Para usarla en un iPhone:

1. Publica el repositorio en GitHub y, en **Settings > Pages**, selecciona **GitHub Actions** como fuente. El flujo `.github/workflows/deploy-pwa.yml` publicarÃ¡ `prototype/` en cada cambio de `main`.
2. Abre la URL de GitHub Pages con Safari en el iPhone.
3. Usa **Compartir > AÃ±adir a pantalla de inicio**. La primera carga necesita Internet; despuÃ©s la interfaz funciona sin conexiÃ³n.
4. Importa tus MP3 u otros audios desde el botÃ³n `+`. Haz una copia desde **Exportar copia** con regularidad. La copia contiene playlists y metadatos, no los archivos de audio; vuelve a importar los audios antes de restaurarla para asociarlos por huella.

Los audios y playlists no se suben a GitHub Pages ni a ningÃºn servidor. Safari controla su cuota y puede borrar los datos al limpiar el sitio, por lo que el respaldo manual es importante.

Para probarla localmente:

```powershell
python -m http.server 8765 --directory prototype
```

Abre `http://localhost:8765`. El service worker solo se registra en un origen seguro o en `localhost`; para instalarla en el iPhone se necesita la URL HTTPS de GitHub Pages.

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
