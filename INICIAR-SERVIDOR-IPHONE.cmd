@echo off
setlocal
title YT-MP3 Studio - Servidor privado para iPhone
cd /d "%~dp0"

echo =====================================================
echo   YT-MP3 Studio - Servidor privado para iPhone
echo =====================================================
echo.
echo Este servidor NO abre puertos en el router.
echo Solo escucha dentro de este PC y Tailscale lo comparte
echo de forma privada con tus dispositivos autorizados.
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-mobile-server.ps1"

if errorlevel 1 (
    echo.
    echo No se pudo iniciar el servidor.
    echo Comprueba que Python y Tailscale esten instalados.
    echo.
    pause
)

endlocal
