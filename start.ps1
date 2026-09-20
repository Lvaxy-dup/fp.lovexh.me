param([int]$Port = 8000)
Set-Location -LiteralPath $PSScriptRoot
$travelPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $travelPython) {
    & $travelPython -m uvicorn server.app:app --host 127.0.0.1 --port $Port --workers 1
} else {
    python -m uvicorn server.app:app --host 127.0.0.1 --port $Port --workers 1
}
