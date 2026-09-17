"""
组合 Beta 管理器。

计算各持仓股票相对沪深300的滚动 Beta，汇总为加权组合 Beta，
并根据市场状态（regime）输出目标仓位暴露倍数。

Beta = Cov(r_stock, r_market) / Var(r_market)，OLS 估计，窗口 60 日。
暴露映射：
  strong_trending  → 0.90
  trending         → 0.80
  weak_trending    → 0.70
  ranging          → 0.65
  risk_off         → 0.45
  severe_risk_off  → 0.35
"""

import time
from ...db import get_db
from ...data import fetcher

_LOOKBACK = 60
_MIN_HISTORY = 20
_CACHE: dict = {}
_CACHE_TS: dict = {}
_CACHE_TTL = 1800   # 30 分钟

_EXPOSURE_MAP = {
    'strong_trending': 0.90,
    'trending':        0.80,
    'weak_trending':   0.70,
    'ranging':         0.65,
    'risk_off':        0.45,
    'severe_risk_off': 0.35,
}


def _get_index_returns(days: int = _LOOKBACK + 5) -> list:
    """获取沪深300（000300）日收益率序列，先查本地 K 线库，fallback 实时接口。"""
    db = get_db()
    try:
        rows = db.execute(
            "SELECT close FROM stock_kline_daily WHERE stock_code='000300' "
            "ORDER BY date DESC LIMIT ?",
            (days + 1,)
        ).fetchall()
    finally:
        db.close()

    closes = [float(r['close']) for r in reversed(rows)]
    if len(closes) >= 2:
        return [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]

    kline = fetcher.get_kline_data('000300', days=days + 5) or []
    closes = [k['close'] for k in kline]
    if len(closes) < 2:
        return []
    return [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]


def _get_stock_returns(stock_code: str, days: int = _LOOKBACK + 5) -> list:
    db = get_db()
    try:
        rows = db.execute(
            "SELECT close FROM stock_kline_daily WHERE stock_code=? "
            "ORDER BY date DESC LIMIT ?",
            (stock_code, days + 1)
        ).fetchall()
    finally:
        db.close()

    closes = [float(r['close']) for r in reversed(rows)]
    if len(closes) >= 2:
        return [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]

    kline = fetcher.get_kline_data(stock_code, days=days + 5) or []
    closes = [k['close'] for k in kline]
    if len(closes) < 2:
        return []
    return [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]


def compute_stock_beta(stock_code: str, market_returns: list = None) -> float:
    """计算单只股票相对沪深300的 Beta，带 30 分钟缓存。"""
    cache_key = f'beta_{stock_code}'
    now = time.time()
    if cache_key in _CACHE and now - _CACHE_TS.get(cache_key, 0) < _CACHE_TTL:
        return _CACHE[cache_key]

    if market_returns is None:
        market_returns = _get_index_returns()

    stock_returns = _get_stock_returns(stock_code)

    if len(stock_returns) < _MIN_HISTORY or len(market_returns) < _MIN_HISTORY:
        _CACHE[cache_key] = 1.0
        _CACHE_TS[cache_key] = now
        return 1.0

    T = min(len(stock_returns), len(market_returns), _LOOKBACK)
    sr = stock_returns[-T:]
    mr = market_returns[-T:]

    mean_s = sum(sr) / T
    mean_m = sum(mr) / T
    cov = sum((sr[i] - mean_s) * (mr[i] - mean_m) for i in range(T)) / max(T - 1, 1)
    var_m = sum((mr[i] - mean_m) ** 2 for i in range(T)) / max(T - 1, 1)

    beta = cov / var_m if var_m > 1e-12 else 1.0
    beta = round(max(0.1, min(beta, 3.0)), 3)

    _CACHE[cache_key] = beta
    _CACHE_TS[cache_key] = now
    return beta


def compute_portfolio_beta(positions: list) -> dict:
    """
    计算持仓组合的加权平均 Beta。
    positions: [{stock_code, current_price, shares, stock_name}, ...]
    """
    if not positions:
        return {'portfolio_beta': 1.0, 'stocks': [], 'total_mv': 0}

    market_returns = _get_index_returns()
    total_mv = sum(p['current_price'] * p['shares'] for p in positions)
    if total_mv <= 0:
        return {'portfolio_beta': 1.0, 'stocks': [], 'total_mv': 0}

    stocks = []
    weighted_beta = 0.0
    for p in positions:
        mv = p['current_price'] * p['shares']
        w = mv / total_mv
        beta = compute_stock_beta(p['stock_code'], market_returns)
        weighted_beta += w * beta
        stocks.append({
            'stock_code': p['stock_code'],
            'stock_name': p['stock_name'],
            'beta': beta,
            'weight': round(w, 4),
            'market_value': round(mv, 2),
        })

    stocks.sort(key=lambda x: -x['beta'])

    return {
        'portfolio_beta': round(weighted_beta, 3),
        'stocks': stocks,
        'total_mv': round(total_mv, 2),
    }


def get_exposure_multiplier(regime: str = None) -> dict:
    """
    根据 regime 返回目标仓位暴露倍数。
    regime 为 None 时自动检测。
    """
    if regime is None:
        try:
            from ..market_regime import detect_regime
            regime = detect_regime()['regime']
        except Exception:
            regime = 'unknown'

    multiplier = _EXPOSURE_MAP.get(regime, 0.70)
    return {
        'regime': regime,
        'multiplier': multiplier,
        'target_pct': f'{int(multiplier * 100)}%',
    }
