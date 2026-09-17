@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo [%date% %time%] Starting Quant Dashboard...

REM Set UTF-8 encoding
set PYTHONUTF8=1

REM Start Python server
python run.py

pause
