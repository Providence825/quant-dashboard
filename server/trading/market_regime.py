"""
Market regime detector — determines whether the market is trending or ranging
to automatically route between trend/swing and short-term strategies.

Core indicators:
- ADX (trend strength): >25 trending, <20 ranging
- MA alignment: MA20/MA60/MA120 on Shanghai Index
- Market breadth: up/down ratio across all stocks
- Volatility: 20-day ATR percentile

Regime types: trending_up, trending_down, ranging, transitional
Switching requires 3 consecutive days of same signal.
"""

from datetime import datetime, timedelta
from ..data import fetcher
from ..db import get_db
import json
import os

REGIME_CACHE_FILE = os.path.join(os.path.dirname(__file__), '..', '..', 'regime_state.json')


def _compute_adx(kline, period=14):
    """Compute ADX from daily K-line data."""
    if not kline or len(kline) < period + 1:
        return 20

    highs = [k['high'] for k in kline]
    lows = [k['low'] for k in kline]
    closes = [k['close'] for k in kline]

    tr_list = []
    plus_dm = []
    minus_dm = []

    for i in range(1, len(kline)):
        h, l = highs[i], lows[i]
        ph, pl = highs[i-1], lows[i-1]

        tr = max(h - l, abs(h - closes[i-1]), abs(l - closes[i-1]))
        tr_list.append(tr)

        up_move = h - ph
        down_move = pl - l
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0)

    tr_list = tr_list[-period:]
    plus_dm = plus_dm[-period:]
    minus_dm = minus_dm[-period:]

    atr = sum(tr_list) / period
    sm_plus = sum(plus_dm) / period
    sm_minus = sum(minus_dm) / period

    if atr == 0:
        return 20

    plus_di = sm_plus / atr * 100
    minus_di = sm_minus / atr * 100
    dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) > 0 else 0

    return round(dx, 1)


def _compute_ma(values, period):
    if len(values) < period:
        return sum(values) / len(values) if values else 0
    return sum(values[-period:]) / period


def _get_index_kline(code='000001', days=120):
    """Get index daily K-line (真指数 OHLC) from DB or Sina.

    注意: 必须走 get_index_kline_data, 而非 get_kline_data。后者会把 '000001'
    解析成平安银行(sz000001), 导致 ADX/均线算在个股上 (历史 bug)。"""
    kline = fetcher.get_index_kline_data(code, days=days)
    if not kline or len(kline) < 30:
        return None
    return kline


def _get_market_breadth():
    """Calculate up/down ratio from stock list."""
    stocks = fetcher.get_stock_list()
    if not stocks:
        return 50, 0

    up = sum(1 for s in stocks if float(s.get('涨跌幅', 0)) > 0)
    down = sum(1 for s in stocks if float(s.get('涨跌幅', 0)) < 0)
    total = max(up + down, 1)
    breadth = round(up / total * 100, 1)
    return breadth, total


def detect_regime():
    """
    Determine current market regime.
    Returns: {
        'regime': 'trending_up'|'trending_down'|'ranging'|'transitional',
        'regime_label': str (中文),
        'confidence': 0-100,
        'adx': float,
        'breadth': float (up%),
        'ma_alignment': 'bullish'|'bearish'|'mixed',
        'volatility_pct': float,
        'recommended_strategy': 'trend'|'short_term',
        'details': str
    }
    """
    kline = _get_index_kline('000001', days=120)
    if not kline:
        return {
            'regime': 'transitional',
            'regime_label': '方向不明',
            'confidence': 30,
            'adx': 0,
            'breadth': 50,
            'ma_alignment': 'mixed',
            'volatility_pct': 0,
            'recommended_strategy': 'short_term',
            'details': '无K线数据，默认震荡市'
        }

    # 6. Market breadth (live: from realtime stock list)
    breadth, total_stocks = _get_market_breadth()

    s = score_regime(kline, breadth)

    # ── Persist and apply 3-day confirmation ────────────────────────
    confirmed_regime, confirmed_strategy = _apply_confirmation(s['regime'], s['recommended'])

    regime_labels = {
        'trending_up': '上升趋势',
        'trending_down': '下降趋势',
        'ranging': '震荡整理',
        'transitional': '方向不明',
    }

    result = {
        'regime': confirmed_regime,
        'regime_label': regime_labels.get(confirmed_regime, confirmed_regime),
        'confidence': s['trending_pct'] if 'trending' in confirmed_regime else (100 - s['trending_pct']),
        'raw_regime': s['regime'],
        'adx': s['adx'],
        'breadth': breadth,
        'ma_alignment': s['ma_alignment'],
        'ma20': round(s['ma20'], 2),
        'ma60': round(s['ma60'], 2),
        'ma120': round(s['ma120'], 2),
        'current_price': round(s['current'], 2),
        'ret_20d': round(s['ret_20d'], 2),
        'volatility_pct': round(s['vol_percentile'], 1),
        'trending_score': s['score_trending'],
        'ranging_score': s['score_ranging'],
        'recommended_strategy': confirmed_strategy,
        'details': _format_details(s['regime'], s['adx'], breadth, s['ma_alignment'], s['ret_20d'], s['vol_percentile']),
    }

    return result


def score_regime(kline, breadth):
    """Pure regime scoring — single source of truth for BOTH live (detect_regime)
    and backtest (_regime_reco_at). Given a chronological OHLC kline ending at the
    evaluation day and the market breadth (up% 0-100), returns the raw regime and
    recommendation plus all diagnostics. No I/O, no confirmation, no persistence.

    kline: list of {open,high,low,close,volume} in ascending date order, <= eval day.
    breadth: up-stock percentage 0-100 (live: realtime list; backtest: day's pool).
    """
    closes = [k['close'] for k in kline]
    current = closes[-1] if closes else 0

    # 1. ADX
    adx = _compute_adx(kline, period=14)

    # 2. MA alignment
    ma20 = _compute_ma(closes, 20)
    ma60 = _compute_ma(closes, 60)
    ma120 = _compute_ma(closes, 120)

    if ma20 > ma60 > ma120:
        ma_alignment = 'bullish'
    elif ma20 < ma60 < ma120:
        ma_alignment = 'bearish'
    else:
        ma_alignment = 'mixed'

    # 3. Price vs MAs
    above_ma20 = current > ma20
    above_ma60 = current > ma60

    # 4. 20-day returns (trend direction confirmation)
    if len(closes) >= 20:
        ret_20d = (closes[-1] - closes[-20]) / closes[-20] * 100
    else:
        ret_20d = 0

    # 5. Volatility (20d ATR / price)
    if len(closes) >= 20:
        daily_changes = [abs((closes[i] - closes[i-1]) / closes[i-1] * 100) for i in range(1, len(closes))]
        recent_vol = sum(daily_changes[-20:]) / 20
        hist_vol = sum(daily_changes) / len(daily_changes) if daily_changes else 1
        vol_percentile = min(100, max(0, recent_vol / hist_vol * 50)) if hist_vol > 0 else 50
    else:
        vol_percentile = 50

    # ── Regime Decision ──────────────────────────────────────────────
    score_trending = 0
    score_ranging = 0

    # ADX contribution
    if adx >= 30:
        score_trending += 30
    elif adx >= 25:
        score_trending += 20
    elif adx >= 20:
        score_trending += 10
    else:
        score_ranging += 25

    # MA alignment contribution
    if ma_alignment == 'bullish' and above_ma20:
        score_trending += 25
    elif ma_alignment == 'bearish' and not above_ma60:
        score_trending += 20  # trending down is still trending
    elif ma_alignment == 'mixed':
        score_ranging += 15

    # Breadth contribution (extreme breadth suggests trend)
    if breadth > 70 or breadth < 30:
        score_trending += 15
    elif 40 <= breadth <= 60:
        score_ranging += 15

    # Volatility contribution (moderate vol = trending, too high/low = ranging)
    if 30 <= vol_percentile <= 70:
        score_trending += 10
    elif vol_percentile > 85:
        score_ranging += 10  # extreme volatility → chaotic
    else:
        score_ranging += 5

    # 20d return contribution
    if abs(ret_20d) > 5:
        score_trending += 15
    elif abs(ret_20d) < 2:
        score_ranging += 10

    total_score = score_trending + score_ranging
    trending_pct = round(score_trending / total_score * 100) if total_score > 0 else 50

    # Determine regime
    if score_trending > score_ranging + 10:
        if ret_20d > 0 and ma_alignment in ('bullish', 'mixed'):
            regime = 'trending_up'
        elif ret_20d < 0 and ma_alignment in ('bearish', 'mixed'):
            regime = 'trending_down'
        else:
            regime = 'trending_up' if ret_20d >= 0 else 'trending_down'
        recommended = 'trend'
    elif score_ranging > score_trending + 10:
        regime = 'ranging'
        recommended = 'short_term'
    else:
        regime = 'transitional'
        recommended = 'short_term'

    return {
        'regime': regime,
        'recommended': recommended,
        'adx': adx,
        'ma_alignment': ma_alignment,
        'ma20': ma20, 'ma60': ma60, 'ma120': ma120,
        'current': current,
        'ret_20d': ret_20d,
        'vol_percentile': vol_percentile,
        'score_trending': score_trending,
        'score_ranging': score_ranging,
        'trending_pct': trending_pct,
    }


def _apply_confirmation(current_regime, current_recommendation):
    """
    3-day confirmation: require 3 consecutive days of same signal
    before switching strategy mode. Prevents whipsaw.
    """
    today = datetime.now().strftime('%Y-%m-%d')
    history = _load_regime_history()

    # Add today's reading (replace if already exists to avoid duplicates)
    history = [d for d in history if d.get('date') != today]
    history.append({
        'date': today,
        'regime': current_regime,
        'recommended': current_recommendation,
    })

    # Keep last 5 days
    if len(history) > 5:
        history = history[-5:]

    _save_regime_history(history)

    # Check last 3 days
    if len(history) < 3:
        return 'ranging', 'short_term'

    last_3 = history[-3:]
    regimes = [d['regime'] for d in last_3]
    recommends = [d['recommended'] for d in last_3]

    # All 3 agree on regime category
    all_trending = all(r.startswith('trending') for r in regimes)
    all_ranging = all(r == 'ranging' for r in regimes)
    all_recommend = recommends[0] if all(r == recommends[0] for r in recommends) else None

    if all_trending and all_recommend == 'trend':
        return current_regime, 'trend'
    elif all_ranging and all_recommend == 'short_term':
        return 'ranging', 'short_term'
    else:
        # No consensus → keep previous confirmed state
        if len(history) >= 4:
            prev = history[-4]
            if prev['regime'].startswith('trending'):
                return prev['regime'], 'trend'
        return 'ranging', 'short_term'


def _load_regime_history():
    try:
        if os.path.exists(REGIME_CACHE_FILE):
            with open(REGIME_CACHE_FILE, 'r') as f:
                return json.load(f)
    except:
        pass
    return []


def _save_regime_history(history):
    import tempfile
    try:
        dir_name = os.path.dirname(os.path.abspath(REGIME_CACHE_FILE))
        with tempfile.NamedTemporaryFile('w', dir=dir_name, delete=False,
                                         suffix='.tmp', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False)
            tmp_path = f.name
        os.replace(tmp_path, REGIME_CACHE_FILE)
    except:
        pass


def _format_details(regime, adx, breadth, ma_align, ret_20d, vol_pct):
    labels = {
        'trending_up': '上升趋势',
        'trending_down': '下降趋势',
        'ranging': '震荡整理',
        'transitional': '方向不明',
    }
    label = labels.get(regime, regime)

    ma_labels = {
        'bullish': '多头',
        'bearish': '空头',
        'mixed': '纠缠',
    }
    ma_label = ma_labels.get(ma_align, ma_align)

    parts = [
        f'市场状态: {label}',
        f'ADX趋势强度: {adx}',
        f'涨跌比: {breadth}%',
        f'均线排列: {ma_label}',
        f'20日涨跌: {ret_20d:+.1f}%',
        f'波动分位: {vol_pct}%',
    ]
    return ' | '.join(parts)


def get_active_strategy_mode():
    """Get the currently recommended strategy mode based on market regime."""
    regime_data = detect_regime()
    return regime_data['recommended_strategy'], regime_data
