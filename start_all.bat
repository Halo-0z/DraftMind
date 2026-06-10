@echo off
REM ============================================================
REM DraftMind - one-click backend + frontend starter
REM Works under both PowerShell (chcp 65001) and cmd.exe.
REM ============================================================
chcp 65001 >nul 2>&1
setlocal EnableExtensions

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

set "BACKEND=%ROOT%\backend"
set "FRONTEND=%ROOT%\frontend"
set "BACKEND_LOG=%ROOT%\backend\_backend.log"
set "FRONTEND_LOG=%ROOT%\frontend\_frontend.log"

echo ============================================================
echo  DraftMind starter
echo  Root     : %ROOT%
echo  Backend  : %BACKEND%
echo  Frontend : %FRONTEND%
echo ============================================================

REM ---- pre-flight checks ----
if not exist "%BACKEND%\app\main.py" (
    echo [ERROR] %BACKEND%\app\main.py not found.
    pause
    exit /b 1
)
if not exist "%FRONTEND%\package.json" (
    echo [ERROR] %FRONTEND%\package.json not found.
    pause
    exit /b 1
)

REM ---- launch backend ----
echo [1/3] starting FastAPI on http://127.0.0.1:8000
if exist "%BACKEND_LOG%" del /f /q "%BACKEND_LOG%" >nul 2>&1
start "DraftMind-Backend" /MIN cmd /c "set PYTHONPATH=%BACKEND%&& set PYTHONUNBUFFERED=1&& cd /d %BACKEND%&& python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload >> %BACKEND_LOG% 2>&1"

REM ---- launch frontend ----
echo [2/3] starting Next.js on http://127.0.0.1:3000
if exist "%FRONTEND_LOG%" del /f /q "%FRONTEND_LOG%" >nul 2>&1
start "DraftMind-Frontend" /MIN cmd /c "cd /d %FRONTEND%&& npm run dev >> %FRONTEND_LOG% 2>&1"

echo [3/3] waiting 10s for services to come up...
timeout /t 10 /nobreak >nul

echo.
echo ============================================================
echo  DraftMind is up.
echo  API docs : http://127.0.0.1:8000/docs
echo  Web app  : http://127.0.0.1:3000/draft
echo  API log  : %BACKEND_LOG%
echo  UI log   : %FRONTEND_LOG%
echo ============================================================
echo  Stop with :  stop_all.bat
echo.
pause
endlocal
