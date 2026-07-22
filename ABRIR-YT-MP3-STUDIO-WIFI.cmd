@echo off
setlocal
title YT-MP3 Studio - Web en tu WiFi
cd /d "%~dp0"
echo.
echo YT-MP3 Studio se abrira en el navegador de este PC.
echo Ademas, cualquier dispositivo en tu misma WiFi (por ejemplo tu iPhone)
echo podra abrirla usando la direccion que se mostrara, SIN necesitar clave.
echo No se abre ningun puerto en el router: solo funciona dentro de tu WiFi.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-web-server.ps1" -Lan
if errorlevel 1 (
  echo.
  echo No se pudo iniciar la aplicacion web.
  pause
)
