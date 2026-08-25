# PowerShell launcher. Same behaviour as run.bat.
Set-Location $PSScriptRoot
$root = $PSScriptRoot

$py = "python"
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { $py = "py" }

& $py -c "import uvicorn, fastapi, numpy, httpx" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing dependencies..."
    & $py -m pip install --disable-pip-version-check -r "$root\requirements.txt"
}

if (Test-Path "$root\.env") {
    Get-Content "$root\.env" | Where-Object { $_ -match '^\s*[^#].*=' } | ForEach-Object {
        $k, $v = $_ -split '=', 2
        [Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim())
    }
}

Write-Host ""
Write-Host "  Sentinel is starting on http://127.0.0.1:8000"
Write-Host "  Press Ctrl+C to stop."
Write-Host ""
Set-Location "$root\backend"
& $py -m uvicorn app:app --host 127.0.0.1 --port 8000
