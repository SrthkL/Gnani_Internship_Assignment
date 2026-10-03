param(
    [ValidateRange(1, 65535)]
    [int]$Port = 3000
)

$ErrorActionPreference = 'Stop'
$frontendDir = Join-Path $PSScriptRoot 'Frontend'
$npmCandidates = @(
    (Join-Path $env:ProgramFiles 'nodejs\npm.cmd'),
    (Join-Path $env:LOCALAPPDATA 'Programs\nodejs\npm.cmd')
)
$npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
if ($npmCommand) {
    $npmCandidates += $npmCommand.Source
}
$npmPath = $npmCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1

if (-not $npmPath) {
    throw 'npm.cmd was not found. Install Node.js LTS, then reopen your terminal.'
}
if (-not (Test-Path -LiteralPath (Join-Path $frontendDir 'node_modules\next\package.json'))) {
    throw "Frontend dependencies are missing. Run npm.cmd ci inside $frontendDir first."
}

Write-Host "Starting Next.js at http://127.0.0.1:$Port"
Write-Host 'Start the backend in a second terminal before uploading audio.'

# Use the installed Node/npm together instead of an unrelated Node on PATH.
$previousPath = $env:Path
$env:Path = "$(Split-Path -Parent $npmPath);$previousPath"
Push-Location $frontendDir
try {
    & $npmPath run dev -- --hostname 127.0.0.1 --port $Port
    if ($LASTEXITCODE -ne 0) {
        throw "Next.js stopped with exit code $LASTEXITCODE. Check the error above."
    }
} finally {
    Pop-Location
    $env:Path = $previousPath
}
