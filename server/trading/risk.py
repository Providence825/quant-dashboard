import os
from ..db import get_db
from datetime import datetime, timedelta

MAX_DAILY_LOSS_PCT = 0.03
MAX_CONSECUTIVE_LOSSES = 3
MAX_DRAWDOWN_PCT = 0.15
MAX_INTRADAY_DRAWDOWN_PCT = 0.02   # 日内回撤熔断：今日相对昨收跌超2%
MAX_WEEKLY_DRAWDOWN_PCT = 0.05     # 周度回撤熔断：相对5日前跌超5%
MAX_SECTOR_POSITIONS = 2           # 同板块最多持仓数，超出时拒绝买入


def check_risk_limits():
    db = get_db()
    try:
        acc = dict(db.execute("SELECT * FROM account WHERE id=1").fetchone())
        initial = acc['initial_capital']
        current = acc['total_asset']

        # 最大回撤：从历史高水位算，而非初始资金
        peak_row = db.execute("SELECT MAX(total_asset) as peak FROM asset_snapshot").fetchone()
        peak = float(peak_row['peak']) if peak_row and peak_row['peak'] else max(initial, current)
        drawdown = (current - peak) / peak if peak > 0 else 0
        if drawdown < -MAX_DRAWDOWN_PCT:
            return {'halt': True, 'reason': f'最大回撤 {drawdown*100:.1f}% 超限，暂停3天',
                    'resume_date': (datetime.now() + timedelta(days=3)).strftime('%Y-%m-%d')}

        today = datetime.now().strftime('%Y-%m-%d')

        # 日内回撤熔断：今日相对昨收
        yesterday_snap = db.execute(
            "SELECT total_asset FROM asset_snapshot WHERE date < ? ORDER BY date DESC LIMIT 1",
            (today,)).fetchone()
        if yesterday_snap:
            prev_asset = float(yesterday_snap['total_asset'])
            intraday_dd = (current - prev_asset) / prev_asset if prev_asset > 0 else 0
            if intraday_dd < -MAX_INTRADAY_DRAWDOWN_PCT:
                return {'halt': True,
                        'reason': f'日内回撤 {intraday_dd*100:.1f}% 超{MAX_INTRADAY_DRAWDOWN_PCT*100:.0f}%，今日暂停新开仓'}

        # 周度回撤熔断：相对5个交易日前
        week_ago_snap = db.execute(
            "SELECT total_asset FROM asset_snapshot WHERE date < ? ORDER BY date DESC LIMIT 1 OFFSET 4",
            (today,)).fetchone()
        if week_ago_snap:
            week_asset = float(week_ago_snap['total_asset'])
            weekly_dd = (current - week_asset) / week_asset if week_asset > 0 else 0
            if weekly_dd < -MAX_WEEKLY_DRAWDOWN_PCT:
                return {'halt': True,
                        'reason': f'周度回撤 {weekly_dd*100:.1f}% 超{MAX_WEEKLY_DRAWDOWN_PCT*100:.0f}%，暂停新开仓'}

        daily_pnl = db.execute("SELECT COALESCE(SUM(pnl_amount),0) as pnl FROM trade_log WHERE date(created_at)=?", (today,)).fetchone()
        if daily_pnl['pnl'] < -initial * MAX_DAILY_LOSS_PCT:
            return {'halt': True, 'reason': f'单日亏损 {daily_pnl["pnl"]:.0f} 超 3%，暂停新开仓'}

        recent_losses = db.execute(
            "SELECT COUNT(*) as cnt FROM (SELECT pnl_amount FROM trade_log WHERE direction='sell' ORDER BY created_at DESC LIMIT ?) WHERE pnl_amount < 0",
            (MAX_CONSECUTIVE_LOSSES,)).fetchone()
        if recent_losses['cnt'] >= MAX_CONSECUTIVE_LOSSES:
            return {'halt': True, 'reason': f'连续{MAX_CONSECUTIVE_LOSSES}笔亏损，仓位减半'}

        return {'halt': False, 'reason': ''}
    finally:
        db.close()


def check_sector_concentration(stock_code: str) -> dict:
    """
    检查板块集中度：若现有持仓中同板块数量已达 MAX_SECTOR_POSITIONS，拒绝买入。
    Returns {'halt': bool, 'reason': str, 'sector': str, 'same_sector_count': int}
    """
    db = get_db()
    try:
        sector_row = db.execute(
            "SELECT sector FROM stocks WHERE code=?", (stock_code,)).fetchone()
        sector = sector_row['sector'] if sector_row and sector_row['sector'] else ''

        if not sector:
            return {'halt': False, 'reason': '', 'sector': '', 'same_sector_count': 0}

        same_sector_count = db.execute(
            """SELECT COUNT(*) as cnt FROM positions p
               JOIN stocks s ON p.stock_code = s.code
               WHERE p.status='holding' AND s.sector=? AND p.stock_code != ?""",
            (sector, stock_code)).fetchone()['cnt']

        if same_sector_count >= MAX_SECTOR_POSITIONS:
            return {
                'halt': True,
                'reason': f'板块集中度超限：{sector} 已持 {same_sector_count} 只（上限{MAX_SECTOR_POSITIONS}）',
                'sector': sector,
                'same_sector_count': same_sector_count,
            }
        return {'halt': False, 'reason': '', 'sector': sector, 'same_sector_count': same_sector_count}
    finally:
        db.close()
