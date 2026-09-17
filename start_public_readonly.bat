@echo off
REM ==== Quant Dashboard PUBLIC read-only instance (port 5001) ====
REM This instance is what cpolar exposes to the internet.
REM READONLY=true blocks all trade/import/write operations (returns 403).
REM It reads the SAME database as your local 5000 instance, so viewers
REM see live data but can never modify anything.
cd /d "C:\Users\20137\quant-dashboard"

REM If already listening on 5001, do nothing
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 5001 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if %errorlevel%==0 exit

set READONLY=true
set FLASK_PORT=5001
set FLASK_HOST=0.0.0.0

REM Start read-only server hidden in background, no browser
start "" /b python run.py
exit
