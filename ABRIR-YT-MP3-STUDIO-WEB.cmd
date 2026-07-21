@echo off
setlocal
title YT-MP3 Studio - Web local
cd /d "%~dp0"
echo.
echo YT-MP3 Studio se abrira en el navegador de este PC.
echo No se comparte con Internet ni abre puertos en el router.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-web-server.ps1"
if errorlevel 1 (
  echo.
  echo No se pudo iniciar la aplicacion web.
  pause
)
