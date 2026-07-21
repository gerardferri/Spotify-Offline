# YT-MP3 Studio — Arquitectura

## 1. Objetivo y alcance

Aplicación de escritorio para Windows que permite buscar vídeos públicos de YouTube, seleccionar resultados, convertir el audio a MP3, administrar una cola persistente y reproducir la biblioteca local. La aplicación no elude DRM ni controles de acceso y debe mostrar un aviso para que el usuario descargue únicamente contenido para el que tenga derechos o permiso.

Este documento es el contrato de implementación para las fases de backend, frontend, QA y empaquetado. Los cambios incompatibles en señales, modelos o base de datos deberán reflejarse aquí antes de modificar consumidores.

## 2. Stack elegido

### Decisión: PySide6 / Qt 6

- **Aplicación y UI:** Python 3.11+, PySide6 Widgets y Qt Multimedia.
- **Descarga y metadatos:** `yt-dlp` como paquete Python, ejecutado mediante un adaptador aislado.
- **Conversión:** binario `ffmpeg` detectado en `PATH` o distribuido junto a la aplicación.
- **Persistencia:** SQLite 3 mediante `sqlite3`, con migraciones versionadas.
- **Tests:** `pytest`, `pytest-qt` y dobles de prueba para `yt-dlp`/procesos.
- **Build Windows:** PyInstaller, preferentemente `onedir`; instalador mediante Inno Setup.

PySide6 se elige frente a Tauri + React porque el núcleo del producto ya depende del ecosistema Python (`yt-dlp`), SQLite está incluido en la biblioteca estándar y Qt ofrece UI, threading, señales y reproducción multimedia en el mismo runtime. Esto reduce el puente entre procesos/lenguajes, la superficie de empaquetado y los puntos de fallo. Tauri produciría una carcasa potencialmente más ligera, pero obligaría a mantener React/TypeScript, Rust y un sidecar Python o a reimplementar la integración con `yt-dlp`; ese coste no aporta una ventaja suficiente en este proyecto.

## 3. Principios y límites

1. El hilo principal de Qt nunca ejecuta búsquedas, descargas, conversión, consultas pesadas ni comprobaciones de binarios.
2. La UI consume servicios mediante comandos y señales Qt; no accede directamente a SQLite, `yt-dlp`, archivos ni procesos.
3. La cola y su estado se persisten. Al arrancar, un trabajo que quedó `downloading`, `converting`, `pausing` o `cancelling` pasa a `interrupted` y puede reintentarse.
4. Pausar una descarga activa significa detener limpiamente el proceso/adaptador y conservar el `.part`; reanudar crea una nueva ejecución con continuidad habilitada. No se suspende un proceso indefinidamente.
5. Cancelar detiene el trabajo y elimina únicamente temporales pertenecientes a ese trabajo. Un MP3 completado nunca se borra al cancelar.
6. Los errores son datos explícitos y se muestran en la UI; nunca se silencian. Los detalles técnicos completos se escriben en el log.
7. Las actualizaciones de progreso pueden descartarse/coalescerse, pero los cambios de estado no.

## 4. Estructura de carpetas

```text
YT-MP3-Studio/
├── ARCHITECTURE.md
├── README.md
├── pyproject.toml
├── requirements.lock
├── src/
│   └── ytmp3studio/
│       ├── __init__.py
│       ├── __main__.py              # entrada de desarrollo
│       ├── app.py                   # composición/inyección y ciclo Qt
│       ├── domain/
│       │   ├── models.py            # dataclasses/enums compartidos
│       │   ├── errors.py            # AppError y códigos estables
│       │   └── ports.py             # Protocols de repositorios/adaptadores
│       ├── backend/
│       │   ├── facade.py            # contrato único consumido por UI
│       │   ├── search_service.py
│       │   ├── queue_service.py
│       │   ├── library_service.py
│       │   ├── settings_service.py
│       │   ├── dependency_service.py
│       │   ├── workers.py            # QRunnable/QThreadPool
│       │   └── adapters/
│       │       ├── ytdlp_adapter.py
│       │       ├── ffmpeg_adapter.py
│       │       └── media_files.py
│       ├── persistence/
│       │   ├── database.py           # conexiones, transacciones, pragmas
│       │   ├── repositories.py
│       │   └── migrations/
│       │       ├── 001_initial.sql
│       │       └── ...
│       ├── ui/
│       │   ├── main_window.py
│       │   ├── theme.py
│       │   ├── models/               # QAbstractItemModel/proxies
│       │   ├── pages/
│       │   │   ├── search_page.py
│       │   │   ├── queue_page.py
│       │   │   ├── library_page.py
│       │   │   └── settings_page.py
│       │   └── widgets/
│       │       ├── result_card.py
│       │       ├── queue_item.py
│       │       ├── player_bar.py
│       │       └── feedback.py
│       └── resources/
│           ├── resources.qrc
│           ├── icons/
│           └── styles/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── ui/
│   └── fixtures/
├── packaging/
│   ├── ytmp3studio.spec
│   └── installer.iss
└── scripts/
    ├── build.ps1
    └── verify.ps1
```

Los datos de usuario no se escriben en el directorio de instalación:

- Base de datos: `%LOCALAPPDATA%/YT-MP3 Studio/ytmp3studio.db`
- Logs rotativos: `%LOCALAPPDATA%/YT-MP3 Studio/logs/app.log`
- Descargas: carpeta elegida por el usuario; por defecto `%USERPROFILE%/Music/YT-MP3 Studio`
- Temporales: subdirectorio `.ytmp3studio-tmp` dentro de la carpeta de descarga para permitir continuidad en el mismo volumen.

## 5. Capas y responsabilidades

### Dominio

Modelos sin dependencia visual: `SearchResult`, `DownloadRequest`, `DownloadJob`, `LibraryTrack`, `Settings`, `Progress`, `AppError`, `DependencyStatus`. Los identificadores internos son UUID en texto; un resultado de YouTube se identifica además por `video_id`.

### Fachada de backend

`BackendFacade(QObject)` es la única dependencia del frontend. Valida argumentos, agenda trabajos y emite señales. No bloquea. Devuelve un `request_id: str` inmediatamente en operaciones asíncronas para correlacionar respuestas y descartar resultados obsoletos.

### Servicios

- `SearchService`: busca varios resultados, normaliza datos y no encola automáticamente.
- `QueueService`: máquina de estados, planificador, concurrencia, reintentos y progreso.
- `LibraryService`: consulta, filtro, reconciliación básica de archivos y apertura para reproducción.
- `SettingsService`: validación y persistencia de preferencias.
- `DependencyService`: detecta versiones/rutas de `yt-dlp` y `ffmpeg`, y clasifica errores accionables.

### Adaptadores

`YtDlpAdapter` y `FfmpegAdapter` ocultan librerías/procesos externos. En tests se sustituyen por fakes deterministas. `MediaFiles` resuelve nombres seguros, colisiones y limpieza limitada al directorio temporal del trabajo.

### Persistencia

Repositorios con transacciones cortas. Cada thread abre su propia conexión; ninguna conexión SQLite se comparte entre threads. Se activan `PRAGMA foreign_keys=ON`, `journal_mode=WAL` y `busy_timeout=5000`.

## 6. Contrato frontend/backend

No se expone HTTP/WebSocket: al ser un único proceso de escritorio, se usan métodos públicos y señales Qt con objetos de dominio inmutables. Si en el futuro se separa el backend, esta fachada será el límite a adaptar.

### Comandos de `BackendFacade`

| Método | Entrada | Respuesta inmediata | Efecto |
|---|---|---|---|
| `reveal_library_track(track_id)` | UUID | `request_id` | Revela el archivo existente en el Explorador de Windows. |
| `initialize()` | — | `None` | Migra DB, recupera cola y comprueba dependencias. |
| `search(query, limit=12)` | texto no vacío, `1..50` | `request_id` | Busca resultados; una búsqueda nueva no cancela necesariamente la anterior. |
| `enqueue(video_ids, quality_kbps=None)` | lista no vacía | `request_id` | Resuelve metadatos completos y crea uno o varios trabajos. |
| `pause_job(job_id)` | UUID | `request_id` | Pausa un trabajo en espera o solicita parada conservando `.part`. |
| `resume_job(job_id)` | UUID | `request_id` | Devuelve el trabajo pausado/interrumpido a espera. |
| `cancel_job(job_id)` | UUID | `request_id` | Cancela trabajo no terminal y limpia sus temporales. |
| `retry_job(job_id)` | UUID | `request_id` | Reinicia contador y reencola un fallo recuperable o interrumpido. |
| `remove_job(job_id)` | UUID | `request_id` | Oculta/elimina solo trabajos terminales; conserva biblioteca e historial. |
| `list_queue()` | — | `request_id` | Solicita snapshot ordenado de trabajos. |
| `list_library(filter_text="", limit=200, offset=0)` | filtro y paginación | `request_id` | Consulta por título/canal/archivo. |
| `remove_library_track(track_id, delete_file=False)` | UUID, bandera | `request_id` | Quita registro; borrar archivo requiere confirmación previa en UI. |
| `get_settings()` | — | `request_id` | Obtiene configuración efectiva. |
| `update_settings(patch)` | campos parciales | `request_id` | Valida, persiste y reconfigura el planificador/tema. |
| `check_dependencies()` | — | `request_id` | Repite diagnóstico de herramientas. |
| `shutdown()` | — | `None` | Impide nuevos trabajos, persiste estado y detiene workers con plazo acotado. |

### Señales de `BackendFacade`

| Señal | Payload | Garantía |
|---|---|---|
| `initialized(snapshot)` | settings, dependencias, cola | Se emite una vez por inicialización correcta. |
| `search_started(request_id)` | correlación | Antes de resultados/error. |
| `search_succeeded(request_id, results)` | `list[SearchResult]` | Incluye 0..N resultados, nunca solo el primero por diseño. |
| `queue_snapshot(request_id, jobs)` | lista ordenada | Respuesta a `list_queue` o inicialización. |
| `job_added(job)` | `DownloadJob` | Tras commit de DB. |
| `job_updated(job)` | estado/metadatos no ligados al progreso | Tras cambio persistido. |
| `job_progress(progress)` | bytes, total, %, velocidad, ETA, fase | Máximo recomendado: 5 emisiones/segundo/trabajo. |
| `job_completed(job, track)` | trabajo y elemento de biblioteca | Solo después de mover el MP3 y confirmar transacción. |
| `library_snapshot(request_id, tracks, total)` | página y total | Respuesta paginada. |
| `library_changed()` | — | Invalida el snapshot de UI. |
| `settings_changed(settings)` | configuración completa | Después de validación y commit. |
| `dependency_status(request_id, status)` | rutas/versiones/estado | Distingue ausente, anticuado y operativo. |
| `operation_failed(request_id, error)` | `AppError` | Error de comando; siempre correlacionable. |
| `fatal_error(error)` | `AppError` | Fallo no recuperable de inicialización/DB. |

### Formas mínimas de los modelos

```text
SearchResult:
  video_id, webpage_url, title, channel, duration_seconds?, thumbnail_url?,
  availability?, is_live

DownloadJob:
  id, video_id, source_url, title, channel, thumbnail_url?, duration_seconds?,
  quality_kbps, output_dir, state, attempt_count, max_attempts,
  progress_percent?, downloaded_bytes?, total_bytes?, speed_bps?, eta_seconds?,
  error_code?, error_message?, created_at, updated_at

LibraryTrack:
  id, video_id, title, channel, duration_seconds?, thumbnail_url?, source_url,
  file_path, file_size_bytes, quality_kbps, created_at, last_played_at?

Settings:
  download_dir, quality_kbps, theme, concurrency, max_retries,
  retry_base_seconds

AppError:
  code, user_message, technical_message?, recoverable, suggested_action?
```

`duration_seconds`, tamaño total, velocidad y ETA son opcionales porque YouTube no siempre los proporciona. La UI no inventará valores: mostrará “Desconocido” o progreso indeterminado.

### Códigos de error estables

`INVALID_INPUT`, `SEARCH_FAILED`, `NETWORK_ERROR`, `VIDEO_UNAVAILABLE`, `AGE_OR_LOGIN_REQUIRED`, `LIVE_NOT_SUPPORTED`, `YTDLP_MISSING`, `YTDLP_OUTDATED`, `FFMPEG_MISSING`, `FFMPEG_FAILED`, `DOWNLOAD_FAILED`, `PERMISSION_DENIED`, `DISK_FULL`, `FILE_NOT_FOUND`, `DATABASE_ERROR`, `INVALID_STATE`, `CANCELLED`, `INTERNAL_ERROR`.

Los mensajes para usuario son breves y en español; `technical_message` y traceback van al log y no se muestran completos salvo en una vista de detalles.

## 7. Búsqueda y descarga

### Búsqueda

`yt-dlp` se invoca con búsqueda de múltiples entradas (por defecto 12), sin descargar. El adaptador normaliza resultados incompletos, descarta entradas sin `video_id`/URL reproducible, marca directos como no compatibles y conserva el orden devuelto. Un resultado individual defectuoso no invalida toda la lista; un fallo global sí emite `operation_failed`.

### Cola y concurrencia

La cola usa un planificador único protegido por lock y un pool acotado. `concurrency` es configurable entre 1 y 4; cambiarlo afecta nuevas asignaciones y no mata trabajos activos. El orden base es FIFO por `created_at`.

Estados:

```text
queued -> resolving -> downloading -> converting -> completed
   |          |             |              |
   +----------+-------------+--------------+-> failed
   |          |             |
   +----------+-------------+-> pausing -> paused -> queued (resume)
   +----------+-------------+--------------+-> cancelling -> cancelled

Estados recuperados tras cierre inesperado -> interrupted -> queued (retry/resume)
```

Transiciones inválidas producen `INVALID_STATE`. `completed`, `failed` y `cancelled` son terminales; `failed` puede originar un nuevo intento del mismo trabajo si corresponde.

### Reintentos

- Por defecto: 3 intentos totales, configurable mediante `max_retries` como reintentos adicionales (`0..5`).
- Solo para errores recuperables: red, timeout, HTTP transitorio y ciertos fallos de extracción.
- Backoff exponencial: `retry_base_seconds * 2^(attempt-1)`, con jitter pequeño y máximo de 5 minutos.
- No se reintentan automáticamente: cancelación, entrada inválida, vídeo privado/eliminado, login requerido, falta de espacio/permisos, `ffmpeg` ausente o estado inválido.
- El trabajo permanece visible con el próximo intento y el error anterior.

### Archivos y finalización atómica

Cada trabajo posee un directorio temporal identificado por UUID. `yt-dlp` descarga con continuidad y `ffmpeg` produce un archivo temporal. Solo al terminar se mueve atómicamente al destino con un nombre saneado; las colisiones añaden ` (2)`, ` (3)`, etc. Después se insertan/actualizan biblioteca e historial en una transacción. Una reconciliación al inicio detecta archivos registrados que ya no existen.

## 8. Esquema SQLite

Todas las fechas se guardan como ISO-8601 UTC con sufijo `Z`. No se guardan secretos ni cookies en esta versión.

```sql
CREATE TABLE schema_migrations (
    version       INTEGER PRIMARY KEY,
    applied_at    TEXT NOT NULL
);

CREATE TABLE settings (
    key            TEXT PRIMARY KEY,
    value_json     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE TABLE download_jobs (
    id                 TEXT PRIMARY KEY,
    video_id           TEXT NOT NULL,
    source_url         TEXT NOT NULL,
    title              TEXT,
    channel            TEXT,
    thumbnail_url      TEXT,
    duration_seconds   INTEGER CHECK (duration_seconds IS NULL OR duration_seconds >= 0),
    quality_kbps       INTEGER NOT NULL CHECK (quality_kbps IN (128, 192, 256, 320)),
    output_dir         TEXT NOT NULL,
    temp_dir           TEXT NOT NULL,
    state              TEXT NOT NULL CHECK (state IN (
                           'queued','resolving','downloading','converting',
                           'pausing','paused','cancelling','cancelled',
                           'completed','failed','interrupted')),
    attempt_count      INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts       INTEGER NOT NULL CHECK (max_attempts >= 1),
    downloaded_bytes   INTEGER CHECK (downloaded_bytes IS NULL OR downloaded_bytes >= 0),
    total_bytes        INTEGER CHECK (total_bytes IS NULL OR total_bytes >= 0),
    progress_percent   REAL CHECK (progress_percent IS NULL OR
                                    (progress_percent >= 0 AND progress_percent <= 100)),
    error_code         TEXT,
    error_message      TEXT,
    next_retry_at      TEXT,
    created_at         TEXT NOT NULL,
    started_at         TEXT,
    finished_at        TEXT,
    updated_at         TEXT NOT NULL
);

CREATE INDEX idx_download_jobs_state_created
    ON download_jobs(state, created_at);
CREATE INDEX idx_download_jobs_video_id
    ON download_jobs(video_id);

CREATE TABLE library_tracks (
    id                 TEXT PRIMARY KEY,
    job_id             TEXT UNIQUE,
    video_id           TEXT NOT NULL,
    source_url         TEXT NOT NULL,
    title              TEXT NOT NULL,
    channel            TEXT,
    duration_seconds   INTEGER CHECK (duration_seconds IS NULL OR duration_seconds >= 0),
    thumbnail_url      TEXT,
    file_path          TEXT NOT NULL UNIQUE,
    file_size_bytes    INTEGER NOT NULL CHECK (file_size_bytes >= 0),
    quality_kbps       INTEGER NOT NULL,
    created_at         TEXT NOT NULL,
    last_played_at     TEXT,
    FOREIGN KEY (job_id) REFERENCES download_jobs(id) ON DELETE SET NULL
);

CREATE INDEX idx_library_tracks_title ON library_tracks(title COLLATE NOCASE);
CREATE INDEX idx_library_tracks_channel ON library_tracks(channel COLLATE NOCASE);
CREATE INDEX idx_library_tracks_video_id ON library_tracks(video_id);

CREATE TABLE history_events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id         TEXT,
    video_id       TEXT,
    event_type     TEXT NOT NULL CHECK (event_type IN (
                       'enqueued','started','paused','resumed','retry_scheduled',
                       'completed','failed','cancelled','removed')),
    detail_json    TEXT,
    created_at     TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES download_jobs(id) ON DELETE SET NULL
);

CREATE INDEX idx_history_events_created ON history_events(created_at DESC);
CREATE INDEX idx_history_events_job ON history_events(job_id);
```

Valores iniciales de `settings`:

| Clave | Valor |
|---|---|
| `download_dir` | carpeta Música del usuario + `YT-MP3 Studio` |
| `quality_kbps` | `192` |
| `theme` | `"system"` (`system`, `light`, `dark`) |
| `concurrency` | `2` (`1..4`) |
| `max_retries` | `2` (`0..5`) |
| `retry_base_seconds` | `2` (`1..60`) |

La búsqueda no se persiste en v1. Las miniaturas se referencian por URL; no se consideran parte de la biblioteca crítica.

## 9. Dependencias, logging y observabilidad

Al inicializar y antes de la primera descarga se comprueba:

- que el módulo/ejecutable de `yt-dlp` responde y su versión es válida;
- que `ffmpeg -version` responde desde el binario incluido o `PATH`;
- que la carpeta de destino existe o puede crearse y escribirse.

Una versión de `yt-dlp` se considera “posiblemente desactualizada” cuando el propio extractor devuelve su error característico de actualización o cuando una política configurable de antigüedad lo indique; no se bloqueará solo por comparar una versión embebida. La UI ofrece instrucciones, no actualiza silenciosamente el programa empaquetado.

Logging con `RotatingFileHandler`: 5 MiB por archivo, 5 copias, UTF-8. Formato: timestamp UTC, nivel, thread, componente, `request_id`/`job_id` cuando exista y mensaje. Se registran transiciones de estado, intentos, diagnósticos y excepciones; URLs se pueden registrar, pero nunca cookies, tokens ni cabeceras de autenticación.

## 10. Diseño de interfaz

Ventana única con navegación a Búsqueda, Cola, Biblioteca y Configuración; barra inferior de reproducción persistente.

- **Búsqueda:** campo con debounce, botón explícito, skeleton/carga, tarjetas seleccionables con miniatura, título, canal y duración; selección múltiple y CTA “Añadir a cola”. Estado vacío y error con acción de reintentar.
- **Cola:** lista ordenada, fase y progreso en tiempo real, velocidad/ETA si existen, acciones válidas según estado. Los errores se ven junto al trabajo con detalle y reintento cuando procede.
- **Biblioteca:** filtro local solicitado al backend, paginación, título/canal/duración/calidad/ruta, acción reproducir y revelar en Explorador. Si falta el archivo se marca y se permite quitar el registro.
- **Reproductor:** `QMediaPlayer` + `QAudioOutput`, reproducir/pausar, seek, volumen, tiempo actual/total. La reproducción no altera la cola.
- **Configuración:** selector de carpeta, calidad 128/192/256/320 kbps, tema sistema/claro/oscuro, concurrencia 1..4 y reintentos. Validación inline y confirmación de guardado.

Los botones se deshabilitan durante la operación correspondiente, pero la ventana no se congela. El tema y los estados de foco/hover/deshabilitado/error deben ser consistentes y accesibles. Las imágenes remotas fallidas muestran placeholder.

## 11. Estrategia de tests y criterios de aceptación

### Unitarios

- Normalización de 0, 1 y múltiples resultados de búsqueda; metadatos ausentes y error global.
- Todas las transiciones válidas e inválidas de la máquina de estados.
- FIFO, límites de concurrencia y cambio de concurrencia.
- Pausar/reanudar/cancelar, incluyendo limpieza limitada de temporales.
- Reintentos recuperables, backoff y ausencia de reintento para errores permanentes.
- Saneado/colisiones de nombres y mapeo de errores.
- Validación de configuración.

### Integración

- Migración desde DB vacía, CRUD de trabajos/biblioteca/configuración/historial y recuperación tras interrupción.
- Cola con adaptador fake: progreso, finalización atómica, fallo y reintento.
- Diagnóstico con `ffmpeg`/`yt-dlp` ausentes sin que el proceso termine abruptamente.
- Fachada: correlación por `request_id` y señales terminales.

### UI mínima

- Una búsqueda muestra varios resultados y permite selección múltiple.
- Estados de carga, vacío y error son visibles.
- Progreso y acciones de cola reaccionan a señales.
- Filtro de biblioteca, reproductor y configuración no bloquean la UI.

Las pruebas de red reales con YouTube son opcionales y se marcan `external`; no forman parte del conjunto determinista por defecto. Ningún test normal debe descargar contenido real.

Comandos previstos:

```powershell
python -m pytest
python -m pytest -m external  # manual/CI programada
```

## 12. Empaquetado y decisiones operativas

Se genera primero un bundle PyInstaller `onedir`, más fácil de inspeccionar y compatible con plugins multimedia de Qt. El `.spec` incluye plugins Qt necesarios y, si la licencia/distribución lo permite, `ffmpeg.exe`; en caso contrario se documenta su instalación en `PATH`. Inno Setup crea accesos directos, entrada de desinstalación y un instalador por usuario, sin requerir privilegios administrativos.

El build debe ejecutarse y probarse en Windows, no cruzarse desde otro sistema. Antes de crear instalador se ejecutan tests, un smoke test del ejecutable en una máquina limpia/VM y comprobaciones de búsqueda, descarga breve autorizada, reproducción y persistencia.

## 13. Decisiones diferidas y limitaciones aceptadas de v1

- Solo MP3 y solo Windows en el artefacto inicial.
- No hay autenticación de YouTube, cookies, playlists completas ni directos.
- No hay actualización automática de la aplicación, `yt-dlp` ni `ffmpeg`.
- Pausar durante la fase final de conversión puede esperar a un punto seguro o reiniciar esa conversión al reanudar; nunca expone un MP3 parcial como completado.
- El progreso puede ser indeterminado si el servidor no informa el tamaño.
- Qt Multimedia depende de los codecs disponibles; MP3 en Windows soportado debe verificarse en el smoke test.
- La calidad elegida es un objetivo de transcodificación y no mejora la fuente original.

## 14. Definition of Done por fase

1. **Arquitectura:** este documento aceptado antes de código.
2. **Backend:** fachada y servicios implementados; DB migrable; cola persistente y tests críticos verdes.
3. **Frontend:** cuatro vistas y reproductor conectados únicamente a la fachada; estados de carga/error completos.
4. **QA:** revisión contra contratos, pruebas verdes, smoke test y limitaciones documentadas.
5. **Empaquetado:** build reproducible, ejecutable probado, script de instalador y README final.
