$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $ProjectRoot
try {
    py -3.11 -m http.server 5173 -d frontend
}
finally {
    Pop-Location
}
