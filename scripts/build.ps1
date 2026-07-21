[CmdletBinding()]
param(
    [string]$Python = "python",
    [switch]$SkipTests,
    [switch]$Installer
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$SpecPath = Join-Path $ProjectRoot "packaging\ytmp3studio.spec"
$ExePath = Join-Path $ProjectRoot "dist\YT-MP3 Studio\YT-MP3 Studio.exe"
$OptionalFfmpeg = Join-Path $ProjectRoot "tools\ffmpeg.exe"

Push-Location $ProjectRoot
try {
    & $Python -c "import PyInstaller, PySide6, yt_dlp"
    if ($LASTEXITCODE -ne 0) {
        throw "Faltan dependencias de build. Ejecuta: $Python -m pip install -r requirements.lock"
    }

    if (-not $SkipTests) {
        & $Python -m pytest
        if ($LASTEXITCODE -ne 0) { throw "La suite de tests ha fallado." }
    }

    if (Test-Path -LiteralPath $OptionalFfmpeg) {
        Write-Host "Se incluirá tools\ffmpeg.exe en el bundle."
    } else {
        Write-Warning "No existe tools\ffmpeg.exe. El programa requerirá ffmpeg en PATH."
    }

    & $Python -m PyInstaller --noconfirm --clean $SpecPath
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $ExePath)) {
        throw "PyInstaller no generó el ejecutable esperado: $ExePath"
    }

    & (Join-Path $PSScriptRoot "verify.ps1") -SkipTests
    if ($LASTEXITCODE -ne 0) { throw "La verificación del bundle ha fallado." }

    if ($Installer) {
        $IsccCommand = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
        $IsccCandidates = @(
            if ($IsccCommand) { $IsccCommand.Source }
            "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
            "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
        ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -Unique
        $Iscc = $IsccCandidates | Select-Object -First 1
        if (-not $Iscc) {
            throw "Inno Setup 6 no está instalado o ISCC.exe no está disponible."
        }
        & $Iscc (Join-Path $ProjectRoot "packaging\installer.iss")
        if ($LASTEXITCODE -ne 0) { throw "Inno Setup no pudo generar el instalador." }
    }

    Write-Host "Bundle verificado: $ExePath"
} finally {
    Pop-Location
}
