# ================================================================
#  lab.ps1  -  ABRIR EL NOTEBOOK DEL LABORATORIO
# ================================================================
#      .\lab.ps1
#
#  Se puede correr desde cualquier carpeta: el script se ubica solo.
#  Para cerrar el servidor de Jupyter: Ctrl+C dos veces en esta
#  terminal.
# ================================================================

$raiz = $PSScriptRoot
$jupyter = Join-Path $raiz '.venv\Scripts\jupyter-lab.exe'

if (-not (Test-Path $jupyter)) {
    Write-Host 'Falta el entorno virtual. Corre primero:' -ForegroundColor Yellow
    Write-Host '    .\setup.ps1'
    exit 1
}

# Jupyter se lanza CON LA RAIZ DEL REPO como directorio de trabajo:
# el notebook usa rutas relativas (data/, src/, unity/) y desde otra
# carpeta fallarian.
Set-Location $raiz
& $jupyter 'laboratorio.ipynb'
