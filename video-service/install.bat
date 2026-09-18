@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================
echo   Video Dub Service - Environment Setup
echo ============================================
echo.

if exist "venv\Scripts\python.exe" (
  echo [OK] venv already exists. Installing/updating packages ...
  goto install
)

REM ---- Find a real base Python (skip Microsoft Store stub) ----
set "BASEPY="

REM 1) WorkBuddy managed Python (this machine)
for /f "delims=" %%p in ('dir /b /ad /o-n "%USERPROFILE%\.workbuddy\binaries\python\versions 2>nul"') do (
  if not defined BASEPY if exist "%USERPROFILE%\.workbuddy\binaries\python\versions\%%p\python.exe" (
    set "BASEPY=%USERPROFILE%\.workbuddy\binaries\python\versions\%%p\python.exe"
  )
)

REM 2) py launcher
if not defined BASEPY (
  py -3 -c "import sys" >nul 2>&1 && set "BASEPY=py -3"
)

REM 3) python on PATH, but reject the zero-byte WindowsApps Store alias
if not defined BASEPY (
  for /f "delims=" %%p in ('where python 2^>nul') do (
    if not defined BASEPY (
      echo %%p | findstr /i "WindowsApps" >nul
      if errorlevel 1 (
        "%%p" -c "import sys" >nul 2>&1 && set "BASEPY=%%p"
      )
    )
  )
)

if not defined BASEPY (
  echo [ERROR] No real Python 3.10+ found.
  echo.
  echo Install Python first, either:
  echo   winget install Python.Python.3.12
  echo or download from https://www.python.org/downloads/
  echo ^(check "Add python to PATH" during install^)
  echo.
  pause
  exit /b 1
)

echo Using base Python:
!BASEPY! --version
echo.

echo Creating virtual environment ...
!BASEPY! -m venv venv
if errorlevel 1 (
  echo [ERROR] Failed to create venv.
  pause
  exit /b 1
)

:install
set "VENV_PY=venv\Scripts\python.exe"

echo Upgrading pip ...
"%VENV_PY%" -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
echo.
echo Installing requirements ...
"%VENV_PY%" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
  echo.
  echo Mirror failed, retrying with official PyPI ...
  "%VENV_PY%" -m pip install -r requirements.txt
)
if errorlevel 1 (
  echo [ERROR] Dependency installation failed. Check your network.
  pause
  exit /b 1
)

REM ---- First run: create local config from template ----
if not exist "service.json" (
  if exist "service.example.json" (
    copy /y "service.example.json" "service.json" >nul
    echo [OK] Created service.json from template - edit it anytime for port / paths / CORS.
  )
)

echo.
echo Checking ffmpeg ...
"%VENV_PY%" -c "import config; assert config.ffmpeg_available()" >nul 2>&1
if errorlevel 1 (
  echo ffmpeg not found.
  choice /c YN /m "Auto-download ffmpeg essentials build now (~90 MB)"
  if errorlevel 2 goto ffmpeg_skip
  echo Downloading and extracting into .\ffmpeg\ ...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; New-Item -ItemType Directory -Force -Path 'ffmpeg' | Out-Null; Invoke-WebRequest -Uri 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip' -OutFile 'ffmpeg\ffmpeg.zip'; Expand-Archive -Path 'ffmpeg\ffmpeg.zip' -DestinationPath 'ffmpeg' -Force; Remove-Item 'ffmpeg\ffmpeg.zip'"
  if errorlevel 1 (
    echo [WARN] Auto-download failed ^(network?^). Install manually instead:
    echo        winget install Gyan.FFmpeg
    echo    or unzip an essentials build into .\ffmpeg\
  ) else (
    echo [OK] ffmpeg installed into .\ffmpeg\
  )
)
:ffmpeg_skip

echo.
echo ============================================
echo   Setup complete. Run start.bat next.
echo ============================================
pause
