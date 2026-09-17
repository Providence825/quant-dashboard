"""
信号特征记录器。

在回测/实盘信号生成后，把 signal_detail 字段 + 当前 regime 写入 signal_log 表。
回测结束后调用 label_backtest_signals() 标注结果（实际收益率 → label）。
"""
import json
from ...db import get_db


def log_signal(signal_date: str, stock_code: str, stock_name: str,
               strategy: str, score: float, regime: str,
               features: dict, backtest_run_id=None) -> int:
    """插入一条未标注信号记录，返回 rowid。"""
    db = get_db()
    try:
        cur = db.execute(
            """INSERT OR IGNORE INTO signal_log
               (signal_date, stock_code, stock_name, strategy, score, regime,
                features_json, label, backtest_run_id)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (signal_date, stock_code, stock_name, strategy, score, regime,
             json.dumps(features, ensure_ascii=False), -1, backtest_run_id),
        )
        db.commit()
        return cur.lastrowid
    finally:
        db.close()


def label_backtest_signals(run_id: int, close_by_code_date: dict,
                           label_days: int = 5, threshold: float = 0.03):
    """
    回测结束后批量标注：
    对 run_id 对应的全部信号，查信号日后 label_days 根K线的最高收益率，
    >= threshold → label=1，< 0 最大亏损 → label=0，否则 label=0。

    close_by_code_date: {code: {date: close}} (backtest._run 已有此变量)
    """
    db = get_db()
    try:
        rows = db.execute(
            "SELECT id, signal_date, stock_code FROM signal_log "
            "WHERE backtest_run_id=? AND label=-1",
            (run_id,)
        ).fetchall()
        updates = []
        for row in rows:
            code_closes = close_by_code_date.get(row['stock_code'], {})
            dates_after = sorted(
                d for d in code_closes if d > row['signal_date']
            )[:label_days]
            if len(dates_after) < 2:
                continue
            entry_close = code_closes.get(row['signal_date'])
            if not entry_close:
                continue
            prices_after = [code_closes[d] for d in dates_after]
            max_ret = (max(prices_after) - entry_close) / entry_close
            min_ret = (min(prices_after) - entry_close) / entry_close
            label = 1 if max_ret >= threshold else 0
            updates.append((label, round(max_ret * 100, 3), label_days, row['id']))
        if updates:
            db.executemany(
                "UPDATE signal_log SET label=?, outcome_pct=?, label_days=? WHERE id=?",
                updates,
            )
            db.commit()
        return len(updates)
    finally:
        db.close()


def get_labeled_signals(min_samples: int = 20) -> list:
    """返回所有已标注信号（label != -1），用于模型训练。"""
    db = get_db()
    try:
        rows = db.execute(
            "SELECT * FROM signal_log WHERE label != -1 ORDER BY signal_date"
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d['features'] = json.loads(d.get('features_json') or '{}')
            except Exception:
                d['features'] = {}
            result.append(d)
        return result if len(result) >= min_samples else []
    finally:
        db.close()
