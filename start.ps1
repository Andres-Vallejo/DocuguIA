param([int]$Port = 8765)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$envPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $envPython)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el entorno. Instala Python 3.12 o superior.' }
}
& $envPython -m pip install -e .
if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar las dependencias.' }
Write-Host "DocuguIA: http://127.0.0.1:$Port — Ctrl+C para detener"
& $envPython -m uvicorn app.main:app --host 127.0.0.1 --port $Port --no-access-log
