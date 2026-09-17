@echo off
REM ==== cpolar tunnel for HuiTouDun (port 5002) ====
REM This creates a public URL for the HTD competition demo.
REM Free tier: URL changes on every restart, no custom domain.

cd /d "C:\Users\20137\quant-dashboard"

REM Check if 5002 is listening before starting tunnel
powershell -NoProfile -Command "if (-not (Get-NetTCPConnection -LocalPort 5002 -State Listen -ErrorAction SilentlyContinue)) { Write-Host '[ERROR] Port 5002 not listening. Start HTD instance first with start_htd_public.bat'; exit 1 }"
if %errorlevel% neq 0 exit /b 1

echo [INFO] Starting cpolar tunnel for port 5002...
echo [INFO] Tunnel URL will be logged below (look for cpolar.cn or cpolar.top)
echo [INFO] Press Ctrl+C to stop the tunnel
echo.

REM Run cpolar in foreground and capture output
REM The public URL appears in the tunnel creation log
"C:\Program Files\cpolar\cpolar.exe" http 5002
