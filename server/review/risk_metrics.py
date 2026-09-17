"""
Risk / performance metrics (风险绩效指标).

Pure functions. Given an equity curve and a list of closed trades, compute the
standard risk-adjusted metrics: annualized return, Sharpe, Sortino, Calmar,
max drawdown (+ drawdown series), win rate, profit factor, payoff ratio and a
conservative Kelly position suggestion.

No numpy dependency — plain Python so it runs anywhere the rest of the app does.
Formulas follow the common conventions (annualization factor = 252 trading days,
risk-free rate defaults to 0).
"""

import math

TRADING_DAYS = 252


def _std(xs):
    """Sample standard deviation (n-1). Returns 0 for < 2 points."""
    n = len(xs)
    if n < 2:
        return 0.0
    mean = sum(xs) / n
    var = sum((x - mean) ** 2 for x in xs) / (n - 1)
    return math.sqrt(var)


def _daily_returns(equity_values):
    """Simple period-over-period returns from an equity value series."""
    rets = []
    for i in range(1, len(equity_values)):
        prev = equity_values[i - 1]
        if prev and prev > 0:
            rets.append(equity_values[i] / prev - 1)
        else:
            rets.append(0.0)
    return rets


def max_drawdown(equity_values):
    """
    Return (max_drawdown_fraction, drawdown_series).
    max_drawdown_fraction is negative (e.g. -0.153 = -15.3%); 0 if no drawdown.
    drawdown_series[i] = equity_i / running_peak_i - 1  (<= 0).
    """
    if not equity_values:
        return 0.0, []
    peak = equity_values[0]
    dd_series = []
    max_dd = 0.0
    for v in equity_values:
        if v > peak:
            peak = v
        dd = (v / peak - 1) if peak > 0 else 0.0
        dd_series.append(dd)
        if dd < max_dd:
            max_dd = dd
    return max_dd, dd_series


def compute_attribution(trades):
    """
    按策略分组的交易级归因 (single-strategy attribution).

    老师第2点: 避免某个核心策略掩盖其他噪声策略的长期亏损。交易级(非权益级)
    分组算每个策略的笔数/胜率/盈亏比/总盈亏, 并给出对组合总盈亏的贡献占比,
    一眼看出钱究竟靠哪个策略赚、哪个在长期拖后腿。

    trades: list of closed sell trades, each with 'pnl_amount' and 'strategy'.
            没有 'strategy' 的记入 '未标注' 组 (历史实盘无策略来源)。
    Returns list of per-strategy dicts, sorted by total_pnl desc.
    """
    trades = trades or []
    if not trades:
        return []

    groups = {}
    for t in trades:
        key = t.get('strategy') or '未标注'
        groups.setdefault(key, []).append(float(t.get('pnl_amount', 0)))

    rows = []
    for name, pnls in groups.items():
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        total_pnl = sum(pnls)
        avg_win = gross_profit / len(wins) if wins else 0.0
        avg_loss = gross_loss / len(losses) if losses else 0.0

        if gross_loss > 0:
            profit_factor = round(gross_profit / gross_loss, 2)
        elif gross_profit > 0:
            profit_factor = 999.0
        else:
            profit_factor = 0.0

        rows.append({
            'strategy': name,
            'total_trades': len(pnls),
            'win_trades': len(wins),
            'loss_trades': len(losses),
            'win_rate': round(len(wins) / len(pnls) * 100, 1) if pnls else 0.0,
            'total_pnl': round(total_pnl, 2),
            'avg_win': round(avg_win, 2),
            'avg_loss': round(-avg_loss, 2),
            'payoff_ratio': round(avg_win / avg_loss, 2) if avg_loss > 0 else 0.0,
            'profit_factor': profit_factor,
        })

    # 贡献占比: 分母为所有盈利策略的总盈利之和。盈利策略占比累加=100%,
    # 亏损策略为负 (表示相对盈利池吃掉了多少), 净值接近 0 时不再放大成 400%。
    gross_profit_all = sum(r['total_pnl'] for r in rows if r['total_pnl'] > 0)
    for r in rows:
        r['contribution_pct'] = (round(r['total_pnl'] / gross_profit_all * 100, 1)
                                 if gross_profit_all > 0 else 0.0)

    rows.sort(key=lambda r: r['total_pnl'], reverse=True)
    return rows


def compute_metrics(equity=None, trades=None, risk_free_rate=0.0):
    """
    equity: list of {'date': str, 'total_asset': float}  (chronological)
    trades: list of closed sell trades with 'pnl_amount' (and optionally 'pnl_pct')
    Returns a metrics dict. Guards against empty / insufficient data.
    """
    equity = equity or []
    trades = trades or []

    values = [float(e['total_asset']) for e in equity if e.get('total_asset') is not None]
    dates = [e.get('date') for e in equity]

    result = {
        'insufficient_data': False,
        'start_asset': round(values[0], 2) if values else 0,
        'end_asset': round(values[-1], 2) if values else 0,
        'total_return_pct': 0.0,
        'annualized_return_pct': 0.0,
        'sharpe': 0.0,
        'sortino': 0.0,
        'calmar': 0.0,
        'max_drawdown_pct': 0.0,
        'volatility_pct': 0.0,
        'drawdown_series': [],
        'dates': dates,
        'win_rate': 0.0,
        'profit_factor': 0.0,
        'payoff_ratio': 0.0,
        'kelly_pct': 0.0,
        'total_trades': len(trades),
        'win_trades': 0,
        'loss_trades': 0,
        'strategy_attribution': compute_attribution(trades),
    }

    if len(values) < 2:
        result['insufficient_data'] = True

    # ── Return & risk from equity curve ──────────────────────────────
    if len(values) >= 2:
        total_ret = values[-1] / values[0] - 1 if values[0] > 0 else 0.0
        result['total_return_pct'] = round(total_ret * 100, 2)

        n_days = len(values) - 1  # number of return periods
        if n_days > 0 and values[0] > 0 and values[-1] > 0:
            ann = (values[-1] / values[0]) ** (TRADING_DAYS / n_days) - 1
            result['annualized_return_pct'] = round(ann * 100, 2)

        rets = _daily_returns(values)
        if rets:
            mean_r = sum(rets) / len(rets)
            sd = _std(rets)
            rf_daily = risk_free_rate / TRADING_DAYS
            result['volatility_pct'] = round(sd * math.sqrt(TRADING_DAYS) * 100, 2)
            if sd > 0:
                result['sharpe'] = round((mean_r - rf_daily) / sd * math.sqrt(TRADING_DAYS), 2)
            downside = [r for r in rets if r < 0]
            dsd = _std(downside) if len(downside) >= 2 else 0.0
            if dsd > 0:
                result['sortino'] = round((mean_r - rf_daily) / dsd * math.sqrt(TRADING_DAYS), 2)

        max_dd, dd_series = max_drawdown(values)
        result['max_drawdown_pct'] = round(max_dd * 100, 2)
        result['drawdown_series'] = [round(d * 100, 2) for d in dd_series]
        if max_dd < 0:
            ann_frac = result['annualized_return_pct'] / 100
            result['calmar'] = round(ann_frac / abs(max_dd), 2)

    # ── Trade-level stats ────────────────────────────────────────────
    if trades:
        pnls = [float(t.get('pnl_amount', 0)) for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        result['win_trades'] = len(wins)
        result['loss_trades'] = len(losses)
        result['win_rate'] = round(len(wins) / len(pnls) * 100, 1) if pnls else 0.0

        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        if gross_loss > 0:
            result['profit_factor'] = round(gross_profit / gross_loss, 2)
        elif gross_profit > 0:
            result['profit_factor'] = 999.0  # no losses

        avg_win = gross_profit / len(wins) if wins else 0.0
        avg_loss = gross_loss / len(losses) if losses else 0.0
        if avg_loss > 0:
            result['payoff_ratio'] = round(avg_win / avg_loss, 2)

        # Kelly: f = W - (1-W)/R ; clip to [0, 0.5] as a conservative cap
        w = len(wins) / len(pnls) if pnls else 0.0
        r = (avg_win / avg_loss) if avg_loss > 0 else 0.0
        if r > 0:
            kelly = w - (1 - w) / r
            result['kelly_pct'] = round(max(0.0, min(0.5, kelly)) * 100, 1)

    return result


# ── Self-test ────────────────────────────────────────────────────────

def _selftest():
    # Upward-drifting but varying daily returns → positive sharpe, no drawdown
    daily_rets = [0.02, 0.005, 0.015, 0.008, 0.012, 0.003, 0.018, 0.006, 0.01, 0.014]
    vals = [100.0]
    for r in daily_rets:
        vals.append(vals[-1] * (1 + r))
    eq = [{'date': f'd{i}', 'total_asset': v} for i, v in enumerate(vals)]
    m = compute_metrics(equity=eq, trades=[
        {'pnl_amount': 300}, {'pnl_amount': 200}, {'pnl_amount': -100}, {'pnl_amount': -50},
    ])
    assert m['total_return_pct'] > 10.0, m['total_return_pct']
    assert m['max_drawdown_pct'] == 0.0, m['max_drawdown_pct']
    assert m['sharpe'] > 0, m['sharpe']
    assert m['win_rate'] == 50.0, m['win_rate']
    # profit factor = 500 / 150 = 3.33
    assert abs(m['profit_factor'] - 3.33) < 0.05, m['profit_factor']
    # payoff = avg_win(250) / avg_loss(75) = 3.33 ; kelly = .5 - .5/3.33 = .35
    assert abs(m['kelly_pct'] - 35.0) < 1.0, m['kelly_pct']

    # Drawdown case: 100 → 120 → 90 → 110  (peak 120, trough 90 → -25%)
    eq2 = [{'date': f'd{i}', 'total_asset': v} for i, v in enumerate([100, 120, 90, 110])]
    m2 = compute_metrics(equity=eq2, trades=[])
    assert abs(m2['max_drawdown_pct'] - (-25.0)) < 0.01, m2['max_drawdown_pct']

    # Empty / insufficient
    m3 = compute_metrics(equity=[], trades=[])
    assert m3['insufficient_data'] is True
    assert m3['sharpe'] == 0.0
    assert m3['strategy_attribution'] == []

    # Attribution: two strategies, A net +400 / B net -80, one trade unlabeled
    attrib = compute_attribution([
        {'pnl_amount': 300, 'strategy': 'A'}, {'pnl_amount': 100, 'strategy': 'A'},
        {'pnl_amount': -80, 'strategy': 'B'},
        {'pnl_amount': 50},  # no strategy → 未标注
    ])
    by = {r['strategy']: r for r in attrib}
    assert by['A']['total_pnl'] == 400.0, by['A']['total_pnl']
    assert by['A']['win_rate'] == 100.0, by['A']['win_rate']
    assert by['B']['total_pnl'] == -80.0, by['B']['total_pnl']
    assert '未标注' in by, list(by)
    # sorted by total_pnl desc → A first
    assert attrib[0]['strategy'] == 'A', attrib[0]['strategy']
    # contribution = share of total *profit* (denom = 400+50 = 450 positive pnl)
    assert abs(by['A']['contribution_pct'] - 88.9) < 0.1, by['A']['contribution_pct']
    assert abs(by['B']['contribution_pct'] - (-17.8)) < 0.1, by['B']['contribution_pct']

    print('risk_metrics selftest OK:',
          'sharpe=%.2f' % m['sharpe'],
          'maxDD=%.1f%%' % m2['max_drawdown_pct'],
          'kelly=%.1f%%' % m['kelly_pct'],
          'PF=%.2f' % m['profit_factor'])


if __name__ == '__main__':
    _selftest()
