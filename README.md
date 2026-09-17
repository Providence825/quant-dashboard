# 量化交易看板 (Quant Dashboard)

基于 Flask + SQLite 的 A 股模拟盘 / 策略信号 / 回测复盘一体化看板。数据源以新浪财经 HTTP 接口为主，AKShare 作为兜底。

> ⚠️ 本项目仅用于学习与模拟，**不构成任何投资建议**，且**没有登录鉴权**，请勿直接暴露到公网。

## 一句话介绍

A股量化交易系统：多策略回测引擎 + 实盘监控看板，支持均线突破 / 龙头战法 / 板块动量等策略，内置市场 regime 识别、基本面因子选股、风险控制模块。历史回测 run#117 实现 36% 收益（Sharpe 0.90，最大回撤 -17.8%）。技术栈：Python / Flask / SQLite / ECharts。

## 环境要求

- Python **3.10 或以上**（开发环境为 3.13）
- 无需数据库服务，SQLite 首次启动自动建库
- 可联网访问新浪财经行情接口

## 快速开始

### 1. 获取代码

```bash
git clone https://github.com/Providence825/quant-dashboard.git
cd quant-dashboard
```

### 2. 创建并激活虚拟环境

Windows (PowerShell)：
```powershell
python -m venv venv
venv\Scripts\Activate.ps1
```

> 若 PowerShell 提示脚本被禁止，先执行一次：
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

macOS / Linux：
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 配置环境变量

```powershell
# Windows
copy .env.example .env
```
```bash
# macOS / Linux
cp .env.example .env
```

按需编辑 `.env`。本机使用保持默认即可（`FLASK_HOST=127.0.0.1`）。

### 5. 启动

```bash
python run.py
```

首次启动会自动：建库（`data/quant.db`）→ 预加载股票列表 → 回填指数历史 → 预热策略缓存。看到 `[INIT] ... ready` / `warmed` 日志后即就绪。

打开浏览器访问：**http://127.0.0.1:5000**

## 常见配置

| 变量 | 说明 | 默认 |
|------|------|------|
| `FLASK_HOST` | 监听地址，局域网访问填 `0.0.0.0` | `127.0.0.1` |
| `FLASK_PORT` | 端口 | `5000` |
| `READONLY` | `true` 时只读、禁交易、不启动调度器（用于对外分享） | `false` |
| `INITIAL_CAPITAL` | 模拟盘初始资金 | `1000000` |

其余风控/策略参数见 `.env.example` 注释。

## 局域网 / 手机访问

1. `.env` 设 `FLASK_HOST=0.0.0.0`
2. 放行防火墙端口（Windows 可运行仓库内 `添加防火墙规则_用管理员运行.bat`）
3. 手机与电脑同一局域网，访问 `http://<电脑内网IP>:5000`

## 目录结构

```
quant-dashboard/
├── run.py              # 启动入口
├── requirements.txt
├── .env.example        # 环境变量模板
├── server/
│   ├── app.py          # Flask 应用工厂 + 调度器
│   ├── db.py           # SQLite 建表 / 连接
│   ├── routes.py       # API 路由
│   ├── data/           # 行情抓取 / 缓存 / 选股
│   ├── trading/        # 策略 / 回测 / 风控 / 交易引擎
│   └── review/         # 复盘 / 风险指标
├── static/             # 前端页面 (原生 JS)
└── data/               # 运行时生成的 SQLite 库（已 gitignore）
```

> 每个文件的详细职责、数据库表结构、请求流转示例见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 说明

- **数据库自动生成**：`data/quant.db` 会在首次运行时自动创建，无需手动初始化。
- **雪球情绪功能（可选）**：如需舆情抓取的登录态，在项目根目录放置 `xueqiu_cookies.json`（该文件已被 gitignore，不会提交）。不配置也能正常运行，仅影响情绪数据完整度。
- **无鉴权**：任何能访问端口的人都可操作模拟盘。对外分享请用 `READONLY=true` 起一个只读实例。

Co-Authored-By: Claude Code <noreply@anthropic.com>
