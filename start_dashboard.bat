@echo off
REM ==== Quant Dashboard launcher ====
cd /d "C:\Users\20137\quant-dashboard"

REM Is the server already listening on port 5000?
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if %errorlevel%==0 goto open

REM Not running -> start it hidden in the background
start "" /b python run.py

REM Wait up to ~15s for the port to come up
powershell -NoProfile -Command "for ($i=0; $i -lt 30; $i++) { if (Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue) { break }; Start-Sleep -Milliseconds 500 }"

:open
start "" "http://127.0.0.1:5000"
exit
