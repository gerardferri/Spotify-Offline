# Conectar Google Drive

YT-MP3 Studio puede vincular una cuenta de Google desde la aplicación web que
se ejecuta en el PC. La autorización y los tokens permanecen en el PC; el
iPhone solo consulta el catálogo personal mediante el servidor de la app.

## Preparación en Google Cloud

1. Crea o abre un proyecto en [Google Cloud Console](https://console.cloud.google.com/).
2. Activa **Google Drive API** en **APIs y servicios > Biblioteca**.
3. Configura la pantalla de consentimiento OAuth. Para uso personal puedes
   mantenerla en pruebas y añadir tu propia cuenta como usuario de prueba.
4. Declara los permisos `drive.readonly` y `drive.file`. El primero permite
   detectar archivos que añades manualmente; el segundo permite crear la
   carpeta dedicada cuando todavía no existe.
5. Crea un cliente OAuth de tipo **Aplicación de escritorio** y descarga el
   JSON de credenciales.
6. Renómbralo como `google-client-secret.json` y guárdalo en:

   ```text
   %LOCALAPPDATA%\YT-MP3 Studio\google-client-secret.json
   ```

No subas ese archivo al repositorio ni lo compartas.

## Primera conexión

1. Abre `ABRIR-YT-MP3-STUDIO-WEB.cmd`.
2. En **Biblioteca > Google Drive**, pulsa **Conectar Google Drive**.
3. Completa la autorización en Google.
4. La aplicación crea o reutiliza `YT-MP3 Studio`, recorre sus subcarpetas y
   las muestra como playlists de Drive.

La web vuelve a sincronizar al abrirse, cada cinco minutos mientras permanece
abierta y cuando pulsas **Sincronizar**. Los audios no se copian automáticamente
al iPhone: abre una carpeta y pulsa **Guardar en iPhone** en las canciones que
quieras conservar offline.

## Privacidad y publicación

`drive.readonly` es un permiso restringido. El modo de pruebas sirve para una
cuenta personal, pero Google puede exigir verificación antes de distribuir la
aplicación públicamente. Desconectar Drive revoca la autorización local y borra
el catálogo remoto del PC; nunca elimina las copias offline del iPhone.
