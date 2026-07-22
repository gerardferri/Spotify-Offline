param(
    [int]$Port = 8766,
    [switch]$Lan
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
    throw "No se ha encontrado Python 3. Instala Python o crea .venv antes de iniciar la aplicacion web."
}

$serverArgs = @("-m", "ytmp3studio.mobile_server", "--web", "--open-browser", "--port", $Port)
if ($Lan) {
    Write-Host "Iniciando YT-MP3 Studio web para este PC y tu misma WiFi..." -ForegroundColor Green
    Write-Host "Cualquier dispositivo en tu misma WiFi podra abrirla sin clave; no se abre ningun puerto en el router." -ForegroundColor Yellow
    $serverArgs += "--lan"
} else {
    Write-Host "Iniciando YT-MP3 Studio web para este PC..." -ForegroundColor Green
    Write-Host "Solo se abrira http://127.0.0.1:$Port; no se abre ningun puerto en el router." -ForegroundColor Cyan
}
& $pythonCommand @pythonArgs @serverArgs
