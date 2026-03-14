$ErrorActionPreference = "Stop"

$pythonCandidates = @(
    (Join-Path $PSScriptRoot ".venv312\Scripts\python.exe"),
    (Join-Path $PSScriptRoot ".venv\Scripts\python.exe"),
    (Join-Path $PSScriptRoot ".venv-check\Scripts\python.exe"),
    "$env:LOCALAPPDATA\Python\bin\python.exe"
)

$pythonPath = $pythonCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $pythonPath) {
    throw "No working Python interpreter was found. Create a virtual environment first."
}

& $pythonPath -m bot @args
