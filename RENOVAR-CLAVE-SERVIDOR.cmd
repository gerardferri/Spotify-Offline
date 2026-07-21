@echo off
setlocal
title YT-MP3 Studio - Renovar clave privada
cd /d "%~dp0"

echo Se eliminara la clave anterior y se generara una nueva.
echo Tendras que copiar la nueva clave en los ajustes del iPhone.
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-mobile-server.ps1" -RegenerateToken

if errorlevel 1 (
    echo.
    echo No se pudo renovar la clave.
    echo Instala y conecta Tailscale antes de intentarlo de nuevo.
    echo.
    pause
)

endlocal
