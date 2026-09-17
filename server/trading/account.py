import os
from ..db import get_db
from datetime import datetime, timedelta

INITIAL_CAPITAL = float(os.getenv('INITIAL_CAPITAL', 1000000))
COMMISSION_RATE = float(os.getenv('COMMISSION_RATE', 0.00025))
STAMP_TAX_RATE = float(os.getenv('STAMP_TAX_RATE', 0.001))
# 账户1改用板块动量参数: 止损5%/止盈12%/最长5日/移动止盈3%
STOP_LOSS_PCT = float(os.getenv('STOP_LOSS_PCT', 0.05))
TAKE_PROFIT_PCT = float(os.getenv('TAKE_PROFIT_PCT', 0.12))
TRAILING_STOP_PCT = float(os.getenv('TRAILING_STOP_PCT', 0.03))
MAX_HOLD_DAYS = int(os.getenv('MAX_HOLD_DAYS', 5))
MAX_POSITION_PCT = float(os.getenv('MAX_POSITION_PCT', 0.10))  # 单仓10%
MAX_TOTAL_POSITION = float(os.getenv('MAX_TOTAL_POSITION', 0.90))

def get_account():
    db = get_db()
    try:
        acc = db.execute("SELECT * FROM account WHERE id=1").fetchone()
    finally:
        db.close()
    return dict(acc)

def get_positions():
    db = get_db()
    try:
        rows = db.execute("SELECT * FROM positions WHERE status='holding'").fetchall()
    finally:
        db.close()
    return [dict(r) for r in rows]

def calc_max_buy_amount():
    acc = get_account()
    available = acc['cash'] - acc['frozen']
    positions = get_positions()
    pos_value = sum(p['current_price'] * p['shares'] for p in positions)
    max_pos = acc['total_asset'] * MAX_TOTAL_POSITION
    room = max_pos - pos_value
    return min(available, max(0, room))
