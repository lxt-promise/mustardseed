@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo   Build OFFLINE portable zip (zero-download)
echo ============================================
echo.

if not exist "python\python.exe" (
  echo [ERROR] Bundled runtime not found: python\python.exe
  echo.
  echo This script only works after the offline runtime was prepared.
  echo Source-only users should use install.bat instead.
  echo.
  pause
  exit /b 1
)

REM Tip: stop the running service window first for a perfectly clean archive.

set "STAGE=%TEMP%\vd-pack-stage"
set "OUT=%CD%\..\video-service-portable.zip"

echo [1/4] Preparing clean staging folder ...
if exist "%STAGE%" rd /s /q "%STAGE%" 2>nul
mkdir "%STAGE%\video-service" >nul 2>&1

echo [2/4] Copying files ^(excluding venv, data, caches^) ...
REM /XD excludes directories by name at every level; /XF excludes file types.
robocopy "%CD%" "%STAGE%\video-service" /E ^
  /XD venv data __pycache__ .git ^
  /XF *.pyc *.log ^
  /NFL /NDL /NJH /NJS /NP /R:1 /W:1
REM robocopy exit codes 0-7 are success.
if errorlevel 8 (
  echo [ERROR] Staging copy failed.
  pause
  exit /b 1
)

echo [3/4] Packing with tar ^(Windows built-in^) ...
if exist "%OUT%" del /f /q "%OUT%"
tar -a -cf "%OUT%" -C "%STAGE%" "video-service"
if errorlevel 1 (
  echo [ERROR] Pack failed.
  pause
  exit /b 1
)

echo [4/4] Cleaning up staging folder ...
rd /s /q "%STAGE%" 2>nul

echo.
echo Done:
for %%F in ("%OUT%") do echo       %%~fF  ^(%%~zF bytes^)
echo.
echo Copy this zip to another Windows PC, extract and run start.bat - no internet needed.
pause
