@echo off
REM ==== 慧投盾 cpolar 隧道启动脚本 ====
REM
REM 前提条件:
REM   1. 慧投盾实例已在 5002 端口运行 (start_htd_public.bat)
REM   2. cpolar 配置文件已包含 htd 隧道定义
REM
REM 使用方法:
REM   方法1: 双击此脚本，会打开新窗口显示公网地址
REM   方法2: 在 PowerShell 中运行: .\start_cpolar_htd.bat
REM
REM 注意:
REM   - 如果有旧的 cpolar 进程无法停止，请手动重启电脑
REM   - Free 版本的公网地址每次启动都会变化

echo [CHECK] 检查 5002 端口...
powershell -NoProfile -Command "if (-not (Get-NetTCPConnection -LocalPort 5002 -State Listen -ErrorAction SilentlyContinue)) { Write-Host '[ERROR] 5002 端口未监听，请先运行 start_htd_public.bat'; pause; exit 1 }"
if %errorlevel% neq 0 exit /b 1

echo [OK] 5002 端口正常
echo.

echo [INFO] 清理现有 cpolar 进程...
taskkill /F /IM cpolar.exe >nul 2>&1
timeout /t 2 /nobreak >nul

echo [INFO] 启动 cpolar 隧道 'htd'...
echo [INFO] 等待 10 秒获取公网地址...
echo.

start /B "" "C:\Program Files\cpolar\cpolar.exe" start htd
timeout /t 10 /nobreak >nul

echo [INFO] 尝试获取公网地址...
powershell -NoProfile -Command "$maxRetry=5; $retry=0; while($retry -lt $maxRetry) { try { $r = Invoke-RestMethod 'http://127.0.0.1:4040/api/tunnels' -TimeoutSec 2; if ($r.tunnels.Count -gt 0) { Write-Host ''; Write-Host '========================================'; Write-Host '    慧投盾公网访问地址'; Write-Host '========================================'; $htd = $r.tunnels | Where-Object { $_.name -match 'htd' -or $_.config.addr -match '5002' } | Select-Object -First 1; if ($htd) { Write-Host ''; Write-Host \"  $($htd.public_url)/htd\"; Write-Host ''; Write-Host '========================================'; Write-Host '提示: Free 版地址每次启动都会变化'; Write-Host '      按任意键关闭窗口...'; Write-Host '========================================' } else { Write-Host '未找到 htd 隧道，所有隧道:'; $r.tunnels | ForEach-Object { Write-Host \"  $($_.public_url)\" } }; break } } catch { }; $retry++; Start-Sleep -Seconds 2 }; if ($retry -eq $maxRetry) { Write-Host '[ERROR] 无法获取隧道信息'; Write-Host '请手动访问 http://127.0.0.1:4040 查看' }"

pause
