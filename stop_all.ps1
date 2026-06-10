# ============================================================
# DraftMind - stop both servers
# ============================================================
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Write-Host "Stopping DraftMind servers..." -ForegroundColor Yellow

# Kill by listening port - this catches every flavor of uvicorn / flask
# / gunicorn launcher (the wrapper script is python.exe, not uvicorn.exe
# on Windows, so name-based kills miss it).
function Stop-ByPort([int]$Port) {
    $pids = (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue).OwningProcess
    foreach ($p in ($pids | Sort-Object -Unique)) {
        if ($p -and $p -ne 0) {
            try { Stop-Process -Id $p -Force -ErrorAction Stop; Write-Host "  killed PID $p on port $Port" } catch {}
        }
    }
}
Stop-ByPort 8000
Stop-ByPort 3000

# Belt-and-braces: also kill any leftover next-server / uvicorn by name.
Get-Process -Name uvicorn -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "name='node.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*next*" -or $_.CommandLine -like "*3000*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Get-Process -Name node -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowTitle -like "*DraftMind*" } |
    ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
Write-Host "[stopped]" -ForegroundColor Green
pause
