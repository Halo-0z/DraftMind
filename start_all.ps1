# ============================================================
# DraftMind - PowerShell starter (encoding-safe)
# Run:   powershell -ExecutionPolicy Bypass -File .\start_all.ps1
# Or:    .\start_all.ps1
# ============================================================
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 | Out-Null

$ErrorActionPreference = "Stop"
# $PSScriptRoot is the folder containing this .ps1 file (i.e. D:\DraftMind).
$Root      = $PSScriptRoot
$Backend   = Join-Path $Root "backend"
$Frontend  = Join-Path $Root "frontend"
$BackendLog  = Join-Path $Backend  "_backend.log"
$FrontendLog = Join-Path $Frontend "_frontend.log"
$PythonExe = "D:\anaconda\python.exe"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " DraftMind starter" -ForegroundColor Cyan
Write-Host " Root      : $Root"
Write-Host " Backend   : $Backend"
Write-Host " Frontend  : $Frontend"
Write-Host "============================================================" -ForegroundColor Cyan

# Pre-flight
if (-not (Test-Path (Join-Path $Backend "app\main.py"))) {
    Write-Host "[ERROR] backend\app\main.py not found" -ForegroundColor Red
    pause; exit 1
}
if (-not (Test-Path (Join-Path $Frontend "package.json"))) {
    Write-Host "[ERROR] frontend\package.json not found" -ForegroundColor Red
    pause; exit 1
}
if (-not (Test-Path $PythonExe)) {
    Write-Host "[ERROR] Backend Python not found: $PythonExe" -ForegroundColor Red
    pause; exit 1
}

# Kill any leftover uvicorn / next dev from previous runs.  Use the
# listening port as the ground truth because the python wrapper script
# is named _start_backend.py (not uvicorn.exe on Windows).
function Stop-ByPort([int]$Port) {
    $pids = (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue).OwningProcess
    foreach ($p in ($pids | Sort-Object -Unique)) {
        if ($p -and $p -ne 0) {
            try { Stop-Process -Id $p -Force -ErrorAction Stop } catch {}
        }
    }
}
Stop-ByPort 8000
Stop-ByPort 3000
Get-Process -Name uvicorn -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Get-Process -Name python -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*_start_backend.py*" -or $_.CommandLine -like "*uvicorn*" } |
    ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
Get-CimInstance Win32_Process -Filter "name='node.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*next*dev*" -or $_.CommandLine -like "*next-server*" -or $_.CommandLine -like "*3000*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 1
Write-Host "[ok] cleared any leftover dev processes" -ForegroundColor DarkGreen

# Clear stale Next.js build cache only when explicitly requested.
# Next dev owns .next while it is running; deleting the cache on every
# starter run can leave the dev server with missing manifest files.
$nextCache = Join-Path $Frontend ".next"
if ($env:DRAFTMIND_CLEAR_NEXT_CACHE -eq "1" -and (Test-Path $nextCache)) {
    Remove-Item -Recurse -Force $nextCache -ErrorAction SilentlyContinue
    Write-Host "[ok] cleared frontend .next cache" -ForegroundColor DarkGreen
}

# Ensure backend deps are installed (fast skip if already present).
try {
    & $PythonExe -c "import feedparser, requests, bs4, fastapi, sqlalchemy, openai, lxml" 2>$null
    if ($LASTEXITCODE -ne 0) { throw "deps missing" }
    Write-Host "[ok] backend python deps already installed" -ForegroundColor DarkGreen
} catch {
    Write-Host "[setup] installing backend deps (one-time, may take 1-2 min) ..." -ForegroundColor Yellow
    Push-Location $Backend
    & $PythonExe -m pip install -e . 2>&1 | Tee-Object -FilePath (Join-Path $Backend "_pip_install.log") | Select-Object -Last 5
    Pop-Location
}

# Optional: run news tests in verbose mode when an env var is set.
if ($env:RUN_NEWS_TESTS -eq "1") {
    Write-Host "[test] running news tests ..." -ForegroundColor Yellow
    Push-Location $Backend
    & $PythonExe -m pytest app/tests/test_news_service.py app/tests/test_news_api.py -v 2>&1 | Tee-Object -FilePath (Join-Path $Backend "_pytest_news.log") | Select-Object -Last 30
    Pop-Location
}

# Ensure frontend node_modules exists.
if (-not (Test-Path (Join-Path $Frontend "node_modules"))) {
    Write-Host "[setup] installing frontend deps (one-time, may take 1-3 min) ..." -ForegroundColor Yellow
    Push-Location $Frontend
    npm install 2>&1 | Tee-Object -FilePath (Join-Path $Frontend "_npm_install.log") | Select-Object -Last 5
    Pop-Location
}

# Start backend
Write-Host "[1/3] starting FastAPI on http://127.0.0.1:8000 ..." -ForegroundColor Green
if (Test-Path $BackendLog) { Remove-Item $BackendLog -Force -ErrorAction SilentlyContinue }
$env:PYTHONPATH = $Backend
$env:PYTHONUNBUFFERED = "1"
# Use a tiny wrapper script so we can force a clean PYTHONPATH and an
# unbuffered log redirect that survives the sandbox / detached process.
$bootScript = Join-Path $Backend "_start_backend.py"
@'
import os, sys, traceback
os.environ["PYTHONPATH"] = r"__DRAFTMIND_BACKEND__"
os.environ["PYTHONUNBUFFERED"] = "1"
sys.path.insert(0, r"__DRAFTMIND_BACKEND__")
log_path = r"__DRAFTMIND_BACKEND_LOG__"
try:
    sys.stdout = open(log_path, "w", encoding="utf-8", buffering=1)
    sys.stderr = sys.stdout
    import logging
    # Surface INFO messages from the news service so the smoke output
    # actually shows how many raw items each source returned.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )
    import uvicorn
    print("[boot] uvicorn ver:", uvicorn.__version__, flush=True)
    print("[boot] importing app.main ...", flush=True)
    from app.main import app
    print("[boot] app loaded:", app, flush=True)
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
except Exception:
    traceback.print_exc()
    sys.stdout.flush()
    sys.exit(1)
'@ | ForEach-Object {
    $_ -replace '__DRAFTMIND_BACKEND_LOG__', $BackendLog `
       -replace '__DRAFTMIND_BACKEND__', $Backend
} | Set-Content $bootScript -Encoding UTF8

$existingApiOk = $false
try {
    $existingApi = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/health" -UseBasicParsing -TimeoutSec 2
    if ($existingApi.StatusCode -eq 200) { $existingApiOk = $true }
} catch { }

if ($existingApiOk) {
    Write-Host "[ok] FastAPI already running on http://127.0.0.1:8000" -ForegroundColor DarkGreen
    @(
        "[boot] FastAPI was already running on http://127.0.0.1:8000."
        "[boot] start_all.ps1 did not launch a second backend process."
        "[boot] Backend launcher is configured to use: $PythonExe"
    ) | Set-Content $BackendLog -Encoding UTF8
} else {
    Start-Process -FilePath $PythonExe -ArgumentList "`"$bootScript`"" -WindowStyle Hidden -WorkingDirectory $Backend
}

# Start frontend
Write-Host "[2/3] starting Next.js on http://127.0.0.1:3000 ..." -ForegroundColor Green
Remove-Item $FrontendLog -Force -ErrorAction SilentlyContinue
$frontendCmd = "cd /d `"$Frontend`" && npm run dev >> `"$FrontendLog`" 2>&1"
Start-Process -FilePath "cmd.exe" -ArgumentList "/c", $frontendCmd -WindowStyle Minimized -WorkingDirectory $Frontend

Write-Host "[3/3] waiting 20s for services to come up ..." -ForegroundColor Green
Start-Sleep -Seconds 20

# Health check with retry (give each endpoint up to 3 attempts)
function Test-Endpoint {
    param([string]$Url, [int]$Attempts = 8)
    for ($i = 1; $i -le $Attempts; $i++) {
        try {
            $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ($r.StatusCode -eq 200) { return $true }
        } catch { }
        Start-Sleep -Seconds 2
    }
    return $false
}

$apiOk = Test-Endpoint "http://127.0.0.1:8000/api/health"
$uiOk  = Test-Endpoint "http://127.0.0.1:3000/draft"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " DraftMind status:" -ForegroundColor Cyan
Write-Host ("  API  (8000) : " + ($(if($apiOk){"OK"} else {"DOWN - check backend\_backend.log"})))
Write-Host ("  UI   (3000) : " + ($(if($uiOk) {"OK"} else {"DOWN - check frontend\_frontend.log"})))
Write-Host ""
Write-Host "  Web app : http://127.0.0.1:3000/draft"
Write-Host "  API docs: http://127.0.0.1:8000/docs"
Write-Host "  Stop    :  .\stop_all.ps1"
Write-Host "  Backend log: $BackendLog"
Write-Host "============================================================" -ForegroundColor Cyan
if (-not $apiOk) {
    Write-Host ""
    Write-Host "----- backend log tail -----" -ForegroundColor Yellow
    if (Test-Path $BackendLog) {
        Get-Content $BackendLog -Tail 30
    } else {
        Write-Host "(log file not created yet)" -ForegroundColor DarkYellow
    }
    Write-Host "----------------------------" -ForegroundColor Yellow
}
pause
