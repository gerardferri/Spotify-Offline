# Memoria de proyecto para Claude

## Propósito de este archivo

Lee este documento completo antes de modificar el proyecto. Es la memoria operativa de YT-MP3 Studio para Claude Code. Complementa `README.md`, `ARCHITECTURE.md`, `GOOGLE_DRIVE_SETUP.md` y `KNOWN_LIMITATIONS.md`; cuando la implementación y la documentación antigua difieran, inspecciona el código y los tests antes de decidir.

## Visión del producto

YT-MP3 Studio debe ser una aplicación musical extremadamente sencilla e intuitiva. El usuario quiere:

1. Buscar una canción o pegar una URL desde la web del PC.
2. Descargar y convertir contenido autorizado a MP3 en el PC.
3. Organizar la música mediante carpetas de Google Drive.
4. Ver esas carpetas automáticamente como playlists en la aplicación.
5. Guardar canciones concretas en el iPhone para escucharlas offline.
6. Usar un reproductor reconocible, con controles claros y una barra de progreso que permita avanzar y retroceder.

La prioridad actual es la **web local para PC y la integración con Google Drive para ordenador**. La aplicación nativa PySide6 sigue existiendo, pero no debe asumirse que es la interfaz principal que el usuario quiere mejorar.

## Contexto actual del equipo

- Sistema principal: Windows.
- Raíz del repositorio: `I:\CODEX\Spotify Offline`.
- Google Drive para ordenador ya está instalado y vinculado.
- Unidad detectada en este PC: `F:\Mi unidad`.
- Carpeta musical acordada: `F:\Mi unidad\YT-MP3 Studio`.
- Puerto de la web local: `8766`.
- URL local: `http://127.0.0.1:8766`.
- Idioma de producto y comunicación con el usuario: español.

No introduzcas OAuth ni Google Cloud como requisito para este equipo. El modo preferido lee la unidad local sincronizada y no cuesta dinero. OAuth/API se conserva únicamente como alternativa para equipos sin Google Drive para ordenador.

## Estado funcional que debe conservarse

- La web local sirve `prototype/` y la API desde el mismo proceso Python.
- El buscador y la descarga remota funcionan mediante la API local.
- La descarga vuelve a estar visible en PC como **Descargar música**, no escondida bajo un nombre ambiguo como “Buscar”.
- Hay accesos desde la cabecera de escritorio, la biblioteca y la navegación.
- La página de descargas muestra la cola del PC.
- El reproductor web tiene reproducción/pausa, anterior/siguiente, repetición, aleatorio y seek mediante slider.
- La barra del reproductor debe permanecer por encima de la navegación inferior y ser visible en pantallas pequeñas.
- La web guarda música offline en IndexedDB; no guardes audio en `localStorage`.
- La integración local de Drive detecta la unidad, crea/reutiliza `YT-MP3 Studio`, escanea carpetas y audio, y las expone como playlists.
- La sincronización de Drive se solicita al iniciar, manualmente y cada cinco minutos mientras la web está activa.
- La integración OAuth/API de Drive sigue disponible como fallback.
- La suite determinista no accede a YouTube ni descarga contenido real.

## Arquitectura real

### Web/PWA

- `prototype/index.html`: estructura de las páginas y controles.
- `prototype/styles.css`: diseño responsive para iPhone y PC.
- `prototype/app.js`: navegación, IndexedDB, reproductor, búsqueda/descargas y Drive.
- `prototype/sw.js`: service worker.
- `prototype/manifest.webmanifest`: instalación como PWA.

La web es JavaScript sin framework ni proceso de build. Mantén esta sencillez salvo que el usuario autorice expresamente una migración.

### Servidor web local

- `src/ytmp3studio/mobile_server.py`: servidor HTTP, API, archivos estáticos y streaming con soporte de `Range`.
- `ABRIR-YT-MP3-STUDIO-WEB.cmd`: acceso principal para el usuario.
- `scripts/start-web-server.ps1`: configura `PYTHONPATH` y arranca el servidor.

Endpoints principales:

- `GET /api/health`
- `GET /api/search?q=...`
- `GET /api/jobs`
- `POST /api/jobs`
- `GET /api/tracks/{id}/audio`
- `GET /api/drive/status`
- `POST /api/drive/connect`
- `POST /api/drive/sync`
- `POST /api/drive/disconnect`
- `GET /api/drive/folders/{id}/tracks`
- `GET /api/drive/files/{id}/audio`

### Google Drive

- `src/ytmp3studio/backend/local_drive_service.py`: modo preferido; detecta y escanea Google Drive para ordenador.
- `src/ytmp3studio/backend/google_drive_service.py`: sincronización mediante Drive API/OAuth como alternativa.
- `src/ytmp3studio/backend/google_drive_client.py`: cliente HTTP/OAuth.
- `src/ytmp3studio/persistence/drive_repository.py`: estado y catálogo persistido.
- `src/ytmp3studio/persistence/migrations/004_google_drive_catalog.sql`: tablas de Drive.

La variable `YTMP3_GOOGLE_DRIVE_ROOT` permite indicar una raíz local explícita durante desarrollo o pruebas. No codifiques la letra `F:` como única posibilidad: la detección debe seguir funcionando en otros equipos.

### Núcleo de escritorio

- `src/ytmp3studio/domain/`: modelos, errores y puertos.
- `src/ytmp3studio/backend/`: búsqueda, cola, descargas, biblioteca, playlists y adaptadores.
- `src/ytmp3studio/persistence/`: SQLite y migraciones.
- `src/ytmp3studio/ui/`: interfaz PySide6.
- `src/ytmp3studio/app.py`: composición de la aplicación nativa.

La UI no debe acceder directamente a SQLite ni ejecutar tareas pesadas en el hilo principal. Conserva las fronteras descritas en `ARCHITECTURE.md`.

## Flujo principal esperado

```text
Web PC → Descargar música → buscar canción/URL → POST /api/jobs
       → cola del PC → yt-dlp + ffmpeg → MP3 terminado
       → biblioteca/carpeta sincronizada de Drive
       → carpeta de Drive aparece como playlist
       → usuario pulsa “Guardar en iPhone”
       → audio se copia a IndexedDB → reproducción offline
```

No afirmes que una descarga terminó o llegó a Drive hasta que el backend lo confirme.

## Principios de interfaz

- Debe entenderse sin instrucciones largas.
- Usa texto claro: **Descargar**, **Sincronizar**, **Guardar en iPhone**, **Reproducir**.
- Los iconos deben ser coherentes y reconocibles; evita emojis como iconografía final cuando exista una alternativa CSS/SVG consistente.
- Ninguna función importante puede depender solo de un icono sin `aria-label` o texto accesible.
- En PC, la acción de descarga debe ser visible sin buscarla en menús secundarios.
- En móvil, no tapes el slider ni el reproductor con la barra de navegación o el safe area.
- Mantén estados de carga, vacío, éxito y error explícitos.
- No muestres errores técnicos crudos como “Load failed” si se puede dar una explicación y una acción en español.
- Conserva foco por teclado, botones reales y atributos ARIA.
- Antes de rediseñar de forma amplia, revisa `design-references/mobile/` y compara con el comportamiento real.

## Comandos de trabajo

Desde PowerShell en la raíz:

```powershell
# Instalar para desarrollo
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,build]"

# Ejecutar aplicación nativa
.\.venv\Scripts\python.exe -m ytmp3studio

# Ejecutar web local
.\ABRIR-YT-MP3-STUDIO-WEB.cmd

# Alternativa sin abrir navegador automáticamente
$env:PYTHONPATH = "$PWD\src"
.\.venv\Scripts\python.exe -m ytmp3studio.mobile_server --web --port 8766

# Tests deterministas
.\.venv\Scripts\python.exe -m pytest -q

# Comprobar JavaScript
node --check .\prototype\app.js

# Comprobar errores de whitespace
git diff --check
```

En este entorno, pytest puede no poder escribir `.pytest_cache`. Si ocurre, usa un `--basetemp` dentro de `output/` y elimina únicamente ese directorio temporal al terminar. Una advertencia de caché no equivale a un fallo de tests.

## Tests relevantes

- `tests/unit/test_web_download_entrypoint.py`: acceso visible a Descargar música.
- `tests/unit/test_web_player.py`: reproductor y slider.
- `tests/unit/test_web_drive.py`: contrato de la web con Drive.
- `tests/unit/test_local_drive_service.py`: detección y escaneo del Drive local.
- `tests/unit/test_google_drive_service.py`: lógica de sincronización API.
- `tests/unit/test_google_drive_client.py`: cliente remoto.
- `tests/unit/test_mobile_server.py`: endpoints y servidor.
- `tests/integration/test_drive_persistence.py`: persistencia del catálogo.

Antes de entregar un cambio web, ejecuta como mínimo `node --check`, los tests relacionados y `git diff --check`. Para cambios transversales, ejecuta toda la suite. La última referencia conocida antes de crear esta memoria es **128 tests superados**.

## Reglas de modificación

1. Inspecciona `git status --short` antes de editar.
2. El árbol de trabajo puede contener cambios de otra sesión o de otro agente. No los descartes, reviertas ni reformatees masivamente.
3. Lee el archivo y los tests relacionados antes de cambiar contratos.
4. Añade o actualiza tests para cada corrección de comportamiento.
5. No uses red real en la suite normal; usa fakes y temporales.
6. No incluyas tokens, secretos OAuth, cookies, música del usuario, bases de datos locales ni rutas privadas nuevas en commits.
7. No edites artefactos generados de `build-update/` o `dist-update/` para implementar funciones; modifica las fuentes.
8. No reconstruyas instaladores salvo petición expresa.
9. No borres archivos de usuario ni pistas para “reparar” una sincronización.
10. Mantén compatibilidad con Windows y rutas que contienen espacios.
11. Usa UTF-8 y conserva el español correcto en la interfaz.
12. Las descargas solo se plantean para contenido propio, autorizado o de dominio público; no añadas mecanismos para eludir DRM, login o restricciones.

## Árbol de trabajo al crear esta memoria

Hay trabajo local deliberadamente no confirmado relacionado con Google Drive, la web y el reproductor. Incluye modificaciones en documentación, `prototype/`, `mobile_server.py`, persistencia de Drive y tests, además del nuevo servicio local de Drive. Trátalo como trabajo válido del usuario/Codex: revisa el diff y continúa encima; no hagas `reset`, `checkout --`, `clean` ni reemplazos globales.

Como esta lista puede quedar obsoleta, `git status --short` es siempre la fuente actual.

## Prioridades siguientes

1. Probar manualmente en la web local el flujo completo de descarga desde PC.
2. Confirmar que el MP3 terminado queda en la carpeta correcta de Google Drive o definir claramente el paso que falta.
3. Validar actualización automática al añadir/quitar carpetas y pistas desde Drive.
4. Pulir el diseño responsive de PC sin degradar iPhone.
5. Sustituir iconos provisionales y mensajes genéricos por controles consistentes.
6. Comprobar el reproductor con audio real: slider visible, seek, anterior/siguiente, repetición y aleatorio.
7. Mantener estados de error accionables cuando el PC, Drive o una pista no estén disponibles.

No des por completada una prioridad únicamente porque exista la interfaz: verifica el comportamiento de extremo a extremo o deja documentado exactamente qué parte falta.

## Forma de colaborar con el usuario

- Responde en español y empieza por el resultado observable.
- El usuario prefiere que avances con autonomía y que organices revisiones especializadas cuando sea útil.
- Si una decisión cambia arquitectura, costes, privacidad o requiere credenciales, explícalo antes de asumirla.
- Para cambios visuales, muestra qué se ha mejorado y cómo comprobarlo.
- Si algo “ya no está”, busca primero si sigue implementado pero quedó oculto, renombrado o tapado por el layout.
- No declares que una función funciona basándote solo en que el botón existe.

## Definition of Done

Una tarea está terminada cuando:

- el comportamiento solicitado existe y es visible;
- los estados de error y vacío siguen siendo comprensibles;
- no se han sobrescrito cambios ajenos;
- los tests pertinentes pasan;
- el JavaScript es sintácticamente válido si se tocó la web;
- `git diff --check` no informa errores;
- se explica al usuario cómo probar el resultado y cualquier limitación real.
