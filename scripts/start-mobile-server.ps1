param(
    [int]$Port = 8766,
    [switch]$SkipTailscale
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $projectRoot "src"

$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$pythonArgs = @()
if (Test-Path -LiteralPath $venvPython) {
    $pythonCommand = $venvPython
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonCommand = "py"
    $pythonArgs = @("-3")
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonCommand = "python"
} else {
    throw "No se ha encontrado Python 3. Instala Python o crea .venv antes de iniciar el servidor."
}

if (-not $SkipTailscale) {
    $tailscale = Get-Command tailscale -ErrorAction SilentlyContinue
    if (-not $tailscale) {
        $tailscale = @(
            "$env:ProgramFiles\Tailscale\tailscale.exe",
            "$env:ProgramFiles\Tailscale IPN\tailscale.exe"
        ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    }
    if ($tailscale) {
        Write-Host "Configurando el acceso HTTPS privado de Tailscale..." -ForegroundColor Cyan
        $tailscalePath = if ($tailscale.Source) { $tailscale.Source } else { $tailscale }
        & $tailscalePath serve --bg "http://127.0.0.1:$Port"
        & $tailscalePath serve status
    } else {
        Write-Warning "Tailscale no está instalado o no está en PATH. El servidor solo será accesible desde este PC."
    }
}

Write-Host "Iniciando YT-MP3 Studio para iPhone..." -ForegroundColor Green
& $pythonCommand @pythonArgs -m ytmp3studio.mobile_server --port $Port
