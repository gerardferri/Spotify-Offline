param(
    [int]$Port = 8766,
    [switch]$SkipTailscale,
    [switch]$RegenerateToken
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
        throw "Tailscale no está instalado. Instálalo desde https://tailscale.com/download/windows y vuelve a ejecutar el lanzador."
    }
}

if ($RegenerateToken) {
    $tokenPath = Join-Path $env:LOCALAPPDATA "YT-MP3 Studio\mobile-server-token.txt"
    if (Test-Path -LiteralPath $tokenPath) {
        Remove-Item -LiteralPath $tokenPath -Force
    }
    Write-Host "Se generará una clave personal nueva." -ForegroundColor Yellow
}

Write-Host "Iniciando YT-MP3 Studio para iPhone..." -ForegroundColor Green
& $pythonCommand @pythonArgs -m ytmp3studio.mobile_server --port $Port
