@echo off
REM ==== HuiTouDun PUBLIC instance (port 5002) ====
REM This instance only serves /htd route for the competition demo.
REM READONLY=true blocks all trade/import/write operations (returns 403).
REM HTD_ONLY=true limits routes to /htd endpoint only.
cd /d "C:\Users\20137\quant-dashboard"

REM If already listening on 5002, do nothing
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 5002 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if %errorlevel%==0 exit

set READONLY=true
set HTD_ONLY=true
set FLASK_PORT=5002
set FLASK_HOST=0.0.0.0

REM Start HTD public instance hidden in background
start "" /b python3.13.exe run.py
exit
