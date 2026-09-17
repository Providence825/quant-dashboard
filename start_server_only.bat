@echo off
REM ==== Quant Dashboard server-only launcher (for autostart) ====
cd /d "C:\Users\20137\quant-dashboard"

REM If already listening on 5000, do nothing
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if %errorlevel%==0 exit

REM Start server hidden in background, no browser
start "" /b python run.py
exit
