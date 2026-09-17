"""
IC/IR 因子信息系数追踪器。

IC = Spearman(signal_score, forward_return)  衡量信号预测力
IR = IC_mean / IC_std                        衡量预测力稳定性

评级标准（行业惯例）：
  IC  > 0.10 → 强；0.05~0.10 → 有效；0~0.05 → 弱；< 0 → 反向/无效
  IR  > 0.50 → 稳定；0.30~0.50 → 一般；< 0.30 → 不稳定
"""
import json
import math
import time
from collections import defaultdict
from ...db import get_db

_cache: dict = {}
_cache_ts: float = 0.0
_CACHE_TTL = 3600  # 1小时


# ── 无外部依赖的 Spearman 实现 ────────────────────────────────────────

def _rank(arr: list) -> list:
    n = len(arr)
    indexed = sorted(range(n), key=lambda i: arr[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n - 1 and arr[indexed[j + 1]] == arr[indexed[j]]:
            j += 1
        avg = (i + j + 2) / 2.0
        for k in range(i, j + 1):
            ranks[indexed[k]] = avg
        i = j + 1
    return ranks


def _pearson(x: list, y: list) -> tuple:
    n = len(x)
    if n < 3:
        return 0.0, 1.0
    mx = sum(x) / n
    my = sum(y) / n
    num = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    sx = math.sqrt(sum((v - mx) ** 2 for v in x) / n)
    sy = math.sqrt(sum((v - my) ** 2 for v in y) / n)
    if sx == 0 or sy == 0:
        return 0.0, 1.0
    r = num / (n * sx * sy)
    r = max(-1.0, min(1.0, r))
    t = r * math.sqrt((n - 2) / max(1 - r ** 2, 1e-10))
    pval = min(1.0, 2 * (1 - _norm_cdf(abs(t))))
    return r, pval


def _norm_cdf(x: float) -> float:
    return (1 + math.erf(x / math.sqrt(2))) / 2


def _spearman(x: list, y: list) -> tuple:
    return _pearson(_rank(x), _rank(y))


# ── IC 时间序列（按周分组）───────────────────────────────────────────

def compute_ic_series(window: str = 'weekly', min_per_period: int = 5) -> list:
    """
    按 window 分组计算 composite score 的 IC 时间序列。
    window: 'weekly' | 'monthly'
    Returns list of {period, ic, pval, n}，按 period 升序。
    """
    db = get_db()
    try:
        rows = db.execute(
            "SELECT signal_date, score, outcome_pct FROM signal_log "
            "WHERE label != -1 AND outcome_pct IS NOT NULL ORDER BY signal_date"
        ).fetchall()
    finally:
        db.close()

    if not rows:
        return []

    periods: dict = defaultdict(list)
    for r in rows:
        try:
            from datetime import datetime
            dt = datetime.strptime(r['signal_date'], '%Y-%m-%d')
            period = (f"{dt.year}-W{dt.isocalendar()[1]:02d}"
                      if window == 'weekly'
                      else f"{dt.year}-{dt.month:02d}")
        except Exception:
            continue
        periods[period].append((float(r['score'] or 0), float(r['outcome_pct'] or 0)))

    result = []
    for period in sorted(periods):
        batch = periods[period]
        if len(batch) < min_per_period:
            continue
        scores, outcomes = zip(*batch)
        ic, pval = _spearman(list(scores), list(outcomes))
        result.append({'period': period, 'ic': round(ic, 4), 'pval': round(pval, 4), 'n': len(batch)})
    return result


# ── 单因子 IC（所有已标注样本）───────────────────────────────────────

_NUMERIC_FACTORS = [
    'vol_ratio', 'breakout_pct', 'trend_r2', 'pullback_pct', 'turnover',
    'above_low_pct', 'rs_vs_market', 'momentum_accel', 'dist_to_ma',
    'price_vs_ma60', 'price_vs_ma20',
]


def compute_factor_ic(min_samples: int = 30) -> dict:
    """
    计算 composite score 及各个子因子相对于 outcome_pct 的 IC。
    Returns dict keyed by factor → {ic, pval, n, quality}。
    如样本不足返回 {'error': ...}。
    """
    db = get_db()
    try:
        rows = db.execute(
            "SELECT score, outcome_pct, features_json FROM signal_log "
            "WHERE label != -1 AND outcome_pct IS NOT NULL"
        ).fetchall()
    finally:
        db.close()

    if len(rows) < min_samples:
        return {'error': f'样本不足（需≥{min_samples}条，当前{len(rows)}条）'}

    global_scores, global_outcomes = [], []
    factor_pairs: dict = defaultdict(list)

    for r in rows:
        outcome = float(r['outcome_pct'])
        global_scores.append(float(r['score'] or 0))
        global_outcomes.append(outcome)

        try:
            feats = json.loads(r['features_json'] or '{}')
        except Exception:
            feats = {}

        for k in _NUMERIC_FACTORS:
            raw = feats.get(k)
            if raw is None:
                continue
            try:
                if isinstance(raw, str):
                    raw = raw.replace('%', '').replace('+', '').strip()
                factor_pairs[k].append((float(raw), outcome))
            except Exception:
                pass

    def _tag(ic: float) -> str:
        if ic > 0.10:
            return '强'
        if ic > 0.05:
            return '有效'
        if ic >= 0:
            return '弱'
        return '反向'

    results = {}

    # Composite score
    if len(global_scores) >= min_samples:
        ic, pval = _spearman(global_scores, global_outcomes)
        results['composite_score'] = {
            'ic': round(ic, 4), 'pval': round(pval, 4),
            'n': len(global_scores), 'quality': _tag(ic),
        }

    # Individual factors
    for k, pairs in factor_pairs.items():
        if len(pairs) < min_samples:
            continue
        xs, ys = zip(*pairs)
        ic, pval = _spearman(list(xs), list(ys))
        results[k] = {
            'ic': round(ic, 4), 'pval': round(pval, 4),
            'n': len(pairs), 'quality': _tag(ic),
        }

    return dict(sorted(results.items(), key=lambda kv: -abs(kv[1]['ic'])))


# ── 策略维度 IC ───────────────────────────────────────────────────────

def compute_strategy_ic(min_samples: int = 20) -> list:
    """
    按策略分组，计算每种策略的平均 IC 和样本量。
    Returns list of {strategy, ic, n, quality}，按 |ic| 降序。
    """
    db = get_db()
    try:
        rows = db.execute(
            "SELECT strategy, score, outcome_pct FROM signal_log "
            "WHERE label != -1 AND outcome_pct IS NOT NULL"
        ).fetchall()
    finally:
        db.close()

    buckets: dict = defaultdict(list)
    for r in rows:
        buckets[r['strategy']].append((float(r['score'] or 0), float(r['outcome_pct'])))

    results = []
    for strategy, pairs in buckets.items():
        if len(pairs) < min_samples:
            continue
        xs, ys = zip(*pairs)
        ic, pval = _spearman(list(xs), list(ys))
        quality = ('强' if ic > 0.10 else '有效' if ic > 0.05 else '弱' if ic >= 0 else '反向')
        results.append({
            'strategy': strategy, 'ic': round(ic, 4),
            'pval': round(pval, 4), 'n': len(pairs), 'quality': quality,
        })

    results.sort(key=lambda r: -abs(r['ic']))
    return results


# ── 完整报告（含 IR）─────────────────────────────────────────────────

def get_ic_report(force_refresh: bool = False) -> dict:
    """
    汇总报告：factor_ic、strategy_ic、ic_series、summary(IC均值/IR/质量评级)。
    结果缓存1小时。
    """
    global _cache, _cache_ts
    now = time.time()
    if not force_refresh and now - _cache_ts < _CACHE_TTL and _cache:
        return _cache

    factor_ic = compute_factor_ic()
    strategy_ic = compute_strategy_ic()
    ic_series = compute_ic_series(window='weekly')

    ics = [r['ic'] for r in ic_series]
    if len(ics) >= 4:
        ic_mean = sum(ics) / len(ics)
        ic_std = math.sqrt(sum((v - ic_mean) ** 2 for v in ics) / len(ics))
        ir = round(ic_mean / ic_std, 3) if ic_std > 0 else 0.0
        quality = ('优秀 (IR>0.5)' if ir > 0.5
                   else '一般 (IR 0.3-0.5)' if ir > 0.3
                   else '不稳定 (IR<0.3)')
    else:
        ic_mean = sum(ics) / len(ics) if ics else 0.0
        ir = None
        quality = '数据不足（需≥4个周期）'

    report = {
        'factor_ic': factor_ic,
        'strategy_ic': strategy_ic,
        'ic_series': ic_series[-52:],
        'summary': {
            'ic_mean': round(ic_mean, 4),
            'ir': ir,
            'n_periods': len(ic_series),
            'quality': quality,
        },
    }

    _cache = report
    _cache_ts = now
    return report
