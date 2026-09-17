from ..db import get_db
from datetime import datetime

def generate_daily_review():
    today = datetime.now().strftime('%Y-%m-%d')
    db = get_db()
    try:
        return _generate_daily_review_body(db, today)
    finally:
        db.close()


def _generate_daily_review_body(db, today):
    # Refresh position prices from stock list cache BEFORE reading account
    _refresh_position_prices(db)

    acc = dict(db.execute("SELECT * FROM account WHERE id=1").fetchone())
    initial = acc['initial_capital']
    total = acc['total_asset']

    sells = db.execute("SELECT * FROM trade_log WHERE direction='sell' AND date(created_at)=?", (today,)).fetchall()
    buys = db.execute("SELECT * FROM trade_log WHERE direction='buy' AND date(created_at)=?", (today,)).fetchall()

    total_pnl = sum(s['pnl_amount'] for s in sells) if sells else 0
    wins = [s for s in sells if s['pnl_amount'] > 0]

    # Daily return = change in total asset from previous trading day (or from initial capital)
    yesterday_snap = db.execute(
        "SELECT total_asset FROM asset_snapshot WHERE date < ? ORDER BY date DESC LIMIT 1",
        (today,)
    ).fetchone()
    if yesterday_snap and yesterday_snap['total_asset'] > 0:
        daily_return = (total - yesterday_snap['total_asset']) / yesterday_snap['total_asset'] * 100
    elif initial > 0:
        daily_return = (total - initial) / initial * 100
    else:
        daily_return = 0

    # Cumulative return = absolute return from initial capital
    cumulative_return = (total - initial) / initial * 100 if initial > 0 else 0

    review_parts = []
    issues = []
    improvements = []

    if sells:
        review_parts.append(f"今日完成{len(sells)}笔卖出，{len(wins)}盈{len(sells)-len(wins)}亏")
        if wins:
            avg_win = sum(w['pnl_amount'] for w in wins) / len(wins)
            review_parts.append(f"盈利均值 {avg_win:.0f}元")
        loss_sells = [s for s in sells if s['pnl_amount'] <= 0]
        if loss_sells:
            strategies = {}
            for s in loss_sells:
                reason = s['trigger_reason'] or '未知'
                strategies[reason] = strategies.get(reason, 0) + 1
            top_loss_reason = max(strategies, key=strategies.get)
            review_parts.append(f"最大亏损原因: {top_loss_reason} ×{strategies[top_loss_reason]}次")
            issues.append(f"亏损集中在「{top_loss_reason}」信号，需评估该条件的有效性")
    else:
        review_parts.append("今日无卖出交易")

    if buys:
        review_parts.append(f"今日买入{len(buys)}笔")

    watchlist_rows = db.execute("SELECT * FROM watchlist").fetchall()
    if watchlist_rows:
        watch_codes = [w['stock_code'] for w in watchlist_rows]
        review_parts.append(_analyze_watchlist(db, watch_codes, today))

    # Include cumulative return in review text
    review_parts.append(f"累计收益率 {cumulative_return:+.2f}%")

    db.execute("""INSERT OR REPLACE INTO daily_review (date, total_asset, daily_pnl, daily_return_pct,
                  win_trades, total_trades, review_text, strategy_issues, improvement_notes)
                  VALUES (?,?,?,?,?,?,?,?,?)""",
               (today, total, total_pnl, round(daily_return, 2),
                len(wins), len(sells),
                '；'.join(review_parts),
                '；'.join(issues) if issues else None,
                '；'.join(improvements) if improvements else None))

    db.execute("""INSERT OR REPLACE INTO asset_snapshot (date, total_asset, cash, position_value,
                  daily_return_pct, cumulative_return_pct)
                  VALUES (?,?,?,(SELECT COALESCE(SUM(current_price*shares),0) FROM positions WHERE status='holding'),?,?)""",
               (today, total, acc['cash'], round(daily_return, 4), round(cumulative_return, 4)))

    db.commit()

    # Also save index snapshot for return curve comparison
    try:
        from ..data.fetcher import save_daily_index_snapshot
        save_daily_index_snapshot()
    except:
        pass

    return {'date': today, 'daily_pnl': total_pnl, 'daily_return': round(daily_return, 2), 'trades': len(sells)}


def _refresh_position_prices(db):
    """Update positions.current_price and account.total_asset from stock list cache."""
    try:
        from ..data.fetcher import _stock_list_cache, _stock_list_ts
        import time
        stocks = _stock_list_cache
        if not stocks or (time.time() - _stock_list_ts) > 300:
            return
        stock_map = {s['代码']: s for s in stocks}
        positions = db.execute("SELECT * FROM positions WHERE status='holding'").fetchall()
        for p in positions:
            s = stock_map.get(p['stock_code'])
            if s:
                new_price = float(s['最新价'])
                if new_price > 0:
                    db.execute("UPDATE positions SET current_price=?, highest_price=MAX(highest_price,?) WHERE id=?",
                               (new_price, new_price, p['id']))
        pos_mv = db.execute("SELECT COALESCE(SUM(current_price*shares),0) FROM positions WHERE status='holding'").fetchone()[0]
        acc = db.execute("SELECT * FROM account WHERE id=1").fetchone()
        total = acc['cash'] + acc['frozen'] + pos_mv
        db.execute("UPDATE account SET total_asset=? WHERE id=1", (total,))
        # No commit here — caller owns the transaction boundary
    except:
        pass

def _analyze_watchlist(db, watch_codes, today):
    from ..data.fetcher import fetch_quotes_for_codes
    try:
        name_rows = db.execute("SELECT stock_code, stock_name FROM watchlist").fetchall()
        name_map = {r['stock_code']: r['stock_name'] for r in name_rows}
    except Exception:
        name_map = {}
    quotes = fetch_quotes_for_codes(watch_codes)
    if not quotes:
        return "自选股: 数据获取失败"
    wdata = []
    for code in watch_codes:
        s = quotes.get(code, {})
        if not s.get('最新价', 0):
            continue
        wdata.append({
            'name': name_map.get(code, code),
            'code': code,
            'price': s.get('最新价', 0),
            'change_pct': float(s.get('涨跌幅', 0)),
        })
    if not wdata:
        return "自选股: 无数据"
    wdata.sort(key=lambda x: x['change_pct'], reverse=True)
    top = wdata[0]
    bottom = wdata[-1]
    avg_change = sum(w['change_pct'] for w in wdata) / len(wdata)
    up_count = sum(1 for w in wdata if w['change_pct'] > 0)
    parts = [
        f"自选股({len(wdata)}只): {up_count}涨{len(wdata)-up_count}跌, 均{avg_change:+.2f}%",
        f"最强: {top['name']} {top['change_pct']:+.2f}%",
        f"最弱: {bottom['name']} {bottom['change_pct']:+.2f}%",
    ]
    return '；'.join(parts)


def get_buy_analysis(date=None):
    from datetime import datetime as _dt
    if not date:
        date = _dt.now().strftime('%Y-%m-%d')
    db = get_db()
    try:
        return _get_buy_analysis_body(db, date)
    finally:
        db.close()


def _get_buy_analysis_body(db, date):
    buys = db.execute(
        "SELECT * FROM trade_log WHERE direction='buy' AND date(created_at)=? ORDER BY created_at",
        (date,)
    ).fetchall()

    try:
        from ..trading.market_regime import detect_regime
        regime = detect_regime().get('regime', 'neutral')
    except Exception:
        regime = 'neutral'

    results = []
    for b in buys:
        b = dict(b)
        strategy = b.get('strategy') or ''
        trigger = b.get('trigger_reason') or '未知'

        kelly_row = None
        if strategy:
            kelly_row = db.execute(
                "SELECT * FROM ml_winrate_cache WHERE strategy=? AND regime=? ORDER BY updated_at DESC LIMIT 1",
                (strategy, regime)
            ).fetchone()
            if not kelly_row:
                kelly_row = db.execute(
                    "SELECT * FROM ml_winrate_cache WHERE strategy=? ORDER BY sample_count DESC LIMIT 1",
                    (strategy,)
                ).fetchone()

        if kelly_row:
            kr = dict(kelly_row)
            from ..trading.ml.kelly import kelly_from_winrate_row
            kelly_pct = kelly_from_winrate_row(kr)
            win_rate = kr['win_rate']
            sample_count = kr['sample_count']
        else:
            kelly_pct = None
            win_rate = None
            sample_count = 0

        if regime == 'trending_down':
            advice, advice_color = '市场偏弱，控仓', 'warn'
        elif kelly_pct is None or sample_count < 10:
            advice, advice_color = '暂无胜率数据', 'neutral'
        elif kelly_pct >= 0.20:
            advice, advice_color = f'可加仓 ({kelly_pct*100:.0f}%)', 'up'
        elif kelly_pct >= 0.12:
            advice, advice_color = f'适量持有 ({kelly_pct*100:.0f}%)', 'neutral'
        else:
            advice, advice_color = f'轻仓观察 ({kelly_pct*100:.0f}%)', 'down'

        results.append({
            'stock_code': b['stock_code'],
            'stock_name': b['stock_name'],
            'strategy': strategy or '未标注',
            'entry_signal': trigger,
            'price': b['price'],
            'shares': b['shares'],
            'amount': b['amount'],
            'kelly_pct': round(kelly_pct * 100, 1) if kelly_pct is not None else None,
            'win_rate': round(win_rate * 100, 1) if win_rate is not None else None,
            'sample_count': sample_count,
            'advice': advice,
            'advice_color': advice_color,
        })

    return {'date': date, 'regime': regime, 'trades': results}


def generate_suggestions():
    db = get_db()
    try:
        recent = db.execute("SELECT * FROM trade_log WHERE direction='sell' ORDER BY created_at DESC LIMIT 20").fetchall()
    finally:
        db.close()

    if len(recent) < 5:
        return []

    suggestions = []
    losses = [r for r in recent if r['pnl_amount'] <= 0]
    loss_rate = len(losses) / len(recent) * 100

    if loss_rate > 60:
        suggestions.append(f"近{len(recent)}笔交易亏损率{loss_rate:.0f}%，建议降低仓位或暂停交易审查策略")

    loss_reasons = {}
    for l in losses:
        reason = l['trigger_reason'] or '未知'
        loss_reasons[reason] = loss_reasons.get(reason, 0) + 1
    if loss_reasons:
        top = max(loss_reasons, key=loss_reasons.get)
        if loss_reasons[top] >= 3:
            suggestions.append(f"「{top}」信号触发{loss_reasons[top]}次亏损，建议调整该条件参数或暂时关闭")

    total_pnl = sum(r['pnl_amount'] for r in recent)
    if total_pnl < 0:
        suggestions.append(f"近{len(recent)}笔净亏损{total_pnl:.0f}元，暂停开仓等待策略优化")

    return suggestions
