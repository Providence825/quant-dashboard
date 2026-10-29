@echo off
REM ==== 首投守护者 launcher (port 5002, 原版量化看板/慧投盾独占5000) ====
cd /d "C:\Users\20137\shoutouzhehuzhe"

REM Is the server already listening on port 5002?
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 5002 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if %errorlevel%==0 goto open

REM Not running -> start it hidden in the background
start "" /b python3.13.exe run.py

REM Wait up to ~20s for the port to come up
powershell -NoProfile -Command "for ($i=0; $i -lt 40; $i++) { if (Get-NetTCPConnection -LocalPort 5002 -State Listen -ErrorAction SilentlyContinue) { break }; Start-Sleep -Milliseconds 500 }"

:open
start "" "http://127.0.0.1:5002"
exit
