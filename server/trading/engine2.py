"""账户2 (板块动量) 的买卖执行引擎。"""

from ..db import get_db
from ..data import fetcher
from .strategies.sector_momentum import SECTOR_ACCT2_PARAMS

COMMISSION_RATE = 0.00025
STAMP_TAX_RATE  = 0.001


def get_account2():
    db = get_db()
    try:
        row = db.execute("SELECT * FROM account2 WHERE id=1").fetchone()
        return dict(row) if row else {}
    finally:
        db.close()


def get_positions2():
    db = get_db()
    try:
        rows = db.execute("SELECT * FROM positions2 WHERE status='holding'").fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()


def execute_buy2(stock_code, amount, reason='板块动量买入', sector=''):
    db = get_db()
    try:
        acc = dict(db.execute("SELECT * FROM account2 WHERE id=1").fetchone())
        available = acc['cash'] - acc['frozen']

        stock_info = _find_stock(stock_code)
        if not stock_info:
            return {'success': False, 'error': f'未找到股票 {stock_code}'}
        if stock_info.get('_demo'):
            return {'success': False, 'error': '演示数据，拒绝买入'}

        price = float(stock_info['最新价'])
        stock_name = stock_info['名称']
        if price <= 0:
            return {'success': False, 'error': '无法获取价格'}

        # 单笔仓位按账户净值比例
        max_single = acc['total_asset'] * SECTOR_ACCT2_PARAMS['per_position_pct']
        use_amount = min(amount, available, max_single)
        shares = int(use_amount / price / 100) * 100
        if shares < 100:
            return {'success': False, 'error': f'金额不足，需{price*100:.0f}元/手'}

        amount_needed = shares * price
        commission = max(COMMISSION_RATE * amount_needed, 5)
        total_cost = amount_needed + commission
        if total_cost > available:
            return {'success': False, 'error': f'资金不足 ({available:.0f})'}

        # 单只持仓上限检查
        existing = sum(p['current_price'] * p['shares'] for p in get_positions2()
                       if p['stock_code'] == stock_code)
        if existing + amount_needed > max_single * 1.5:
            return {'success': False, 'error': '单只持仓已达上限'}

        from datetime import datetime, timedelta
        today = datetime.now().strftime('%Y-%m-%d')
        can_sell = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

        db.execute("UPDATE account2 SET cash = cash - ?, frozen = frozen + ? WHERE id=1",
                   (total_cost, total_cost))
        db.execute("""INSERT INTO positions2
            (stock_code, stock_name, shares, avg_cost, current_price, highest_price,
             buy_date, buy_price, can_sell_date, sector, status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (stock_code, stock_name, shares, price, price, price,
             today, price, can_sell, sector, 'holding'))
        db.execute("UPDATE account2 SET frozen = frozen - ?, total_asset = cash + frozen + "
                   "(SELECT COALESCE(SUM(current_price*shares),0) FROM positions2 WHERE status='holding') WHERE id=1",
                   (total_cost,))
        db.execute("""INSERT INTO trade_log2
            (stock_code, stock_name, direction, price, shares, amount, commission, sector, trigger_reason)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (stock_code, stock_name, 'buy', price, shares, amount_needed, commission, sector, reason))
        db.commit()
        return {'success': True, 'price': price, 'shares': shares, 'amount': amount_needed}
    except Exception as e:
        db.rollback()
        return {'success': False, 'error': str(e)}
    finally:
        db.close()


def execute_sell2(stock_code, shares=None, reason='板块动量卖出'):
    db = get_db()
    try:
        pos = db.execute("SELECT * FROM positions2 WHERE stock_code=? AND status='holding'",
                         (stock_code,)).fetchone()
        if not pos:
            return {'success': False, 'error': f'未持有 {stock_code}'}
        pos = dict(pos)

        from datetime import datetime
        if datetime.now().strftime('%Y-%m-%d') < pos['can_sell_date']:
            return {'success': False, 'error': f'T+1限制，{pos["can_sell_date"]}后可卖'}

        if shares is None or shares >= pos['shares']:
            shares = pos['shares']

        stock_info = _find_stock(stock_code)
        price = float(stock_info['最新价']) if stock_info else pos['current_price']
        stock_name = stock_info['名称'] if stock_info else pos['stock_name']

        amount = shares * price
        commission = max(COMMISSION_RATE * amount, 5)
        stamp_tax = STAMP_TAX_RATE * amount
        received = amount - commission - stamp_tax
        cost = pos['avg_cost'] * shares
        buy_commission = max(COMMISSION_RATE * cost, 5)
        pnl = received - cost - buy_commission
        pnl_pct = (received / (cost + buy_commission) - 1) * 100 if cost > 0 else 0

        db.execute("UPDATE account2 SET cash = cash + ? WHERE id=1", (received,))
        remaining = pos['shares'] - shares
        if remaining <= 0:
            db.execute("DELETE FROM positions2 WHERE id=?", (pos['id'],))
        else:
            db.execute("UPDATE positions2 SET shares=? WHERE id=?", (remaining, pos['id']))
        db.execute("UPDATE account2 SET total_asset = cash + frozen + "
                   "(SELECT COALESCE(SUM(current_price*shares),0) FROM positions2 WHERE status='holding') WHERE id=1")
        db.execute("""INSERT INTO trade_log2
            (stock_code, stock_name, direction, price, shares, amount, commission, stamp_tax,
             pnl_amount, pnl_pct, sector, trigger_reason)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (stock_code, stock_name, 'sell', price, shares, amount, commission, stamp_tax,
             pnl, pnl_pct, pos.get('sector', ''), reason))
        db.commit()
        return {'success': True, 'price': price, 'pnl': pnl, 'pnl_pct': pnl_pct}
    except Exception as e:
        db.rollback()
        return {'success': False, 'error': str(e)}
    finally:
        db.close()


def refresh_prices2():
    """更新 positions2 的实时价格，并刷新 account2.total_asset。"""
    from ..data.fetcher import _fetch_sina, _kline_prefix
    import re as _re

    positions = get_positions2()
    if not positions:
        return

    codes = [p['stock_code'] for p in positions]
    id_map = {p['stock_code']: p for p in positions}
    symbols = [f'{_kline_prefix(c)}{c}' for c in codes]
    try:
        text = _fetch_sina('https://hq.sinajs.cn/list=' + ','.join(symbols))
        if not text:
            return
        db = get_db()
        try:
            for line in text.strip().split('\n'):
                m = _re.search(r'hq_str_(\w+)="([^"]*)"', line)
                if not m:
                    continue
                pure_code = m.group(1)[2:] if len(m.group(1)) > 2 else m.group(1)
                pos = id_map.get(pure_code)
                if not pos:
                    continue
                parts = m.group(2).split(',')
                if len(parts) < 4:
                    continue
                cur = float(parts[3]) if parts[3] else 0
                if cur > 0:
                    db.execute("UPDATE positions2 SET current_price=?, highest_price=MAX(highest_price,?) WHERE id=?",
                               (cur, cur, pos['id']))
            db.execute("UPDATE account2 SET total_asset = cash + frozen + "
                       "(SELECT COALESCE(SUM(current_price*shares),0) FROM positions2 WHERE status='holding') WHERE id=1")
            db.commit()
        finally:
            db.close()
    except Exception:
        pass


def _find_stock(stock_code):
    stocks = fetcher.get_stock_list()
    if isinstance(stocks, list) and stocks:
        return next((s for s in stocks if s['代码'] == stock_code), None)
    kline = fetcher.get_kline_data(stock_code, days=2)
    if isinstance(kline, list) and kline:
        last = kline[-1]
        return {'代码': stock_code, '名称': stock_code, '最新价': last['close']}
    return None
