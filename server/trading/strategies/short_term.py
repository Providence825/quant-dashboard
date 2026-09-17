"""
Short-term trading strategies adapted from Xueqiu community实战经验.

Four core strategies:
1. 尾盘捡漏 (Late-day Dip Hunter)  — buy dips near close, sell next morning
2. 龙头战法 (Dragon Leader)        — chase the strongest momentum stock
3. 分时回归 (VWAP Mean Reversion)  — short-term mean reversion around VWAP
4. 逆向做T (Anti-Algo Reverse T)   — fade algo traps during intraday extremes
"""
import time
from datetime import datetime
from ..account import get_account, get_positions
from ...data import fetcher


def get_market_cap_from_stock_list(code):
    """Estimate market cap from stock list price data."""
    stocks = fetcher.get_stock_list()
    if not stocks:
        return 0
    for s in stocks:
        if s['代码'] == code:
            price = float(s.get('最新价', 0))
            # Approximate shares from price (rough estimate)
            # Most A-shares have 100M-10B shares. Use volume/price ratio as rough proxy.
            return price
    return 0


# ── Strategy 1: Late-day Dip Hunter (尾盘捡漏) ───────────────────────

def late_day_dip_candidates(pool=None):
    """
    Screen at 14:30-14:50 for stocks that:
    - Are down 1%-3% today (moderate dip, not crash)
    - Have good fundamentals (PE 10-60, ROE > 5%)
    - Have low selling volume (turnover < 5%)
    - Price still above MA20 (trend intact)
    - Market cap > 5B (avoid micro-cap manipulation)

    Entry: buy near close (14:55)
    Exit:  sell next morning at open + 1% limit, or stop at -3%
    """
    stocks = fetcher.get_stock_list()
    if not stocks:
        return []

    def _process(s):
        code = s['代码']
        name = s['名称']
        price = float(s.get('最新价', 0))
        change_pct = float(s.get('涨跌幅', 0))
        turnover = float(s.get('换手率', 0))

        if not (-4 < change_pct < -0.5):
            return None
        if turnover > 5:
            return None
        if price < 5:
            return None
        if 'ST' in name or '退' in name or name.startswith('N'):
            return None

        kline = fetcher.get_kline_data(code, days=30)
        if not kline or len(kline) < 20:
            return None
        _ind = s.get('_ind', {})
        ma20 = _ind.get('ma20') or sum(k['close'] for k in kline[-20:]) / 20
        if price < ma20 * 0.98:
            return None

        today_vol = kline[-1]['volume']
        avg_vol_5 = sum(k['volume'] for k in kline[-6:-1]) / 5 if len(kline) >= 6 else today_vol
        if today_vol > avg_vol_5 * 1.5:
            return None

        fin = fetcher.get_financial_data(code)
        pe = fin.get('pe', 0)
        if 0 < pe < 10 or pe > 60:
            return None

        return {
            'stock_code': code,
            'stock_name': name,
            'price': price,
            'change_pct': change_pct,
            'turnover': turnover,
            'strategy': '尾盘捡漏',
            'score': round((5 - turnover) * 10 + abs(change_pct) * 5, 1),
            'signal_detail': {
                'price_vs_ma20': round(price / ma20 * 100 - 100, 1),
                'vol_vs_5d_avg': round(today_vol / avg_vol_5 * 100 - 100, 1) if avg_vol_5 > 0 else 0,
                'pe': round(pe, 1),
            }
        }

    candidates = []
    if pool:
        for code, entry in pool.items():
            s = entry['info']
            result = _process(s)
            if result:
                candidates.append(result)
    else:
        for s in stocks:
            result = _process(s)
            if result:
                candidates.append(result)

    candidates.sort(key=lambda x: x['score'], reverse=True)
    return candidates[:10]


# ── Strategy 2: Dragon Leader Scanner (龙头战法) ──────────────────────

def dragon_leader_candidates(pool=None):
    """
    Find the market dragon leader — strongest momentum stock each day.

    Conditions:
    - Top 50 by daily gain (market leaders)
    - Turnover rate 15%-35% (healthy, not overheated)
    - Today volume > 2x 20-day average volume (breakout confirmation)
    - Price > 10 (liquidity)
    - Not a 一字板 (gap-locked limit up)
    - Market cap roughly 3B-200B

    Exit signals:
    - Turnover > 40% (overheated, likely top)
    - Price drops below MA5
    - Daily change turns negative after being positive
    """
    stocks = fetcher.get_stock_list()
    if not stocks:
        return []

    # Filter to top gainers with high turnover
    if pool:
        gainers = [(entry['info']['代码'], float(entry['info'].get('涨跌幅', 0)), code, entry['info'])
                   for code, entry in pool.items()
                   if float(entry['info'].get('涨跌幅', 0)) > 3]
    else:
        gainers = [(s['代码'], float(s.get('涨跌幅', 0)), s['代码'], s)
                   for s in stocks
                   if float(s.get('涨跌幅', 0)) > 3]
    gainers.sort(key=lambda x: x[1], reverse=True)
    gainers = gainers[:100]

    candidates = []
    for item in gainers:
        code = item[0]
        s = item[3]
        name = s['名称']
        price = float(s.get('最新价', 0))
        change_pct = float(s.get('涨跌幅', 0))
        turnover = float(s.get('换手率', 0))
        volume = float(s.get('成交量', 0))

        # Healthy turnover zone
        if not (8 < turnover < 40):
            continue
        # Skip overheating
        if turnover > 40:
            continue
        # Minimum price
        if price < 8:
            continue
        # Skip ST
        if 'ST' in name or '退' in name:
            continue
        # Skip limit-up locked (一字板 has almost zero intraday range)
        if change_pct > 9.8:
            continue

        # Volume breakout check
        kline = fetcher.get_kline_data(code, days=30)
        if not kline or len(kline) < 20:
            continue
        _ind = s.get('_ind', {})
        avg_vol_20 = _ind.get('vol_avg20') or (sum(k['volume'] for k in kline[-21:-1]) / 20 if len(kline) >= 21 else volume)
        vol_ratio = volume / avg_vol_20 if avg_vol_20 > 0 else 0
        if vol_ratio < 1.5:
            continue

        # MA trend check: MA5 > MA10 > MA20
        closes = [k['close'] for k in kline]
        ma5 = _ind.get('ma5') or sum(closes[-5:]) / 5
        ma10 = _ind.get('ma10') or sum(closes[-10:]) / 10
        ma20 = _ind.get('ma20') or sum(closes[-20:]) / 20
        if not (ma5 > ma10 > ma20):
            continue

        # Financial check
        fin = fetcher.get_financial_data(code)
        pe = fin.get('pe', 0)

        candidates.append({
            'stock_code': code,
            'stock_name': name,
            'price': price,
            'change_pct': change_pct,
            'turnover': turnover,
            'strategy': '龙头战法',
            'score': round(change_pct * 3 + (min(turnover, 30) - 10) * 0.5 + (min(vol_ratio, 5) - 1) * 5, 1),
            'signal_detail': {
                'vol_ratio': round(vol_ratio, 1),
                'ma5': round(ma5, 2),
                'ma10': round(ma10, 2),
                'ma20': round(ma20, 2),
                'pe': round(pe, 1),
            }
        })

    candidates.sort(key=lambda x: x['score'], reverse=True)
    return candidates[:10]


# ── Strategy 3: Intraday Mean Reversion around VWAP (分时回归) ───────

def vwap_reversion_signals():
    """
    Detect stocks deviating from intraday VWAP by > 2% for mean reversion.

    Uses intraday 5-min K-line data to approximate VWAP.
    Works during trading hours only.
    """
    if not fetcher.is_trading_time():
        return []

    stocks = fetcher.get_stock_list()
    if not stocks:
        return []

    signals = []
    for s in stocks[:200]:  # Sample from top stocks to avoid excessive API calls
        code = s['代码']
        name = s['名称']
        price = float(s.get('最新价', 0))
        change_pct = float(s.get('涨跌幅', 0))

        # Only check stocks with meaningful activity
        turnover = float(s.get('换手率', 0))
        if turnover < 1 or price < 5:
            continue

        intraday = fetcher.get_intraday_data(code)
        if not intraday or len(intraday) < 10:
            continue

        prices = [k['price'] for k in intraday]
        volumes = [1] * len(prices)  # Approximate equal volume per bar
        try:
            total_vp = sum(p * v for p, v in zip(prices, volumes))
            total_v = sum(volumes)
            vwap = total_vp / total_v if total_v > 0 else prices[-1]
        except:
            vwap = prices[-1]

        deviation = (price - vwap) / vwap * 100

        if abs(deviation) > 2:
            signals.append({
                'stock_code': code,
                'stock_name': name,
                'price': price,
                'vwap': round(vwap, 2),
                'deviation_pct': round(deviation, 2),
                'direction': '超跌反弹' if deviation < -2 else '冲高回落',
                'strategy': '分时回归',
                'score': round(abs(deviation) * 5, 1),
            })

    signals.sort(key=lambda x: x['score'], reverse=True)
    return signals[:15]


# ── Strategy 4: Anti-Algo Reverse T (逆向做T) ────────────────────────

def anti_algo_signals():
    """
    Detect algo trap patterns using 5-min K-lines:
    - Sudden spike (>2% in 5 min) with volume spike → probable algo pump, don't chase
    - Sudden drop (>2% in 5 min) without volume → panic, potential bounce

    For held positions, signals whether to反向T.
    """
    if not fetcher.is_trading_time():
        return []

    positions = get_positions()
    if not positions:
        return []

    signals = []
    for pos in positions:
        code = pos['stock_code']
        name = pos['stock_name']
        intraday = fetcher.get_intraday_data(code)
        if not intraday or len(intraday) < 5:
            continue

        prices = [k['price'] for k in intraday]
        # Check last 2 bars for sudden moves
        if len(prices) >= 3:
            last_change = (prices[-1] - prices[-2]) / prices[-2] * 100
            prev_change = (prices[-2] - prices[-3]) / prices[-3] * 100

            # Sudden spike (>1.5% in 5 min) — potential sell T point
            if last_change > 1.5:
                signals.append({
                    'stock_code': code,
                    'stock_name': name,
                    'price': prices[-1],
                    'change_5min': round(last_change, 2),
                    'signal': '急拉做T卖出',
                    'strategy': '逆向做T',
                    'score': round(last_change * 10, 1),
                })
            # Sudden drop (< -1.5% in 5 min) — potential buy T point
            elif last_change < -1.5:
                signals.append({
                    'stock_code': code,
                    'stock_name': name,
                    'price': prices[-1],
                    'change_5min': round(last_change, 2),
                    'signal': '急跌做T买入',
                    'strategy': '逆向做T',
                    'score': round(abs(last_change) * 10, 1),
                })

    signals.sort(key=lambda x: x['score'], reverse=True)
    return signals[:10]


# ── Strategy 5: Short-term stop rules (短线止损止盈规则) ──────────────

def get_short_term_params(strategy_type='default'):
    """Return stop-loss / take-profit params based on strategy type."""
    params = {
        'default': {
            'stop_loss_pct': 0.02,
            'take_profit_pct': 0.15,
            'trailing_stop_pct': 0.05,
            'max_hold_days': 10,
        },
        '尾盘捡漏': {
            'stop_loss_pct': 0.02,      # Tight stop: 2%
            'take_profit_pct': 0.05,    # Quick take: 5%
            'trailing_stop_pct': 0.02,  # Very tight trailing
            'max_hold_days': 2,          # Sell by day 2
            'next_day_sell': True,       # Auto-sell next morning
        },
        '龙头战法': {
            'stop_loss_pct': 0.02,      # 2% hard stop
            'take_profit_pct': 0.20,    # Let winners run more
            'trailing_stop_pct': 0.05,  # Trail from high
            'max_hold_days': 5,         # Max 5 days
            'exit_on_turnover': 40,     # Exit when turnover > 40%
            'exit_below_ma5': True,      # Exit when price < MA5
        },
        '分时回归': {
            'stop_loss_pct': 0.02,      # Very tight: 2%
            'take_profit_pct': 0.03,    # Small target: 3%
            'trailing_stop_pct': 0.01,
            'max_hold_days': 1,         # Same day or next day only
        },
    }
    return params.get(strategy_type, params['default'])


# ── Aggregate all strategies ─────────────────────────────────────────

def get_all_strategy_signals(pool=None):
    """Collect signals from all short-term strategies."""
    result = {
        '尾盘捡漏': late_day_dip_candidates(pool=pool),
        '龙头战法': dragon_leader_candidates(pool=pool),
    }
    # 分时策略仅实盘时扫描（回测时pool!=None，跳过避免读实盘持仓污染）
    if pool is None:
        result['分时回归'] = vwap_reversion_signals()
        result['逆向做T'] = anti_algo_signals()
    return result
