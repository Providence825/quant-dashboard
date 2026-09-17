# HTD cpolar tunnel startup script

Write-Host "[CHECK] Checking port 5002..." -ForegroundColor Cyan
$port5002 = Get-NetTCPConnection -LocalPort 5002 -State Listen -ErrorAction SilentlyContinue
if (-not $port5002) {
    Write-Host "[ERROR] Port 5002 not listening. Please run start_htd_public.bat first" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "[OK] Port 5002 is ready" -ForegroundColor Green
Write-Host ""

Write-Host "[INFO] Stopping existing cpolar processes..." -ForegroundColor Cyan
Get-Process -Name cpolar -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

Write-Host "[INFO] Starting cpolar tunnel 'htd'..." -ForegroundColor Cyan
$proc = Start-Process -FilePath 'C:\Program Files\cpolar\cpolar.exe' -ArgumentList 'start','htd' -PassThru -NoNewWindow
Write-Host "[INFO] Process ID: $($proc.Id)" -ForegroundColor Gray
Write-Host "[INFO] Waiting 12 seconds for tunnel..." -ForegroundColor Cyan
Write-Host ""
Start-Sleep -Seconds 12

Write-Host "[INFO] Fetching public URL..." -ForegroundColor Cyan
$maxRetry = 5
$retry = 0
$found = $false

while ($retry -lt $maxRetry -and -not $found) {
    try {
        $r = Invoke-RestMethod -Uri 'http://127.0.0.1:4040/api/tunnels' -TimeoutSec 2
        if ($r.tunnels -and $r.tunnels.Count -gt 0) {
            Write-Host ""
            Write-Host "========================================" -ForegroundColor Yellow
            Write-Host "    HTD Public Access URL" -ForegroundColor Yellow
            Write-Host "========================================" -ForegroundColor Yellow

            $htd = $r.tunnels | Where-Object { $_.name -match 'htd' -or $_.config.addr -match '5002' } | Select-Object -First 1
            if ($htd) {
                Write-Host ""
                Write-Host "  $($htd.public_url)/htd" -ForegroundColor Green
                Write-Host ""
                Write-Host "========================================" -ForegroundColor Yellow
                Write-Host "Note: Free tier URL changes on restart" -ForegroundColor Gray
                Write-Host "========================================" -ForegroundColor Yellow
                Write-Host ""
                $found = $true
            } else {
                Write-Host ""
                Write-Host "HTD tunnel not found. Available tunnels:" -ForegroundColor Yellow
                $r.tunnels | ForEach-Object {
                    Write-Host "  $($_.name): $($_.public_url)" -ForegroundColor Cyan
                }
                Write-Host ""
                $found = $true
            }
        }
    } catch {
        # Silent retry
    }
    if (-not $found) {
        $retry++
        Start-Sleep -Seconds 2
    }
}

if (-not $found) {
    Write-Host "[ERROR] Cannot fetch tunnel info" -ForegroundColor Red
    Write-Host "Please visit http://127.0.0.1:4040 manually" -ForegroundColor Yellow
    Write-Host ""
}

Read-Host "Press Enter to exit"
