$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$env:FG_DEVICE = if ($env:FG_DEVICE) { $env:FG_DEVICE } else { "auto" }
Push-Location $ProjectRoot
try {
    & $PythonExe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
}
finally {
    Pop-Location
}
