# Instala Molink en Windows: entorno virtual, dependencias y acceso en el menu Inicio.
# No pide administrador ni toca el sistema: todo queda en esta carpeta, en
# %LOCALAPPDATA%\Molink y en el menu Inicio del usuario.
# Uso: powershell -ExecutionPolicy Bypass -File .\install.ps1
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

# Python a usar: $env:PYTHON, el lanzador py o python, en ese orden.
if ($env:PYTHON) {
    $python = @($env:PYTHON)
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $python = @('py', '-3')
} else {
    $python = @('python')
}
$exe = $python[0]
$pyArgs = @($python | Select-Object -Skip 1)

& $exe @pyArgs -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Molink necesita Python 3.12 o superior ($($python -join ' ') no sirve)."
    Write-Host 'Instalalo desde python.org o indica otro con: $env:PYTHON = "C:\ruta\python.exe"'
    exit 1
}

& $exe @pyArgs -m venv .venv
if ($LASTEXITCODE -ne 0) {
    Write-Host 'No se pudo crear el entorno virtual.'
    exit 1
}

$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { exit 1 }
# Solo instala las dependencias de pyproject.toml; el codigo corre desde esta carpeta.
& $venvPython -m pip install .
if ($LASTEXITCODE -ne 0) { exit 1 }
& $venvPython main.py --install-launcher
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host ''
Write-Host 'Listo. Abre Molink desde el menu Inicio o con:'
Write-Host '  .venv\Scripts\pythonw.exe main.py'
Write-Host 'Si el otro equipo no te encuentra, el README explica el cortafuegos de Windows.'
