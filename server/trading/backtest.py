"""
Event-driven historical backtest engine (历史回测引擎).

账户1已改用板块动量策略，回测引擎同步调整为板块动量逻辑。
保留原有的trend/short_term/lai_qu/congling代码用于历史对比参考。

Replays strategies day-by-day over locally-stored daily K-line, reusing the
SAME candidate-selection functions the live system uses (so a backtest exercises
the real strategy logic, not a re-implementation).

Design notes / honest limitations (近似回测):
- History only has OHLCV. Realtime-only fields (换手率 turnover, PE) cannot be
  reconstructed. Turnover is APPROXIMATED from volume ratio; PE filters are
  effectively skipped (get_financial_data returns {} during backtest).
- Point-in-time correctness (防未来函数): on day T, strategies only ever see
  bars with date <= T. This is enforced by monkeypatching fetcher during the run.
- Intraday strategies (分时回归 VWAP / 逆向做T) produce nothing — they need
  minute data we don't store.
- Fills use day-T CLOSE price. Commission + stamp tax mirror account.py.

板块动量回测参数 (与账户2/实盘一致):
- 止损5%/止盈12%/移动止盈3%/最长5日
- 单仓10%/总仓90%/最多8只
- 每次扫描取当日强度 top-3 板块，每板块选涨幅+量比综合评分最高的 top-2 只
- 板块排名跌出第6位时提前退出
"""

import json
import threading
import time
from datetime import datetime

from ..db import get_db
from ..data import fetcher
from .account import COMMISSION_RATE, STAMP_TAX_RATE
# 账户1改用板块动量，回测引擎同步
from .strategies.sector_momentum import SECTOR_ACCT2_PARAMS
from ..review.risk_metrics import compute_metrics

_bt_lock = threading.Lock()

# 板块动量回测参数 (与 SECTOR_ACCT2_PARAMS 一致)
MIN_HISTORY = 120           # bars needed before a stock is tradable (MA120)
DEFAULT_UNIVERSE_LIMIT = 300
DEFAULT_MAX_POSITIONS = SECTOR_ACCT2_PARAMS['max_positions']  # 8只
# Universe liquidity ranking window (fixed → reproducible; see _liquidity_window)
# 流动性选池只用 start_date 之前的这么多根K线做排名。锁在回测起点之前 →
# (1) 池子成员不受之后的每日同步/补抓影响 → 回测可复现;
# (2) 修掉前视偏差:旧逻辑用含回测区间的全历史均值选池,等于提前知道哪些股
#     在回测期会放量。若起点前数据不足,回退到最早窗口选池(并在结果里标注)。
LIQUIDITY_LOOKBACK = 120    # trading days used to rank liquidity
MIN_LIQ_BARS = 20           # min bars in that window for a stock to qualify

# ── Market-gate defaults (复盘 2026-03-11~04-03 大回撤引入) ─────────────
# 弱市里满仓追突破是那段 -20% 回撤的根因。RISK_OFF 时只放行"回踩/低吸"类,
# 并把总持仓压到防御档;板块软限仓防止扎堆同一赛道被反复踩。
DEFAULT_MARKET_FILTER = True
DEFAULT_SECTOR_CAP = 3          # 同一已知板块最多持仓数 (未知板块不限)
DEFAULT_DEFENSIVE_MAX_POS = 2   # RISK_OFF 时的持仓上限

# ── 实盘贴近度 (老师第5点:回测与实盘差距) ─────────────────────────────
# 旧回测按收盘价、无限量成交,偏乐观。滑点:买入价上浮、卖出价下浮 (单边)。
# 成交量约束:单日成交不超过当日成交量的 PARTICIPATION,超出截断 (买不满/卖分批)。
DEFAULT_SLIPPAGE = 0.002        # 单边滑点 0.2% (小数)
DEFAULT_PARTICIPATION = 10.0    # 单日最多吃当日成交量的 10% (百分数, 与 cap 公式的 /100 对应)

# ── 情绪闸门 (老师第4点:情绪模块在A股有效性存疑, A/B 验证用) ──────────────
# 照搬实盘 should_buy 的"宽度恐慌"闸门:
#   当日涨跌家数比 <30 (恐慌) → 总持仓上限压到 SENTIMENT_PANIC_MAX_POS。
# 注意:实盘 should_buy 还有一层"雪球文本情绪 phase"(euphoria/greed/capitulation),
# 那层依赖实盘每天抓的 daily_sentiment 表,历史回测期无数据、且读表会把当日情绪
# 泄漏进历史(前视污染),故回测里不参与——只有可从当日行情重构的宽度恐慌层生效。
#
# 默认值按策略模式区分 (2026-07-17 IS/OOS 样本外 A/B 结论):
#   lai_qu(情绪/题材驱动): 闸门有益 → 弱市 +17.4pp、强市不伤收益、两窗口都降回撤。默认开。
#   trend(趋势跟随): 闸门有害 → 恐慌日恰是反弹起涨点,拦掉核心买点,强市 -33.6pp。默认关。
#   其余(short_term/congling/all): 未做样本外验证,保守默认关。
# 显式传 params['sentiment_gate'] 覆盖此默认 (AB 对比用)。
SENTIMENT_GATE_DEFAULT_BY_MODE = {
    'lai_qu': True,
    'trend': False,
    'short_term': False,
    'congling': False,
    'all': False,
}
SENTIMENT_PANIC_THRESHOLD = 30   # 宽度情绪分 <此值 视为恐慌 (与 strategy._get_sentiment 同口径)
SENTIMENT_PANIC_MAX_POS = 0.40   # 恐慌时总持仓上限 (与 strategy.should_buy 同值)

_TREND = ['均线多头突破', '通道突破', '均线回踩', '海龟通道突破']
_LAIQU = ['趋势买点1·底部建仓', '趋势买点2·M60突破', '趋势买点3·回踩重仓',
          '龙头2进3板', '卡位龙头', '补涨龙', '板块最强前排']
_CONGLING = ['关键位突破', '假突破检测', '延续性龙头', '盘面强弱', '科学加仓']

# 突破/追涨型策略:市场 risk_off 时暂停买入(复盘结论:弱市追突破=送钱)。
# 回踩/低吸型不在此列,弱市仍可小仓低吸支撑位。
_BREAKOUT_STRATEGIES = {
    '均线多头突破', '通道突破', '海龟通道突破',
    '关键位突破', '延续性龙头', '龙头2进3板', '补涨龙', '板块最强前排',
    '趋势买点2·M60突破',
    '盘面强弱',  # 纯动量追涨，弱市比延续性龙头更不适合做多
}

# 弱市里仍可低吸的"防御型"买点(回踩/底部建仓)。其余一律视为追涨/突破,
# RISK_OFF 时暂停,直接对应复盘根因(追假突破 + 连环止损换股)。
_DEFENSIVE_STRATEGIES = {'均线回踩', '趋势买点1·底部建仓'}

# 历史回测数据确认：以下策略在所有区间均为负贡献，直接排除。
_EXCLUDED_STRATEGIES = {'通道突破', '趋势买点3·回踩重仓', '卡位龙头', '补涨龙', '均线回踩'}

# 权益回撤门控：当日权益从历史高点回落超此比例，暂停全部新买入。
EQUITY_DD_GATE = 0.20

# 趋势买点3 每日买入上限（防止同天连进4-5笔同类低分信号）
BP3_DAILY_LIMIT = 2
# 趋势买点3 score门槛：保持原始40，score公式在此策略上不单调，不用于过滤
BP3_MIN_SCORE = 40

# ── 凯利仓位 + 塔勒布杠铃分仓 ───────────────────────────────────────────────
# 半凯利(0.5)：全凯利在实盘过于激进，半凯利平衡增长与回撤。
KELLY_FRACTION = 0.5
# 单仓绝对上限：防止孤注一掷(full Kelly 集中度)。
KELLY_CAP = 0.30
# 塔勒布杠铃：防御型超配 × 1.3，突破型低配 × 0.6，其余 × 1.0。
# 与 regime 门控叠加：mild_risk_off 突破类再减半 → 实际 × 0.30。
BARBELL_DEFENSIVE = 1.3
BARBELL_BREAKOUT  = 0.6

# ── 闲置资金收益（模拟货币基金/逆回购）────────────────────────────────────────
CASH_ANNUAL_RATE = 0.02        # 2% 年化，按自然日复利

# ── 超跌反弹策略（severe_risk_off 专用）────────────────────────────────────────
OVERSOLD_DROP_5D     = 0.15    # 5 个交易日跌幅触发阈值
OVERSOLD_MAX_POS     = 1       # 同时最多持有超跌仓数
OVERSOLD_BUDGET_RATIO = 0.5    # 相对正常仓位的资金比例


# 板块动量回测不使用策略参数切换，统一使用 SECTOR_ACCT2_PARAMS
# 保留 _params_for 用于历史对比参考（但当前回测不调用）


def _liquidity_window(db, start_date):
    """
    Fixed date window used to RANK liquidity for universe selection.
    Anchored at the OLD end of the data so it never shifts when new bars are
    appended by the daily sync (that's what made backtests non-reproducible).

    Preferred: the LIQUIDITY_LOOKBACK trading days immediately BEFORE start_date
    (point-in-time correct — no lookahead into the backtest window).
    Fallback: if there is no (or too little) pre-start data, use the EARLIEST
    LIQUIDITY_LOOKBACK trading days on record. Still stable against appends,
    but ranks on in-window data — flagged in the result so the caller can note it.

    Returns (win_start, win_end, used_fallback).
    """
    pre = db.execute(
        "SELECT DISTINCT date FROM stock_kline_daily WHERE date < ? ORDER BY date DESC LIMIT ?",
        (start_date, LIQUIDITY_LOOKBACK)).fetchall()
    dates = sorted(r['date'] for r in pre)
    if len(dates) >= MIN_LIQ_BARS:
        return dates[0], dates[-1], False
    # Fallback: earliest bars on record.
    early = db.execute(
        "SELECT DISTINCT date FROM stock_kline_daily ORDER BY date ASC LIMIT ?",
        (LIQUIDITY_LOOKBACK,)).fetchall()
    edates = sorted(r['date'] for r in early)
    if not edates:
        return None, None, True
    return edates[0], edates[-1], True


def _load_universe(start_date, end_date, universe_limit, fundamental_filter=True):
    """
    Load daily bars for a subset of stocks into memory.
    Returns (bars_by_code, name_by_code, all_dates, used_fallback).
    bars_by_code[code] = [{date,open,high,low,close,volume}, ...] chronological,
    covering enough history BEFORE start_date to warm up indicators.

    Universe membership is ranked over a FIXED liquidity window (see
    _liquidity_window) so the same params reproduce the same result regardless
    of later data syncs, and so selection can't peek at in-window volume.

    fundamental_filter=True: keep only stocks where the most recent report
    (ann_date <= start_date) has ROE>=8% AND profit_yoy>0. Stocks with no
    fundamental data on record are kept (soft constraint).
    """
    db = get_db()
    try:
        win_start, win_end, used_fallback = _liquidity_window(db, start_date)
        if win_start is None:
            return {}, {}, [], used_fallback
        # Pick liquid names: rank by avg turnover-value (close*volume) over the
        # FIXED window [win_start, win_end] — stable against future appends.
        rows = db.execute(
            """
            SELECT stock_code, AVG(close*volume) AS liq, COUNT(*) AS n
            FROM stock_kline_daily
            WHERE date >= ? AND date <= ?
            GROUP BY stock_code
            HAVING n >= ?
            ORDER BY liq DESC
            LIMIT ?
            """,
            (win_start, win_end, MIN_LIQ_BARS, universe_limit),
        ).fetchall()
        codes = [r['stock_code'] for r in rows]
        if not codes:
            return {}, {}, [], used_fallback

        if fundamental_filter and codes:
            phs = ','.join('?' * len(codes))
            fund_rows = db.execute(
                f"""SELECT f.stock_code, f.roe, f.profit_yoy
                    FROM stock_fundamentals f
                    INNER JOIN (
                        SELECT stock_code, MAX(report_date) AS max_rd
                        FROM stock_fundamentals
                        WHERE stock_code IN ({phs}) AND ann_date <= ?
                        GROUP BY stock_code
                    ) best ON f.stock_code=best.stock_code AND f.report_date=best.max_rd""",
                codes + [start_date],
            ).fetchall()
            has_data = {r['stock_code'] for r in fund_rows}
            quality = {r['stock_code'] for r in fund_rows
                       if r['roe'] is not None and r['roe'] > 0}
            # no data → keep (soft); has data → must pass quality gate
            codes = [c for c in codes if c not in has_data or c in quality]

        name_by_code = {}
        nrows = db.execute(
            "SELECT code, name FROM stocks WHERE code IN (%s)" % ",".join("?" * len(codes)),
            codes,
        ).fetchall()
        for r in nrows:
            name_by_code[r['code']] = r['name']

        bars_by_code = {}
        all_dates = set()
        placeholders = ",".join("?" * len(codes))
        krows = db.execute(
            "SELECT stock_code, date, open, high, low, close, volume "
            "FROM stock_kline_daily WHERE stock_code IN (%s) AND date <= ? "
            "ORDER BY stock_code, date" % placeholders,
            codes + [end_date],
        ).fetchall()
        for r in krows:
            bars_by_code.setdefault(r['stock_code'], []).append({
                'date': r['date'], 'open': r['open'], 'high': r['high'],
                'low': r['low'], 'close': r['close'], 'volume': r['volume'],
            })
            if start_date <= r['date'] <= end_date:
                all_dates.add(r['date'])
        return bars_by_code, name_by_code, sorted(all_dates), used_fallback
    finally:
        db.close()


def _load_index_series(end_date):
    """
    Load Shanghai Composite close series (date->close) up to end_date from
    index_snapshot. Used to gate buys by market regime, point-in-time safe
    (only dates <= the bar being processed are ever read).
    """
    db = get_db()
    try:
        rows = db.execute(
            "SELECT date, sh_close FROM index_snapshot "
            "WHERE date <= ? AND sh_close IS NOT NULL ORDER BY date",
            (end_date,)).fetchall()
    finally:
        db.close()
    series = [(r['date'], float(r['sh_close'])) for r in rows if r['sh_close']]
    dates = [d for d, _ in series]
    closes = [c for _, c in series]
    idx = {d: i for i, d in enumerate(dates)}
    return {'dates': dates, 'closes': closes, 'idx': idx}


def _market_regime_at(index_series, day):
    """
    Point-in-time market regime from the SH index as of `day`.
    Returns 'risk_on' | 'neutral' | 'risk_off'.

    risk_off  = 指数跌破 MA60,  或 跌破 MA20 且 MA20 下行  (明确走弱)
    risk_on   = 指数在 MA20/MA60 上方且 MA20 上行            (健康趋势)
    neutral   = 其余

    找不到当日或历史不足时返回 'neutral' (不误伤)。
    """
    idx = index_series['idx'].get(day)
    if idx is None:
        # 用 <= day 的最近一根 (指数交易日与个股一致,通常命中;稳妥兜底)
        import bisect
        pos = bisect.bisect_right(index_series['dates'], day) - 1
        if pos < 0:
            return 'neutral'
        idx = pos
    if idx < 60:
        return 'neutral'
    closes = index_series['closes']
    price = closes[idx]
    ma20 = sum(closes[idx - 19:idx + 1]) / 20
    ma60 = sum(closes[idx - 59:idx + 1]) / 60
    ma20_5d_ago = sum(closes[idx - 24:idx - 4]) / 20 if idx >= 24 else ma20
    ma20_up = ma20 > ma20_5d_ago

    if price < ma60:
        return 'severe_risk_off'
    if price < ma20 and not ma20_up:
        return 'mild_risk_off'
    if price > ma20 and price > ma60 and ma20_up:
        return 'risk_on'
    return 'neutral'


def _load_sector_map(codes):
    """code -> sector (only for codes that have a non-empty sector)."""
    if not codes:
        return {}
    db = get_db()
    try:
        placeholders = ",".join("?" * len(codes))
        rows = db.execute(
            "SELECT code, sector FROM stocks WHERE code IN (%s)" % placeholders,
            codes).fetchall()
    finally:
        db.close()
    return {r['code']: r['sector'] for r in rows if r['sector']}


def _approx_turnover(bars_slice):
    """
    Approximate turnover% from volume ratio (no float-share data available).
    Maps today's volume vs 20-day avg into a plausible 2-15% band so that
    turnover-gated strategies (turtle/channel/dragon) can still fire.
    """
    if len(bars_slice) < 21:
        return 5.0
    today = bars_slice[-1]['volume']
    avg20 = sum(b['volume'] for b in bars_slice[-21:-1]) / 20
    if avg20 <= 0:
        return 5.0
    vr = today / avg20
    turn = 3.0 * vr  # vr=1 → 3%, vr=3 → 9%
    return max(2.1, min(14.5, turn))


def _precompute_indicators(bars_by_code):
    """
    Pre-compute rolling MA and ATR14 for every (code, date) pair before the
    main backtest loop.  Uses numpy O(N) rolling cumsum — eliminates O(N×period)
    Python-level recomputation inside strategy functions each day.

    Returns pre_ind[code][date] = {ma5, ma10, ma20, ma50, ma60, ma120,
                                    atr14, vol_avg20}.
    ATR14 uses Wilder's EMA to match calc_atr() in data/indicators.py.
    vol_avg20 excludes today (= mean of prev-20 bars, matching strategies'
    sum(volumes[-21:-1]) / 20 pattern).
    """
    try:
        import numpy as np
    except ImportError:
        return {}

    pre_ind = {}
    for code, bars in bars_by_code.items():
        if not bars:
            pre_ind[code] = {}
            continue
        n = len(bars)
        dates   = [b['date']   for b in bars]
        closes  = np.array([b['close']  for b in bars], dtype=np.float64)
        highs   = np.array([b['high']   for b in bars], dtype=np.float64)
        lows    = np.array([b['low']    for b in bars], dtype=np.float64)
        vols    = np.array([b['volume'] for b in bars], dtype=np.float64)

        def _rma(arr, p):
            if n < p:
                return [None] * n
            cs = np.cumsum(arr)
            out = [None] * (p - 1)
            ws = cs[p - 1:].copy()
            ws[1:] -= cs[:n - p]
            out.extend((ws / p).tolist())
            return out

        ma5   = _rma(closes, 5)
        ma10  = _rma(closes, 10)
        ma20  = _rma(closes, 20)
        ma50  = _rma(closes, 50)
        ma60  = _rma(closes, 60)
        ma120 = _rma(closes, 120)
        vol20 = _rma(vols, 20)   # vol20[i] = mean(vols[i-19:i+1])

        # ATR14 — Wilder's EMA, matching calc_atr(highs, lows, closes, 14)
        atr14 = [None] * n
        if n > 14:
            tr = [max(float(highs[i] - lows[i]),
                      abs(float(highs[i] - closes[i - 1])),
                      abs(float(lows[i]  - closes[i - 1])))
                  for i in range(1, n)]          # tr[k] = TR of bar k+1
            first = sum(tr[:14]) / 14             # bars 1-14
            atr14[14] = first
            prev = first
            for k in range(14, n - 1):
                prev = (prev * 13 + tr[k]) / 14
                atr14[k + 1] = prev

        ind_by_date = {}
        for i, date in enumerate(dates):
            ind_by_date[date] = {
                'ma5':      ma5[i],
                'ma10':     ma10[i],
                'ma20':     ma20[i],
                'ma50':     ma50[i],
                'ma60':     ma60[i],
                'ma120':    ma120[i],
                'atr14':    atr14[i],
                # exclude today: mean(vols[i-20:i]) = vol20[i-1]
                'vol_avg20': vol20[i - 1] if i >= 1 else None,
            }
        pre_ind[code] = ind_by_date
    return pre_ind


def _build_pool(bars_by_code, name_by_code, idx_by_code, day, pre_ind=None):
    """
    Point-in-time pool for `day`: {code: {'info':..., 'kline': slice<=day}}.
    Only includes stocks that have a bar exactly on `day` and >= MIN_HISTORY
    bars up to and including it.
    """
    pool = {}
    for code, bars in bars_by_code.items():
        idx = idx_by_code[code].get(day)
        if idx is None or idx + 1 < MIN_HISTORY:
            continue
        sl = bars[:idx + 1]
        cur = sl[-1]
        prev_close = sl[-2]['close'] if len(sl) >= 2 else cur['close']
        change_pct = (cur['close'] / prev_close - 1) * 100 if prev_close > 0 else 0.0
        avg20 = (sum(b['volume'] for b in sl[-21:-1]) / 20) if len(sl) >= 21 else cur['volume']
        vol_ratio = (cur['volume'] / avg20) if avg20 > 0 else 1.0
        info = {
            '代码': code,
            '名称': name_by_code.get(code, code),
            '最新价': cur['close'],
            '涨跌幅': round(change_pct, 2),
            '换手率': round(_approx_turnover(sl), 2),
            '量比': round(vol_ratio, 2),
            '成交量': cur['volume'],
            '成交额': cur['close'] * cur['volume'],
        }
        if pre_ind:
            _ind = (pre_ind.get(code) or {}).get(day)
            if _ind:
                info['_ind'] = _ind
        pool[code] = {'info': info, 'kline': sl}
    return pool


class _PointInTimeFetcher:
    """
    Context manager that redirects fetcher.* to serve ONLY the current day's
    pool data. Restores originals on exit. Guarantees no network + no lookahead
    during signal generation.
    """
    _FUNCS = ['get_stock_list', 'get_kline_data', 'get_financial_data',
              'is_trading_time', 'get_intraday_data', 'get_index_data']

    def __init__(self, pool):
        self.pool = pool
        self._saved = {}

    def __enter__(self):
        for fn in self._FUNCS:
            self._saved[fn] = getattr(fetcher, fn, None)
        kline_by_code = {c: e['kline'] for c, e in self.pool.items()}
        stock_infos = [e['info'] for e in self.pool.values()]

        fetcher.get_stock_list = lambda *a, **k: stock_infos
        fetcher.get_kline_data = lambda code, days=60, *a, **k: (kline_by_code.get(code, [])[-days:] if days else kline_by_code.get(code, []))
        fetcher.get_financial_data = lambda code, *a, **k: {}   # PE unknown in history
        fetcher.is_trading_time = lambda *a, **k: True
        fetcher.get_intraday_data = lambda *a, **k: []
        fetcher.get_index_data = lambda *a, **k: []
        return self

    def __exit__(self, *exc):
        for fn, orig in self._saved.items():
            if orig is not None:
                setattr(fetcher, fn, orig)
        return False


def _gather_signals(mode, pool):
    """
    账户1改用板块动量策略，回测引擎生成板块动量候选信号。
    保留原mode参数用于历史对比（但当前不再使用）。
    """
    from ..data.sectors import compute_sector_strength, stock_matches_sector

    with _PointInTimeFetcher(pool):
        # 计算板块强度（基于当日pool）
        sectors = compute_sector_strength()
        if not sectors:
            return []

        params = SECTOR_ACCT2_PARAMS
        top_sectors = sectors[:params['top_sectors']]

        flat = []
        for rank, sec in enumerate(top_sectors):
            sec_name = sec['name']
            sec_stocks = []

            for code, entry in pool.items():
                info = entry['info']
                name = info.get('名称', '')
                price = float(info.get('最新价', 0))

                # 过滤ST/退市/低价
                if price < params['min_price'] or 'ST' in name or '退' in name:
                    continue

                # 板块匹配
                if not stock_matches_sector(name, sec_name):
                    continue

                change = float(info.get('涨跌幅', 0))
                vol_ratio = float(info.get('量比', 0))

                if change < params['min_change_pct'] or vol_ratio < params['min_vol_ratio']:
                    continue

                score = round(change * 5 + vol_ratio * 8, 1)
                sec_stocks.append({
                    'stock_code': code,
                    'stock_name': name,
                    'score': score,
                    'strategy': '板块动量',
                    'signal_detail': {
                        'sector': sec_name,
                        'sector_rank': rank + 1,
                        'change_pct': change,
                        'vol_ratio': vol_ratio,
                        'price': price,
                    }
                })

            sec_stocks.sort(key=lambda x: x['score'], reverse=True)
            flat.extend(sec_stocks[:params['stocks_per_sector']])

        flat.sort(key=lambda x: x['score'], reverse=True)
        return flat[:params['max_positions']]


def _exit_decision(pos, price, hold_days):
    """
    板块动量回测退出规则：止损5%/止盈12%/移动止盈3%/最长5日。
    与 should_exit_sector_position 对齐（无板块排名检查，回测无实时板块数据）。
    """
    params = SECTOR_ACCT2_PARAMS
    cost = pos['avg_cost']
    highest = pos['highest_price']
    change = (price / cost - 1) if cost > 0 else 0
    from_high = (price / highest - 1) if highest > 0 else 0

    if change <= -params['stop_loss_pct']:
        return f"板块动量止损({change*100:.1f}%)"
    if change >= params['take_profit_pct']:
        return f"板块动量止盈({change*100:.1f}%)"
    if highest > cost * (1 + params['take_profit_pct']) and from_high <= -params['trailing_stop_pct']:
        return f"板块动量移动止盈(最高{highest:.2f}回撤{from_high*100:.1f}%)"
    if hold_days >= params['max_hold_days']:
        return f"板块动量到期({hold_days}天)"
    return None


def _breadth_sentiment(pool):
    """当日宽度情绪分 0~100 (涨跌家数比), 口径同 strategy._get_sentiment。
    仅用当日 pool 的涨跌幅, 无前视。pool 为空时返回中性 50。"""
    up = down = 0
    for e in pool.values():
        chg = float(e.get('info', {}).get('涨跌幅', 0))
        if chg > 0:
            up += 1
        elif chg < 0:
            down += 1
    total = max(up + down, 1)
    return min(100, max(0, round(up / total * 100)))


# ── 机制A 回测复现 (老师第5点:策略切换滞后 A/B) ──────────────────────────
# 模拟盘用 market_regime.detect_regime() 在 trend/short_term 间切换策略模式,
# 切换要连续 N 天(现网 3)同信号才生效(_apply_confirmation)。回测里原本没接这套
# (回测 mode 整段固定)。这里逐日、无前视地复现 A 的 regime 判定 + 可配置确认窗口,
# 才能样本外对比"3天确认 vs 更快切换"的收益/回撤。
# 复用 market_regime.score_regime (打分公式单一来源,live/backtest 不会漂移)。

def _load_index_ohlc(end_date, index_code='000001'):
    """Load index daily OHLC (date->bar) up to end_date from index_kline_daily.
    Point-in-time safe: 只读 <= 处理日的bar。返回 {'dates':[...], 'bars':[...], 'idx':{date:i}}。"""
    db = get_db()
    try:
        rows = db.execute(
            "SELECT date, open, high, low, close, volume FROM index_kline_daily "
            "WHERE index_code=? AND date <= ? ORDER BY date",
            (index_code, end_date)).fetchall()
    finally:
        db.close()
    bars = [{'date': r['date'], 'open': r['open'], 'high': r['high'],
             'low': r['low'], 'close': r['close'], 'volume': r['volume']} for r in rows]
    dates = [b['date'] for b in bars]
    return {'dates': dates, 'bars': bars, 'idx': {d: i for i, d in enumerate(dates)}}


def _regime_reco_at(index_ohlc, day, breadth):
    """Point-in-time regime recommendation ('trend'|'short_term') as of `day`.
    喂给 score_regime 的是 <= day 的最近 120 根指数OHLC + 当日宽度分(由 pool 重构)。
    指数无当日bar时取 <= day 最近一根;历史不足120根时用现有全部(与live首日行为一致)。"""
    import bisect
    idx = index_ohlc['idx'].get(day)
    if idx is None:
        pos = bisect.bisect_right(index_ohlc['dates'], day) - 1
        if pos < 0:
            return 'short_term', None
        idx = pos
    window = index_ohlc['bars'][max(0, idx - 119):idx + 1]
    if len(window) < 30:
        return 'short_term', None
    from .market_regime import score_regime
    s = score_regime(window, breadth)
    return s['recommended'], s


def _confirm_mode(history, confirm_days, current_active):
    """确认窗口: 最近 confirm_days 个 raw 推荐全部一致且与当前不同才切换,否则保持。
    confirm_days=1 → 即时切换(无滞后)。history 是 raw 推荐列表(旧→新), 已含今日。"""
    if len(history) < confirm_days:
        return current_active
    recent = history[-confirm_days:]
    if all(r == recent[0] for r in recent):
        return recent[0]
    return current_active


def _run(run_id, params):
    start = params['start_date']
    end = params['end_date']
    mode = params['strategy_mode']
    capital = float(params['initial_capital'])
    max_pos = int(params['max_positions'])
    uni = int(params['universe_limit'])
    # 风控开关 (默认开启; AB对比时可关闭复现旧行为)
    market_filter = bool(params.get('market_filter', True))
    sector_cap = int(params.get('sector_cap', 3))            # 同板块最多持仓数 (0=不限)
    defensive_max_pos = int(params.get('defensive_max_positions', 2))  # risk_off 时最大持仓
    # 实盘贴近度 (0 = 关闭, 用于 AB 对比复现旧的乐观口径)
    slippage = float(params.get('slippage', DEFAULT_SLIPPAGE))
    participation_rate = float(params.get('participation', DEFAULT_PARTICIPATION))
    # 情绪闸门 (老师第4点 A/B 验证): 显式传参优先, 否则按策略模式取默认。
    if 'sentiment_gate' in params:
        sentiment_gate = bool(params['sentiment_gate'])
    else:
        sentiment_gate = SENTIMENT_GATE_DEFAULT_BY_MODE.get(mode, False)
    # ML 信号过滤: p_up < ml_filter_threshold 的候选直接跳过。
    # 依赖 xgb_scorer (有模型时用 XGBoost, 无模型回退贝叶斯胜率)。
    # 默认关闭, 传 ml_filter=true 开启; 样本不足时自动降级不报错。
    ml_filter = bool(params.get('ml_filter', False))
    ml_threshold = float(params.get('ml_filter_threshold', 0.45))
    fundamental_filter = bool(params.get('fundamental_filter', True))

    # ── auto 模式 (老师第5点:regime 逐日在 trend/short_term 间切换) ──────────
    # mode=='auto' 时复现模拟盘机制A:逐日算 regime 推荐,连续 confirm_days 天同信号
    # 才切换当日策略模式。confirm_days=1=即时(无滞后),3=现网口径。A/B 用。
    auto_mode = (mode == 'auto')
    confirm_days = int(params.get('confirm_days', 3))
    regime_index_code = params.get('regime_index_code', '000001')

    bars_by_code, name_by_code, all_dates, universe_fallback = _load_universe(start, end, uni, fundamental_filter)
    if not all_dates:
        _finish(run_id, error='选定区间内没有可用的本地K线数据')
        return

    idx_by_code = {}
    for code, bars in bars_by_code.items():
        idx_by_code[code] = {b['date']: i for i, b in enumerate(bars)}
    close_by_code_date = {
        code: {b['date']: b['close'] for b in bars} for code, bars in bars_by_code.items()
    }
    vol_by_code_date = {
        code: {b['date']: b['volume'] for b in bars} for code, bars in bars_by_code.items()
    }
    # Pre-compute MA / ATR for all stocks before the main loop so strategy
    # functions can do O(1) dict lookups instead of O(period) Python sums.
    pre_ind = _precompute_indicators(bars_by_code)
    index_series = _load_index_series(end) if market_filter else None
    sector_by_code = _load_sector_map(list(bars_by_code.keys())) if sector_cap > 0 else {}
    # ML 评分器预加载 (避免在买入热循环里反复 import)
    _ml_score_fn = None
    if ml_filter:
        try:
            from .ml.xgb_scorer import score_signal as _ml_score_fn
        except Exception:
            pass
    # 凯利仓位: 预加载 strategy × regime → kelly_f 映射 (来自 ml_winrate_cache)
    kelly_cache = {}
    _kdb = get_db()
    try:
        _krows = _kdb.execute(
            'SELECT strategy, regime, kelly_f FROM ml_winrate_cache').fetchall()
        for r in _krows:
            kelly_cache[(r['strategy'], r['regime'])] = float(r['kelly_f'])
    except Exception:
        pass
    finally:
        _kdb.close()

    regime_days = {'risk_on': 0, 'neutral': 0, 'mild_risk_off': 0, 'severe_risk_off': 0}
    # 情绪闸门触发统计: panic_days=当日恐慌天数, panic_blocked=因恐慌限仓被拦下的建仓次数
    sentiment_days = {'panic': 0, 'normal': 0, 'blocked': 0}
    # auto 模式状态: 指数OHLC(点内安全)、raw推荐历史、当前生效模式、切换次数、各模式在市天数
    index_ohlc = _load_index_ohlc(end, regime_index_code) if auto_mode else None
    regime_reco_history = []           # raw 推荐(trend/short_term)逐日, 旧→新
    active_mode = 'short_term'         # 首日默认(与 live _apply_confirmation 未满窗口时一致)
    auto_switches = 0
    auto_mode_days = {'trend': 0, 'short_term': 0}   # auto 各模式在市天数

    cash = capital
    peak_equity = capital  # 权益高水位，用于回撤门控
    severe_consecutive = 0  # 连续 severe_risk_off 天数，用于持续熊市识别
    positions = {}   # code -> {shares, avg_cost, highest_price, buy_date, strategy, params, can_sell_date}
    equity = []
    trades = []
    total_days = len(all_dates)
    # 超跌反弹用：每个code的bar日期列表（已排序），避免每日遍历
    from bisect import bisect_right as _bisect_right
    _bars_dates = {code: [b['date'] for b in bars] for code, bars in bars_by_code.items()}
    # 预导入，避免在买入热循环里反复 import（Python import 缓存但仍有 dict 查找开销）
    _log_signal_fn = None
    try:
        from .ml.signal_log import log_signal as _log_signal_fn
    except Exception:
        pass
    # 凯利均值预计算（kelly_cache 在回测期内不变）
    _kf_avg = (sum(kelly_cache.values()) / len(kelly_cache)) if kelly_cache else 0.0

    for di, day in enumerate(all_dates):
        pool = _build_pool(bars_by_code, name_by_code, idx_by_code, day, pre_ind)
        # 当日 datetime 对象：sell 循环 hold_days 计算用，避免每持仓每日都 strptime
        day_dt = datetime.strptime(day, '%Y-%m-%d')

        # mark-to-market highest for holdings present today
        for code, pos in positions.items():
            px = close_by_code_date.get(code, {}).get(day)
            if px:
                pos['highest_price'] = max(pos['highest_price'], px)

        # ── 提前计算 regime（卖出循环需要用，移到 SELL 前）─────────────────
        regime = _market_regime_at(index_series, day) if index_series else 'neutral'
        if regime == 'severe_risk_off':
            severe_consecutive += 1
        else:
            severe_consecutive = 0

        # ── SELL first ────────────────────────────────────────────────
        for code in list(positions.keys()):
            pos = positions[code]
            px = close_by_code_date.get(code, {}).get(day)
            if not px:
                continue
            if day < pos['can_sell_date']:   # T+1
                continue
            hold_days = (day_dt - pos['buy_date_dt']).days
            # severe_risk_off 强制平仓突破类策略：牛市买的追涨仓在熊市不等止损，主动退出
            if (market_filter and regime == 'severe_risk_off'
                    and pos['strategy'] in _BREAKOUT_STRATEGIES):
                reason = f"regime清仓(severe_risk_off,{hold_days}天)"
            else:
                reason = _exit_decision(pos, px, hold_days)
            if not reason:
                continue
            # 成交量约束: 单日最多吃当日成交量的 participation_rate。卖不完则分批,
            # 剩余仓位留到下一交易日继续(此后每天只要仍在持仓就再次触发退出判断)。
            day_vol = vol_by_code_date.get(code, {}).get(day, 0)
            sell_shares = pos['shares']
            partial = False
            if participation_rate > 0 and day_vol > 0:
                cap = int(day_vol * participation_rate / 100) * 100
                if cap < sell_shares:
                    sell_shares = cap
                    partial = True
            if sell_shares < 100:
                continue  # 当日流动性吃不下最小一手, 顺延
            # 滑点: 卖出实际成交价 = 收盘价 × (1 - 滑点)
            fill_px = px * (1 - slippage)
            amount = sell_shares * fill_px
            commission = max(COMMISSION_RATE * amount, 5)
            stamp = STAMP_TAX_RATE * amount
            proceeds = amount - commission - stamp
            cost = pos['avg_cost'] * sell_shares
            buy_commission = max(COMMISSION_RATE * cost, 5)
            total_cost = cost + buy_commission
            pnl = proceeds - total_cost
            cash += proceeds
            trades.append({
                'date': day, 'stock_code': code, 'stock_name': pos['stock_name'],
                'direction': 'sell', 'price': round(fill_px, 2), 'shares': sell_shares,
                'pnl_amount': round(pnl, 2),
                'pnl_pct': round((proceeds / total_cost - 1) * 100, 2) if total_cost > 0 else 0,
                'strategy': pos['strategy'],
                'reason': reason + ('·分批(量限)' if partial else ''),
            })
            if partial:
                pos['shares'] -= sell_shares   # 剩余留到下一日继续卖
            else:
                del positions[code]

        # ── market regime gate (point-in-time, no lookahead) ─────────
        # regime 已在 SELL 前计算好，这里只做统计和 effective_max 调整
        regime_days[regime] = regime_days.get(regime, 0) + 1
        # risk_off 时收紧总持仓上限,只留防守型策略的建仓空间
        if market_filter and regime == 'severe_risk_off':
            effective_max = defensive_max_pos
        elif market_filter and regime == 'mild_risk_off':
            effective_max = max(max_pos - 1, defensive_max_pos)  # 轻度调整: 少一个槽
        else:
            effective_max = max_pos

        # 当日宽度分: auto 模式(regime判定)与情绪闸门都要用, 只算一次(无前视, 仅当日pool)。
        breadth = _breadth_sentiment(pool) if (auto_mode or sentiment_gate) else 50

        # ── auto 模式: 逐日 regime → 确认窗口 → 切换当日策略模式 ──────────
        # day_mode 是本日实际用于选股的模式。非 auto 时恒等于固定 mode。
        day_mode = mode
        if auto_mode:
            reco, _ = _regime_reco_at(index_ohlc, day, breadth)
            regime_reco_history.append(reco)
            new_active = _confirm_mode(regime_reco_history, confirm_days, active_mode)
            if new_active != active_mode:
                auto_switches += 1
                active_mode = new_active
            day_mode = active_mode
            auto_mode_days[active_mode] = auto_mode_days.get(active_mode, 0) + 1

        # 当前各板块持仓计数 (用于软限仓)
        sector_count = {}
        for c in positions:
            sec = sector_by_code.get(c)
            if sec:
                sector_count[sec] = sector_count.get(sec, 0) + 1

        # ── 情绪闸门 (宽度恐慌层, 照搬实盘 should_buy) ─────────────────
        # 恐慌日(宽度分<阈值)把总持仓上限压到 SENTIMENT_PANIC_MAX_POS。
        # 已达上限则当日不开新仓。只压制买入、不强制减仓(同实盘)。
        sent_block = False
        if sentiment_gate:
            if breadth < SENTIMENT_PANIC_THRESHOLD:
                sentiment_days['panic'] += 1
                cur_pos_value = 0
                for c, pz in positions.items():
                    cur_pos_value += (close_by_code_date.get(c, {}).get(day) or pz['avg_cost']) * pz['shares']
                cur_equity = cash + cur_pos_value
                cur_pos_pct = cur_pos_value / cur_equity if cur_equity > 0 else 0
                if cur_pos_pct >= SENTIMENT_PANIC_MAX_POS:
                    sent_block = True
                    sentiment_days['blocked'] += 1
            else:
                sentiment_days['normal'] += 1

        # ── 持续熊市+深度回撤压仓（替代旧的一刀切封锁门控）──────────────
        # 触发条件：市场连续≥20天 severe_risk_off（约1个月持续熊市）
        #           且账户从高水位回撤超过10%
        # 效果：在 regime gate 已收缩的基础上再减1格，不硬封锁
        # 设计原因：单纯账户回撤不触发（回踩类最佳入场恰好在这时），
        #           需要市场也持续走弱才收紧，避免把正常震荡当熊市处理。
        # 当日权益：sell 后、buy 前（用于回撤门控 + 买入定仓，避免在候选循环里反复重算）
        cur_equity = cash + sum(
            (close_by_code_date.get(c, {}).get(day) or p['avg_cost']) * p['shares']
            for c, p in positions.items()
        )
        peak_equity = max(peak_equity, cur_equity)
        dd_pct = (peak_equity - cur_equity) / peak_equity if peak_equity > 0 else 0
        dd_gate_block = market_filter and dd_pct >= EQUITY_DD_GATE
        if market_filter and not dd_gate_block and severe_consecutive >= 20 and dd_pct > 0.10:
            effective_max = max(effective_max - 1, 1)
        day_bp3_count = 0  # 每日趋势买点3计数重置

        # ── BUY ───────────────────────────────────────────────────────
        # severe_risk_off: 全面暂停新建仓（包括防御类）——回测数据证明跌破MA60时
        # 均线回踩/趋势买点1同样是负期望，不买比买更好。
        severe_block = market_filter and regime == 'severe_risk_off'
        if not sent_block and not dd_gate_block and not severe_block and len(positions) < effective_max and cash > 10000:
            candidates = _gather_signals(day_mode, pool)
            slots = effective_max - len(positions)
            for cand in candidates:
                if slots <= 0:
                    break
                code = cand['stock_code']
                if code in positions:
                    continue
                stype = cand['strategy']
                # 永久排除负贡献策略
                if stype in _EXCLUDED_STRATEGIES:
                    continue
                # 趋势买点3: 提高score门槛 + 每日限2笔
                if stype == '趋势买点3·回踩重仓':
                    if cand.get('score', 0) < BP3_MIN_SCORE or day_bp3_count >= BP3_DAILY_LIMIT:
                        continue
                    day_bp3_count += 1
                # 板块软限仓: 同一已知板块持仓不超过 sector_cap
                sec = sector_by_code.get(code)
                if sector_cap > 0 and sec and sector_count.get(sec, 0) >= sector_cap:
                    continue
                # ML 信号过滤: p_up 低于阈值则跳过
                if _ml_score_fn is not None:
                    try:
                        ml = _ml_score_fn(stype, regime, cand.get('signal_detail', {}))
                        if ml['p_up'] < ml_threshold:
                            continue
                    except Exception:
                        pass
                px = close_by_code_date.get(code, {}).get(day)
                if not px or px <= 0:
                    continue
                # 滑点: 买入实际成交价 = 收盘价 × (1 + 滑点)
                fill_px = px * (1 + slippage)
                # 凯利仓位: 相对权重模式 —— 以等权为基准，kelly_f 高的策略超配、低的欠配。
                # cur_equity 和 _kf_avg 在候选循环外已算好，此处直接复用。
                base_slot = cur_equity / max_pos
                kf = kelly_cache.get((stype, regime)) or kelly_cache.get((stype, 'neutral'))
                if kf and kf > 0 and _kf_avg > 0:
                    kelly_ratio = min(kf / _kf_avg, 2.0)
                    kelly_budget = min(base_slot * kelly_ratio, KELLY_CAP * cur_equity)
                else:
                    kelly_budget = base_slot
                budget = min(cash / slots, kelly_budget)
                # 塔勒布杠铃: 防御型超配，突破型低配
                if stype in _DEFENSIVE_STRATEGIES:
                    budget *= BARBELL_DEFENSIVE
                elif stype in _BREAKOUT_STRATEGIES:
                    budget *= BARBELL_BREAKOUT
                # mild_risk_off: 突破类仓位再减半（杠铃之上叠加弱市压缩）
                if market_filter and regime == 'mild_risk_off' and stype in _BREAKOUT_STRATEGIES:
                    budget *= 0.5
                shares = int(budget / fill_px / 100) * 100
                # 成交量约束: 单日买入不超过当日成交量的 participation_rate
                day_vol = vol_by_code_date.get(code, {}).get(day, 0)
                if participation_rate > 0 and day_vol > 0:
                    cap = int(day_vol * participation_rate / 100) * 100
                    if cap < shares:
                        shares = cap
                if shares < 100:
                    continue
                amount = shares * fill_px
                commission = max(COMMISSION_RATE * amount, 5)
                total_cost = amount + commission
                if total_cost > cash:
                    continue
                cash -= total_cost
                positions[code] = {
                    'shares': shares, 'avg_cost': fill_px, 'highest_price': fill_px,
                    'buy_date': day, 'buy_date_dt': day_dt, 'stock_name': cand['stock_name'],
                    'strategy': stype,
                    'sector': cand['signal_detail'].get('sector', ''),  # 板块动量需记录板块
                    'can_sell_date': _next_day(day),
                }
                if sec:
                    sector_count[sec] = sector_count.get(sec, 0) + 1
                trades.append({
                    'date': day, 'stock_code': code, 'stock_name': cand['stock_name'],
                    'direction': 'buy', 'price': round(fill_px, 2), 'shares': shares,
                    'pnl_amount': 0, 'pnl_pct': 0, 'strategy': stype, 'reason': '策略买入',
                })
                # 记录信号特征，供 ML 训练使用
                if _log_signal_fn is not None:
                    try:
                        _log_signal_fn(
                            signal_date=day,
                            stock_code=code,
                            stock_name=cand['stock_name'],
                            strategy=stype,
                            score=cand.get('score', 0),
                            regime=regime,
                            features=cand.get('signal_detail', {}),
                            backtest_run_id=run_id,
                        )
                    except Exception:
                        pass
                slots -= 1

        # ── OVERSOLD BOUNCE (severe_risk_off 专用，不走正常信号) ──────────
        if market_filter and regime == 'severe_risk_off':
            ob_count = sum(1 for p in positions.values() if p.get('strategy') == '超跌反弹')
            if ob_count < OVERSOLD_MAX_POS and cash > 10000:
                ob_cands = []
                for code, bd_list in _bars_dates.items():
                    if code in positions:
                        continue
                    pos_today = _bisect_right(bd_list, day) - 1
                    if pos_today < 5:
                        continue
                    if bd_list[pos_today] != day:
                        continue
                    bars_list = bars_by_code[code]
                    px_now = bars_list[pos_today]['close']
                    px_5d  = bars_list[pos_today - 5]['close']
                    if not px_now or not px_5d or px_5d <= 0:
                        continue
                    ret5 = px_now / px_5d - 1
                    if ret5 < -OVERSOLD_DROP_5D:
                        ob_cands.append((code, px_now, ret5))
                ob_cands.sort(key=lambda x: x[2])  # 跌最多的优先
                for code, px, ob_drop in ob_cands:
                    if ob_count >= OVERSOLD_MAX_POS:
                        break
                    if code in positions:
                        continue
                    fill_px = px * (1 + slippage)
                    cur_equity = cash + sum(
                        (close_by_code_date.get(c, {}).get(day) or p['avg_cost']) * p['shares']
                        for c, p in positions.items()
                    )
                    budget = (cur_equity / max_pos) * OVERSOLD_BUDGET_RATIO
                    shares = int(budget / fill_px / 100) * 100
                    day_vol = vol_by_code_date.get(code, {}).get(day, 0)
                    if participation_rate > 0 and day_vol > 0:
                        cap = int(day_vol * participation_rate / 100) * 100
                        if cap < shares:
                            shares = cap
                    if shares < 100:
                        continue
                    amount = shares * fill_px
                    commission = max(COMMISSION_RATE * amount, 5)
                    if amount + commission > cash:
                        continue
                    cash -= amount + commission
                    positions[code] = {
                        'shares': shares, 'avg_cost': fill_px, 'highest_price': fill_px,
                        'buy_date': day, 'buy_date_dt': day_dt, 'stock_name': name_by_code.get(code, code),
                        'strategy': '超跌反弹',
                        'params': {
                            'stop_loss_pct': 0.03, 'take_profit_pct': 0.08,
                            'trailing_stop_pct': 0.03, 'max_hold_days': 5,
                        },
                        'can_sell_date': _next_day(day),
                    }
                    sec = sector_by_code.get(code)
                    if sec:
                        sector_count[sec] = sector_count.get(sec, 0) + 1
                    trades.append({
                        'date': day, 'stock_code': code,
                        'stock_name': name_by_code.get(code, code),
                        'direction': 'buy', 'price': round(fill_px, 2), 'shares': shares,
                        'pnl_amount': 0, 'pnl_pct': 0,
                        'strategy': '超跌反弹', 'reason': f'5日超跌({ob_drop:.1%})',
                    })
                    ob_count += 1

        # 闲置资金：按自然日 1/365 复利，模拟货币基金/逆回购
        cash *= 1 + CASH_ANNUAL_RATE / 365

        # ── mark equity ───────────────────────────────────────────────
        pos_value = 0
        for code, pos in positions.items():
            px = close_by_code_date.get(code, {}).get(day) or pos['avg_cost']
            pos_value += px * pos['shares']
        equity.append({'date': day, 'total_asset': round(cash + pos_value, 2)})

        if di % 5 == 0 or di == total_days - 1:
            _progress(run_id, round((di + 1) / total_days * 100, 1))

    sell_trades = [t for t in trades if t['direction'] == 'sell']
    metrics = compute_metrics(equity=equity, trades=sell_trades,
                              risk_free_rate=float(params.get('risk_free_rate', 0.0)))
    result = {
        'equity': equity,
        'metrics': metrics,
        'trades': trades[-500:],   # cap payload
        'trade_count': len(trades),
        'params': params,
        'universe_size': len(bars_by_code),
        'universe_fallback': universe_fallback,
        'risk_control': {
            'market_filter': market_filter,
            'sector_cap': sector_cap,
            'defensive_max_positions': defensive_max_pos,
            'regime_days': regime_days,
            'sentiment_gate': sentiment_gate,
            'sentiment_days': sentiment_days,
            'sector_coverage': f'{len(sector_by_code)}/{len(bars_by_code)}',
            'auto_mode': auto_mode,
            'confirm_days': confirm_days if auto_mode else None,
            'auto_switches': auto_switches if auto_mode else None,
            'auto_mode_days': auto_mode_days if auto_mode else None,
        },
        'fills': {
            'slippage_pct': round(slippage * 100, 3),
            'participation_pct': participation_rate,
            'partial_sells': sum(1 for t in trades if t['direction'] == 'sell' and '分批' in t.get('reason', '')),
        },
        'note': '近似回测:历史无换手率/PE,换手率由成交量估算、PE过滤忽略;分时类策略(VWAP/做T)不参与。'
                + ('  风控:上证MA闸门已启用(severe_risk_off屏蔽突破+降仓至防御档;mild_risk_off突破仓位减半+槽位-1)+板块软限仓。' if market_filter else '  风控:已关闭(基线对照)。')
                + ('  选池:流动性排名锁定在起点前窗口,回测可复现。' if not universe_fallback
                   else '  选池:起点前数据不足,改用最早窗口排名(仍可复现,但排名用到区间内数据)。')
                + (f'  成交:滑点{round(slippage*100,3)}%单边+成交量参与率上限{participation_rate}%(卖出可分批)。'
                   if (slippage > 0 or participation_rate > 0) else '  成交:无滑点/量约束(理想成交,基线对照)。'),
    }
    _finish(run_id, result=result)

    # 回测完成后：标注信号结果 → 刷新胜率缓存 → 尝试训练 XGBoost
    try:
        from .ml.signal_log import label_backtest_signals
        from .ml.regime_winrate import refresh_winrate_cache
        from .ml.xgb_scorer import train_if_ready
        label_backtest_signals(run_id, close_by_code_date)
        refresh_winrate_cache()
        train_if_ready()
    except Exception:
        pass


def _next_day(day):
    from datetime import timedelta
    return (datetime.strptime(day, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d')


def _progress(run_id, pct):
    db = get_db()
    try:
        db.execute("UPDATE backtest_runs SET progress_pct=? WHERE id=?", (pct, run_id))
        db.commit()
    finally:
        db.close()


def _finish(run_id, result=None, error=None):
    db = get_db()
    try:
        if error:
            db.execute(
                "UPDATE backtest_runs SET status='error', error_message=?, "
                "completed_at=datetime('now','localtime') WHERE id=?",
                (error, run_id))
        else:
            db.execute(
                "UPDATE backtest_runs SET status='done', progress_pct=100, "
                "result_json=?, completed_at=datetime('now','localtime') WHERE id=?",
                (json.dumps(result, ensure_ascii=False), run_id))
        db.commit()
    finally:
        db.close()


def _worker(run_id, params):
    try:
        _run(run_id, params)
    except Exception as e:
        import traceback
        traceback.print_exc()
        _finish(run_id, error=f'{type(e).__name__}: {e}')
    finally:
        if _bt_lock.locked():
            _bt_lock.release()


def start_backtest(params):
    """
    Kick off a backtest in a background thread. Returns {run_id} or {error}.
    params: start_date, end_date, strategy_mode, initial_capital,
            max_positions, universe_limit, risk_free_rate
    """
    if not _bt_lock.acquire(blocking=False):
        return {'success': False, 'error': '已有回测正在运行,请稍候'}

    try:
        db = get_db()
        try:
            cur = db.execute(
                "INSERT INTO backtest_runs (params_json, status, progress_pct, started_at) "
                "VALUES (?, 'running', 0, datetime('now','localtime'))",
                (json.dumps(params, ensure_ascii=False),))
            db.commit()
            run_id = cur.lastrowid
        finally:
            db.close()
    except Exception as e:
        _bt_lock.release()
        return {'success': False, 'error': str(e)}

    t = threading.Thread(target=_worker, args=(run_id, params), daemon=True)
    t.start()
    return {'success': True, 'run_id': run_id}


def get_backtest_status():
    db = get_db()
    try:
        row = db.execute(
            "SELECT id, status, progress_pct, started_at, completed_at, error_message "
            "FROM backtest_runs ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        db.close()
    if not row:
        return {'status': 'idle', 'run_id': None}
    return {
        'run_id': row['id'], 'status': row['status'],
        'progress_pct': row['progress_pct'], 'started_at': row['started_at'],
        'completed_at': row['completed_at'], 'error': row['error_message'],
    }


def get_backtest_result(run_id):
    db = get_db()
    try:
        row = db.execute(
            "SELECT id, status, result_json, error_message FROM backtest_runs WHERE id=?",
            (run_id,)).fetchone()
    finally:
        db.close()
    if not row:
        return {'error': '未找到该回测'}
    if row['status'] == 'error':
        return {'status': 'error', 'error': row['error_message']}
    if row['status'] != 'done' or not row['result_json']:
        return {'status': row['status']}
    data = json.loads(row['result_json'])
    data['status'] = 'done'
    data['run_id'] = row['id']
    return data


def walk_forward_backtest(base_params, n_folds=4):
    """
    Walk-forward 验证：将回测区间切成 n_folds 段，逐段独立运行，拼接样本外收益曲线。

    每段用同一套策略参数（无参数优化），但资本连续滚动（上段末值=下段初值），
    最终汇报每段及合并的 Sharpe / 收益率 / 最大回撤，评估策略跨时间段的一致性。

    Returns:
        {folds: [...], combined_equity: [...], summary: {...}}
    """
    from datetime import datetime, timedelta

    start = datetime.strptime(base_params['start_date'], '%Y-%m-%d')
    end = datetime.strptime(base_params['end_date'], '%Y-%m-%d')
    total_days = (end - start).days
    if total_days < n_folds * 30:
        return {'error': f'区间太短（{total_days}天），无法切成{n_folds}个有意义的折'}

    fold_days = total_days // n_folds
    base_capital = float(base_params.get('initial_capital', 1_000_000))
    running_capital = base_capital
    fold_results = []
    combined_equity = []

    db = get_db()
    try:
        for i in range(n_folds):
            fs = (start + timedelta(days=i * fold_days)).strftime('%Y-%m-%d')
            fe = (start + timedelta(days=(i + 1) * fold_days - 1)).strftime('%Y-%m-%d') \
                 if i < n_folds - 1 else base_params['end_date']

            fold_params = dict(base_params)
            fold_params['start_date'] = fs
            fold_params['end_date'] = fe
            fold_params['initial_capital'] = running_capital

            cur = db.execute(
                "INSERT INTO backtest_runs (params_json, status, progress_pct, started_at) "
                "VALUES (?, 'running', 0, datetime('now','localtime'))",
                (json.dumps(fold_params, ensure_ascii=False),))
            db.commit()
            run_id = cur.lastrowid

            try:
                _run(run_id, fold_params)
            except Exception as e:
                fold_results.append({'fold': i + 1, 'start': fs, 'end': fe, 'error': str(e)})
                continue

            read_db = get_db()
            try:
                row = read_db.execute(
                    "SELECT result_json, error_message FROM backtest_runs WHERE id=?",
                    (run_id,)).fetchone()
            finally:
                read_db.close()

            if row and row['result_json']:
                r = json.loads(row['result_json'])
                eq = r.get('equity', [])
                combined_equity.extend(eq)
                m = r.get('metrics', {})
                running_capital = eq[-1]['total_asset'] if eq else running_capital
                fold_results.append({
                    'fold': i + 1,
                    'start': fs,
                    'end': fe,
                    'run_id': run_id,
                    'return_pct': round(m.get('total_return_pct', 0), 2),
                    'sharpe': round(m.get('sharpe_ratio', 0), 3),
                    'max_drawdown_pct': round(m.get('max_drawdown_pct', 0), 2),
                    'trade_count': r.get('trade_count', 0),
                    'win_rate_pct': round(m.get('win_rate_pct', 0), 1),
                    'final_asset': round(running_capital, 2),
                })
            else:
                err = row['error_message'] if row else '未知错误'
                fold_results.append({'fold': i + 1, 'start': fs, 'end': fe, 'error': err})
    finally:
        db.close()

    valid = [r for r in fold_results if 'error' not in r]
    total_return = round((running_capital / base_capital - 1) * 100, 2)
    avg_sharpe = round(sum(r['sharpe'] for r in valid) / len(valid), 3) if valid else 0
    profitable_folds = sum(1 for r in valid if r['return_pct'] > 0)
    consistency = round(profitable_folds / len(fold_results) * 100, 1) if fold_results else 0

    return {
        'folds': fold_results,
        'combined_equity': combined_equity,
        'summary': {
            'n_folds': n_folds,
            'profitable_folds': profitable_folds,
            'total_folds': len(fold_results),
            'consistency_pct': consistency,
            'total_return_pct': total_return,
            'avg_sharpe': avg_sharpe,
            'base_capital': base_capital,
            'final_capital': round(running_capital, 2),
        },
    }




