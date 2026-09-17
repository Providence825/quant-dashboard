# 慧投盾 cpolar 公网通道配置指南

## 当前状态

✅ **已完成：**
1. 慧投盾独立实例已配置在 5002 端口
2. cpolar 配置文件已添加 htd 隧道定义
3. 启动脚本已创建：`start_cpolar_htd.ps1`

❌ **待解决：**
- 有两个 cpolar 后台进程（PID 7416, 314892）占用资源，导致新隧道无法启动
- 这两个进程是系统服务级别启动的，普通权限无法终止

## 解决方案

### 方案 A：重启电脑（推荐）

这是最简单可靠的方法：

1. **重启电脑**
2. 重启后运行以下命令：
   ```powershell
   cd C:\Users\20137\quant-dashboard
   .\start_htd_public.bat
   .\start_cpolar_htd.ps1
   ```
3. 脚本会自动显示公网地址

### 方案 B：用管理员权限手动操作

如果不想重启，用管理员权限操作：

1. **以管理员身份打开 PowerShell**
   - 右键点击"开始"菜单 → Windows PowerShell (管理员)

2. **强制终止所有 cpolar 进程**
   ```powershell
   taskkill /F /IM cpolar.exe
   ```

3. **导航到项目目录**
   ```powershell
   cd C:\Users\20137\quant-dashboard
   ```

4. **确认 5002 端口在运行**
   ```powershell
   Get-NetTCPConnection -LocalPort 5002 -State Listen
   ```
   如果没有输出，运行：
   ```powershell
   .\start_htd_public.bat
   ```

5. **启动 cpolar 隧道**
   ```powershell
   & 'C:\Program Files\cpolar\cpolar.exe' start-all
   ```

6. **等待 10 秒，然后获取公网地址**
   ```powershell
   Start-Sleep -Seconds 10
   $r = Invoke-RestMethod 'http://127.0.0.1:4040/api/tunnels'
   $htd = $r.tunnels | Where-Object { $_.name -match 'htd' -or $_.config.addr -match '5002' }
   Write-Host "`n慧投盾公网地址: $($htd.public_url)/htd`n" -ForegroundColor Green
   ```

### 方案 C：使用现有的 website 隧道（临时方案）

如果急需公网访问，可以复用现有的 5000 端口隧道：

1. 确认 website 隧道是否在运行：
   ```powershell
   $r = Invoke-RestMethod 'http://127.0.0.1:4040/api/tunnels'
   $website = $r.tunnels | Where-Object { $_.name -eq 'website' }
   if ($website) {
       Write-Host "慧投盾临时访问地址: $($website.public_url)/htd"
   }
   ```

2. 这种方式下，访问者能同时看到量化看板和慧投盾两个系统

## 配置文件位置

- **cpolar 配置：** `C:\Users\20137\.cpolar\cpolar.yml`
- **htd 隧道定义：**
  ```yaml
  htd:
    proto: http
    addr: "5002"
    host_header: localhost:5002
    bind_tls: both
    start_type: enable
  ```

- **慧投盾启动脚本：** `C:\Users\20137\quant-dashboard\start_htd_public.bat`
- **cpolar 启动脚本：** `C:\Users\20137\quant-dashboard\start_cpolar_htd.ps1`

## 验证步骤

配置完成后，验证以下几点：

1. **本地访问测试**
   ```powershell
   curl http://localhost:5002/htd
   ```
   应该返回慧投盾首页 HTML

2. **公网地址获取**
   ```powershell
   $r = Invoke-RestMethod 'http://127.0.0.1:4040/api/tunnels'
   $r.tunnels | ForEach-Object { Write-Host "$($_.name): $($_.public_url)" }
   ```
   应该能看到 `htd` 隧道

3. **公网访问测试**
   - 用手机 4G 网络访问 `{public_url}/htd`
   - 应该能看到慧投盾界面

## 注意事项

⚠️ **Free 版本限制：**
- 公网地址每次重启都会变化
- 每个账号最多 2 个同时在线的隧道
- 当前已有 remoteDesktop (3389) 和 website (5000) 两个自动启动的隧道

💡 **建议：**
- 如果不需要远程桌面，可以将 remoteDesktop 的 `start_type` 改为 `none`
- 慧投盾用于比赛演示，建议比赛期间临时启动，平时关闭以节省隧道配额

## 常见问题

**Q: 为什么 `start_cpolar_htd.ps1` 显示"No tunnels found"？**
A: 有后台 cpolar 服务进程在运行，新进程无法创建隧道。需要用管理员权限终止或重启电脑。

**Q: 公网地址可以固定吗？**
A: Free 版本不支持。需要升级到付费版才能使用固定域名。

**Q: 可以同时运行量化看板和慧投盾的公网通道吗？**
A: 可以，但 Free 版最多 2 个隧道。需要停掉 remoteDesktop 或 website 其中一个。

## 快速命令参考

```powershell
# 启动慧投盾实例
cd C:\Users\20137\quant-dashboard
.\start_htd_public.bat

# 启动 cpolar 隧道（普通权限）
.\start_cpolar_htd.ps1

# 查看所有隧道
(Invoke-RestMethod 'http://127.0.0.1:4040/api/tunnels').tunnels | 
  ForEach-Object { "$($_.name): $($_.public_url)" }

# 查看慧投盾隧道
$r = Invoke-RestMethod 'http://127.0.0.1:4040/api/tunnels'
$htd = $r.tunnels | Where-Object { $_.name -match 'htd' }
"慧投盾: $($htd.public_url)/htd"
```
