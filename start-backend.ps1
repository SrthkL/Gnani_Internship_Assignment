param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8010
)

$ErrorActionPreference = 'Stop'
$backendDir = Join-Path $PSScriptRoot 'backend'
$pythonPath = Join-Path $backendDir '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Backend Python was not found at $pythonPath. Restore the backend .venv before starting the API."
}
if (-not (Test-Path -LiteralPath (Join-Path $backendDir '.env'))) {
    throw 'Create backend\.env with DATABASE_URL before starting the API.'
}

Write-Host "Starting FastAPI at http://127.0.0.1:$Port"
Write-Host 'Keep this terminal open. Press Ctrl+C to stop.'

# Resolve imports and local storage from the project, regardless of your shell's folder.
Push-Location $backendDir
try {
    & $pythonPath -m app.init_db
    if ($LASTEXITCODE -ne 0) {
        throw 'Database schema initialization failed. Check the error above.'
    }
    # Windows reload uses a loop that cannot launch our FFmpeg subprocesses.
    & $pythonPath -m uvicorn main:app --app-dir $backendDir --host 127.0.0.1 --port $Port
    if ($LASTEXITCODE -ne 0) {
        throw "FastAPI stopped with exit code $LASTEXITCODE. Check the error above."
    }
} finally {
    Pop-Location
}
