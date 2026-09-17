"""
凯利公式仓位计算器。

full_kelly = (p * b - (1 - p)) / b
  p = 胜率 (0-1)
  b = 平均盈亏比 = avg_win / avg_loss

实际使用半凯利(0.5f)，避免波动过大。
返回值为占总资金的比例 (0.0-1.0)，已做安全截断。
"""


def kelly_position(win_rate: float, avg_win_pct: float, avg_loss_pct: float,
                   fraction: float = 0.5, max_pos: float = 0.30,
                   min_pos: float = 0.05) -> float:
    """
    计算凯利仓位比例。

    Args:
        win_rate:     历史胜率 (0-1)
        avg_win_pct:  平均盈利幅度，如 0.12 = 12%
        avg_loss_pct: 平均亏损幅度（绝对值），如 0.05 = 5%
        fraction:     凯利分数，默认半凯利 0.5
        max_pos:      单仓上限（默认 30%）
        min_pos:      最小仓位（默认 5%）

    Returns:
        建议仓位比例 (0.0-1.0)
    """
    if avg_loss_pct <= 0 or win_rate <= 0:
        return min_pos
    b = avg_win_pct / avg_loss_pct
    p = win_rate
    q = 1.0 - p
    f = (p * b - q) / b
    f = f * fraction
    return round(max(min_pos, min(max_pos, f)), 4)


def kelly_from_winrate_row(row: dict, fraction: float = 0.5) -> float:
    """从 ml_winrate_cache 行直接算仓位。"""
    return kelly_position(
        win_rate=float(row.get('win_rate', 0.5)),
        avg_win_pct=float(row.get('avg_win_pct', 0.10)),
        avg_loss_pct=float(row.get('avg_loss_pct', 0.05)),
        fraction=fraction,
    )


def atr_position(kline: list, capital: float, price: float,
                 risk_pct: float = 0.01, period: int = 20,
                 max_pos: float = 0.30, min_pos: float = 0.05) -> float:
    """
    ATR归一化仓位：每笔承担 risk_pct × capital 的风险，
    以 ATR20 作为每股波动基准。

    position_value = (risk_pct × capital) / (ATR / price)
    返回值为占总资金的比例 (0.0-1.0)。

    Args:
        kline:    OHLCV 列表，至少 period+1 根
        capital:  当前总资产
        price:    当前价格
        risk_pct: 每笔愿意承担的最大风险比例（默认1%）
        period:   ATR 周期（默认20日）
    """
    if not kline or len(kline) < period + 1 or price <= 0 or capital <= 0:
        return min_pos

    # 计算 ATR
    tr_list = []
    for i in range(1, len(kline)):
        h = kline[i]['high']
        l = kline[i]['low']
        pc = kline[i - 1]['close']
        tr_list.append(max(h - l, abs(h - pc), abs(l - pc)))

    atr = sum(tr_list[-period:]) / period if len(tr_list) >= period else sum(tr_list) / len(tr_list)
    if atr <= 0:
        return min_pos

    # 每股风险 = ATR；仓位金额 = 风险预算 / (ATR/price)
    risk_budget = capital * risk_pct
    position_value = risk_budget / (atr / price)
    fraction = position_value / capital

    return round(max(min_pos, min(max_pos, fraction)), 4)
