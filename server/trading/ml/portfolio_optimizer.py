"""
风险平价组合优化器。

替代单仓 ATR/Kelly 独立定仓，改为在组合层面均衡每只持仓的波动率贡献。

算法：
  1. 拉取各股过去 lookback 日的日收益率序列
  2. 构建样本协方差矩阵 Σ
  3. 迭代求解风险平价权重 w，使 w_i * (Σw)_i = portfolio_vol / N
  4. 将权重乘以总资产，得到每只股票的建议持仓金额

回退链（数据不足时逐级降级）：
  风险平价 → 逆波动率加权 → 等权
"""

import math
from ...db import get_db
from ...data import fetcher

_MIN_HISTORY = 15        # 最少需要的日 K 线根数
_MAX_ITER = 200          # 风险平价迭代次数
_TOL = 1e-8              # 收敛容差
_LOOKBACK = 30           # 协方差估计窗口（交易日）


# ── 纯 Python 矩阵工具（备用，无 numpy 时使用）──────────────────────

def _dot(A, b):
    return [sum(A[i][j] * b[j] for j in range(len(b))) for i in range(len(A))]


def _cov_matrix(returns_matrix):
    """returns_matrix[i] = list of daily returns for asset i."""
    n = len(returns_matrix)
    T = min(len(r) for r in returns_matrix)
    means = [sum(r[-T:]) / T for r in returns_matrix]
    cov = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i, n):
            ri = returns_matrix[i][-T:]
            rj = returns_matrix[j][-T:]
            c = sum((ri[k] - means[i]) * (rj[k] - means[j]) for k in range(T)) / max(T - 1, 1)
            cov[i][j] = cov[j][i] = c
    return cov


# ── 风险平价核心（numpy 加速，纯 Python 备用）──────────────────────

def _risk_parity_numpy(cov_matrix, max_iter=_MAX_ITER, tol=_TOL):
    import numpy as np
    C = np.array(cov_matrix)
    n = C.shape[0]
    w = np.ones(n) / n
    for _ in range(max_iter):
        sigma = math.sqrt(float(w @ C @ w))
        if sigma < 1e-12:
            break
        mrc = (C @ w) / sigma          # marginal risk contribution
        rc = w * mrc                   # absolute risk contribution
        target = sigma / n
        grad = rc - target
        if np.max(np.abs(grad)) < tol:
            break
        lr = 0.5 / (n * sigma)
        w = w - lr * grad
        w = np.maximum(w, 1e-8)
        w /= w.sum()
    return w.tolist()


def _risk_parity_pure(cov_matrix, max_iter=_MAX_ITER, tol=_TOL):
    n = len(cov_matrix)
    w = [1.0 / n] * n
    for _ in range(max_iter):
        Cw = _dot(cov_matrix, w)
        sigma2 = sum(w[i] * Cw[i] for i in range(n))
        sigma = math.sqrt(max(sigma2, 1e-24))
        rc = [w[i] * Cw[i] / sigma for i in range(n)]
        target = sigma / n
        max_diff = max(abs(rc[i] - target) for i in range(n))
        if max_diff < tol:
            break
        lr = 0.5 / (n * sigma)
        w = [max(w[i] - lr * (rc[i] - target), 1e-8) for i in range(n)]
        s = sum(w)
        w = [x / s for x in w]
    return w


def _solve_risk_parity(cov_matrix):
    try:
        return _risk_parity_numpy(cov_matrix)
    except Exception:
        return _risk_parity_pure(cov_matrix)


# ── 收益率序列获取 ────────────────────────────────────────────────────

def _get_returns(stock_code: str, days: int = _LOOKBACK + 5) -> list:
    """从本地 K 线数据库或实时接口取日收益率，返回最近 days 根。"""
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

    # fallback: live kline
    kline = fetcher.get_kline_data(stock_code, days=days + 5) or []
    closes = [k['close'] for k in kline]
    if len(closes) < 2:
        return []
    return [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]


# ── 主接口 ───────────────────────────────────────────────────────────

def compute_portfolio_weights(
    stock_codes: list,
    min_history: int = _MIN_HISTORY,
    max_single: float = 0.35,
    min_single: float = 0.05,
) -> dict:
    """
    计算风险平价权重。

    Args:
        stock_codes: 股票代码列表（现有持仓 + 候选新仓）
        max_single:  单只上限
        min_single:  单只下限

    Returns:
        {code: weight}，权重已归一化且满足上下限约束。
        如所有股票数据不足，返回等权分配。
    """
    if not stock_codes:
        return {}
    if len(stock_codes) == 1:
        return {stock_codes[0]: 1.0}

    returns_by_code = {}
    for code in stock_codes:
        rets = _get_returns(code)
        if len(rets) >= min_history:
            returns_by_code[code] = rets

    valid = list(returns_by_code.keys())

    if len(valid) < 2:
        # 数据不足：等权
        eq = 1.0 / len(stock_codes)
        return {c: eq for c in stock_codes}

    # 协方差矩阵
    T = min(len(returns_by_code[c]) for c in valid)
    T = min(T, _LOOKBACK)
    ret_matrix = [returns_by_code[c][-T:] for c in valid]

    try:
        cov = _cov_matrix(ret_matrix)
    except Exception:
        # 等权回退
        eq = 1.0 / len(stock_codes)
        return {c: eq for c in stock_codes}

    # 风险平价权重
    weights_valid = _solve_risk_parity(cov)

    # 无数据的股票用均值填充
    avg_w = sum(weights_valid) / len(weights_valid)
    raw = {}
    for i, code in enumerate(valid):
        raw[code] = weights_valid[i]
    for code in stock_codes:
        if code not in raw:
            raw[code] = avg_w

    # 上下限 clip + 重新归一化（两轮）
    for _ in range(3):
        s = sum(raw.values())
        raw = {c: v / s for c, v in raw.items()}
        raw = {c: max(min_single, min(max_single, v)) for c, v in raw.items()}
    s = sum(raw.values())
    return {c: round(v / s, 4) for c, v in raw.items()}


def suggest_buy_amount(
    candidate_code: str,
    total_asset: float,
    current_positions: list,
    available_cash: float,
    max_single: float = 0.35,
) -> float:
    """
    在加入候选股后，用风险平价计算该候选股的建议持仓金额。
    目标金额 = 总资产 × 暴露倍数（regime驱动） × 风险平价权重。

    Returns: 建议买入金额（已考虑可用资金上限）。
    """
    holding_codes = [p['stock_code'] for p in current_positions]
    all_codes = holding_codes + ([candidate_code] if candidate_code not in holding_codes else [])

    weights = compute_portfolio_weights(all_codes, max_single=max_single)
    target_w = weights.get(candidate_code, 1.0 / max(len(all_codes), 1))

    # 暴露倍数：根据 regime 缩放可部署资产
    try:
        from .beta_tracker import get_exposure_multiplier
        exposure = get_exposure_multiplier()['multiplier']
    except Exception:
        exposure = 0.80

    # 目标持仓金额 = 总资产 × 暴露倍数 × 风险平价权重
    target_amount = total_asset * exposure * target_w

    # 当前已持有该股的市值
    current_val = next(
        (p['current_price'] * p['shares'] for p in current_positions
         if p['stock_code'] == candidate_code), 0.0)

    # 需要新买入的金额（不超过可用现金）
    need = max(0.0, target_amount - current_val)
    return round(min(need, available_cash * 0.95), 2)


def get_portfolio_analysis(current_positions: list, total_asset: float) -> dict:
    """
    对现有持仓做风险平价分析：计算当前实际权重 vs 理想权重，找出偏差最大的仓位。
    供 API 调用/前端展示。
    """
    if not current_positions:
        return {'positions': [], 'summary': {'status': '空仓'}}

    codes = [p['stock_code'] for p in current_positions]
    ideal_weights = compute_portfolio_weights(codes)

    result = []
    total_mv = sum(p['current_price'] * p['shares'] for p in current_positions)

    for pos in current_positions:
        code = pos['stock_code']
        mv = pos['current_price'] * pos['shares']
        actual_w = mv / total_mv if total_mv > 0 else 0
        ideal_w = ideal_weights.get(code, 1.0 / len(codes))
        deviation = actual_w - ideal_w
        action = ('减仓' if deviation > 0.05 else '加仓' if deviation < -0.05 else '持有')
        result.append({
            'stock_code': code,
            'stock_name': pos['stock_name'],
            'actual_weight': round(actual_w, 4),
            'ideal_weight': round(ideal_w, 4),
            'deviation': round(deviation, 4),
            'action': action,
            'market_value': round(mv, 2),
        })

    result.sort(key=lambda r: -abs(r['deviation']))

    overweight = [r for r in result if r['action'] == '减仓']
    underweight = [r for r in result if r['action'] == '加仓']

    return {
        'positions': result,
        'summary': {
            'total_mv': round(total_mv, 2),
            'cash_ratio': round(1 - total_mv / total_asset, 4) if total_asset > 0 else 1.0,
            'overweight': [r['stock_name'] for r in overweight],
            'underweight': [r['stock_name'] for r in underweight],
            'status': '均衡' if not overweight and not underweight else f'{len(overweight)}只超配/{len(underweight)}只低配',
        },
    }
