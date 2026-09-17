"""
贝叶斯 regime×strategy 胜率表。

从 signal_log 中聚合已标注信号，计算：
  win_rate / avg_win_pct / avg_loss_pct / kelly_f
按 (strategy, regime) 分组，写入 ml_winrate_cache。

典型调用：
  from .regime_winrate import refresh_winrate_cache, get_winrate_table
  refresh_winrate_cache()           # 回测结束后刷新
  table = get_winrate_table()       # API 或实盘选仓时读取
"""
import json
from datetime import datetime
from ...db import get_db
from .kelly import kelly_position


# 没有历史数据时使用的先验值（保守估计）
_PRIOR = {
    'win_rate': 0.45,
    'avg_win_pct': 0.08,
    'avg_loss_pct': 0.05,
    'sample_count': 0,
}

# 贝叶斯平滑：先验权重（等价于 N 条虚拟样本）
_PRIOR_WEIGHT = 20


def refresh_winrate_cache() -> dict:
    """
    从 signal_log 重新计算所有 (strategy, regime) 的胜率并写入缓存。
    返回 {(strategy, regime): {win_rate, avg_win, avg_loss, kelly_f, n}}。
    """
    db = get_db()
    try:
        rows = db.execute(
            "SELECT strategy, regime, label, outcome_pct "
            "FROM signal_log WHERE label != -1"
        ).fetchall()
    finally:
        db.close()

    # 聚合
    buckets = {}
    for r in rows:
        key = (r['strategy'], r['regime'])
        if key not in buckets:
            buckets[key] = {'wins': 0, 'losses': 0, 'win_rets': [], 'loss_rets': []}
        if r['label'] == 1:
            buckets[key]['wins'] += 1
            if r['outcome_pct'] is not None:
                buckets[key]['win_rets'].append(float(r['outcome_pct']) / 100)
        else:
            buckets[key]['losses'] += 1
            if r['outcome_pct'] is not None:
                # outcome_pct is max_ret; positive means trade rose before stopping out
                # — use default 3% stop as proxy; negative means straight drop, use abs
                raw = float(r['outcome_pct'])
                loss_val = abs(raw) / 100 if raw < 0 else 0.03
                buckets[key]['loss_rets'].append(loss_val)

    result = {}
    db = get_db()
    try:
        for (strategy, regime), b in buckets.items():
            n = b['wins'] + b['losses']
            # 贝叶斯平滑（拉普拉斯 + 先验权重）
            p_w = _PRIOR_WEIGHT
            smooth_wins = b['wins'] + p_w * _PRIOR['win_rate']
            smooth_n = n + p_w
            win_rate = smooth_wins / smooth_n

            avg_win = (sum(b['win_rets']) / len(b['win_rets'])) if b['win_rets'] else _PRIOR['avg_win_pct']
            avg_loss = (sum(b['loss_rets']) / len(b['loss_rets'])) if b['loss_rets'] else _PRIOR['avg_loss_pct']

            kf = kelly_position(win_rate, avg_win, avg_loss)

            db.execute(
                """INSERT INTO ml_winrate_cache
                   (strategy, regime, win_rate, avg_win_pct, avg_loss_pct,
                    sample_count, kelly_f, updated_at)
                   VALUES (?,?,?,?,?,?,?,datetime('now','localtime'))
                   ON CONFLICT(strategy, regime) DO UPDATE SET
                     win_rate=excluded.win_rate,
                     avg_win_pct=excluded.avg_win_pct,
                     avg_loss_pct=excluded.avg_loss_pct,
                     sample_count=excluded.sample_count,
                     kelly_f=excluded.kelly_f,
                     updated_at=excluded.updated_at""",
                (strategy, regime, round(win_rate, 4),
                 round(avg_win, 4), round(avg_loss, 4), n, round(kf, 4)),
            )
            result[(strategy, regime)] = {
                'win_rate': win_rate, 'avg_win': avg_win,
                'avg_loss': avg_loss, 'kelly_f': kf, 'n': n,
            }
        db.commit()
    finally:
        db.close()

    return result


def get_winrate_table() -> list:
    """读取缓存表，返回前端可直接渲染的列表。"""
    db = get_db()
    try:
        rows = db.execute(
            "SELECT * FROM ml_winrate_cache ORDER BY strategy, regime"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()


def lookup_winrate(strategy: str, regime: str) -> dict:
    """
    查询单个 (strategy, regime) 的胜率。
    若无历史数据，返回先验默认值。
    """
    db = get_db()
    try:
        row = db.execute(
            "SELECT * FROM ml_winrate_cache WHERE strategy=? AND regime=?",
            (strategy, regime),
        ).fetchone()
    finally:
        db.close()
    if row:
        return dict(row)
    return {
        'strategy': strategy,
        'regime': regime,
        'win_rate': _PRIOR['win_rate'],
        'avg_win_pct': _PRIOR['avg_win_pct'],
        'avg_loss_pct': _PRIOR['avg_loss_pct'],
        'sample_count': 0,
        'kelly_f': kelly_position(
            _PRIOR['win_rate'], _PRIOR['avg_win_pct'], _PRIOR['avg_loss_pct']
        ),
    }


def detect_strategy_decay(recent_n: int = 20, decay_threshold: float = 0.15) -> list:
    """
    滑动窗口策略衰减检测。
    对每个策略取最近 recent_n 笔已标注信号，计算近期胜率。
    若 近期胜率 < 历史基准胜率 - decay_threshold，标记为衰减告警。

    Returns: list of dicts，每条包含策略名、近期胜率、历史胜率、差值、告警状态。
    """
    db = get_db()
    try:
        # 所有有已标注信号的策略
        strategies = db.execute(
            "SELECT DISTINCT strategy FROM signal_log WHERE label != -1"
        ).fetchall()
        strategies = [r['strategy'] for r in strategies]

        results = []
        for strategy in strategies:
            recent = db.execute(
                "SELECT label FROM signal_log WHERE strategy=? AND label != -1 "
                "ORDER BY created_at DESC LIMIT ?",
                (strategy, recent_n),
            ).fetchall()

            if len(recent) < 5:  # 样本太少跳过
                continue

            recent_wins = sum(1 for r in recent if r['label'] == 1)
            recent_wr = recent_wins / len(recent)

            # 历史基准：ml_winrate_cache（贝叶斯平滑后的全量胜率）
            cached = db.execute(
                "SELECT win_rate, sample_count FROM ml_winrate_cache WHERE strategy=?",
                (strategy,),
            ).fetchone()
            baseline_wr = float(cached['win_rate']) if cached else _PRIOR['win_rate']
            sample_count = int(cached['sample_count']) if cached else 0

            delta = recent_wr - baseline_wr
            degrading = delta < -decay_threshold

            results.append({
                'strategy': strategy,
                'recent_n': len(recent),
                'recent_win_rate': round(recent_wr, 4),
                'baseline_win_rate': round(baseline_wr, 4),
                'delta': round(delta, 4),
                'total_samples': sample_count,
                'degrading': degrading,
                'status': '⚠ 衰减' if degrading else '正常',
            })

        results.sort(key=lambda x: x['delta'])
        return results
    finally:
        db.close()
