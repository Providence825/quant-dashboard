"""
Trend/swing trading strategies (趋势波段策略).

Three core strategies:
1. 均线多头突破 (MA Bullish Breakout)     — MA20>MA60>MA120 + price breakout + volume
2. 通道突破 (Channel Breakout)             — 20-day Donchian channel breakout
3. 均线回踩买入 (MA Pullback Buy)          — price pulls back to rising MA20 with support

Designed for trending markets. All use wider stops and longer holds than short-term.
"""

from ...data import fetcher
import time


def get_trend_params(strategy_type='default'):
    """Return stop-loss / take-profit params for trend strategies."""
    params = {
        'default': {
            'stop_loss_pct': 0.02,
            'take_profit_pct': 0.25,
            'trailing_stop_pct': 0.08,
            'max_hold_days': 20,
        },
        '均线多头突破': {
            'stop_loss_pct': 0.02,
            'take_profit_pct': 0.30,
            'trailing_stop_pct': 0.08,
            'max_hold_days': 15,
            'exit_on_ma_break': True,
            'add_on_pullback': True,
        },
        '通道突破': {
            'stop_loss_pct': 0.02,
            'take_profit_pct': 0.35,
            'trailing_stop_pct': 0.10,
            'max_hold_days': 25,
            'exit_on_channel_mid': True,
        },
        '均线回踩': {
            'stop_loss_pct': 0.02,
            'take_profit_pct': 0.20,
            'trailing_stop_pct': 0.06,
            'max_hold_days': 7,
            'entry_near_ma': True,
        },
        '海龟通道突破': {
            'stop_loss_pct': 0.02,
            'take_profit_pct': 0.35,
            'trailing_stop_pct': 0.10,
            'max_hold_days': 30,
            'exit_on_channel_mid': True,
        },
    }
    return params.get(strategy_type, params['default'])


# ── Strategy 1: MA Bullish Breakout (均线多头突破) ──────────────────────

def ma_breakout_candidates(pool=None):
    """
    Stocks in a bullish MA alignment (MA20>MA60>MA120) with:
    - Price just broke above MA20 or is consolidating above it
    - Volume > 1.5x 20-day average (confirmation)
    - Moderate PE (10-80, trend stocks can carry higher PE)
    - Price > 10 (liquidity filter)
    - Not already limit-up (avoid chasing)
    """
    stocks = fetcher.get_stock_list()
    if not stocks:
        return []

    def _process(s, kline_hint=None):
        code = s['代码']
        name = s['名称']
        _ind = s.get('_ind', {})
        price = float(s.get('最新价', 0))
        change_pct = float(s.get('涨跌幅', 0))

        if price < 10:
            return None
        if 'ST' in name or '退' in name or name.startswith('N'):
            return None
        if change_pct > 9.5:
            return None

        kline = kline_hint if kline_hint and len(kline_hint) >= 60 else fetcher.get_kline_data(code, days=130)
        if not kline or len(kline) < 60:
            return None

        closes = [k['close'] for k in kline]
        volumes = [k['volume'] for k in kline]

        ma20  = _ind.get('ma20')  or sum(closes[-20:]) / 20
        ma60  = _ind.get('ma60')  or sum(closes[-60:]) / 60
        ma120 = _ind.get('ma120') or (sum(closes[-120:]) / 120 if len(closes) >= 120 else ma60)

        if not (ma20 > ma60 > ma120):
            return None

        price_vs_ma20 = (price - ma20) / ma20 * 100
        if price_vs_ma20 > 8:
            return None
        if price_vs_ma20 < -3:
            return None

        if len(closes) >= 25:
            ma20_5d_ago = sum(closes[-25:-5]) / 20
        else:
            ma20_5d_ago = ma20
        ma20_sloping_up = ma20 > ma20_5d_ago * 1.01

        today_vol = volumes[-1]
        avg_vol_20 = _ind.get('vol_avg20') or (sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else today_vol)
        vol_ratio = today_vol / avg_vol_20 if avg_vol_20 > 0 else 0

        fin = fetcher.get_financial_data(code)
        pe = fin.get('pe', 0)
        if pe > 0 and pe > 80:
            return None

        score = 0
        score += min(price_vs_ma20 + 3, 8) * 3
        score += min(vol_ratio, 3) * 3
        score += (5 if ma20_sloping_up else 0)
        score += min((80 - pe) / 10, 5) if pe > 0 else 3
        score += abs(change_pct) * 0.3

        return {
            'stock_code': code,
            'stock_name': name,
            'price': price,
            'change_pct': change_pct,
            'strategy': '均线多头突破',
            'score': round(score, 1),
            'signal_detail': {
                'price_vs_ma20': f'{price_vs_ma20:+.1f}%',
                'ma20': round(ma20, 2),
                'ma60': round(ma60, 2),
                'ma120': round(ma120, 2),
                'vol_ratio': round(vol_ratio, 1),
                'ma20_up': ma20_sloping_up,
                'pe': round(pe, 1),
            }
        }

    candidates = []
    if pool:
        for code, entry in pool.items():
            s = entry['info']
            result = _process(s, kline_hint=entry.get('kline'))
            if result:
                candidates.append(result)
    else:
        for s in stocks:
            result = _process(s)
            if result:
                candidates.append(result)

    candidates.sort(key=lambda x: x['score'], reverse=True)
    return candidates[:15]


# ── Strategy 2: Channel Breakout (通道突破) ─────────────────────────────

def channel_breakout_candidates(pool=None):
    """
    20-day Donchian channel breakout:
    - Price breaks above 20-day high (resistance)
    - Volume > 1.8x average (strong breakout confirmation)
    - Price above MA60 (long-term trend filter)
    - Turnover 3-25% (active but not overheated)
    """
    stocks = fetcher.get_stock_list()
    if not stocks:
        return []

    def _process(s, kline_hint=None):
        code = s['代码']
        name = s['名称']
        _ind = s.get('_ind', {})
        price = float(s.get('最新价', 0))
        change_pct = float(s.get('涨跌幅', 0))
        turnover = float(s.get('换手率', 0))

        if price < 8:
            return None
        if 'ST' in name or '退' in name:
            return None
        if not (3 < turnover < 25):
            return None
        if change_pct > 9.5:
            return None

        kline = kline_hint if kline_hint and len(kline_hint) >= 60 else fetcher.get_kline_data(code, days=130)
        if not kline or len(kline) < 25:
            return None

        closes = [k['close'] for k in kline]
        highs = [k['high'] for k in kline]
        lows = [k['low'] for k in kline]
        volumes = [k['volume'] for k in kline]

        channel_high = max(highs[-21:-1])
        channel_low = min(lows[-21:-1])

        if price <= channel_high * 0.98:
            return None

        today_vol = volumes[-1]
        avg_vol_20 = _ind.get('vol_avg20') or (sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else today_vol)
        vol_ratio = today_vol / avg_vol_20 if avg_vol_20 > 0 else 0
        if vol_ratio < 1.8:
            return None

        if len(closes) >= 60:
            ma60 = _ind.get('ma60') or sum(closes[-60:]) / 60
            if price < ma60 * 0.97:
                return None

        channel_width = (channel_high - channel_low) / channel_low * 100
        if channel_width < 8:
            return None

        # ATR volatility quality filter (turtle insight): skip dead or erratic names
        from ...data.indicators import calc_atr
        atr = _ind.get('atr14') or 0
        if not atr:
            atr_series = calc_atr(highs, lows, closes, 14)
            atr = atr_series[-1] if atr_series and atr_series[-1] else 0
        atr_pct = atr / price * 100 if (atr and price > 0) else 0
        if atr_pct and not (1.2 <= atr_pct <= 10.0):
            return None
        # ATR-normalized breakout strength (how decisively price cleared the channel)
        breakout_atr = (price - channel_high) / atr if atr > 0 else 0

        fin = fetcher.get_financial_data(code)
        pe = fin.get('pe', 0)

        if len(closes) >= 14:
            adx_like = _quick_trend_strength(closes)
        else:
            adx_like = 20

        score = round(
            (price / channel_high * 100 - 98) * 5 +
            min(vol_ratio, 4) * 4 +
            min(channel_width, 20) * 0.5 +
            min(adx_like, 40) * 0.3 +
            (25 - min(turnover, 25)) * 0.3 +
            min(max(breakout_atr, 0), 2) * 6,
            1
        )

        return {
            'stock_code': code,
            'stock_name': name,
            'price': price,
            'change_pct': change_pct,
            'turnover': turnover,
            'strategy': '通道突破',
            'score': score,
            'signal_detail': {
                'channel_high': round(channel_high, 2),
                'channel_low': round(channel_low, 2),
                'atr_pct': f'{atr_pct:.1f}%' if atr_pct else 'n/a',
                'breakout_atr': f'{breakout_atr:.2f} ATR' if atr > 0 else 'n/a',
                'channel_width': f'{channel_width:.1f}%',
                'vol_ratio': round(vol_ratio, 1),
                'trend_strength': round(adx_like, 1),
                'pe': round(pe, 1),
            }
        }

    candidates = []
    if pool:
        for code, entry in pool.items():
            s = entry['info']
            result = _process(s, kline_hint=entry.get('kline'))
            if result:
                candidates.append(result)
    else:
        for s in stocks:
            result = _process(s)
            if result:
                candidates.append(result)

    candidates.sort(key=lambda x: x['score'], reverse=True)
    return candidates[:15]


# ── Strategy 3: MA Pullback Buy (均线回踩买入) ──────────────────────────

def ma_pullback_candidates(pool=None):
    """
    In an uptrend, buy when price pulls back to rising MA20:
    - MA20 > MA60 (confirmed uptrend)
    - Price 0-3% above MA20 (near support)
    - Volume declining (selling exhausted)
    - Today change > -3% (not a crash)
    """
    stocks = fetcher.get_stock_list()
    if not stocks:
        return []

    def _process(s, kline_hint=None):
        code = s['代码']
        name = s['名称']
        price = float(s.get('最新价', 0))
        change_pct = float(s.get('涨跌幅', 0))

        if price < 8:
            return None
        if 'ST' in name or '退' in name:
            return None
        if change_pct < -3:
            return None

        kline = kline_hint if kline_hint and len(kline_hint) >= 60 else fetcher.get_kline_data(code, days=130)
        if not kline or len(kline) < 125:
            return None

        closes = [k['close'] for k in kline]
        volumes = [k['volume'] for k in kline]
        _ind = s.get('_ind', {})

        ma20  = _ind.get('ma20')  or sum(closes[-20:]) / 20
        ma60  = _ind.get('ma60')  or sum(closes[-60:]) / 60
        ma120 = _ind.get('ma120') or sum(closes[-120:]) / 120

        # 三均线全部对齐才算真正上升趋势
        if not (ma20 > ma60 > ma120):
            return None

        price_vs_ma20 = (price - ma20) / ma20 * 100
        # 必须贴近 MA20（+4% 根本不是回踩）
        if not (-0.5 <= price_vs_ma20 <= 2.0):
            return None

        if len(closes) >= 25:
            ma20_5d_ago = sum(closes[-25:-5]) / 20
            if (ma20 - ma20_5d_ago) / ma20 < 0.005:
                return None

        today_vol = volumes[-1]
        avg_vol_10 = sum(volumes[-11:-1]) / 10 if len(volumes) >= 11 else today_vol
        vol_ratio = today_vol / avg_vol_10 if avg_vol_10 > 0 else 1
        if vol_ratio > 1.3:
            return None

        recent_high = max(closes[-10:-1]) if len(closes) >= 11 else max(closes[:-1])
        pulled_back = (recent_high - price) / recent_high * 100
        if pulled_back < 5:
            return None

        fin = fetcher.get_financial_data(code)
        pe = fin.get('pe', 0)

        score = round(
            (2 - price_vs_ma20) * 5 +
            pulled_back * 2 +
            (1.3 - min(vol_ratio, 1.3)) * 10 +
            ((10 - min(pe / 5, 10)) if pe > 0 else 5),
            1
        )

        if score < 18:
            return None

        return {
            'stock_code': code,
            'stock_name': name,
            'price': price,
            'change_pct': change_pct,
            'strategy': '均线回踩',
            'score': score,
            'signal_detail': {
                'price_vs_ma20': f'{price_vs_ma20:+.1f}%',
                'ma20': round(ma20, 2),
                'ma60': round(ma60, 2),
                'ma120': round(ma120, 2),
                'pulled_back': f'{pulled_back:.1f}%',
                'vol_vs_10d': round(vol_ratio, 1),
                'pe': round(pe, 1),
            }
        }

    candidates = []
    if pool:
        for code, entry in pool.items():
            s = entry['info']
            result = _process(s, kline_hint=entry.get('kline'))
            if result:
                candidates.append(result)
    else:
        for s in stocks:
            result = _process(s)
            if result:
                candidates.append(result)

    candidates.sort(key=lambda x: x['score'], reverse=True)
    return candidates[:15]


# ── Strategy 4: Turtle Donchian Breakout (海龟通道突破) ──────────────────

def turtle_breakout_candidates(pool=None):
    """
    海龟交易法 唐奇安通道突破 (ATR 波动率自适应版).

    参考 ea-python 海龟策略 + alphahunter 多周期确认思想:
    - 价格突破 20 日唐奇安通道上轨 (不含当日)
    - 突破幅度 >= 0.5 ATR (波动率确认，过滤微弱假突破)
    - 长周期趋势过滤: 价格 > MA50 且 MA50 上行
    - 量能确认: 量比 > 1.5
    - ATR% 适中 (1.5%-9%)，剔除过于死板或过度波动的标的
    - 评分用 ATR 归一化突破强度，可跨标的横向比较
    """
    from ...data.indicators import calc_atr

    stocks = fetcher.get_stock_list()
    if not stocks:
        return []

    def _process(s, kline_hint=None):
        code = s['代码']
        name = s['名称']
        price = float(s.get('最新价', 0))
        change_pct = float(s.get('涨跌幅', 0))
        turnover = float(s.get('换手率', 0))

        if price < 8:
            return None
        if 'ST' in name or '退' in name or name.startswith('N'):
            return None
        if change_pct > 9.5:
            return None
        if not (2 < turnover < 25):
            return None

        kline = kline_hint if kline_hint and len(kline_hint) >= 60 else fetcher.get_kline_data(code, days=130)
        if not kline or len(kline) < 55:
            return None

        closes = [k['close'] for k in kline]
        highs = [k['high'] for k in kline]
        lows = [k['low'] for k in kline]
        volumes = [k['volume'] for k in kline]
        _ind = s.get('_ind', {})

        # 20-day Donchian upper channel excluding today
        channel_high = max(highs[-21:-1])
        if price <= channel_high:
            return None

        atr = _ind.get('atr14') or 0
        if not atr:
            atr_series = calc_atr(highs, lows, closes, 14)
            atr = atr_series[-1] if atr_series and atr_series[-1] else 0
        if not atr or atr <= 0:
            return None
        atr_pct = atr / price * 100
        if not (1.5 <= atr_pct <= 9.0):
            return None

        # Breakout margin in ATR units (turtle volatility confirmation)
        breakout_atr = (price - channel_high) / atr
        if breakout_atr < 0.5:
            return None

        # Long-term trend filter
        ma50 = _ind.get('ma50') or sum(closes[-50:]) / 50
        if price < ma50:
            return None
        ma50_10d_ago = sum(closes[-60:-10]) / 50 if len(closes) >= 60 else ma50
        if ma50 <= ma50_10d_ago:
            return None

        # Volume confirmation
        today_vol = volumes[-1]
        avg_vol_20 = _ind.get('vol_avg20') or (sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else today_vol)
        vol_ratio = today_vol / avg_vol_20 if avg_vol_20 > 0 else 0
        if vol_ratio < 1.5:
            return None

        fin = fetcher.get_financial_data(code)
        pe = fin.get('pe', 0)
        if pe > 0 and pe > 100:
            return None

        # ATR-normalized composite score (comparable across stocks)
        score = round(
            min(breakout_atr, 3) * 12 +
            min(vol_ratio, 4) * 5 +
            min((price - ma50) / ma50 * 100, 15) * 0.6 +
            (5 if 2 <= atr_pct <= 5 else 0),
            1
        )

        # Suggested ATR-based stops (2 ATR stop, entry reference)
        stop_price = round(price - 2 * atr, 2)

        return {
            'stock_code': code,
            'stock_name': name,
            'price': price,
            'change_pct': change_pct,
            'turnover': turnover,
            'strategy': '海龟通道突破',
            'score': score,
            'signal_detail': {
                'channel_high': round(channel_high, 2),
                'breakout_atr': f'{breakout_atr:.2f} ATR',
                'atr': round(atr, 2),
                'atr_pct': f'{atr_pct:.1f}%',
                'ma50': round(ma50, 2),
                'vol_ratio': round(vol_ratio, 1),
                'atr_stop': stop_price,
                'pe': round(pe, 1),
            }
        }

    candidates = []
    if pool:
        for code, entry in pool.items():
            result = _process(entry['info'], kline_hint=entry.get('kline'))
            if result:
                candidates.append(result)
    else:
        for s in stocks:
            result = _process(s)
            if result:
                candidates.append(result)

    candidates.sort(key=lambda x: x['score'], reverse=True)
    return candidates[:15]


# ── Utility ────────────────────────────────────────────────────────────

def _quick_trend_strength(closes):
    """Quick ADX-like trend strength estimate from closes only."""
    if len(closes) < 14:
        return 20
    changes = [abs(closes[i] - closes[i-1]) for i in range(1, len(closes))]
    up_moves = [max(closes[i] - closes[i-1], 0) for i in range(1, len(closes))]
    down_moves = [max(closes[i-1] - closes[i], 0) for i in range(1, len(closes))]

    atr = sum(changes[-14:]) / 14
    if atr == 0:
        return 20

    plus_di = sum(up_moves[-14:]) / 14 / atr * 100
    minus_di = sum(down_moves[-14:]) / 14 / atr * 100
    dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) > 0 else 0
    return round(dx, 1)


def get_all_trend_signals(pool=None):
    """Collect signals from all trend strategies."""
    return {
        '均线多头突破': ma_breakout_candidates(pool=pool),
        '通道突破': channel_breakout_candidates(pool=pool),
        '均线回踩': ma_pullback_candidates(pool=pool),
        '海龟通道突破': turtle_breakout_candidates(pool=pool),
    }
