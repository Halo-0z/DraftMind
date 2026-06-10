@echo off
REM ============================================================
REM DraftMind - stop both servers (pure ASCII, encoding-safe)
REM ============================================================
chcp 65001 >nul 2>&1

echo Stopping DraftMind servers...
taskkill /FI "WINDOWTITLE eq DraftMind-Backend*"  /T /F 2>nul
taskkill /FI "WINDOWTITLE eq DraftMind-Frontend*" /T /F 2>nul
taskkill /IM uvicorn.exe /F 2>nul
echo [stopped]
pause
