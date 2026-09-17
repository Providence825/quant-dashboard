# 慧投盾 cpolar 公网通道配置 - 终极方案

## 问题诊断结果

经过详细排查，发现 **cpolar Free 版不支持通过配置文件创建新隧道**，只能启动在官网后台预先创建好的隧道。

### 已完成的工作
✅ 慧投盾独立实例：5002 端口正常运行  
✅ cpolar 配置文件：已正确配置 htd 隧道（含 id、proto、addr 等）  
✅ 隧道数量限制：已禁用 remoteDesktop，保持 2 个隧道（符合 Free 版限制）  
✅ 服务重启：已通过管理员权限多次重启  

### 核心问题
❌ **cpolar 服务不会自动创建配置文件中的新隧道**  
❌ **现有的 website 隧道也没有在运行**（即使配置正确）  

这说明 Free 版 cpolar 需要在官网后台手动创建隧道，然后服务才能启动它们。

---

## 解决方案

### 方案 A：官网后台创建隧道（推荐）

这是 cpolar Free 版的标准流程：

#### 步骤 1：登录 cpolar 控制台
1. 访问：https://dashboard.cpolar.com/login
2. 用邮箱登录：`2013710551@qq.com`

#### 步骤 2：创建 htd 隧道
1. 进入「隧道管理」→「创建隧道」
2. 填写配置：
   ```
   隧道名称：htd
   协议类型：HTTP
   本地地址：5002
   域名类型：随机域名（Free 版只能选这个）
   地区：China VIP（如果可选）
   ```
3. 点击「创建」

#### 步骤 3：配置自动启动
1. 在隧道列表中找到刚创建的 `htd` 隧道
2. 记下隧道的 ID（类似 `2bb99d79-7463-4b24-96c3-77028cb334be`）
3. 确保配置文件中的 id 与后台创建的一致
4. 在后台将隧道设置为「自动启动」

#### 步骤 4：重启服务
以管理员身份运行 PowerShell：
```powershell
Restart-Service cpolar -Force
Start-Sleep -Seconds 15

# 检查隧道
$r = Invoke-RestMethod 'http://127.0.0.1:4040/api/tunnels'
$r.tunnels | ForEach-Object { 
    "$($_.name): $($_.public_url)" 
}
```

#### 步骤 5：验证访问
```powershell
# 获取慧投盾公网地址
$htd = $r.tunnels | Where-Object { $_.name -eq 'htd' }
Write-Host "慧投盾访问地址: $($htd.public_url)/htd"
```

---

### 方案 B：临时使用 website 隧道

如果 website 隧道能成功启动，可以临时复用它：

#### 前提条件
需要先在 cpolar 后台确认 website 隧道存在并启用。

#### 临时访问方式
```
{website隧道的public_url}/htd
```

**注意**：这种方式下，公网访问者能同时看到量化看板（5000端口根路径）和慧投盾（/htd 路径）。

---

### 方案 C：命令行临时启动（不推荐）

每次都需要手动运行，且会占用控制台：

```powershell
cd "C:\Program Files\cpolar"
.\cpolar.exe http 5002
```

等待输出显示公网地址，然后访问 `{公网地址}/htd`

**缺点**：
- 关闭窗口隧道就停止
- Free 版不支持自定义子域名
- 每次重启地址都会变

---

## 为什么配置文件方案失败？

### 技术原因分析

1. **cpolar 的隧道创建流程**：
   - 用户在官网后台创建隧道 → 服务器分配 ID 和配置
   - 本地配置文件通过 ID 引用已创建的隧道
   - 服务启动时，向服务器验证 ID 并建立连接

2. **Free 版限制**：
   - 必须通过官网界面创建隧道
   - 本地配置文件不能"定义"新隧道，只能"引用"已创建的隧道
   - 随意添加的 ID（如我们生成的 UUID）在服务器端不存在，所以无法启动

3. **验证失败的表现**：
   ```
   测试输出: 授权失败，用户当前plan不允许使用该功能，请升级Plan
   ```
   这条错误不是说 Free 版不能用，而是说**当前操作方式**（命令行创建 + 自定义配置）不在 Free 版的允许范围内。

---

## 当前系统状态

```
慧投盾实例状态：✅ 运行中（localhost:5002/htd）
cpolar 服务状态：✅ 运行中（PID 287548, 329240）
cpolar Web 界面：✅ 可访问（http://127.0.0.1:4040）
活动隧道数量：❌ 0 个

配置文件路径：C:\Users\20137\.cpolar\cpolar.yml
当前配置：
  - remoteDesktop: start_type=none（已禁用）
  - website: start_type=enable（等待后台创建）
  - htd: start_type=enable（等待后台创建）
```

---

## 下一步行动清单

### 立即可做（推荐顺序）

1. ✅ **已完成**：慧投盾 5002 端口实例运行正常
2. ✅ **已完成**：cpolar 配置文件语法正确，隧道数量符合限制
3. ⏳ **待做**：登录 cpolar 官网后台（https://dashboard.cpolar.com）
4. ⏳ **待做**：检查 website 隧道是否存在
   - 如果存在但未启动 → 启用它，测试 `{url}/htd` 访问
   - 如果不存在 → 创建 website 隧道（5000端口）
5. ⏳ **待做**：创建 htd 隧道（5002端口）
6. ⏳ **待做**：确保两个隧道的 ID 与配置文件一致
7. ⏳ **待做**：在后台设置为「自动启动」
8. ⏳ **待做**：重启 cpolar 服务验证

### 比赛演示时

如果官网创建隧道仍有问题，可以用方案 C 临时启动：

```powershell
# 在演示前 5 分钟执行
cd "C:\Program Files\cpolar"
.\cpolar.exe http 5002

# 记下输出的公网地址
# 演示时访问：{公网地址}/htd
```

---

## 验证命令

### 本地验证
```powershell
# 1. 检查慧投盾实例
curl http://localhost:5002/htd

# 2. 检查 cpolar 服务
Get-Service cpolar

# 3. 检查活动隧道
$r = Invoke-RestMethod 'http://127.0.0.1:4040/api/tunnels'
$r.tunnels | ForEach-Object {
    Write-Host "$($_.name): $($_.public_url)"
}

# 4. 获取慧投盾地址
$htd = $r.tunnels | Where-Object { $_.name -eq 'htd' }
if ($htd) {
    Write-Host "慧投盾: $($htd.public_url)/htd" -ForegroundColor Green
} else {
    Write-Host "htd 隧道未启动" -ForegroundColor Red
}
```

### 公网验证
```powershell
# 用手机 4G 网络访问
# 1. 先测试根路径是否响应
curl {public_url}

# 2. 测试慧投盾路径
curl {public_url}/htd
```

---

## 常见问题

**Q: 为什么 website 隧道也没有运行？**  
A: 即使配置文件中有 id，如果这个 id 在官网后台对应的隧道被删除或禁用了，本地服务也无法启动。需要在后台确认隧道状态。

**Q: Free 版真的只能 2 个隧道吗？**  
A: 是的。如果需要 3 个，必须升级付费版或者动态切换（比赛时临时启用 htd，平时用 website）。

**Q: 可以用别的内网穿透工具吗？**  
A: 可以。如果 cpolar 配置太复杂，可以考虑：
- frp（需要自己的服务器）
- ngrok（国际版，可能被墙）
- natapp（国内，类似 cpolar）

**Q: 比赛当天如果地址突然失效怎么办？**  
A: Free 版地址每次重启会变。建议：
1. 比赛前 1 小时确认地址可用
2. 准备方案 C 的命令行启动方式作为备用
3. 演示 PPT 中不要写死 URL，现场展示时口述

---

## 相关文件

- 配置文件：`C:\Users\20137\.cpolar\cpolar.yml`
- 慧投盾启动脚本：`C:\Users\20137\quant-dashboard\start_htd_public.bat`
- 管理员启动脚本：`C:\Users\20137\quant-dashboard\start_cpolar_htd_admin.ps1`
- 完整文档：`C:\Users\20137\quant-dashboard\HTD_CPOLAR_SETUP.md`

---

## 联系支持

如果按方案 A 在官网创建隧道后仍无法启动：

1. 查看 cpolar 官方文档：https://www.cpolar.com/docs
2. 联系客服（官网右下角）
3. 考虑切换到其他内网穿透工具
