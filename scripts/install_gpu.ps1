param(
    [string]$Cuda = "cu118"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $PythonExe)) {
    throw "Virtual environment not found at $PythonExe. Run from project root: py -3.11 -m venv .venv"
}

if ($Cuda -ne "cu118") {
    throw "Only cu118 is configured for this project. Edit requirements-gpu-cu118.txt if another Paddle wheel is required."
}

Push-Location $ProjectRoot
try {
    & $PythonExe -m pip uninstall -y paddlepaddle
    & $PythonExe -m pip install -r requirements-gpu-cu118.txt
    & $PythonExe scripts\check_cuda.py
}
finally {
    Pop-Location
}
