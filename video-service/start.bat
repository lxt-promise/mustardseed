@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo   Video Dub Service (MustardSeed)
echo ============================================
echo.

REM ---- First run: create local config from template ----
if not exist "service.json" (
  if exist "service.example.json" (
    copy /y "service.example.json" "service.json" >nul
    echo [INFO] Created service.json from template.
    echo        Edit it if you need a custom port / paths / CORS.
    echo.
  )
)

REM ---- Locate a Python runtime (offline bundle first) ----
set "PYEXE="
REM 1) Fully offline portable runtime bundled in this folder - zero install
if exist "python\python.exe" set "PYEXE=python\python.exe"
REM 2) venv created by install.bat
if not defined PYEXE if exist "venv\Scripts\python.exe" set "PYEXE=venv\Scripts\python.exe"
REM 3) Legacy workbench venv on this machine
if not defined PYEXE if exist "D:\app\videodub\venv\Scripts\python.exe" set "PYEXE=D:\app\videodub\venv\Scripts\python.exe"

REM WorkBuddy managed Python (deps may be global there)
if not defined PYEXE (
  for /f "delims=" %%p in ('dir /b /ad /o-n "%USERPROFILE%\.workbuddy\binaries\python\versions 2>nul"') do (
    if not defined PYEXE if exist "%USERPROFILE%\.workbuddy\binaries\python\versions\%%p\python.exe" (
      set "PYEXE=%USERPROFILE%\.workbuddy\binaries\python\versions\%%p\python.exe"
    )
  )
)

if not defined PYEXE (
  echo [ERROR] Python environment not found.
  echo Please run install.bat once first.
  echo.
  pause
  exit /b 1
)

echo Using Python: %PYEXE%

"%PYEXE%" -c "import fastapi, uvicorn" >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Dependencies missing ^(fastapi / uvicorn^).
  echo Please run install.bat first.
  echo.
  pause
  exit /b 1
)

REM ---- Port in-use warning (port read from service.json) ----
set "SERVICE_PORT="
for /f "delims=" %%i in ('"%PYEXE%" -c "import config;print(config.PORT)" 2^>nul') do set "SERVICE_PORT=%%i"
if not defined SERVICE_PORT set "SERVICE_PORT=8765"
netstat -ano | findstr ":%SERVICE_PORT% " | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 (
  echo [WARN] Port %SERVICE_PORT% is already in use - another instance may be running.
  echo.
  pause
)

echo.
echo Keep this window open while using the tool. Press Ctrl+C to stop.
echo API docs: http://127.0.0.1:%SERVICE_PORT%/docs
echo ----------------------------------------------------------------
echo.

"%PYEXE%" run.py

echo.
echo Service stopped.
pause
