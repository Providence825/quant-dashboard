from ..db import get_db
from datetime import datetime

def calculate_stats(period='all'):
    db = get_db()
    query = "SELECT * FROM trade_log WHERE direction='sell'"
    if period == 'week':
        query += " AND created_at >= date('now','-7 days')"
    elif period == 'month':
        query += " AND created_at >= date('now','-30 days')"

    try:
        trades = db.execute(query + " ORDER BY created_at").fetchall()
    finally:
        db.close()

    if not trades:
        return {'total_trades': 0, 'win_rate': 0, 'avg_pnl': 0, 'total_pnl': 0,
                'best_trade': 0, 'worst_trade': 0, 'avg_hold_days': 0}

    wins = [t for t in trades if t['pnl_amount'] > 0]
    pnls = [t['pnl_amount'] for t in trades]
    total = sum(pnls)
    win_rate = len(wins) / len(trades) * 100

    return {
        'total_trades': len(trades),
        'win_trades': len(wins),
        'loss_trades': len(trades) - len(wins),
        'win_rate': round(win_rate, 1),
        'total_pnl': round(total, 2),
        'avg_pnl': round(total / len(trades), 2),
        'best_trade': round(max(pnls), 2),
        'worst_trade': round(min(pnls), 2),
        'avg_win': round(sum(t['pnl_amount'] for t in wins) / max(len(wins), 1), 2),
        'avg_loss': round(sum(t['pnl_amount'] for t in trades if t['pnl_amount'] <= 0) / max(len(trades) - len(wins), 1), 2),
    }

def get_daily_snapshots(days=365):
    db = get_db()
    try:
        rows = db.execute("SELECT * FROM asset_snapshot ORDER BY date DESC LIMIT ?", (days,)).fetchall()
    finally:
        db.close()
    return [dict(r) for r in reversed(rows)]
