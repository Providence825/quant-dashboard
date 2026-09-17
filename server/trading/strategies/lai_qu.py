"""
来去由心 quantitative strategies.
Based on B站 trader methodology: 情绪周期 + 趋势三买点 + 板块选股 + 龙头识别

Signal format matches existing convention:
    {stock_code, stock_name, price, change_pct, score, strategy, signal_detail}
"""

from ...data import fetcher
from datetime import datetime
import time

# Module-level result cache to avoid recalculating on every API request
_results_cache = {}
_results_ts = 0.0
_RESULTS_TTL = 30  # seconds
_MAX_POOL_SIZE = 200  # Limit candidate pool for performance


# ── Utility functions ─────────────────────────────────────────────────

def _compute_ma(closes, period):
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


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


def _volume_drying(kline, period=10):
    """Check if volume is drying up relative to historical average."""
    if len(kline) < period + 5:
        return False, 0
    recent_vol = [k['volume'] for k in kline[-5:]]
    hist_vol = [k['volume'] for k in kline[-(period + 5):-5]]
    recent_avg = sum(recent_vol) / len(recent_vol)
    hist_avg = sum(hist_vol) / len(hist_vol) if hist_vol else recent_avg
    ratio = recent_avg / hist_avg if hist_avg > 0 else 1
    return ratio < 0.6, round(ratio, 2)


def _strong_close(kline):
    """Brooks strong close: close in upper 1/3 of bar's range. Returns (bool, ratio)."""
    bar = kline[-1]
    rng = bar['high'] - bar['low']
    if rng < 0.001:
        return True, 1.0  # Doji — neutral, don't penalise
    ratio = (bar['close'] - bar['low']) / rng
    return ratio >= 0.65, round(ratio, 2)


def _two_legged_pullback(kline, lookback=15):
    """
    Two-legged pullback: two distinct swing lows where the second is >= first.
    Returns (bool, detail_str).
    """
    if len(kline) < lookback:
        return False, ''
    closes = [k['close'] for k in kline[-lookback:]]
    valleys = []
    for i in range(1, len(closes) - 1):
        if closes[i] < closes[i - 1] and closes[i] < closes[i + 1]:
            valleys.append((i, closes[i]))
    if len(valleys) < 2:
        return False, ''
    v1_price = valleys[-2][1]
    v2_price = valleys[-1][1]
    # Second low >= first low (with 1% tolerance)
    is_two_leg = v2_price >= v1_price * 0.99
    return is_two_leg, f'低1={v1_price:.2f} 低2={v2_price:.2f}'


def _quick_filter(s):
    """Pre-filter before expensive K-line fetch."""
    name = s.get('名称', '')
    price = float(s.get('最新价', 0))
    if price < 5:
        return False
    if 'ST' in name or '退' in name:
        return False
    return True


# ── Buy Point 1: 底部建仓 (1/3 position) ─────────────────────────────

def buy_point_1_candidates(pool=None):
    """
    底部建仓 — 来去由心第一买点，1/3仓位试探。

    Conditions:
    - Price near 120-day low (within 20%)
    - Volume significantly drying (recent < 60% of historical avg)
    - Trendline flattening → starting to rise
    - Double bottom pattern (two lows within 5%, 20-60 days apart)
    - Price still below M60 (hasn't broken out yet)
    - Stop: break of trendline/low point
    """
    if pool is None:
        pool = _get_candidate_pool()

    candidates = []
    for code, entry in pool.items():
        s = entry['info']
        name = s.get('名称', '')
        price = float(s.get('最新价', 0))
        change_pct = float(s.get('涨跌幅', 0))

        # Lazy load kline
        if entry['kline'] is None:
            entry['kline'] = fetcher.get_kline_data(code, days=130)
        kline = entry['kline']
        if not kline or len(kline) < 60:
            continue

        closes = [k['close'] for k in kline]
        _ind = s.get('_ind', {})
        ma60 = _ind.get('ma60') or _compute_ma(closes, 60)
        if not ma60:
            continue

        # Price below M60 (hasn't broken out)
        if price > ma60 * 1.05:
            continue

        # Near long-term low
        low_120 = min(closes[-120:]) if len(closes) >= 120 else min(closes)
        above_low_pct = (price - low_120) / low_120 * 100
        if above_low_pct > 20:
            continue

        # Volume drying
        vol_drying, vol_ratio = _volume_drying(kline)
        if not vol_drying:
            continue

        # Trendline turning up
        slope_recent, r2_recent = _compute_trendline(closes, 30)
        slope_older, _ = _compute_trendline(closes[:-15], 30) if len(closes) >= 45 else (0, 0)
        trend_turning = slope_recent > slope_older and slope_recent > -0.02

        # Double bottom check
        double_bottom = False
        if len(closes) >= 60:
            lows_60 = closes[-60:]
            l1 = min(lows_60[:40])
            l2 = min(lows_60[-30:])
            if max(l1, l2) > 0 and abs(l1 - l2) / max(l1, l2) < 0.05:
                double_bottom = True

        score = 0
        score += (1 - vol_ratio) * 30
        score += (15 - above_low_pct) * 1.5
        score += 20 if double_bottom else 0
        score += 15 if trend_turning else 0
        score += min((ma60 - price) / ma60 * 100, 10)
        score = round(max(0, min(100, score)), 1)

        if score < 40:
            continue

        candidates.append({
            'stock_code': code,
            'stock_name': name,
            'price': price,
            'change_pct': change_pct,
            'strategy': '趋势买点1·底部建仓',
            'score': score,
            'signal_detail': {
                'above_120d_low': f'{above_low_pct:.1f}%',
                'vol_drying': str(vol_drying),
                'vol_ratio': f'{vol_ratio:.2f}',
                'ma60': round(ma60, 2),
                'price_vs_ma60': f'{(price/ma60 - 1)*100:+.1f}%',
                'trend_slope': round(slope_recent, 4),
                'double_bottom': str(double_bottom),
                'position': '1/3仓位',
            }
        })

    candidates.sort(key=lambda x: x['score'], reverse=True)
    return candidates[:15]


# ── Buy Point 2: M60突破加仓 (6-7成 position) ────────────────────────

def buy_point_2_candidates(pool=None):
    """
    M60突破加仓 — 来去由心第二买点，加仓至6-7成。

    Conditions:
    - Effective M60 breakout (price > M60 for 2+ days)
    - Trendline clearly upward (positive slope, r-squared > 0.4)
    - Volume expansion >= 1.3x on breakout
    - MA20 > MA60 (confirmed uptrend)
    - Not chasing limit-up (change_pct < 9.5%)
    - Stop: fall back below M60 within 3 days
    """
    if pool is None:
        pool = _get_candidate_pool()

    candidates = []
    for code, entry in pool.items():
        s = entry['info']
        name = s.get('名称', '')
        price = float(s.get('最新价', 0))
        change_pct = float(s.get('涨跌幅', 0))
        turnover = float(s.get('换手率', 0))

        if price < 8:
            continue
        if change_pct > 9.5:
            continue

        # Lazy load kline
        if entry['kline'] is None:
            entry['kline'] = fetcher.get_kline_data(code, days=130)
        kline = entry['kline']
        if not kline or len(kline) < 65:
            continue

        closes = [k['close'] for k in kline]
        volumes = [k['volume'] for k in kline]
        _ind = s.get('_ind', {})

        ma20 = _ind.get('ma20') or _compute_ma(closes, 20)
        ma60 = _ind.get('ma60') or _compute_ma(closes, 60)
        if not ma20 or not ma60:
            continue

        # Price above M60
        if price < ma60 * 1.01:
            continue

        # M60 above for at least 2 bars
        breakout_bars = sum(1 for c in closes[-5:] if c > ma60)
        if breakout_bars < 2:
            continue

        # Trendline upward
        slope, r2 = _compute_trendline(closes, 30)
        if slope <= 0.001 or r2 < 0.4:
            continue

        # Volume expansion
        vol_avg_20 = _ind.get('vol_avg20') or (sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else volumes[-1])
        vol_ratio = volumes[-1] / vol_avg_20 if vol_avg_20 > 0 else 1
        if vol_ratio < 1.3:
            continue

        # MA20 > MA60
        if ma20 <= ma60:
            continue

        # Strong close: Brooks确认棒，收盘在K线上1/3才算有效突破
        sc_pass, sc_ratio = _strong_close(kline)
        if not sc_pass:
            continue

        gap_up = kline[-1]['low'] > kline[-2]['high'] if len(kline) >= 2 else False
        nb = fetcher.get_northbound_flow(code)
        nb_bullish = nb['bullish'] if nb else False

        score = 0
        score += min((price / ma60 - 1) * 100 * 3, 30)
        score += min(vol_ratio, 3) * 8
        score += min(slope * 10000, 10)
        score += r2 * 20
        score += 10 if gap_up else 0
        score += 8 if nb_bullish else 0
        score += (35 - min(turnover, 35)) * 0.3
        score = round(max(0, min(100, score)), 1)

        if score < 45:
            continue

        candidates.append({
            'stock_code': code,
            'stock_name': name,
            'price': price,
            'change_pct': change_pct,
            'strategy': '趋势买点2·M60突破',
            'score': score,
            'signal_detail': {
                'price_vs_ma60': f'{(price/ma60 - 1)*100:+.1f}%',
                'ma60': round(ma60, 2),
                'ma20': round(ma20, 2),
                'vol_ratio': round(vol_ratio, 1),
                'trend_slope': round(slope, 4),
                'r2': round(r2, 3),
                'gap_up': str(gap_up),
                'strong_close': f'{sc_ratio:.2f}',
                'northbound': f'+{nb["net_5d"]:.0f}万' if nb_bullish else '无',
                'breakout_days': breakout_bars,
                'position': '6-7成仓位',
            }
        })

    candidates.sort(key=lambda x: x['score'], reverse=True)
    return candidates[:15]


# ── Buy Point 3: 回踩重仓 (full position) ───────────────────────────

def buy_point_3_candidates(pool=None):
    """
    回踩重仓 — 来去由心第三买点，满仓/重仓出手。

    Conditions:
    - Prior M60 breakout confirmed (10+ of last 20 days above M60)
    - MA20 > MA60 (trend intact)
    - Price pulls back to M5 or M10 (shorter MA = stronger)
    - Volume shrinking on pullback (not heavy distribution)
    - Price above MA20 by 3%+ (safety net)
    - At least 3% pullback from recent high
    - Stop: break below pullback low or M20
    """
    if pool is None:
        pool = _get_candidate_pool()

    candidates = []
    for code, entry in pool.items():
        s = entry['info']
        name = s.get('名称', '')
        price = float(s.get('最新价', 0))
        change_pct = float(s.get('涨跌幅', 0))

        if price < 10:
            continue

        # Lazy load kline
        if entry['kline'] is None:
            entry['kline'] = fetcher.get_kline_data(code, days=130)
        kline = entry['kline']
        if not kline or len(kline) < 65:
            continue

        closes = [k['close'] for k in kline]
        volumes = [k['volume'] for k in kline]
        _ind = s.get('_ind', {})

        ma5 = _ind.get('ma5') or _compute_ma(closes, 5)
        ma10 = _ind.get('ma10') or _compute_ma(closes, 10)
        ma20 = _ind.get('ma20') or _compute_ma(closes, 20)
        ma60 = _ind.get('ma60') or _compute_ma(closes, 60)
        if not all([ma5, ma10, ma20, ma60]):
            continue

        # Prior M60 breakout
        above_ma60_count = sum(1 for c in closes[-20:] if c > ma60)
        if above_ma60_count < 10:
            continue

        # Trend intact
        if ma20 <= ma60:
            continue

        # Pullback to M5 or M10
        dist_ma5 = abs(price - ma5) / ma5 * 100
        dist_ma10 = abs(price - ma10) / ma10 * 100
        near_ma5 = dist_ma5 <= 3
        near_ma10 = dist_ma10 <= 3
        if not (near_ma5 or near_ma10):
            continue

        ma_target = 'M5' if near_ma5 else 'M10'
        ma_value = ma5 if near_ma5 else ma10
        strength_label = '强' if near_ma5 else '中'

        if price < ma_value * 0.98:
            continue

        # Volume shrinking
        recent_vol = sum(volumes[-3:]) / 3
        vol_10d = sum(volumes[-13:-3]) / 10 if len(volumes) >= 13 else recent_vol
        vol_contracting = recent_vol < vol_10d * 0.8

        # Pullback from recent high
        recent_high_20 = max(closes[-20:])
        pullback_pct = (recent_high_20 - price) / recent_high_20 * 100
        if pullback_pct < 3:
            continue

        # Above M20 safety
        if price < ma20 * 0.97:
            continue

        slope, r2 = _compute_trendline(closes, 30)
        sc_pass, sc_ratio = _strong_close(kline)
        two_leg, two_leg_detail = _two_legged_pullback(kline, lookback=15)
        nb = fetcher.get_northbound_flow(code)
        nb_bullish = nb['bullish'] if nb else False

        score = 0
        score += (3 - (dist_ma5 if near_ma5 else dist_ma10)) * 10
        score += pullback_pct * 3
        score += 15 if vol_contracting else 0
        score += min(slope * 50000, 15)
        score += above_ma60_count * 1.5
        score += 10 if sc_pass else 0    # Brooks强收盘加分
        score += 12 if two_leg else 0    # 两腿回调结构加分
        score += 8 if nb_bullish else 0
        score = round(max(0, min(100, score)), 1)

        if score < 40:
            continue

        candidates.append({
            'stock_code': code,
            'stock_name': name,
            'price': price,
            'change_pct': change_pct,
            'strategy': '趋势买点3·回踩重仓',
            'score': score,
            'signal_detail': {
                'ma_target': ma_target,
                'ma_value': round(ma_value, 2),
                'dist_to_ma': f'{dist_ma5 if near_ma5 else dist_ma10:.1f}%',
                'pullback': f'{pullback_pct:.1f}%',
                'ma20': round(ma20, 2),
                'ma60': round(ma60, 2),
                'vol_shrink': str(vol_contracting),
                'above_ma60': f'{above_ma60_count}/20天',
                'strength': strength_label,
                'strong_close': f'{sc_ratio:.2f}',
                'two_leg': two_leg_detail if two_leg else '否',
                'northbound': f'+{nb["net_5d"]:.0f}万' if nb_bullish else '无',
                'position': '满仓/重仓',
            }
        })

    candidates.sort(key=lambda x: x['score'], reverse=True)
    return candidates[:15]


# ── Sector Frontline (板块最强前排) ──────────────────────────────────

def sector_frontline_candidates(pool=None):
    """
    板块最强前排 — 来去由心板块选股法。

    1. Rank sectors by strength
    2. Pick top 3 sectors
    3. Within each, rank stocks by change/volume/leader quality
    4. Return top 5 per sector
    """
    try:
        from ...data.sectors import compute_sector_strength
        sectors = compute_sector_strength()
    except Exception:
        return []

    if not sectors:
        return []

    top_sectors = [s['name'] for s in sectors[:3]]

    if pool is None:
        stocks = fetcher.get_stock_list()
        if not stocks:
            return []
        stock_iter = stocks
    else:
        stock_iter = [entry['info'] for entry in pool.values()]

    # Build keyword map from SECTOR_DEFS
    from ...data.sectors import SECTOR_DEFS
    sector_keywords = {}
    for name, _cat, _etf in SECTOR_DEFS:
        sector_keywords[name] = name

    candidates = []
    for s in stock_iter:
        if not _quick_filter(s):
            continue
        code = s['代码']
        name = s['名称']
        price = float(s.get('最新价', 0))
        change_pct = float(s.get('涨跌幅', 0))
        vol_ratio = float(s.get('量比', 0))
        turnover = float(s.get('换手率', 0))

        # Check if stock belongs to top sector
        matched_sector = None
        for sec_name in top_sectors:
            # Simple keyword match
            if sec_name in name:
                matched_sector = sec_name
                break

        if not matched_sector:
            continue

        if change_pct < 0:
            continue

        score = min(change_pct * 6, 40) + min(vol_ratio, 4) * 8 + turnover * 0.5
        score = round(max(0, min(100, score)), 1)

        if score < 25:
            continue

        candidates.append({
            'stock_code': code,
            'stock_name': name,
            'price': price,
            'change_pct': change_pct,
            'strategy': '板块最强前排',
            'score': score,
            'signal_detail': {
                'sector': matched_sector,
                'change_pct': f'{change_pct:+.1f}%',
                'vol_ratio': round(vol_ratio, 1),
                'turnover': f'{turnover:.1f}%',
            }
        })

    candidates.sort(key=lambda x: x['score'], reverse=True)
    return candidates[:15]


# ── Dragon Leader: 2进3板检测 ──────────────────────────────────────

def dragon_2jin3_candidates(pool=None):
    """
    2进3板检测 — 来去由心龙头战法关键节点。

    Find stocks that had 2 consecutive limit-ups and attempting the 3rd.
    The 2→3 transition is the most critical entry for dragon leaders.
    """
    if pool is None:
        pool = _get_candidate_pool()

    candidates = []
    for code, entry in pool.items():
        s = entry['info']
        name = s.get('名称', '')
        price = float(s.get('最新价', 0))
        change_pct = float(s.get('涨跌幅', 0))
        vol_ratio = float(s.get('量比', 0))
        turnover = float(s.get('换手率', 0))

        # Only need short history for 2→3 check
        if entry['kline'] is None:
            entry['kline'] = fetcher.get_kline_data(code, days=10)
        kline = entry['kline']
        if not kline or len(kline) < 3:
            continue

        # Check last 2 days for limit-up
        yesterday_change = (kline[-2]['close'] / kline[-3]['close'] - 1) * 100 if len(kline) >= 3 else 0
        day_before_change = (kline[-3]['close'] / kline[-4]['close'] - 1) * 100 if len(kline) >= 4 else 0

        if not (yesterday_change >= 9.5 and day_before_change >= 9.5):
            continue

        # Today is the 3rd day attempt
        if change_pct > 9.5:
            continue  # Already limit-up, too late
        if change_pct < -3:
            continue  # Breaking down, too risky

        # Volume and turnover must be healthy
        if vol_ratio < 1.5:
            continue
        if turnover < 8 or turnover > 45:
            continue

        # Score: higher for strong opening, volume confirmation, moderate turnover
        score = 0
        score += min(change_pct + 3, 10) * 3  # Closer to limit-up = better
        score += min(vol_ratio, 5) * 5
        score += (15 - abs(turnover - 20)) * 1.5  # Sweet spot around 20%
        score = round(max(0, min(100, score)), 1)

        if score < 45:
            continue

        candidates.append({
            'stock_code': code,
            'stock_name': name,
            'price': price,
            'change_pct': change_pct,
            'strategy': '龙头2进3板',
            'score': score,
            'signal_detail': {
                'yesterday': f'{yesterday_change:+.1f}%',
                'day_before': f'{day_before_change:+.1f}%',
                'today': f'{change_pct:+.2f}%',
                'vol_ratio': round(vol_ratio, 1),
                'turnover': f'{turnover:.1f}%',
            }
        })

    candidates.sort(key=lambda x: x['score'], reverse=True)
    return candidates[:10]


# ── Dragon Leader: 卡位分析 ─────────────────────────────────────────

def dragon_kawai_analysis(pool=None):
    """
    卡位分析 — detect stocks jockeying for sector leader position.

    A stock "卡位" when:
    - It leads its sector by significant margin (>3% over sector avg)
    - Its volume dwarfs sector peers
    - It has more consecutive up days
    - Strong K-line pattern
    """
    if pool is None:
        stocks = fetcher.get_stock_list()
        if not stocks:
            return []
        if not isinstance(stocks, list) or len(stocks) < 10:
            return []
        stock_items = [(s.get('代码', ''), s) for s in stocks]
    else:
        stock_items = [(code, entry['info']) for code, entry in pool.items()]
        if len(stock_items) < 10:
            return []

    # Calculate sector averages
    sectors = {}
    for code, s in stock_items:
        name = s.get('名称', '')
        change = float(s.get('涨跌幅', 0))
        turnover = float(s.get('换手率', 0))
        vol_ratio = float(s.get('量比', 0))

        if not code or change == 0:
            continue

        # Broad sector grouping by board prefix
        if code.startswith('60'):
            sector = '上海主板'
        elif code.startswith('00'):
            sector = '深圳主板'
        elif code.startswith('30'):
            sector = '创业板'
        elif code.startswith('68'):
            sector = '科创板'
        else:
            continue

        if sector not in sectors:
            sectors[sector] = []
        sectors[sector].append({
            'code': code, 'name': name, 'change': change,
            'turnover': turnover, 'vol_ratio': vol_ratio,
            'price': float(s.get('最新价', 0))
        })

    candidates = []
    for sector, members in sectors.items():
        if len(members) < 5:
            continue

        avg_change = sum(m['change'] for m in members) / len(members)
        avg_vol = sum(m['vol_ratio'] for m in members) / len(members)

        for m in members:
            # Leader must outperform sector avg significantly
            if m['change'] < avg_change + 2:
                continue
            if m['vol_ratio'] < avg_vol * 1.5:
                continue
            if m['turnover'] < 5:
                continue

            lead_margin = m['change'] - avg_change
            score = min(lead_margin * 8, 40) + m['vol_ratio'] * 6 + m['turnover'] * 0.5
            score = round(max(0, min(100, score)), 1)

            if score < 30:
                continue

            candidates.append({
                'stock_code': m['code'],
                'stock_name': m['name'],
                'price': m['price'],
                'change_pct': m['change'],
                'strategy': '卡位龙头',
                'score': score,
                'signal_detail': {
                    'sector': sector,
                    'sector_avg': f'{avg_change:+.1f}%',
                    'lead_margin': f'{lead_margin:+.1f}%',
                    'vol_ratio': round(m['vol_ratio'], 1),
                    'turnover': f'{m["turnover"]:.1f}%',
                }
            })

    candidates.sort(key=lambda x: x['score'], reverse=True)
    return candidates[:10]


# ── Dragon Leader: 补涨龙识别 ──────────────────────────────────────

def dragon_buchang_candidates(pool=None):
    """
    补涨龙识别 — 同板块跟风补涨标的。

    When the main dragon is too expensive (5+ boards), find compensatory dragons:
    - Same sector as main dragon
    - Recently strengthening (momentum accelerating last 2-3 days)
    - Still accessible (not limit-up locked)
    - Volume expanding
    """
    if pool is None:
        pool = _get_candidate_pool()

    candidates = []
    for code, entry in pool.items():
        s = entry['info']
        name = s.get('名称', '')
        price = float(s.get('最新价', 0))
        change_pct = float(s.get('涨跌幅', 0))
        vol_ratio = float(s.get('量比', 0))
        turnover = float(s.get('换手率', 0))

        if change_pct > 9.5:
            continue
        if change_pct < 2:
            continue

        if entry['kline'] is None:
            entry['kline'] = fetcher.get_kline_data(code, days=10)
        kline = entry['kline']
        if not kline or len(kline) < 5:
            continue

        closes = [k['close'] for k in kline]
        _ind = s.get('_ind', {})

        # Today's change is accelerating vs prior days
        today_ret = (closes[-1] / closes[-2] - 1) * 100
        prior_avg_ret = sum((closes[i] / closes[i - 1] - 1) * 100 for i in range(-4, -1)) / 3 if len(closes) >= 5 else 0

        if today_ret < prior_avg_ret * 1.5:
            continue
        if vol_ratio < 1.8:
            continue
        if turnover < 5 or turnover > 40:
            continue

        ma5 = _ind.get('ma5') or _compute_ma(closes, 5)
        ma10 = _ind.get('ma10') or _compute_ma(closes, 10)
        if not ma5 or not ma10:
            continue
        if price < ma10:
            continue

        score = round(change_pct * 5 + vol_ratio * 8 + turnover * 0.5, 1)
        score = max(0, min(100, score))

        if score < 30:
            continue

        candidates.append({
            'stock_code': code,
            'stock_name': name,
            'price': price,
            'change_pct': change_pct,
            'strategy': '补涨龙',
            'score': score,
            'signal_detail': {
                'accel': f'{today_ret - prior_avg_ret:+.1f}%',
                'vol_ratio': round(vol_ratio, 1),
                'turnover': f'{turnover:.1f}%',
                'ma5': round(ma5, 2),
                'ma10': round(ma10, 2),
            }
        })

    candidates.sort(key=lambda x: x['score'], reverse=True)
    return candidates[:10]


# ── Stop/take-profit params ──────────────────────────────────────────

LaiQuParams = {
    'default': {
        'stop_loss_pct': 0.02, 'take_profit_pct': 0.25,
        'trailing_stop_pct': 0.07, 'max_hold_days': 20,
    },
    '趋势买点1·底部建仓': {
        'stop_loss_pct': 0.02, 'take_profit_pct': 0.30,
        'trailing_stop_pct': 0.06, 'max_hold_days': 30,
        'suggested_position_pct': 0.33,
    },
    '趋势买点2·M60突破': {
        'stop_loss_pct': 0.02, 'take_profit_pct': 0.25,
        'trailing_stop_pct': 0.07, 'max_hold_days': 20,
        'suggested_position_pct': 0.65,
        'exit_below_ma60': True,
    },
    '趋势买点3·回踩重仓': {
        'stop_loss_pct': 0.02, 'take_profit_pct': 0.20,
        'trailing_stop_pct': 0.08, 'max_hold_days': 15,
        'suggested_position_pct': 0.90,
        'exit_below_ma20': True,
    },
    '龙头2进3板': {
        'stop_loss_pct': 0.02, 'take_profit_pct': 0.30,
        'trailing_stop_pct': 0.08, 'max_hold_days': 5,
    },
    '卡位龙头': {
        'stop_loss_pct': 0.02, 'take_profit_pct': 0.25,
        'trailing_stop_pct': 0.07, 'max_hold_days': 7,
    },
    '补涨龙': {
        'stop_loss_pct': 0.02, 'take_profit_pct': 0.20,
        'trailing_stop_pct': 0.06, 'max_hold_days': 5,
    },
}


def get_lai_qu_params(strategy_type='default'):
    return LaiQuParams.get(strategy_type, LaiQuParams['default'])


# ── Aggregation ─────────────────────────────────────────────────────

def _get_candidate_pool():
    """
    Build a shared candidate pool to avoid repeated K-line fetches across strategies.
    Returns dict {code: {'info': stock_info_dict, 'kline': kline_list}}.
    Only includes the most active/volatile stocks, limited to _MAX_POOL_SIZE.
    """
    stocks = fetcher.get_stock_list()
    if not stocks:
        return {}

    # Score all stocks by "interestingness"
    scored = []
    for s in stocks:
        if not _quick_filter(s):
            continue
        code = s.get('代码', '')
        price = float(s.get('最新价', 0))
        change = float(s.get('涨跌幅', 0))
        vol_ratio = float(s.get('量比', 0))
        turnover = float(s.get('换手率', 0))

        if price < 5:
            continue

        # Interest score: prioritize volatile, high-volume stocks
        interest = abs(change) * 3 + abs(vol_ratio - 1) * 5 + turnover * 0.5
        if interest < 5:
            continue

        scored.append((interest, code, s))

    # Take top N most interesting
    scored.sort(key=lambda x: x[0], reverse=True)
    scored = scored[:_MAX_POOL_SIZE]

    pool = {}
    for interest, code, s in scored:
        pool[code] = {
            'info': s,
            'kline': None,  # Lazy load
        }

    return pool


def get_all_lai_qu_signals(use_cache=True, pool=None):
    """Collect all 来去由心 strategy signals. Uses result cache with 20s TTL."""
    global _results_cache, _results_ts

    if use_cache and pool is None and _results_cache and (time.time() - _results_ts) < _RESULTS_TTL:
        return _results_cache

    # Build pool if not provided
    if pool is None:
        pool = _get_candidate_pool()
    if not pool:
        return {n: [] for n, _ in [
            ('趋势买点1·底部建仓', None), ('趋势买点2·M60突破', None),
            ('趋势买点3·回踩重仓', None), ('板块最强前排', None),
            ('龙头2进3板', None), ('卡位龙头', None), ('补涨龙', None),
        ]}

    result = {}
    strategy_funcs = [
        ('趋势买点1·底部建仓', buy_point_1_candidates),
        ('趋势买点2·M60突破', buy_point_2_candidates),
        ('趋势买点3·回踩重仓', buy_point_3_candidates),
        ('板块最强前排', sector_frontline_candidates),
        ('龙头2进3板', dragon_2jin3_candidates),
        ('卡位龙头', dragon_kawai_analysis),
        ('补涨龙', dragon_buchang_candidates),
    ]
    for name, func in strategy_funcs:
        try:
            result[name] = func(pool=pool)
        except Exception:
            result[name] = []

    _results_cache = result
    _results_ts = time.time()
    return result
