@echo off
chcp 65001 >nul 2>&1
setlocal
cd /d "%~dp0"

echo 正在打包 video-service → video-service-linux.tar.gz

tar.exe ^
  --exclude=video-service/venv ^
  --exclude=video-service/.venv ^
  --exclude=video-service/data ^
  --exclude=video-service/python ^
  --exclude=video-service/ffmpeg ^
  --exclude=video-service/.git ^
  --exclude=video-service/service.json ^
  --exclude=video-service/models ^
  --exclude=video-service/models_retry ^
  --exclude=*/__pycache__ ^
  --exclude=*.pyc ^
  --exclude=*.pyo ^
  --exclude=*.log ^
  --exclude=*.tmp ^
  -C "%~dp0" ^
  -czf video-service-linux.tar.gz ^
  video-service

if %errorlevel% neq 0 (
  echo 打包失败 (exit %errorlevel%)
  pause
  exit /b 1
)

echo.
echo 完成: video-service-linux.tar.gz
for %%A in (video-service-linux.tar.gz) do echo 大小: %%~zA 字节
pause
