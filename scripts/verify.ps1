[CmdletBinding()]
param(
    [string]$Python = "python",
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BundleRoot = Join-Path $ProjectRoot "dist\YT-MP3 Studio"
$ExePath = Join-Path $BundleRoot "YT-MP3 Studio.exe"
$MigrationPath = Join-Path $BundleRoot "_internal\ytmp3studio\persistence\migrations\001_initial.sql"

Push-Location $ProjectRoot
try {
    if (-not $SkipTests) {
        & $Python -m pytest
        if ($LASTEXITCODE -ne 0) { throw "La suite de tests ha fallado." }
    }
    if (-not (Test-Path -LiteralPath $ExePath)) {
        throw "No existe el ejecutable: $ExePath"
    }
    if (-not (Test-Path -LiteralPath $MigrationPath)) {
        throw "El bundle no contiene la migración SQLite inicial."
    }

    $Process = Start-Process -FilePath $ExePath -ArgumentList "--smoke-test" -WorkingDirectory $env:TEMP -PassThru
    if (-not $Process.WaitForExit(30000)) {
        Get-Process -ErrorAction SilentlyContinue | Where-Object {
            try { $_.Path -eq $ExePath } catch { $false }
        } | Stop-Process -Force -ErrorAction SilentlyContinue
        throw "El smoke test no terminó por sí solo en 30 segundos; sus procesos fueron detenidos."
    }
    $SmokeExitCode = $Process.ExitCode
    if ($SmokeExitCode -ne 0) {
        throw "El smoke test del ejecutable terminó con código $SmokeExitCode."
    }
    Write-Host "Tests estructurales y smoke test correctos."
} finally {
    Pop-Location
}
