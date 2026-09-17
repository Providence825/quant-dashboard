from ..db import get_db
from datetime import datetime

def log_trade(stock_code, stock_name, direction, price, shares, amount,
              commission, stamp_tax, pnl_amount, pnl_pct, trigger_reason, tags=None):
    db = get_db()
    try:
        db.execute("""INSERT INTO trade_log (stock_code, stock_name, direction, price, shares, amount,
                      commission, stamp_tax, pnl_amount, pnl_pct, trigger_reason, review_tags)
                      VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                   (stock_code, stock_name, direction, price, shares, amount,
                    commission, stamp_tax, pnl_amount or 0, pnl_pct or 0, trigger_reason, tags))
        db.commit()
    finally:
        db.close()

def get_today_trades():
    today = datetime.now().strftime('%Y-%m-%d')
    db = get_db()
    try:
        rows = db.execute("SELECT * FROM trade_log WHERE date(created_at)=? ORDER BY created_at", (today,)).fetchall()
    finally:
        db.close()
    return [dict(r) for r in rows]

def get_recent_sells(limit=50):
    db = get_db()
    try:
        rows = db.execute("SELECT * FROM trade_log WHERE direction='sell' ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    finally:
        db.close()
    return [dict(r) for r in rows]
