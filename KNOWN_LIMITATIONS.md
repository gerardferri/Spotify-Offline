# Limitaciones conocidas

Revisadas en la fase de QA del 20 de julio de 2026.

- La version 1 genera solo MP3 y el artefacto de produccion se dirige solo a Windows.
- No admite autenticacion ni cookies de YouTube, videos privados o restringidos por edad ni directos.
- Exportify no incluye portadas en el ZIP. La portada exacta de una playlist debe elegirse manualmente despues de importarla.
- Los enlaces fisicos de las carpetas de playlists requieren que la biblioteca este en un volumen NTFS. En otros sistemas de archivos se conserva `playlist.m3u8`, pero el audio no puede aparecer dentro de cada carpeta sin duplicarse.
- La seleccion automatica es conservadora, pero los metadatos de YouTube pueden ser ambiguos. Las coincidencias rechazadas quedan para revision y `Cambiar version` permite probar una alternativa.
- YouTube puede cambiar sus extractores. `yt-dlp` y `ffmpeg` se diagnostican con errores visibles, pero su actualizacion es manual.
- Pausa y cancelacion son cooperativas. `ffmpeg` se termina de forma explicita y `yt-dlp` usa hooks y timeout de socket; una llamada externa que ignore ambos puede sobrevivir al plazo de cierre de cinco segundos y finalizar su limpieza en segundo plano.
- Si SQLite falla justo despues de publicar atomicamente el MP3, puede quedar un archivo valido sin registrar en la biblioteca. No se elimina automaticamente para evitar perdida de audio; se puede importar o retirar manualmente.
- Las miniaturas se cargan desde su URL y no se guardan para uso sin conexion.
- La reproduccion MP3 depende de Qt Multimedia y de los codecs disponibles en Windows; debe comprobarse en el smoke test del instalador.
- La calidad seleccionada es un objetivo de transcodificacion y no puede mejorar el audio fuente.
- La suite automatizada es determinista y no accede a YouTube. La compatibilidad real con red, una descarga autorizada y la reproduccion se validan como smoke test manual antes de publicar.
