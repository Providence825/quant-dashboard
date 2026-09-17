@echo off
REM 右键本文件 -> 以管理员身份运行, 只需运行一次
REM 作用: 允许同一WiFi下的其他设备(手机)访问端口 5000

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] 请右键本文件, 选择"以管理员身份运行"
    pause
    exit /b
)

powershell -NoProfile -Command "if (Get-NetFirewallRule -DisplayName 'Quant Dashboard 5000' -ErrorAction SilentlyContinue) { Write-Host '规则已存在, 无需重复添加' } else { New-NetFirewallRule -DisplayName 'Quant Dashboard 5000' -Direction Inbound -LocalPort 5000 -Protocol TCP -Action Allow -Profile Private | Out-Null; Write-Host '防火墙规则添加成功: 端口 5000 已对局域网放行' }"

echo.
echo 完成! 手机连同一个WiFi, 浏览器打开:  http://192.168.1.5:5000
pause
