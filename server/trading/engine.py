from ..db import get_db
from .account import (get_account, get_positions, COMMISSION_RATE, STAMP_TAX_RATE,
                       MAX_POSITION_PCT, STOP_LOSS_PCT, TAKE_PROFIT_PCT,
                       TRAILING_STOP_PCT, MAX_HOLD_DAYS, calc_max_buy_amount)
from ..data import fetcher
from .strategies.short_term import get_short_term_params
from .risk import check_sector_concentration
from datetime import datetime, timedelta

def execute_buy(stock_code, shares=None, amount=None, reason='策略买入', strategy_type='default'):
    db = get_db()
    try:
        acc = dict(db.execute("SELECT * FROM account WHERE id=1").fetchone())
        available = acc['cash'] - acc['frozen']

        stock_info = _find_stock(stock_code)
        if not stock_info:
            return {'success': False, 'error': f'未找到股票 {stock_code}（网络不可用）'}
        if stock_info.get('_demo'):
            return {'success': False, 'error': '当前为演示数据（真实行情不可用），已拒绝买入以防污染账户'}

        price = float(stock_info['最新价'])
        stock_name = stock_info['名称']

        if price <= 0:
            return {'success': False, 'error': '无法获取实时价格'}

        if shares:
            shares = (int(shares) // 100) * 100
            if shares < 100:
                return {'success': False, 'error': '最小买入100股（1手）'}
            amount_needed = shares * price
        elif amount:
            amount_needed = min(amount, available, calc_max_buy_amount())
            shares = int(amount_needed / price / 100) * 100
            amount_needed = shares * price
        else:
            # 风险平价定仓：根据当前持仓+候选股组合计算目标金额
            try:
                from .ml.portfolio_optimizer import suggest_buy_amount
                positions = get_positions()
                amount_rp = suggest_buy_amount(stock_code, acc['total_asset'], positions, available)
            except Exception:
                amount_rp = min(acc['total_asset'] * 0.10, available)
            amount_needed = min(amount_rp, available, calc_max_buy_amount())
            shares = int(amount_needed / price / 100) * 100
            amount_needed = shares * price
            if shares < 100:
                return {'success': False, 'error': f'风险平价仓位过小，资金不足一手（建议{amount_rp:.0f}元）'}

        if shares < 100:
            return {'success': False, 'error': f'金额不足，{price:.2f}元×100股=需{price*100:.0f}元，当前可买{amount_needed:.0f}元'}

        commission = max(COMMISSION_RATE * amount_needed, 5)
        total_cost = amount_needed + commission

        if total_cost > available:
            return {'success': False, 'error': f'资金不足，需要 {total_cost:.2f}，可用 {available:.2f}'}

        existing_value = sum(p['current_price'] * p['shares'] for p in get_positions()
                             if p['stock_code'] == stock_code)
        max_single = acc['total_asset'] * MAX_POSITION_PCT
        if existing_value + amount_needed > max_single:
            return {'success': False, 'error': f'单只股票持仓上限 {max_single:.0f}（已持 {existing_value:.0f}）'}

        sector_check = check_sector_concentration(stock_code)
        if sector_check['halt']:
            return {'success': False, 'error': sector_check['reason']}

        today = datetime.now().strftime('%Y-%m-%d')
        can_sell = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

        db.execute("UPDATE account SET cash = cash - ?, frozen = frozen + ? WHERE id=1",
                   (total_cost, total_cost))
        db.execute("INSERT INTO orders (stock_code, stock_name, direction, price, shares, status, strategy_reason) VALUES (?,?,?,?,?,?,?)",
                   (stock_code, stock_name, 'buy', price, shares, 'pending', reason))
        order_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("INSERT INTO positions (stock_code, stock_name, shares, avg_cost, current_price, highest_price, buy_date, buy_price, can_sell_date, strategy_type, status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (stock_code, stock_name, shares, price, price, price, today, price, can_sell, strategy_type, 'holding'))
        db.execute("UPDATE account SET frozen = frozen - ?, total_asset = cash + frozen + (SELECT COALESCE(SUM(current_price*shares),0) FROM positions WHERE status='holding') WHERE id=1",
                   (total_cost,))
        db.execute("INSERT INTO trade_log (stock_code, stock_name, direction, price, shares, amount, commission, trigger_reason) VALUES (?,?,?,?,?,?,?,?)",
                   (stock_code, stock_name, 'buy', price, shares, amount_needed, commission, reason))
        db.execute("UPDATE orders SET status='filled', filled_shares=?, updated_at=datetime('now','localtime') WHERE id=?",
                   (shares, order_id))
        db.commit()
        return {'success': True, 'order_id': order_id, 'price': price, 'shares': shares, 'amount': amount_needed, 'commission': commission}
    except Exception as e:
        db.rollback()
        return {'success': False, 'error': str(e)}
    finally:
        db.close()

def execute_sell(stock_code, shares=None, reason='策略卖出'):
    db = get_db()
    try:
        pos = db.execute("SELECT * FROM positions WHERE stock_code=? AND status='holding'", (stock_code,)).fetchone()
        if not pos:
            return {'success': False, 'error': f'未持有 {stock_code}'}

        pos = dict(pos)
        if shares is None or shares >= pos['shares']:
            shares = pos['shares']

        stock_info = _find_stock(stock_code)
        price = float(stock_info['最新价']) if stock_info else pos['current_price']
        stock_name = stock_info['名称'] if stock_info else pos['stock_name']

        if datetime.now().strftime('%Y-%m-%d') < pos['can_sell_date']:
            return {'success': False, 'error': f'T+1限制，{pos["can_sell_date"]}后方可卖出'}

        amount = shares * price
        commission = max(COMMISSION_RATE * amount, 5)
        stamp_tax = STAMP_TAX_RATE * amount
        total_received = amount - commission - stamp_tax
        cost = pos['avg_cost'] * shares
        buy_commission = max(COMMISSION_RATE * cost, 5)
        total_cost = cost + buy_commission
        pnl = total_received - total_cost
        pnl_pct = (total_received / total_cost - 1) * 100 if total_cost > 0 else 0

        db.execute("UPDATE account SET cash = cash + ? WHERE id=1", (total_received,))
        db.execute("INSERT INTO orders (stock_code, stock_name, direction, price, shares, filled_shares, status, strategy_reason) VALUES (?,?,?,?,?,?,?,?)",
                   (stock_code, stock_name, 'sell', price, shares, shares, 'filled', reason))

        remaining = pos['shares'] - shares
        if remaining <= 0:
            db.execute("DELETE FROM positions WHERE id=?", (pos['id'],))
        else:
            db.execute("UPDATE positions SET shares=? WHERE id=?", (remaining, pos['id']))

        db.execute("UPDATE account SET total_asset = cash + frozen + (SELECT COALESCE(SUM(current_price*shares),0) FROM positions WHERE status='holding') WHERE id=1")
        db.execute("INSERT INTO trade_log (stock_code, stock_name, direction, price, shares, amount, commission, stamp_tax, pnl_amount, pnl_pct, trigger_reason, strategy) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   (stock_code, stock_name, 'sell', price, shares, amount, commission, stamp_tax, pnl, pnl_pct, reason, pos.get('strategy_type', '')))
        db.commit()
        return {'success': True, 'price': price, 'shares': shares, 'amount': amount, 'pnl': pnl, 'pnl_pct': pnl_pct}
    except Exception as e:
        db.rollback()
        return {'success': False, 'error': str(e)}
    finally:
        db.close()

def _find_stock(stock_code):
    stocks = fetcher.get_stock_list()
    if isinstance(stocks, list) and stocks:
        return next((s for s in stocks if s['代码'] == stock_code), None)
    kline = fetcher.get_kline_data(stock_code, days=2)
    if isinstance(kline, list) and kline:
        last = kline[-1]
        return {'代码': stock_code, '名称': stock_code, '最新价': last['close'], '涨跌幅': 0, '量比': 0, '换手率': 0}
    return None

def check_stop_conditions():
    # Fetch stock data FIRST without holding a DB connection
    stocks = fetcher.get_stock_list()
    if isinstance(stocks, dict) and 'error' in stocks:
        return []
    if not isinstance(stocks, list):
        return []

    stock_map = {s['代码']: s for s in stocks}

    db = get_db()
    try:
        positions = db.execute("SELECT * FROM positions WHERE status='holding'").fetchall()

        alerts = []
        for pos in positions:
            pos = dict(pos)
            stock_info = stock_map.get(pos['stock_code'])
            if not stock_info:
                continue
            current_price = float(stock_info['最新价'])
            if current_price <= 0:
                continue
            db.execute("UPDATE positions SET current_price=?, highest_price=MAX(highest_price,?) WHERE id=?",
                       (current_price, current_price, pos['id']))

            cost = pos['avg_cost']
            change_pct = (current_price / cost - 1) * 100
            highest = max(pos['highest_price'], current_price)
            from_high = (current_price / highest - 1) * 100
            hold_days = (datetime.now() - datetime.strptime(pos['buy_date'], '%Y-%m-%d')).days

            # Use strategy-specific params
            stype = pos.get('strategy_type', 'default')
            params = get_short_term_params(stype)
            sl = params['stop_loss_pct'] * 100
            tp = params['take_profit_pct'] * 100
            ts = params['trailing_stop_pct'] * 100
            mh = params['max_hold_days']

            if change_pct <= -sl:
                alerts.append({'stock_code': pos['stock_code'], 'stock_name': pos['stock_name'],
                              'type': f'{stype}止损', 'price': current_price, 'change_pct': change_pct,
                              'shares': pos['shares']})
            elif change_pct >= tp:
                alerts.append({'stock_code': pos['stock_code'], 'stock_name': pos['stock_name'],
                              'type': f'{stype}止盈', 'price': current_price, 'change_pct': change_pct,
                              'shares': pos['shares']})
            elif highest > cost * (1 + tp/100) and from_high <= -ts:
                alerts.append({'stock_code': pos['stock_code'], 'stock_name': pos['stock_name'],
                              'type': f'{stype}移动止盈', 'price': current_price, 'change_pct': change_pct,
                              'shares': pos['shares']})
            elif hold_days >= mh:
                alerts.append({'stock_code': pos['stock_code'], 'stock_name': pos['stock_name'],
                              'type': f'{stype}到期清仓', 'price': current_price, 'change_pct': change_pct,
                              'shares': pos['shares']})
            # Dragon-specific: exit on overheated turnover
            elif stype == '龙头战法' and params.get('exit_on_turnover'):
                turnover = float(stock_info.get('换手率', 0))
                if turnover > params['exit_on_turnover']:
                    alerts.append({'stock_code': pos['stock_code'], 'stock_name': pos['stock_name'],
                                  'type': '龙头过热', 'price': current_price, 'change_pct': change_pct,
                                  'shares': pos['shares']})

        db.commit()
        return alerts
    finally:
        db.close()
