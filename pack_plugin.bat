@echo off
setlocal

cd /d "%~dp0"

python pack_plugin.py %*
if errorlevel 1 (
    echo.
    echo Package failed.
    pause
    exit /b 1
)

echo.
echo Package completed.
pause
