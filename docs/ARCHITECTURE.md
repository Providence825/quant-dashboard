# 项目架构说明 (Architecture)

本地运行的 **A 股模拟盘 + 策略研究系统**。用真实行情驱动一个虚拟账户，跑多套交易策略、做历史回测、记录并复盘交易。纯本地单用户，数据存在本机，不碰真钱。

## 一、技术框架

| 层 | 用什么 | 说明 |
|---|---|---|
| 后端 | **Flask 3** | 单进程 Web 服务，`run.py` 启动 |
| 定时任务 | **APScheduler** | 盘中定时扫描信号、自动模拟交易 |
| 数据处理 | **pandas / numpy** | K 线指标、回测计算 |
| 数据源 | **新浪财经 HTTP 接口**（主）+ AKShare（fallback） | 免费，无需 API key |
| 数据库 | **SQLite**（内置，零配置） | 见下方 |
| 前端 | **原生 HTML + JS**（无框架） | `static/` 下，单页 + 多个 JS 模块 |

架构是经典的**前后端分离单体**：浏览器 → Flask 提供的 REST API（`/api/*`）→ 数据层（实时抓行情）/ 交易层（策略+账户）/ SQLite。

## 二、数据库

- **位置**：`data/quant.db`（项目根目录下的 `data/` 文件夹，**首次启动自动创建**）
- **类型**：SQLite，WAL 模式（会额外生成 `quant.db-wal`、`quant.db-shm`）
- **建表逻辑**：全部在 `server/db.py` 的 `init_db()` 里，启动时自动执行，已存在则跳过
- **主要的表**：
  - `account` / `positions` / `orders` / `trade_log` — 账户、持仓、委托、成交流水
  - `stocks` / `stock_kline_daily` — 股票列表、日线历史（回测数据底稿）
  - `screener_results` / `watchlist` — 选股结果、自选股
  - `daily_review` / `asset_snapshot` — 每日复盘、资产曲线
  - `daily_sentiment` / `market_notes` — 市场情绪、机构调研笔记
  - `backtest_runs` — 回测任务记录
- ⚠️ 这个库装的是**私人模拟盘数据**，已加进 `.gitignore`，开源不会外泄。

## 三、目录 / 文件职责

### 根目录
| 文件 | 作用 |
|---|---|
| `run.py` | **入口**。读 `.env` → 创建 app → 启动服务 |
| `.env` | 配置（端口/初始资金/止盈止损），**不提交** |
| `requirements.txt` | 依赖清单 |
| `data/quant.db` | SQLite 数据库（自动生成） |
| `start_dashboard.bat` / `.vbs` | Windows 一键启动 / 后台静默启动脚本 |

### `server/` — 后端核心
| 文件 | 作用 |
|---|---|
| `app.py` | **应用工厂**。建 app、初始化库、注册路由、启动预加载线程和调度器；含 `READONLY` 只读模式开关 |
| `db.py` | 数据库连接 + 所有建表语句（`init_db`） |
| `routes.py` | **所有 REST API 路由**（`/api/market/*`、`/api/stock/*`、选股、回测等），前端全靠它 |

### `server/data/` — 数据层（抓行情、算指标）
| 文件 | 作用 |
|---|---|
| `fetcher.py` | **数据总入口**。新浪接口抓实时行情/K线/指数，判断交易日与交易时段 |
| `cache.py` | 内存缓存（带 TTL），减少重复请求 |
| `importer.py` | 批量导入/回补日线历史到数据库（回测数据来源） |
| `indicators.py` | 技术指标计算（均线、MACD、量比等） |
| `patterns.py` | K 线形态识别 |
| `screener.py` | 选股器（多级条件筛选） |
| `sectors.py` | 行业板块数据 / 热力图 |
| `sentiment.py` / `sentiment_fetcher.py` / `content_fetcher.py` | 市场情绪：抓热帖/新闻，可选雪球 cookie |
| `demo.py` | 演示用假数据 |

### `server/trading/` — 交易层（策略、账户、回测）
| 文件 | 作用 |
|---|---|
| `account.py` | 账户与持仓管理，佣金/印花税常量 |
| `engine.py` | **撮合引擎**。执行模拟买卖、更新账户 |
| `strategy.py` | 策略总调度，汇总各策略的买卖信号 |
| `risk.py` | 风控：仓位上限、止损校验 |
| `market_regime.py` | 市场环境判断（强/弱市），推荐对应策略 |
| `scheduler.py` | **定时任务**。盘中定时扫描、自动模拟交易 |
| `backtest.py` | **历史回测引擎**。逐日回放，复用实盘策略函数，防未来函数 |
| `sentiment.py` | 情绪对交易的影响（逆向调仓） |

### `server/trading/strategies/` — 四套具体策略
| 文件 | 策略 |
|---|---|
| `short_term.py` | 短线（尾盘捡漏、龙头战法、分时回归、逆向做 T） |
| `trend.py` | 趋势波段 |
| `lai_qu.py` | 来去由心 |
| `congling.py` | 从零大 A |

### `server/review/` — 复盘分析
| 文件 | 作用 |
|---|---|
| `daily.py` | 每日复盘生成 |
| `journal.py` | 交易日志 |
| `stats.py` | 胜率、盈亏统计 |
| `risk_metrics.py` | 风险指标（最大回撤、夏普等） |

### `static/` — 前端
- `index.html` — 单页主界面
- `js/dashboard.js` — 盯盘大屏主逻辑
- `js/strategies.js` / `backtest.js` / `screener.js` / `positions.js` / `review.js` / `datacenter.js` / `watchlist.js` / `charts.js` / `kline-modal.js` — 各功能页面对应模块
- `css/dashboard.css` — 样式

## 四、一次请求怎么流转（举例）

打开首页看盯盘大屏：
```
浏览器 → GET /api/market/index (routes.py)
       → fetcher.get_index_data() 查缓存
       → 缓存过期则请求新浪接口 → 存入 cache → 返回 JSON
       → dashboard.js 渲染
```

盘中自动交易：
```
APScheduler 定时触发 (scheduler.py)
  → 判断是否交易时段 (fetcher)
  → strategy.py 汇总各策略信号
  → risk.py 风控校验
  → engine.py 执行模拟买卖 → 写入 SQLite
```
