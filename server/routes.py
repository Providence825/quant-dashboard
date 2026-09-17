from flask import Blueprint, jsonify, request, send_file, Response, stream_with_context
import os
import json
from .data import fetcher
from .db import get_db
from datetime import datetime

api = Blueprint('api', __name__)

@api.after_request
def no_cache(response):
    if request.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
    return response

@api.route('/')
def index():
    return send_file(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                   'static', 'index.html'))

@api.route('/htd')
def htd():
    return send_file(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                   'static', 'huitoudun.html'))


@api.route('/api/llm/status')
def llm_status():
    """前端探测大模型是否可用，决定走真模型还是本地模板。"""
    from . import llm
    return jsonify({'enabled': llm.is_enabled()})


@api.route('/api/llm/explain', methods=['POST'])
def llm_explain():
    """解释生成智能体：把个股量化信号交给 DeepSeek，SSE 流式返回大白话解读。
    失败时返回 JSON 错误，前端静默回退本地模板。"""
    from . import llm
    body = request.get_json(silent=True) or {}
    stock = body.get('stock') or {}
    risk = body.get('risk') or {}
    mode = body.get('mode') or 'pick'

    if not llm.is_enabled():
        return jsonify({'error': 'LLM 未配置'}), 503

    def gen():
        try:
            for piece in llm.stream_explain(stock, risk, mode):
                yield 'data: ' + json.dumps({'t': piece}, ensure_ascii=False) + '\n\n'
            yield 'data: ' + json.dumps({'done': True}) + '\n\n'
        except Exception as e:
            yield 'data: ' + json.dumps({'error': str(e)}, ensure_ascii=False) + '\n\n'

    return Response(stream_with_context(gen()), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@api.route('/api/llm/analyze-assessment', methods=['POST'])
def analyze_assessment():
    """AI投资者画像分析：基于测评问卷的标准答案+自定义文字，生成深度画像报告。"""
    from . import llm
    if not llm.is_enabled():
        return jsonify({'ok': False, 'error': 'LLM 未配置'}), 503

    body = request.get_json(silent=True) or {}

    try:
        result = llm.analyze_assessment(body)

        # 保存到数据库
        db = get_db()
        ss = body.get('standard_score')
        db.execute(
            '''INSERT INTO assessment_profiles
               (timestamp, quiz_data, ai_profile, ai_score, standard_score, risk_level)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (datetime.now().isoformat(),
             json.dumps(body, ensure_ascii=False),
             result['profile'],
             result['ai_score'],
             0 if ss is None else float(ss),
             body.get('risk_level', 'C3'))
        )
        db.commit()

        return jsonify({'ok': True, 'profile': result['profile'], 'ai_score': result['ai_score']})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@api.route('/api/llm/analyze_custom_answer', methods=['POST'])
def analyze_custom_answer():
    """分析测评题自定义答案：用户选择"其他"后输入的文字，DeepSeek分析并给出1-4分的风险评分。"""
    from . import llm
    if not llm.is_enabled():
        return jsonify({'error': 'LLM 未配置'}), 503

    body = request.get_json(silent=True) or {}
    question = body.get('question', '')
    dimension = body.get('dimension', '')
    hint = body.get('hint', '')
    options = body.get('options', [])
    user_answer = body.get('user_answer', '')

    if not user_answer or not question:
        return jsonify({'error': '缺少必要参数'}), 400

    try:
        result = llm.analyze_custom_answer(question, dimension, hint, options, user_answer)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api.route('/api/market/index')
def market_index():
    return jsonify(fetcher.get_index_data())

@api.route('/api/market/top50')
def market_top50():
    return jsonify(fetcher.get_top50())

@api.route('/api/market/anomaly')
def market_anomaly():
    return jsonify(fetcher.get_anomaly_stocks())

@api.route('/api/market/sectors')
def market_sectors():
    return jsonify(fetcher.get_sector_data())

@api.route('/api/stock/<code>/intraday')
def stock_intraday(code):
    return jsonify(fetcher.get_intraday_data(code))

@api.route('/api/stock/<code>/kline')
def stock_kline(code):
    days = request.args.get('days', 60, type=int)
    return jsonify(fetcher.get_kline_data(code, days))

@api.route('/api/stock/<code>/analysis')
def stock_analysis(code):
    days = request.args.get('days', 120, type=int)
    return jsonify(fetcher.get_kline_analysis(code, days))


@api.route('/api/stock/<code>/holding-report')
def holding_report(code):
    """持仓体检报告：真实现价/浮盈亏 + 技术指标 + 量化打分 + 与四大指数对比曲线。"""
    cost = request.args.get('cost', type=float)
    window = request.args.get('window', 60, type=int)
    buy_date = request.args.get('buy_date', None)
    return jsonify(fetcher.get_holding_report(code, cost=cost, window=window, buy_date=buy_date))


@api.route('/api/stock/<code>/risk-education')
def risk_education(code):
    """持仓风险教育端点：返回板块、波动率、最大回撤、RSI等风险识别指标。"""
    return jsonify(fetcher.get_risk_education(code))


@api.route('/api/stock/<code>/price-at-date')
def price_at_date(code):
    """查询指定股票在某日的收盘价，用于自动填充成本价。"""
    date = request.args.get('date', None)
    if not date:
        return jsonify({'ok': False, 'error': '缺少 date 参数'})
    return jsonify(fetcher.get_price_at_date(code, date))


@api.route('/api/stock/search')
def stock_search():
    """股票名称/代码模糊搜索，返回匹配的前10条结果。"""
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({'ok': True, 'results': []})
    return jsonify(fetcher.search_stocks(q))


@api.route('/api/screen/run', methods=['POST'])
def screen_run():
    conditions = request.get_json(silent=True) or {}
    from .data.screener import run_screener
    return jsonify(run_screener(conditions))

@api.route('/api/screen/candidates')
def screen_candidates():
    today = datetime.now().strftime('%Y-%m-%d')
    fallback = request.args.get('fallback') == 'recent'
    db = get_db()
    try:
        rows = db.execute("SELECT * FROM screener_results WHERE date=? ORDER BY score DESC", (today,)).fetchall()
        if not rows and fallback:
            latest = db.execute("SELECT MAX(date) AS d FROM screener_results").fetchone()
            if latest and latest['d']:
                rows = db.execute("SELECT * FROM screener_results WHERE date=? ORDER BY score DESC", (latest['d'],)).fetchall()
    finally:
        db.close()
    results = [dict(r) for r in rows]

    # Overlay live prices — fetch Sina quotes even during lunch break
    if results:
        from .data.fetcher import _fetch_sina, _kline_prefix
        import re
        codes = [r['stock_code'] for r in results]
        code_map = {r['stock_code']: r for r in results}
        symbols = [f'{_kline_prefix(c)}{c}' for c in codes]
        text = _fetch_sina('https://hq.sinajs.cn/list=' + ','.join(symbols))
        if text:
            for line in text.strip().split('\n'):
                m = re.search(r'hq_str_(\w+)="([^"]*)"', line)
                if not m:
                    m = re.search(r'var hq_str_(\w+)="([^"]*)"', line)
                if m:
                    raw_code = m.group(1)
                    parts = m.group(2).split(',')
                    pure_code = raw_code[2:] if len(raw_code) > 2 else raw_code
                    r = code_map.get(pure_code)
                    if r and len(parts) >= 4:
                        cur_price = float(parts[3]) if parts[3] else 0
                        preclose = float(parts[2]) if parts[2] else 0
                        if cur_price > 0:
                            r['price'] = cur_price
                        if preclose > 0 and cur_price > 0:
                            r['change_pct'] = round((cur_price - preclose) / preclose * 100, 2)

    return jsonify(results)

@api.route('/api/account/summary')
def account_summary():
    import traceback
    db = None
    try:
        db = get_db()
        acc = db.execute("SELECT * FROM account WHERE id=1").fetchone()
        positions_raw = db.execute("SELECT * FROM positions WHERE status='holding'").fetchall()
        positions = [dict(p) for p in positions_raw]

        # Refresh position prices directly from Sina real-time quotes
        try:
            import re as _re
            from .data.fetcher import _fetch_sina, _kline_prefix
            if positions_raw:
                pos_list = [dict(p) for p in positions_raw]
                codes = [p['stock_code'] for p in pos_list]
                id_map = {p['stock_code']: p for p in pos_list}
                symbols = [f'{_kline_prefix(c)}{c}' for c in codes]
                text = _fetch_sina('https://hq.sinajs.cn/list=' + ','.join(symbols))
                updated = False
                if text:
                    for line in text.strip().split('\n'):
                        m = _re.search(r'hq_str_(\w+)="([^"]*)"', line)
                        if not m:
                            m = _re.search(r'var hq_str_(\w+)="([^"]*)"', line)
                        if not m:
                            continue
                        raw_code = m.group(1)
                        pure_code = raw_code[2:] if len(raw_code) > 2 else raw_code
                        pos = id_map.get(pure_code)
                        if not pos:
                            continue
                        parts = m.group(2).split(',')
                        if len(parts) < 4:
                            continue
                        cur = float(parts[3]) if parts[3] else 0
                        preclose = float(parts[2]) if parts[2] else 0
                        new_price = cur if cur > 0 else preclose
                        if new_price > 0 and abs(new_price - pos['current_price']) > 0.001:
                            db.execute("UPDATE positions SET current_price=?, highest_price=MAX(highest_price,?) WHERE id=?",
                                       (new_price, new_price, pos['id']))
                            updated = True
                if updated:
                    positions_raw = db.execute("SELECT * FROM positions WHERE status='holding'").fetchall()
                    positions = [dict(p) for p in positions_raw]
                    pos_mv = db.execute("SELECT COALESCE(SUM(current_price*shares),0) FROM positions WHERE status='holding'").fetchone()[0]
                    total = acc['cash'] + acc['frozen'] + pos_mv
                    db.execute("UPDATE account SET total_asset=? WHERE id=1", (total,))
                    today = __import__('datetime').datetime.now().strftime('%Y-%m-%d')
                    prev = db.execute("SELECT total_asset FROM asset_snapshot WHERE date < ? ORDER BY date DESC LIMIT 1", (today,)).fetchone()
                    prev_asset = prev['total_asset'] if prev else acc['initial_capital']
                    daily_ret = round((total - prev_asset) / prev_asset * 100, 2) if prev_asset else 0
                    cum_ret = round((total - acc['initial_capital']) / acc['initial_capital'] * 100, 2) if acc['initial_capital'] else 0
                    db.execute("""INSERT OR REPLACE INTO asset_snapshot
                        (date, total_asset, cash, position_value, daily_return_pct, cumulative_return_pct, created_at)
                        VALUES (?,?,?,?,?,?,datetime('now','localtime'))""",
                        (today, total, acc['cash'], pos_mv, daily_ret, cum_ret))
                    db.commit()
        except Exception:
            pass

        acc_row = db.execute("SELECT * FROM account WHERE id=1").fetchone()
        pos = db.execute("SELECT COUNT(*) as cnt, SUM(current_price * shares) as mv FROM positions WHERE status='holding'").fetchone()
        init_cap = acc_row['initial_capital']
        return jsonify({
            'cash': acc_row['cash'], 'frozen': acc_row['frozen'],
            'total_asset': acc_row['total_asset'],
            'initial_capital': init_cap,
            'cumulative_return_pct': round((acc_row['total_asset'] - init_cap) / init_cap * 100, 2) if init_cap else 0,
            'position_count': pos['cnt'] or 0,
            'position_value': pos['mv'] or 0,
            'available_cash': acc_row['cash'] - acc_row['frozen'],
            'positions': positions
        })
    except Exception as e:
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500
    finally:
        if db is not None:
            db.close()

@api.route('/api/account/positions')
def account_positions():
    db = get_db()
    try:
        positions = db.execute("SELECT * FROM positions WHERE status='holding'").fetchall()
    finally:
        db.close()
    results = []
    for p in positions:
        d = dict(p)
        from .trading.strategies.short_term import get_short_term_params
        params = get_short_term_params(d.get('strategy_type', 'default'))
        d['stop_loss_pct'] = params['stop_loss_pct']
        d['take_profit_pct'] = params['take_profit_pct']
        d['max_hold_days'] = params['max_hold_days']
        results.append(d)
    return jsonify(results)

@api.route('/api/account/orders')
def account_orders():
    db = get_db()
    try:
        orders = db.execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT 50").fetchall()
    finally:
        db.close()
    return jsonify([dict(o) for o in orders])

@api.route('/api/account/curve')
def account_curve():
    period = request.args.get('period', '30d')
    limit_map = {'7d': 7, '30d': 30, '90d': 90, '365d': 365, 'all': 3650}
    limit = limit_map.get(period, 30)
    db = get_db()
    try:
        rows = db.execute(f"SELECT * FROM asset_snapshot ORDER BY date DESC LIMIT {limit}").fetchall()
    finally:
        db.close()
    return jsonify([dict(r) for r in reversed(rows)])

@api.route('/api/account/return-curve')
def return_curve():
    """Return cumulative return rates for asset + 4 major indices since account inception."""
    from .data.fetcher import get_return_curve
    data = get_return_curve()
    if data.get('dates'):
        d = data
        print(f'[CURVE] today={d["dates"][-1]} asset={d["asset"][-1]} sh={d["sh"][-1]} sz={d["sz"][-1]} cy={d["cy"][-1]} kc={d["kc"][-1]}')
    return jsonify(data)

# ── Strategy signals ──────────────────────────────────────────────────

_signals_cache = None
_signals_cache_ts = 0.0
_CACHE_TTL = 300  # 5 min — daily K-line data doesn't change intraday

def get_signals_cached():
    """所有策略信号,带 5min 缓存。路由/预热/跨资产下钻共用同一份缓存。
    返回 {策略名: [候选股列表]}。"""
    global _signals_cache, _signals_cache_ts
    import time
    now = time.time()
    if _signals_cache is not None and (now - _signals_cache_ts) < _CACHE_TTL:
        return _signals_cache

    from .trading.strategies.short_term import get_all_strategy_signals
    from .trading.strategies.trend import get_all_trend_signals
    from .trading.strategies.lai_qu import get_all_lai_qu_signals, _get_candidate_pool
    from .trading.strategies.congling import get_all_congling_signals

    pool = _get_candidate_pool()
    short_term = get_all_strategy_signals(pool=pool)
    trend = get_all_trend_signals(pool=pool)
    lai_qu = get_all_lai_qu_signals(pool=pool)
    congling = get_all_congling_signals(pool=pool)

    _signals_cache = {**short_term, **trend, **lai_qu, **congling}
    _signals_cache_ts = now
    return _signals_cache

@api.route('/api/strategy/signals')
def strategy_signals():
    return jsonify(get_signals_cached())

def _warm_signals_cache():
    """Called at startup to pre-populate the signals route cache."""
    get_signals_cached()

@api.route('/api/strategy/active', methods=['GET', 'POST'])
def strategy_active():
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        mode = data.get('mode', 'short_term')
        from .trading.strategy import set_strategy_mode
        set_strategy_mode(mode)
        return jsonify({'success': True, 'mode': mode})
    from .trading.strategy import ACTIVE_STRATEGY, get_effective_strategy
    return jsonify({
        'mode': ACTIVE_STRATEGY,
        'effective_mode': get_effective_strategy(),
    })


@api.route('/api/market/regime')
def market_regime():
    """Get current market regime detection result."""
    from .trading.market_regime import detect_regime
    return jsonify(detect_regime())


# ── Sentiment endpoints ────────────────────────────────────────────────

@api.route('/api/sentiment/current')
def sentiment_current():
    """Get today's sentiment analysis."""
    from .trading.sentiment import get_current_sentiment
    return jsonify(get_current_sentiment())


@api.route('/api/sentiment/history')
def sentiment_history():
    """Get sentiment history."""
    days = request.args.get('days', 90, type=int)
    from .trading.sentiment import get_sentiment_history
    return jsonify(get_sentiment_history(days))


@api.route('/api/sentiment/fetch', methods=['POST'])
def sentiment_fetch():
    """Trigger sentiment data collection and analysis."""
    from .data.sentiment_fetcher import fetch_all_sentiment_sources
    from .trading.sentiment import run_sentiment_analysis

    try:
        texts = fetch_all_sentiment_sources()
        if not texts:
            return jsonify({'success': False, 'error': '未获取到情绪数据', 'texts': 0})
        result = run_sentiment_analysis(texts)
        return jsonify({
            'success': True,
            'texts_collected': len(texts),
            'score': result['score'],
            'phase': result['phase'],
            'phase_label': result['phase_label'],
            'contrarian': result['contrarian'],
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ── 来去由心 endpoints ────────────────────────────────────────────

@api.route('/api/strategy/lai_qu/cycle')
def lai_qu_cycle():
    """Get 来去由心 emotion cycle position and trading params."""
    from .trading.sentiment import get_current_sentiment
    sent = get_current_sentiment()
    cycle_keys = ['lai_qu_cycle', 'lai_qu_cycle_label', 'lai_qu_cycle_desc',
                  'lai_qu_cycle_color', 'lai_qu_cycle_order', 'lai_qu_should_trade',
                  'lai_qu_max_position_pct', 'lai_qu_preferred_strategy',
                  'lai_qu_stop_multiplier', 'lai_qu_position_notes',
                  'lai_qu_action_hint', 'lai_qu_details']
    result = {k.replace('lai_qu_', ''): sent.get(k, '') for k in cycle_keys if k in sent}
    return jsonify(result)


@api.route('/api/sectors/strength')
def sectors_strength():
    """Get sector strength ranking."""
    from .data.sectors import compute_sector_strength
    return jsonify(compute_sector_strength())


@api.route('/api/sectors/top_stocks')
def sectors_top_stocks():
    """Get best stocks in top N sectors (最强前排)."""
    n = request.args.get('n', 3, type=int)
    from .data.sectors import get_top_sector_stocks
    return jsonify(get_top_sector_stocks(n))


@api.route('/api/crossasset/overnight')
def crossasset_overnight():
    """隔夜美股 → A股板块映射(实盘展示,未经回测验证,不参与打分)。"""
    from .data.crossasset import get_overnight_snapshot
    return jsonify(get_overnight_snapshot())

@api.route('/api/crossasset/drilldown')
def crossasset_drilldown():
    """点击某隔夜美股 → 其映射板块内 A 股(当日动量榜 + 策略买点信号)。纯展示。
    symbol 含 $,用 query 参数传(如 ?symbol=gb_$sox)。"""
    symbol = request.args.get('symbol', '')
    if not symbol:
        return jsonify({'error': 'missing symbol'}), 400
    from .data.crossasset import get_symbol_drilldown
    return jsonify(get_symbol_drilldown(symbol))

@api.route('/api/crossasset/commodity')
def crossasset_commodity():
    """黄金/期货行情榜(实盘展示,未经回测验证,不参与打分)。"""
    from .data.crossasset import get_commodity_snapshot
    return jsonify(get_commodity_snapshot())

@api.route('/api/crossasset/commodity_drilldown')
def crossasset_commodity_drilldown():
    """点击某商品 → 其关联A股概念龙头(评分+排名)+ 新闻。纯展示。"""
    symbol = request.args.get('symbol', '')
    if not symbol:
        return jsonify({'error': 'missing symbol'}), 400
    from .data.crossasset import get_commodity_drilldown
    return jsonify(get_commodity_drilldown(symbol))


@api.route('/api/crossasset/fx')
def crossasset_fx():
    from .data.crossasset import get_fx_snapshot
    snap = get_fx_snapshot()
    if snap is None:
        return jsonify({'error': 'no data'}), 503
    return jsonify(snap)


@api.route('/api/trade/buy', methods=['POST'])
def trade_buy():
    data = request.get_json(silent=True) or {}
    stock_code = str(data.get('stock_code', '')).strip()
    if not stock_code:
        return jsonify({'success': False, 'error': '请提供股票代码'}), 400
    from .trading.engine import execute_buy
    result = execute_buy(stock_code, data.get('shares'), data.get('amount'),
                          data.get('reason', '手动买入'),
                          strategy_type=data.get('strategy_type', 'default'))
    return jsonify(result)

@api.route('/api/trade/sell', methods=['POST'])
def trade_sell():
    data = request.get_json(silent=True) or {}
    stock_code = str(data.get('stock_code', '')).strip()
    if not stock_code:
        return jsonify({'success': False, 'error': '请提供股票代码'}), 400
    from .trading.engine import execute_sell
    result = execute_sell(stock_code, data.get('shares'), data.get('reason', '手动卖出'))
    return jsonify(result)

@api.route('/api/journal/trades')
def journal_trades():
    db = get_db()
    try:
        rows = db.execute("SELECT * FROM trade_log ORDER BY created_at DESC LIMIT 200").fetchall()
    finally:
        db.close()
    return jsonify([dict(r) for r in rows])

@api.route('/api/journal/daily')
def journal_daily():
    date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    db = get_db()
    try:
        rows = db.execute("SELECT * FROM trade_log WHERE date(created_at)=? ORDER BY created_at DESC", (date,)).fetchall()
    finally:
        db.close()
    return jsonify([dict(r) for r in rows])

@api.route('/api/review/daily')
def review_daily():
    date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    db = get_db()
    try:
        r = db.execute("SELECT * FROM daily_review WHERE date=?", (date,)).fetchone()
    finally:
        db.close()
    return jsonify(dict(r) if r else {})

@api.route('/api/review/dates')
def review_dates():
    """Return list of dates that have review records."""
    db = get_db()
    try:
        rows = db.execute("SELECT date FROM daily_review ORDER BY date DESC LIMIT 365").fetchall()
    finally:
        db.close()
    return jsonify([r['date'] for r in rows])

@api.route('/api/review/generate', methods=['POST'])
def review_generate():
    from .review.daily import generate_daily_review
    try:
        result = generate_daily_review()
        return jsonify({'success': True, **result})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@api.route('/api/review/stats')
def review_stats():
    period = request.args.get('period', 'all')
    db = get_db()
    try:
        rows = db.execute("SELECT * FROM daily_review ORDER BY date DESC LIMIT 365").fetchall()
    finally:
        db.close()
    if not rows:
        return jsonify({})
    data = [dict(r) for r in rows]
    total_trades = sum(r['total_trades'] for r in data)
    win_trades = sum(r['win_trades'] for r in data)
    returns = [r['daily_return_pct'] for r in data if r['daily_return_pct'] != 0]
    return jsonify({
        'total_trading_days': len(data),
        'total_trades': total_trades,
        'win_trades': win_trades,
        'win_rate': round(win_trades/total_trades*100, 2) if total_trades else 0,
        'avg_daily_return': round(sum(returns)/len(returns), 2) if returns else 0,
        'best_day': round(max(returns), 2) if returns else 0,
        'worst_day': round(min(returns), 2) if returns else 0,
    })

@api.route('/api/review/suggestions')
def review_suggestions():
    from .review.daily import generate_suggestions
    return jsonify({'suggestions': generate_suggestions()})

@api.route('/api/review/buy_analysis')
def review_buy_analysis():
    date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    from .review.daily import get_buy_analysis
    try:
        return jsonify(get_buy_analysis(date))
    except Exception as e:
        return jsonify({'error': str(e), 'trades': [], 'regime': 'neutral'})


@api.route('/api/compliance/sign', methods=['POST'])
def compliance_sign():
    """合规留痕端点：服务端持久化风险揭示书签署记录，附带数字签名。"""
    data = request.get_json(silent=True) or {}
    user_id = data.get('user_id', '').strip()
    risk_code = data.get('risk_code', '').strip()
    signature = data.get('signature', '').strip()
    timestamp = data.get('timestamp', '')

    if not user_id or not risk_code or not signature:
        return jsonify({'success': False, 'error': '缺少必需字段'}), 400

    db = get_db()
    try:
        db.execute(
            '''INSERT INTO compliance_signatures
               (user_id, risk_code, signature, signed_at, created_at)
               VALUES (?, ?, ?, ?, datetime('now','localtime'))''',
            (user_id, risk_code, signature, timestamp)
        )
        db.commit()
        return jsonify({'success': True, 'message': '签署记录已保存'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        db.close()

@api.route('/api/system/status')
def system_status():
    from .trading.scheduler import get_status
    return jsonify(get_status())

@api.route('/api/notes', methods=['GET', 'POST'])
def market_notes():
    db = get_db()
    try:
        if request.method == 'POST':
            data = request.get_json(silent=True) or {}
            content = data.get('content', '').strip()
            source = data.get('source', '机构一手调研（福总）')
            date = data.get('date', datetime.now().strftime('%Y-%m-%d'))
            if content:
                db.execute("INSERT INTO market_notes (source, content, note_date) VALUES (?,?,?)",
                           (source, content, date))
                db.commit()
            return jsonify({'success': True})
        else:
            date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
            source = request.args.get('source', '')
            if source:
                rows = db.execute("SELECT * FROM market_notes WHERE note_date=? AND source=? ORDER BY created_at DESC", (date, source)).fetchall()
            else:
                rows = db.execute("SELECT * FROM market_notes WHERE note_date=? ORDER BY created_at DESC", (date,)).fetchall()
            return jsonify([dict(r) for r in rows])
    finally:
        db.close()


@api.route('/api/notes/fetch', methods=['POST'])
def notes_fetch():
    """Trigger content aggregation from 福总 and 来去由心."""
    from .data.content_fetcher import run_content_aggregator
    try:
        saved = run_content_aggregator()
        return jsonify({'success': True, 'fuzong': saved.get('fuzong', 0), 'laiqu': saved.get('laiqu', 0)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@api.route('/api/news')
def market_news():
    count = request.args.get('count', 10, type=int)
    return jsonify(fetcher.get_market_news(count))


@api.route('/api/watchlist')
def watchlist_list():
    db = get_db()
    try:
        rows = db.execute("SELECT * FROM watchlist ORDER BY added_at DESC").fetchall()
    finally:
        db.close()
    items = [dict(r) for r in rows]
    if items:
        codes = [item['stock_code'] for item in items]
        quotes = fetcher.fetch_quotes_for_codes(codes)
        for item in items:
            q = quotes.get(item['stock_code'], {})
            item['price'] = q.get('最新价', 0)
            item['change_pct'] = q.get('涨跌幅', 0)
            item['volume_ratio'] = q.get('量比', 0)
            item['turnover'] = q.get('换手率', 0)
    return jsonify(items)


@api.route('/api/watchlist/add', methods=['POST'])
def watchlist_add():
    data = request.get_json(silent=True) or {}
    code = data.get('stock_code', '').strip()
    if not code:
        return jsonify({'success': False, 'error': '请输入股票代码'})
    name = data.get('stock_name', '')
    if not name:
        stocks = fetcher.get_stock_list()
        for s in (stocks if isinstance(stocks, list) else []):
            if s.get('代码') == code:
                name = s.get('名称', code)
                break
        if not name:
            name = code
    db = get_db()
    try:
        existing = db.execute("SELECT id FROM watchlist WHERE stock_code=?", (code,)).fetchone()
        if existing:
            return jsonify({'success': False, 'error': '该股票已在自选列表中'})
        db.execute("INSERT INTO watchlist (stock_code, stock_name) VALUES (?,?)", (code, name))
        db.commit()
        return jsonify({'success': True, 'stock_code': code, 'stock_name': name})
    finally:
        db.close()


@api.route('/api/watchlist/<code>', methods=['DELETE'])
def watchlist_remove(code):
    db = get_db()
    try:
        db.execute("DELETE FROM watchlist WHERE stock_code=?", (code,))
        db.commit()
        return jsonify({'success': True})
    finally:
        db.close()


# ── Data import / sync ────────────────────────────────────────────────

@api.route('/api/data/import/stocks', methods=['POST'])
def trigger_import_stocks():
    from .data.importer import import_all_stocks
    result = import_all_stocks()
    return jsonify(result)

@api.route('/api/data/import/kline', methods=['POST'])
def trigger_import_kline():
    data = request.get_json(silent=True) or {}
    days = data.get('days', 250)
    stock_codes = data.get('stock_codes', None)
    from .data.importer import import_kline_history
    result = import_kline_history(stock_codes=stock_codes, days_back=days)
    return jsonify(result)

@api.route('/api/data/sync/daily', methods=['POST'])
def trigger_daily_sync():
    from .data.importer import sync_daily_prices
    result = sync_daily_prices()
    return jsonify(result)

@api.route('/api/data/import/status')
def import_status():
    from .data.importer import get_import_status
    return jsonify(get_import_status())

@api.route('/api/data/stats')
def data_stats():
    db = get_db()
    try:
        stock_count = db.execute("SELECT COUNT(*) as cnt FROM stocks").fetchone()['cnt']
        kline_count = db.execute("SELECT COUNT(*) as cnt FROM stock_kline_daily").fetchone()['cnt']
        latest_kline = db.execute("SELECT MAX(date) as dt FROM stock_kline_daily").fetchone()['dt']
    finally:
        db.close()
    return jsonify({
        'stock_count': stock_count,
        'kline_count': kline_count,
        'latest_kline_date': latest_kline
    })


# ── Backtest & Risk ──────────────────────────────────────────────────

@api.route('/api/backtest/run', methods=['POST'])
def backtest_run():
    data = request.get_json(silent=True) or {}
    start = data.get('start_date')
    end = data.get('end_date')
    if not start or not end:
        return jsonify({'success': False, 'error': '请提供 start_date 和 end_date'}), 400
    if start > end:
        return jsonify({'success': False, 'error': '开始日期不能晚于结束日期'}), 400
    mode = data.get('strategy_mode', 'trend')
    if mode not in ('short_term', 'trend', 'lai_qu', 'congling', 'all'):
        return jsonify({'success': False, 'error': f'未知策略模式 {mode}'}), 400
    params = {
        'start_date': start,
        'end_date': end,
        'strategy_mode': mode,
        'initial_capital': float(data.get('initial_capital', 1000000)),
        'max_positions': int(data.get('max_positions', 5)),
        'universe_limit': min(int(data.get('universe_limit', 300)), 800),
        'risk_free_rate': float(data.get('risk_free_rate', 0.0)),
        'slippage': float(data.get('slippage', 0.002)),
        'participation': float(data.get('participation', 10.0)),
        'market_filter': bool(data.get('market_filter', True)),
        'sector_cap': int(data.get('sector_cap', 3)),
    }
    from .trading.backtest import start_backtest
    return jsonify(start_backtest(params))


@api.route('/api/backtest/status')
def backtest_status():
    from .trading.backtest import get_backtest_status
    return jsonify(get_backtest_status())


@api.route('/api/backtest/result/<int:run_id>')
def backtest_result(run_id):
    from .trading.backtest import get_backtest_result
    return jsonify(get_backtest_result(run_id))


@api.route('/api/backtest/walk-forward', methods=['POST'])
def backtest_walk_forward():
    """Walk-forward 验证：将回测区间切成 n_folds 段逐段运行，返回各折指标和合并收益曲线。"""
    data = request.get_json() or {}
    required = ['start_date', 'end_date', 'strategy_mode', 'initial_capital',
                'max_positions', 'universe_limit']
    for f in required:
        if f not in data:
            return jsonify({'success': False, 'error': f'缺少参数: {f}'})
    n_folds = int(data.pop('n_folds', 4))
    from .trading.backtest import walk_forward_backtest
    result = walk_forward_backtest(data, n_folds=n_folds)
    if 'error' in result:
        return jsonify({'success': False, 'error': result['error']})
    return jsonify({'success': True, **result})


@api.route('/api/risk/status')
def risk_status():
    """Circuit-breaker traffic-light + live risk metrics (read-only)."""
    from .trading.risk import (check_risk_limits, MAX_DAILY_LOSS_PCT,
                               MAX_CONSECUTIVE_LOSSES, MAX_DRAWDOWN_PCT)
    from .review.stats import calculate_stats, get_daily_snapshots
    from .review.risk_metrics import compute_metrics

    breaker = check_risk_limits()

    db = get_db()
    try:
        acc = dict(db.execute("SELECT * FROM account WHERE id=1").fetchone())
        today = datetime.now().strftime('%Y-%m-%d')
        daily_pnl = db.execute(
            "SELECT COALESCE(SUM(pnl_amount),0) as pnl FROM trade_log WHERE date(created_at)=?",
            (today,)).fetchone()['pnl']
        recent = db.execute(
            "SELECT pnl_amount FROM trade_log WHERE direction='sell' ORDER BY created_at DESC LIMIT ?",
            (MAX_CONSECUTIVE_LOSSES,)).fetchall()
    finally:
        db.close()

    initial = acc['initial_capital']
    current = acc['total_asset']
    drawdown = (current - initial) / initial if initial > 0 else 0
    consec_losses = sum(1 for r in recent if r['pnl_amount'] < 0)

    snapshots = get_daily_snapshots(days=365)
    equity = [{'date': s['date'], 'total_asset': s['total_asset']} for s in snapshots]
    db2 = get_db()
    try:
        sells = [dict(r) for r in db2.execute(
            "SELECT pnl_amount, pnl_pct, strategy FROM trade_log WHERE direction='sell'").fetchall()]
    finally:
        db2.close()
    metrics = compute_metrics(equity=equity, trades=sells)

    return jsonify({
        'breaker': breaker,
        'limits': {
            'max_daily_loss_pct': MAX_DAILY_LOSS_PCT,
            'max_consecutive_losses': MAX_CONSECUTIVE_LOSSES,
            'max_drawdown_pct': MAX_DRAWDOWN_PCT,
        },
        'current': {
            'daily_pnl': round(daily_pnl, 2),
            'daily_loss_limit': round(-initial * MAX_DAILY_LOSS_PCT, 2),
            'drawdown_pct': round(drawdown * 100, 2),
            'drawdown_limit_pct': round(-MAX_DRAWDOWN_PCT * 100, 2),
            'consecutive_losses': consec_losses,
            'total_asset': round(current, 2),
        },
        'metrics': metrics,
    })


@api.route('/api/watchlist/anomaly')
def watchlist_anomaly():
    db = get_db()
    try:
        rows = db.execute("SELECT * FROM watchlist").fetchall()
    finally:
        db.close()
    if not rows:
        return jsonify([])
    codes = [r['stock_code'] for r in rows]
    quotes = fetcher.fetch_quotes_for_codes(codes)
    anomalies = []
    for r in rows:
        s = quotes.get(r['stock_code'], {})
        change = float(s.get('涨跌幅', 0))
        vol_r = float(s.get('量比', 0))
        if abs(change) >= 1 or vol_r >= 2:
            anomalies.append({
                'stock_code': r['stock_code'],
                'stock_name': r['stock_name'],
                'price': s.get('最新价', 0),
                'change_pct': change,
                'volume_ratio': vol_r,
                'turnover': s.get('换手率', 0),
                'alert_type': '急涨' if change > 2 else ('急跌' if change < -2 else '放量' if vol_r > 2 else '异动')
            })
    anomalies.sort(key=lambda x: abs(x['change_pct']), reverse=True)
    return jsonify(anomalies)


# ── ML 升级层：贝叶斯胜率 + 凯利仓位 + XGBoost ────────────────────────

@api.route('/api/ml/winrates')
def ml_winrates():
    """返回所有策略×regime的历史胜率表（含凯利建议仓位）。"""
    try:
        from .trading.ml.regime_winrate import get_winrate_table
        table = get_winrate_table()
        return jsonify({'success': True, 'data': table, 'count': len(table)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@api.route('/api/ml/winrates/refresh', methods=['POST'])
def ml_winrates_refresh():
    """手动触发重新计算胜率缓存。"""
    try:
        from .trading.ml.regime_winrate import refresh_winrate_cache
        result = refresh_winrate_cache()
        return jsonify({'success': True, 'updated': len(result)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@api.route('/api/ml/kelly')
def ml_kelly():
    """
    返回当前实盘持仓/候选信号的凯利建议仓位。
    结合当前 regime + 各策略历史胜率计算。
    """
    try:
        from .trading.market_regime import detect_regime
        from .trading.ml.regime_winrate import lookup_winrate
        from .trading.strategies.short_term import get_all_strategy_signals
        from .trading.strategies.trend import get_all_trend_signals
        from .trading.strategies.lai_qu import get_all_lai_qu_signals
        from .trading.strategies.congling import get_all_congling_signals

        regime_data = detect_regime()
        regime = regime_data.get('recommended_strategy', 'neutral')
        # 映射到 risk_on/neutral/risk_off
        regime_label = {
            'trending_up': 'risk_on',
            'trending_down': 'risk_off',
            'ranging': 'neutral',
            'transitional': 'neutral',
        }.get(regime_data.get('regime', 'ranging'), 'neutral')

        # 收集当日所有信号
        all_signals = []
        for groups in [
            get_all_trend_signals(),
            get_all_strategy_signals(),
            get_all_lai_qu_signals(),
            get_all_congling_signals(),
        ]:
            for stype, items in (groups or {}).items():
                for it in (items or []):
                    if it.get('stock_code'):
                        all_signals.append(it)

        result = []
        seen = set()
        for sig in sorted(all_signals, key=lambda x: x.get('score', 0), reverse=True):
            code = sig['stock_code']
            if code in seen:
                continue
            seen.add(code)
            strategy = sig.get('strategy', '')
            wc = lookup_winrate(strategy, regime_label)
            from .trading.ml.xgb_scorer import score_signal
            ml = score_signal(strategy, regime_label, sig.get('signal_detail', {}))
            result.append({
                'stock_code': code,
                'stock_name': sig.get('stock_name', code),
                'strategy': strategy,
                'orig_score': sig.get('score', 0),
                'p_up': ml['p_up'],
                'kelly_f': ml['kelly_f'],
                'kelly_pct': f"{ml['kelly_f']*100:.1f}%",
                'win_rate': wc['win_rate'],
                'sample_count': wc['sample_count'],
                'source': ml['source'],
                'regime': regime_label,
            })

        result.sort(key=lambda x: x['p_up'], reverse=True)
        return jsonify({
            'success': True,
            'regime': regime_label,
            'regime_detail': regime_data.get('regime'),
            'data': result[:20],
        })
    except Exception as e:
        import traceback
        return jsonify({'success': False, 'error': str(e), 'trace': traceback.format_exc()})


@api.route('/api/ml/train', methods=['POST'])
def ml_train():
    """手动触发 XGBoost 训练（需要 >= 100 条已标注信号）。"""
    try:
        from .trading.ml.xgb_scorer import train_model
        result = train_model()
        return jsonify({'success': True, 'result': result})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@api.route('/api/ml/ic-report')
def ml_ic_report():
    """因子 IC/IR 报告：composite score + 子因子 + 策略维度 + 时序。"""
    try:
        force = request.args.get('refresh', '').lower() in ('1', 'true')
        from .trading.ml.ic_tracker import get_ic_report
        return jsonify({'success': True, **get_ic_report(force_refresh=force)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@api.route('/api/portfolio/beta')
def portfolio_beta():
    """组合 Beta + 暴露倍数分析。"""
    try:
        from .trading.ml.beta_tracker import compute_portfolio_beta, get_exposure_multiplier
        from .trading.account import get_positions
        positions = get_positions()
        beta_data = compute_portfolio_beta(positions)
        exposure = get_exposure_multiplier()
        return jsonify({'success': True, **beta_data, 'exposure': exposure})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@api.route('/api/portfolio/weights')
def portfolio_weights():
    """风险平价组合分析：理想权重 vs 实际权重，找出偏差。"""
    try:
        from .trading.ml.portfolio_optimizer import get_portfolio_analysis
        from .trading.account import get_positions
        positions = get_positions()
        db = get_db()
        try:
            acc = dict(db.execute("SELECT * FROM account WHERE id=1").fetchone())
        finally:
            db.close()
        result = get_portfolio_analysis(positions, acc['total_asset'])
        return jsonify({'success': True, **result})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@api.route('/api/ml/strategy-decay')
def ml_strategy_decay():
    """策略衰减检测：近20笔 vs 历史基准胜率，差值 >15pp 告警。"""
    try:
        from .trading.ml.regime_winrate import detect_strategy_decay
        results = detect_strategy_decay()
        alerts = [r for r in results if r['degrading']]
        return jsonify({'success': True, 'data': results, 'alerts': len(alerts)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@api.route('/api/ml/signal-stats')
def ml_signal_stats():
    """返回 signal_log 的统计信息：总数、已标注数、各策略分布。"""
    try:
        db = get_db()
        try:
            total = db.execute("SELECT COUNT(*) FROM signal_log").fetchone()[0]
            labeled = db.execute(
                "SELECT COUNT(*) FROM signal_log WHERE label != -1").fetchone()[0]
            by_strategy = db.execute(
                """SELECT strategy,
                          COUNT(*) as n,
                          SUM(CASE WHEN label=1 THEN 1 ELSE 0 END) as wins,
                          SUM(CASE WHEN label=0 THEN 1 ELSE 0 END) as losses
                   FROM signal_log WHERE label != -1
                   GROUP BY strategy ORDER BY n DESC"""
            ).fetchall()
        finally:
            db.close()
        return jsonify({
            'success': True,
            'total_signals': total,
            'labeled_signals': labeled,
            'pending_label': total - labeled,
            'by_strategy': [dict(r) for r in by_strategy],
            'xgb_ready': labeled >= 100,
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ── 账户2: 板块动量轮动 ──────────────────────────────────────────────────

@api.route('/api/account2/summary')
def account2_summary():
    from .trading.engine2 import get_account2, get_positions2, refresh_prices2
    try:
        refresh_prices2()
        acc = get_account2()
        positions = get_positions2()
        pos_value = sum(p['current_price'] * p['shares'] for p in positions)
        init = acc.get('initial_capital', 1000000)
        return jsonify({
            'cash': acc.get('cash', 0),
            'frozen': acc.get('frozen', 0),
            'total_asset': acc.get('total_asset', 0),
            'initial_capital': init,
            'cumulative_return_pct': round((acc.get('total_asset', init) - init) / init * 100, 2) if init else 0,
            'position_count': len(positions),
            'position_value': round(pos_value, 2),
            'available_cash': acc.get('cash', 0) - acc.get('frozen', 0),
            'positions': positions,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api.route('/api/account2/positions')
def account2_positions():
    from .trading.engine2 import get_positions2
    return jsonify(get_positions2())


@api.route('/api/account2/curve')
def account2_curve():
    period = request.args.get('period', '30d')
    limit_map = {'7d': 7, '30d': 30, '90d': 90, '365d': 365, 'all': 3650}
    limit = limit_map.get(period, 30)
    db = get_db()
    try:
        rows = db.execute(f"SELECT * FROM asset_snapshot2 ORDER BY date DESC LIMIT {limit}").fetchall()
    finally:
        db.close()
    return jsonify([dict(r) for r in reversed(rows)])


@api.route('/api/account2/trades')
def account2_trades():
    db = get_db()
    try:
        rows = db.execute("SELECT * FROM trade_log2 ORDER BY created_at DESC LIMIT 100").fetchall()
    finally:
        db.close()
    return jsonify([dict(r) for r in rows])


@api.route('/api/account2/buy', methods=['POST'])
def account2_buy():
    data = request.get_json(silent=True) or {}
    code = str(data.get('stock_code', '')).strip()
    if not code:
        return jsonify({'success': False, 'error': '请提供股票代码'}), 400
    from .trading.engine2 import execute_buy2
    return jsonify(execute_buy2(code, data.get('amount', 100000),
                                data.get('reason', '手动买入'), data.get('sector', '')))


@api.route('/api/account2/sell', methods=['POST'])
def account2_sell():
    data = request.get_json(silent=True) or {}
    code = str(data.get('stock_code', '')).strip()
    if not code:
        return jsonify({'success': False, 'error': '请提供股票代码'}), 400
    from .trading.engine2 import execute_sell2
    return jsonify(execute_sell2(code, data.get('shares'), data.get('reason', '手动卖出')))


@api.route('/api/account2/scan', methods=['POST'])
def account2_scan():
    """手动触发一次账户2扫描（调试用）。"""
    if not datetime.now().weekday() < 5:
        return jsonify({'success': False, 'error': '非交易日'})
    from .trading.scheduler import _run_acct2_scan
    try:
        _run_acct2_scan()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@api.route('/api/account2/return-curve')
def account2_return_curve():
    """账户2收益率曲线 vs 四大指数。"""
    from .data.fetcher import get_index_data
    db = get_db()
    try:
        acc = db.execute("SELECT initial_capital, total_asset, created_at FROM account2 WHERE id=1").fetchone()
        if not acc:
            return jsonify({'dates': [], 'asset': [], 'sh': [], 'sz': [], 'cy': [], 'kc': []})

        initial = acc['initial_capital']
        live_total = acc['total_asset']
        start_date = acc['created_at'][:10] if acc['created_at'] else datetime.now().strftime('%Y-%m-%d')

        snapshots = db.execute(
            "SELECT date, total_asset FROM asset_snapshot2 WHERE date >= ? ORDER BY date ASC",
            (start_date,)
        ).fetchall()

        index_rows = db.execute(
            "SELECT date, sh_close, sz_close, cy_close, kc_close FROM index_snapshot WHERE date >= ? ORDER BY date ASC",
            (start_date,)
        ).fetchall()
    finally:
        db.close()

    if not snapshots:
        return jsonify({'dates': [], 'asset': [], 'sh': [], 'sz': [], 'cy': [], 'kc': []})

    idx_by_date = {r['date']: r for r in index_rows}
    first_idx = index_rows[0] if index_rows else None
    today_str = datetime.now().strftime('%Y-%m-%d')

    # Fetch live index prices for today
    live_idx = {}
    try:
        idx_data = get_index_data()
        code_to_key = {'000001': 'sh', '399001': 'sz', '399006': 'cy', '000688': 'kc'}
        for item in idx_data:
            key = code_to_key.get(item.get('code', ''))
            if key and item.get('price', 0) > 0:
                live_idx[key] = item['price']
    except:
        pass

    dates, asset_cum, sh_cum, sz_cum, cy_cum, kc_cum = [], [], [], [], [], []

    def calc_ret(cur, base):
        if base and base != 0:
            return round((cur - base) / base * 100, 2)
        return 0

    for s in snapshots:
        date_str = s['date']
        dates.append(date_str)

        asset_val = live_total if date_str == today_str else s['total_asset']
        asset_ret = round((asset_val - initial) / initial * 100, 2) if initial else 0
        asset_cum.append(asset_ret)

        idx_rec = idx_by_date.get(date_str)
        if not idx_rec and first_idx:
            idx_rec = first_idx

        if date_str == today_str and live_idx:
            sh_cum.append(calc_ret(live_idx.get('sh', 0), first_idx['sh_close']) if first_idx else 0)
            sz_cum.append(calc_ret(live_idx.get('sz', 0), first_idx['sz_close']) if first_idx else 0)
            cy_cum.append(calc_ret(live_idx.get('cy', 0), first_idx['cy_close']) if first_idx else 0)
            kc_cum.append(calc_ret(live_idx.get('kc', 0), first_idx['kc_close']) if first_idx else 0)
        elif idx_rec and first_idx:
            sh_cum.append(calc_ret(idx_rec['sh_close'], first_idx['sh_close']))
            sz_cum.append(calc_ret(idx_rec['sz_close'], first_idx['sz_close']))
            cy_cum.append(calc_ret(idx_rec['cy_close'], first_idx['cy_close']))
            kc_cum.append(calc_ret(idx_rec['kc_close'], first_idx['kc_close']))
        else:
            sh_cum.append(0)
            sz_cum.append(0)
            cy_cum.append(0)
            kc_cum.append(0)

    return jsonify({
        'dates': dates,
        'asset': asset_cum,
        'sh': sh_cum,
        'sz': sz_cum,
        'cy': cy_cum,
        'kc': kc_cum,
    })
