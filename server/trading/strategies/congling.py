"""
从零大A quantitative strategies.
Based on B站 UP主「从零大A」(公众号:太阳淘金录) methodology:

体系一《从零构建交易系统》— 关键位突破 + 假突破过滤 + 科学加仓
体系二《淘金名录》— 延续性龙头 + 品种分级 + 盘面强弱

Signal format matches existing convention:
    {stock_code, stock_name, price, change_pct, score, strategy, signal_detail}
"""

from ...data import fetcher


# ── Utility ─────────────────────────────────────────────────────────

def _compute_ma(closes, period):
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def _find_key_levels(highs, lows, lookback=60):
    """Find key support/resistance levels by detecting price clusters (multi-touch points)."""
    if len(highs) < lookback or len(lows) < lookback:
        return [], []

    h = highs[-lookback:]
    l = lows[-lookback:]

    # Cluster highs and lows within 2% bands
    def _cluster(prices, pct=0.02):
        prices = sorted(prices)
        clusters = []
        current = [prices[0]]
        for p in prices[1:]:
            if p <= current[-1] * (1 + pct):
                current.append(p)
            else:
                if len(current) >= 3:  # At least 3 touches = key level
                    clusters.append(sum(current) / len(current))
                current = [p]
        if len(current) >= 3:
            clusters.append(sum(current) / len(current))
        return clusters

    resistance_levels = _cluster(h)
    support_levels = _cluster(l)
    return support_levels, resistance_levels


def _compute_trendline(closes, period=30):
    """Linear regression trendline. Returns (slope, r_squared)."""
    n = min(period, len(closes))
    if n < 10:
        return 0, 0
    x = list(range(n))
    y = closes[-n:]
    x_mean = sum(x) / n
    y_mean = sum(y) / n
    num = sum((x[i] - x_mean) * (y[i] - y_mean) for i in range(n))
    den = sum((x[i] - x_mean) ** 2 for i in range(n))
    if den == 0:
        return 0, 0
    slope = num / den
    ss_res = sum((y[i] - (y_mean + slope * (x[i] - x_mean))) ** 2 for i in range(n))
    ss_tot = sum((y[i] - y_mean) ** 2 for i in range(n))
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
    return slope, r_squared


# ── Strategy 1: 关键位突破 (Key Level Breakout) ──────────────────────

def key_level_breakout_candidates(pool=None):
    """
    关键位突破 — 从零大A体系一核心策略。

    Conditions:
    - Price breaks above identified key resistance level (3+ touches)
    - Volume >= 1.5x 20-day average (breakout confirmation)
    - Price > 10 (liquidity)
    - Not limit-up chasing (change < 9.5%)
    - Trend line sloping up (r² > 0.4)
    - MA20 > MA60 (uptrend context)

    Score: breakout strength + volume ratio + trend quality
    """
    stocks = fetcher.get_stock_list()
    if not stocks:
        return []

    def _process(s, kline_hint=None):
        code = s['代码']
        name = s['名称']
        price = float(s.get('最新价', 0))
        change_pct = float(s.get('涨跌幅', 0))
        turnover = float(s.get('换手率', 0))

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
        highs = [k['high'] for k in kline]
        lows = [k['low'] for k in kline]
        volumes = [k['volume'] for k in kline]

        # Find key resistance levels
        _, resistances = _find_key_levels(highs, lows, 60)
        if not resistances:
            return None

        # Check if price broke above nearest resistance
        nearest_res = min(resistances, key=lambda r: abs(r - price))
        if price < nearest_res * 0.98:
            return None

        breakout_pct = (price - nearest_res) / nearest_res * 100
        if breakout_pct > 8:
            return None  # Too extended

        # Volume confirmation
        today_vol = volumes[-1]
        avg_vol_20 = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else today_vol
        vol_ratio = today_vol / avg_vol_20 if avg_vol_20 > 0 else 0
        if vol_ratio < 1.5:
            return None

        # Check follow-through (last 2 bars above resistance = good)
        bars_above = sum(1 for c in closes[-3:] if c > nearest_res)
        if bars_above < 2:
            return None

        # Trend quality
        _ind = s.get('_ind', {})
        ma20 = _ind.get('ma20') or _compute_ma(closes, 20)
        ma60 = _ind.get('ma60') or _compute_ma(closes, 60)
        if not ma20 or not ma60:
            return None
        if ma20 <= ma60:
            return None

        slope, r2 = _compute_trendline(closes, 30)
        if r2 < 0.3:
            return None

        # Multi-touch quality = more touches = stronger level
        touch_count = sum(1 for h in highs[-60:] if abs(h - nearest_res) / nearest_res < 0.02)

        score = 0
        score += min(breakout_pct, 5) * 4
        score += min(vol_ratio, 3) * 6
        score += min(bars_above, 3) * 4
        score += min(touch_count, 5) * 3
        score += r2 * 15
        score = round(max(0, min(100, score)), 1)

        if score < 40:
            return None

        return {
            'stock_code': code,
            'stock_name': name,
            'price': price,
            'change_pct': change_pct,
            'strategy': '关键位突破',
            'score': score,
            'signal_detail': {
                'key_level': round(nearest_res, 2),
                'breakout_pct': f'{breakout_pct:+.1f}%',
                'vol_ratio': round(vol_ratio, 1),
                'bars_above': bars_above,
                'touch_count': touch_count,
                'trend_r2': round(r2, 3),
                'turnover': f'{turnover:.1f}%',
            }
        }

    candidates = []
    if pool:
        for code, entry in pool.items():
            result = _process(entry['info'], entry.get('kline'))
            if result:
                candidates.append(result)
    else:
        for s in stocks:
            result = _process(s)
            if result:
                candidates.append(result)

    candidates.sort(key=lambda x: x['score'], reverse=True)
    return candidates[:15]


# ── Strategy 2: 假突破过滤 (False Breakout Filter) ──────────────────

def false_breakout_filter(pool=None):
    """
    假突破检测 — 从零大A："80%的突破会失败，关键是识别假突破"。

    Detects stocks that recently broke out but show warning signs:
    - Broke above key level 1-3 days ago
    - No follow-through (price drifting back)
    - Volume declining post-breakout
    - Price back below breakout level = confirmed false breakout

    Returns WARNING signals for positions that may need exit.
    Also returns OPPORTUNITY signals — failed breakdowns that reversed back up.
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

        kline = kline_hint if kline_hint and len(kline_hint) >= 30 else fetcher.get_kline_data(code, days=70)
        if not kline or len(kline) < 30:
            return None

        closes = [k['close'] for k in kline]
        highs = [k['high'] for k in kline]
        lows = [k['low'] for k in kline]
        volumes = [k['volume'] for k in kline]

        # Find recent high as potential breakout level
        recent_high_10 = max(highs[-11:-1])
        recent_high_5 = max(highs[-6:-1])

        # Check if broke above recent high 2-4 days ago
        broke_out = False
        breakout_bar = -1
        for i in range(-4, -1):
            if i >= -len(closes) and closes[i] > recent_high_10 * 1.01:
                broke_out = True
                breakout_bar = i
                break

        if not broke_out:
            return None

        # Check follow-through
        post_breakout_closes = closes[breakout_bar:]
        if len(post_breakout_closes) < 3:
            return None

        # Warning signs:
        vol_before = sum(volumes[breakout_bar - 5:breakout_bar]) / 5 if len(volumes) >= abs(breakout_bar) + 5 else volumes[breakout_bar]
        vol_after = sum(volumes[breakout_bar:]) / len(volumes[breakout_bar:])
        vol_fading = vol_after < vol_before * 0.7

        back_below = price < recent_high_10 * 0.99

        post_trend = post_breakout_closes[-1] - post_breakout_closes[0]

        is_false = back_below or (vol_fading and post_trend < 0)
        is_opportunity = is_false and change_pct > 0 and price > recent_high_10 * 0.97

        tag = '假突破·离场' if is_false and not is_opportunity else \
              '假突破·反转机会' if is_opportunity else '突破存疑·观察'

        score = 0
        score += 30 if back_below else 0
        score += 20 if vol_fading else 0
        score += 15 if post_trend < 0 else 0
        score += 20 if is_opportunity else 0
        score = round(max(0, min(100, score)), 1)

        if score < 35:
            return None

        return {
            'stock_code': code,
            'stock_name': name,
            'price': price,
            'change_pct': change_pct,
            'strategy': '假突破检测',
            'score': score,
            'signal_detail': {
                'tag': tag,
                'breakout_level': round(recent_high_10, 2),
                'vol_fading': str(vol_fading),
                'back_below': str(back_below),
                'post_trend': f'{post_trend:+.2f}',
                'is_opportunity': str(is_opportunity),
            }
        }

    candidates = []
    if pool:
        for code, entry in pool.items():
            result = _process(entry['info'], entry.get('kline'))
            if result:
                candidates.append(result)
    else:
        for s in stocks:
            result = _process(s)
            if result:
                candidates.append(result)

    candidates.sort(key=lambda x: x['score'], reverse=True)
    return candidates[:15]


# ── Strategy 3: 延续性龙头 (Continuity Dragon) ──────────────────────

def continuity_dragon_candidates(pool=None):
    """
    延续性龙头 — 淘金名录核心："延续性是唯一试金石"。

    Conditions:
    - Consecutive up days (3+ days with positive close)
    - At most 1 rest day allowed (if rested yesterday, must bounce today)
    - Today change > 2% (active momentum)
    - Turnover 8-35% (healthy)
    - MA5 > MA10 > MA20 (ascending)
    - Near sector top 3

    Score: continuity days + momentum strength + volume quality.
    """
    stocks = fetcher.get_stock_list()
    if not stocks:
        return []

    def _process(s, kline_hint=None):
        code = s['代码']
        name = s['名称']
        price = float(s.get('最新价', 0))
        change_pct = float(s.get('涨跌幅', 0))
        turnover = float(s.get('换手率', 0))

        if price < 6:
            return None
        if 'ST' in name or '退' in name:
            return None
        if change_pct < 2:
            return None
        if not (5 < turnover < 45):
            return None

        kline = kline_hint if kline_hint and len(kline_hint) >= 25 else fetcher.get_kline_data(code, days=70)
        if not kline or len(kline) < 25:
            return None

        closes = [k['close'] for k in kline]
        volumes = [k['volume'] for k in kline]

        # Count consecutive up days (close > previous close)
        up_streak = 0
        rest_days = 0
        for i in range(len(closes) - 1, 0, -1):
            if closes[i] > closes[i - 1]:
                up_streak += 1
                rest_days = 0
            elif closes[i] >= closes[i - 1] * 0.98:
                # Slight rest day (within 2%)
                rest_days += 1
                if rest_days > 1:
                    break
            else:
                break

        if up_streak < 2:
            return None

        # At most 1 rest day
        if rest_days > 1:
            return None

        # MA alignment
        _ind = s.get('_ind', {})
        ma5 = _ind.get('ma5') or _compute_ma(closes, 5)
        ma10 = _ind.get('ma10') or _compute_ma(closes, 10)
        ma20 = _ind.get('ma20') or _compute_ma(closes, 20)
        if not all([ma5, ma10, ma20]):
            return None
        if not (ma5 > ma10 > ma20):
            return None
        if price < ma5 * 0.98:
            return None

        # Volume: expanding on up days
        today_vol = volumes[-1]
        avg_vol_5 = sum(volumes[-6:-1]) / 5 if len(volumes) >= 6 else today_vol
        vol_expanding = today_vol > avg_vol_5 * 0.9

        # Bottom check: was this recently at a low?
        low_20 = min(closes[-20:])
        from_low = (price - low_20) / low_20 * 100

        # Classify
        if up_streak >= 5 and change_pct > 5:
            grade = '阵眼龙候选'
        elif up_streak >= 3:
            grade = '核心候选'
        elif up_streak >= 2:
            grade = '领涨候选'
        else:
            grade = '观察'

        score = 0
        score += min(up_streak, 7) * 10
        score += change_pct * 4
        score += min(turnover, 35) * 0.4
        score += 10 if vol_expanding else 0
        score += min(from_low, 20) * 0.5
        score = round(max(0, min(100, score)), 1)

        if score < 35:
            return None

        return {
            'stock_code': code,
            'stock_name': name,
            'price': price,
            'change_pct': change_pct,
            'strategy': '延续性龙头',
            'score': score,
            'signal_detail': {
                'grade': grade,
                'up_streak': up_streak,
                'rest_days': rest_days,
                'vol_expanding': str(vol_expanding),
                'ma5': round(ma5, 2),
                'ma10': round(ma10, 2),
                'from_low': f'{from_low:.1f}%',
                'turnover': f'{turnover:.1f}%',
            }
        }

    candidates = []
    if pool:
        for code, entry in pool.items():
            result = _process(entry['info'], entry.get('kline'))
            if result:
                candidates.append(result)
    else:
        for s in stocks:
            result = _process(s)
            if result:
                candidates.append(result)

    candidates.sort(key=lambda x: x['score'], reverse=True)
    return candidates[:15]


# ── Strategy 4: 盘面强弱 (Market Strength Comparison) ────────────────

def market_strength_rank(pool=None):
    """
    盘面强弱对比 — 从零大A："对比大盘/板块判断个股相对强弱"。

    Ranks stocks by:
    - Relative strength vs market index (超额收益)
    - Relative strength vs sector (板块内排名)
    - Volume quality (放量缩量判断)
    - Momentum acceleration (今日涨速 vs 近日平均)

    Returns stocks that are significantly stronger than both market and sector.
    """
    try:
        index_data = fetcher.get_index_data()
        market_change = 0
        if index_data:
            index_changes = [idx.get('change_pct', 0) for idx in index_data[:2]]
            market_change = sum(index_changes) / len(index_changes) if index_changes else 0
    except Exception:
        market_change = 0

    if pool is None:
        stocks = fetcher.get_stock_list()
        if not stocks:
            return []
        stock_iter = stocks
    else:
        stock_iter = [entry['info'] for entry in pool.values()]

    # Group stocks by rough sector (using board prefix)
    sector_groups = {}
    for s in stock_iter:
        code = s.get('代码', '')
        if code.startswith('60'):
            sec = '上海主板'
        elif code.startswith('00'):
            sec = '深圳主板'
        elif code.startswith('30'):
            sec = '创业板'
        elif code.startswith('68'):
            sec = '科创板'
        else:
            continue

        if sec not in sector_groups:
            sector_groups[sec] = []
        sector_groups[sec].append({
            'code': code,
            'change': float(s.get('涨跌幅', 0)),
            'name': s.get('名称', ''),
        })

    # Calculate sector averages
    sector_avgs = {}
    for sec, members in sector_groups.items():
        if len(members) < 5:
            continue
        sector_avgs[sec] = sum(m['change'] for m in members) / len(members)

    def _process(s):
        code = s['代码']
        name = s['名称']
        price = float(s.get('最新价', 0))
        change_pct = float(s.get('涨跌幅', 0))
        turnover = float(s.get('换手率', 0))
        vol_ratio = float(s.get('量比', 0))

        if price < 6:
            return None
        if 'ST' in name or '退' in name:
            return None

        # Determine sector
        if code.startswith('60'):
            sec = '上海主板'
        elif code.startswith('00'):
            sec = '深圳主板'
        elif code.startswith('30'):
            sec = '创业板'
        elif code.startswith('68'):
            sec = '科创板'
        else:
            return None

        sec_avg = sector_avgs.get(sec, 0)

        # Relative strength vs market
        rs_market = change_pct - market_change
        # Relative strength vs sector
        rs_sector = change_pct - sec_avg

        if rs_market < 1 and rs_sector < 1:
            return None

        # Momentum acceleration: today vs recent average
        kline = fetcher.get_kline_data(code, days=10)
        momentum_accel = 0
        if kline and len(kline) >= 5:
            closes = [k['close'] for k in kline]
            today_ret = (closes[-1] / closes[-2] - 1) * 100
            prior_ret = sum((closes[i] / closes[i - 1] - 1) * 100 for i in range(-3, -1)) / 2
            momentum_accel = today_ret - prior_ret

        score = 0
        score += max(rs_market, 0) * 5
        score += max(rs_sector, 0) * 6
        score += min(vol_ratio, 3) * 5
        score += min(turnover, 25) * 0.3
        score += max(momentum_accel, 0) * 3
        score = round(max(0, min(100, score)), 1)

        if score < 20:
            return None

        return {
            'stock_code': code,
            'stock_name': name,
            'price': price,
            'change_pct': change_pct,
            'strategy': '盘面强弱',
            'score': score,
            'signal_detail': {
                'rs_vs_market': f'{rs_market:+.1f}%',
                'rs_vs_sector': f'{rs_sector:+.1f}%',
                'sec_avg': f'{sec_avg:+.1f}%',
                'market_avg': f'{market_change:+.1f}%',
                'vol_ratio': round(vol_ratio, 1),
                'momentum_accel': f'{momentum_accel:+.1f}%',
                'sector': sec,
            }
        }

    candidates = []
    for s in stock_iter:
        result = _process(s)
        if result:
            candidates.append(result)

    candidates.sort(key=lambda x: x['score'], reverse=True)
    return candidates[:15]


# ── Strategy 5: 科学加仓信号 (Scientific Position Adding) ────────────

def scientific_add_signals(pool=None):
    """
    科学加仓 — 从零大A体系一："趋势确认后，回踩关键位不破=加仓点"。

    Detects pullback-to-key-level opportunities for existing uptrends:
    - Stock in confirmed uptrend (MA20 > MA60)
    - Recently pulled back to near key support level or MA20
    - Volume shrinking on pullback (selling exhausted)
    - Price holding above support
    - Not broken structure (higher low intact)

    Signal detail includes suggested add position size.
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

        kline = kline_hint if kline_hint and len(kline_hint) >= 60 else fetcher.get_kline_data(code, days=130)
        if not kline or len(kline) < 60:
            return None

        closes = [k['close'] for k in kline]
        highs = [k['high'] for k in kline]
        lows = [k['low'] for k in kline]
        volumes = [k['volume'] for k in kline]

        # Confirmed uptrend
        _ind = s.get('_ind', {})
        ma20 = _ind.get('ma20') or _compute_ma(closes, 20)
        ma60 = _ind.get('ma60') or _compute_ma(closes, 60)
        if not ma20 or not ma60:
            return None
        if ma20 <= ma60:
            return None

        # Must have broken above MA60 recently (in trend)
        above_ma60_count = sum(1 for c in closes[-30:] if c > ma60)
        if above_ma60_count < 15:
            return None

        # Find support levels from lows
        supports, _ = _find_key_levels(highs, lows, 60)

        # Check if near a support level or MA20
        near_support = False
        support_level = 0
        for s_level in supports:
            if abs(price - s_level) / s_level < 0.03:
                near_support = True
                support_level = s_level
                break

        near_ma20 = abs(price - ma20) / ma20 < 0.03

        if not (near_support or near_ma20):
            return None

        anchor = support_level if near_support else ma20
        anchor_label = '关键支撑位' if near_support else 'MA20'

        # Check for pullback from recent high
        recent_high = max(highs[-20:])
        pullback_pct = (recent_high - price) / recent_high * 100
        if pullback_pct < 3:
            return None
        if pullback_pct > 15:
            return None

        # Volume shrinking on pullback
        recent_vol = sum(volumes[-3:]) / 3
        vol_10d = sum(volumes[-13:-3]) / 10 if len(volumes) >= 13 else recent_vol
        vol_shrinking = recent_vol < vol_10d * 0.8

        # Higher low intact
        low_20 = min(lows[-20:-5])
        low_5 = min(lows[-5:])
        higher_low = low_5 > low_20 * 0.98

        # Suggested add position (based on pullback depth)
        if pullback_pct > 8:
            add_pct = 0.3
        elif pullback_pct > 5:
            add_pct = 0.2
        else:
            add_pct = 0.15

        score = 0
        score += pullback_pct * 3
        score += 15 if vol_shrinking else 0
        score += 20 if higher_low else 0
        score += 10 if near_support else 5
        score += above_ma60_count * 0.5
        score = round(max(0, min(100, score)), 1)

        if score < 35:
            return None

        return {
            'stock_code': code,
            'stock_name': name,
            'price': price,
            'change_pct': change_pct,
            'strategy': '科学加仓',
            'score': score,
            'signal_detail': {
                'anchor': f'{anchor_label} ¥{anchor:.2f}',
                'pullback_pct': f'{pullback_pct:.1f}%',
                'vol_shrinking': str(vol_shrinking),
                'higher_low': str(higher_low),
                'ma20': round(ma20, 2),
                'ma60': round(ma60, 2),
                'add_position': f'{add_pct*100:.0f}%',
                'trend_status': '趋势确认·回踩加仓',
            }
        }

    candidates = []
    if pool:
        for code, entry in pool.items():
            result = _process(entry['info'], entry.get('kline'))
            if result:
                candidates.append(result)
    else:
        for s in stocks:
            result = _process(s)
            if result:
                candidates.append(result)

    candidates.sort(key=lambda x: x['score'], reverse=True)
    return candidates[:15]


# ── Stop/take-profit params ──────────────────────────────────────────

ConglingParams = {
    'default': {
        'stop_loss_pct': 0.02, 'take_profit_pct': 0.20,
        'trailing_stop_pct': 0.06, 'max_hold_days': 15,
    },
    '关键位突破': {
        'stop_loss_pct': 0.02, 'take_profit_pct': 0.25,
        'trailing_stop_pct': 0.08, 'max_hold_days': 20,
        'exit_below_key_level': True,
    },
    '假突破检测': {
        'stop_loss_pct': 0.02, 'take_profit_pct': 0.10,
        'trailing_stop_pct': 0.04, 'max_hold_days': 3,
    },
    '延续性龙头': {
        'stop_loss_pct': 0.02, 'take_profit_pct': 0.30,
        'trailing_stop_pct': 0.07, 'max_hold_days': 7,
        'exit_on_rest_day': True,
    },
    '盘面强弱': {
        'stop_loss_pct': 0.02, 'take_profit_pct': 0.18,
        'trailing_stop_pct': 0.06, 'max_hold_days': 10,
    },
    '科学加仓': {
        'stop_loss_pct': 0.02, 'take_profit_pct': 0.20,
        'trailing_stop_pct': 0.06, 'max_hold_days': 15,
        'pyramid_add': True,
    },
}


def get_congling_params(strategy_type='default'):
    return ConglingParams.get(strategy_type, ConglingParams['default'])


# ── Aggregation ─────────────────────────────────────────────────────

def get_all_congling_signals(pool=None):
    """Collect all 从零大A strategy signals."""
    result = {}
    strategy_funcs = [
        ('关键位突破', key_level_breakout_candidates),
        ('假突破检测', false_breakout_filter),
        ('延续性龙头', continuity_dragon_candidates),
        ('盘面强弱', market_strength_rank),
        ('科学加仓', scientific_add_signals),
    ]
    for name, func in strategy_funcs:
        try:
            result[name] = func(pool=pool)
        except Exception:
            result[name] = []
    return result
