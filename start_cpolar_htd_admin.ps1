# 慧投盾 cpolar 隧道启动脚本（管理员权限版本）
# 需要以管理员身份运行

# 检查管理员权限
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "错误: 此脚本需要管理员权限" -ForegroundColor Red
    Write-Host "请右键点击脚本 -> 以管理员身份运行" -ForegroundColor Yellow
    Read-Host "按 Enter 退出"
    exit 1
}

Write-Host "=== 慧投盾 cpolar 隧道启动 ===" -ForegroundColor Cyan
Write-Host ""

# 检查 5002 端口
Write-Host "[CHECK] 检查 5002 端口..." -ForegroundColor Cyan
$port5002 = Get-NetTCPConnection -LocalPort 5002 -State Listen -ErrorAction SilentlyContinue
if (-not $port5002) {
    Write-Host "[WARNING] 5002 端口未监听" -ForegroundColor Yellow
    Write-Host "[INFO] 正在启动慧投盾实例..." -ForegroundColor Cyan

    $htdPath = "C:\Users\20137\quant-dashboard"
    if (Test-Path "$htdPath\start_htd_public.bat") {
        Start-Process -FilePath "$htdPath\start_htd_public.bat" -WindowStyle Hidden
        Start-Sleep -Seconds 5

        $port5002 = Get-NetTCPConnection -LocalPort 5002 -State Listen -ErrorAction SilentlyContinue
        if ($port5002) {
            Write-Host "[OK] 慧投盾实例已启动" -ForegroundColor Green
        } else {
            Write-Host "[ERROR] 无法启动慧投盾实例" -ForegroundColor Red
            Write-Host "请手动运行: $htdPath\start_htd_public.bat" -ForegroundColor Yellow
            Read-Host "按 Enter 退出"
            exit 1
        }
    } else {
        Write-Host "[ERROR] 找不到启动脚本: $htdPath\start_htd_public.bat" -ForegroundColor Red
        Read-Host "按 Enter 退出"
        exit 1
    }
} else {
    Write-Host "[OK] 5002 端口正常运行" -ForegroundColor Green
}
Write-Host ""

# 重启 cpolar 服务
Write-Host "[INFO] 重启 cpolar 服务以应用配置..." -ForegroundColor Cyan
try {
    Restart-Service -Name 'cpolar' -Force -ErrorAction Stop
    Write-Host "[OK] cpolar 服务已重启" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] 无法重启服务: $($_.Exception.Message)" -ForegroundColor Red
    Read-Host "按 Enter 退出"
    exit 1
}

Write-Host "[INFO] 等待 15 秒让隧道建立..." -ForegroundColor Cyan
Write-Host ""
Start-Sleep -Seconds 15

# 获取隧道信息
Write-Host "[INFO] 获取公网地址..." -ForegroundColor Cyan
$maxRetry = 5
$retry = 0
$found = $false

while ($retry -lt $maxRetry -and -not $found) {
    try {
        $r = Invoke-RestMethod -Uri 'http://127.0.0.1:4040/api/tunnels' -TimeoutSec 2
        if ($r.tunnels -and $r.tunnels.Count -gt 0) {
            Write-Host ""
            Write-Host "========================================" -ForegroundColor Yellow
            Write-Host "    活动隧道列表" -ForegroundColor Yellow
            Write-Host "========================================" -ForegroundColor Yellow
            Write-Host ""

            $htdFound = $false
            foreach ($tunnel in $r.tunnels) {
                Write-Host "  $($tunnel.name): $($tunnel.public_url)" -ForegroundColor Cyan

                if ($tunnel.name -match 'htd' -or $tunnel.config.addr -match '5002') {
                    Write-Host "    慧投盾访问: $($tunnel.public_url)/htd" -ForegroundColor Green
                    $htdFound = $true
                }
            }

            Write-Host ""
            Write-Host "========================================" -ForegroundColor Yellow

            if (-not $htdFound) {
                Write-Host ""
                Write-Host "[WARNING] 未找到 htd 隧道" -ForegroundColor Yellow
                Write-Host "可能的原因:" -ForegroundColor Gray
                Write-Host "  1. Free 版最多 2 个隧道，当前已有其他隧道占用" -ForegroundColor Gray
                Write-Host "  2. 配置文件中 start_type 未设置为 enable" -ForegroundColor Gray
                Write-Host ""
                Write-Host "建议检查配置文件: C:\Users\20137\.cpolar\cpolar.yml" -ForegroundColor Yellow
            }

            $found = $true
        }
    } catch {
        # Silent retry
    }

    if (-not $found) {
        $retry++
        if ($retry -lt $maxRetry) {
            Start-Sleep -Seconds 2
        }
    }
}

if (-not $found) {
    Write-Host ""
    Write-Host "[ERROR] 无法获取隧道信息" -ForegroundColor Red
    Write-Host "请手动访问 http://127.0.0.1:4040 查看" -ForegroundColor Yellow
    Write-Host ""
}

Write-Host ""
Read-Host "按 Enter 退出"
