from datetime import datetime
from ..db import get_db
from ..data import fetcher
from .strategy import should_buy, should_sell, get_buy_candidates
from .risk import check_risk_limits
from .engine import execute_buy, execute_sell
import time
import threading

_auto_trading = False
_last_scan_time = None

def get_status():
    status = {
        'auto_trading': _auto_trading,
        'is_trading_day': fetcher.is_trading_day(),
        'is_trading_time': fetcher.is_trading_time(),
        'last_scan': _last_scan_time,
    }
    try:
        from .market_regime import detect_regime
        regime = detect_regime()
        status['regime'] = regime['regime']
        status['recommended_strategy'] = regime['recommended_strategy']
        status['regime_detail'] = regime['details']
    except:
        pass
    try:
        from .strategy import ACTIVE_STRATEGY, get_effective_strategy
        status['strategy_mode'] = ACTIVE_STRATEGY
        status['effective_mode'] = get_effective_strategy()
    except:
        pass
    return status

def register_jobs(scheduler, app):
    def morning_scan():
        if not fetcher.is_trading_day() or not fetcher.is_trading_time():
            return
        with app.app_context():
            _run_morning_scan()

    def monitor_loop():
        if not fetcher.is_trading_day() or not fetcher.is_trading_time():
            return
        with app.app_context():
            _run_monitor()

    def closing_scan():
        if not fetcher.is_trading_day() or not fetcher.is_trading_time():
            return
        with app.app_context():
            _run_closing()

    def after_close():
        if not fetcher.is_trading_day():
            return
        with app.app_context():
            _run_after_close()

    def fetch_content():
        with app.app_context():
            try:
                from ..data.content_fetcher import run_content_aggregator
                saved = run_content_aggregator()
                print(f"[AUTO] 内容采集: 福总{saved.get('fuzong',0)}条, 来去由心{saved.get('laiqu',0)}条")
            except Exception as e:
                print(f"[AUTO] 内容采集失败: {e}")

    scheduler.add_job(fetch_content, 'cron', hour=8, minute=30, id='fetch_content_morning', coalesce=True, misfire_grace_time=300)
    scheduler.add_job(fetch_content, 'cron', hour=21, minute=0, id='fetch_content_evening', coalesce=True, misfire_grace_time=300)
    scheduler.add_job(morning_scan, 'cron', hour=9, minute=35, id='morning_scan', coalesce=True, misfire_grace_time=300)
    scheduler.add_job(monitor_loop, 'interval', seconds=30, id='monitor_loop', max_instances=1, coalesce=True, misfire_grace_time=60)
    scheduler.add_job(closing_scan, 'cron', hour=14, minute=50, id='closing_scan', coalesce=True, misfire_grace_time=300)

    def late_day_dip_scan():
        """14:40 — scan for late-day dip opportunities (尾盘捡漏)."""
        if not fetcher.is_trading_day() or not fetcher.is_trading_time():
            return
        with app.app_context():
            try:
                from .strategies.short_term import late_day_dip_candidates
                from .engine import execute_buy
                dips = late_day_dip_candidates()
                if not dips:
                    print("[AUTO] 尾盘捡漏: 无符合条件的标的")
                    return
                print(f"[AUTO] 尾盘捡漏: 发现{len(dips)}个候选, Top={dips[0]['stock_name']}")
                # Only auto-buy top 1, small position
                top = dips[0]
                result = execute_buy(top['stock_code'], amount=50000,
                                    reason='尾盘捡漏-' + str(top.get('signal_detail', {})),
                                    strategy_type='尾盘捡漏')
                if result.get('success'):
                    print(f"[AUTO] 尾盘买入 {top['stock_name']} {result['shares']}股 @{result['price']}")
                else:
                    print(f"[AUTO] 尾盘买入失败: {result.get('error')}")
            except Exception as e:
                print(f"[AUTO] 尾盘捡漏异常: {e}")

    def next_day_sell_dips():
        """9:35 — auto-sell late-day dip positions from yesterday."""
        if not fetcher.is_trading_day() or not fetcher.is_trading_time():
            return
        with app.app_context():
            try:
                from .engine import execute_sell
                from ..db import get_db
                db = get_db()
                positions = db.execute(
                    "SELECT * FROM positions WHERE status='holding' AND strategy_type='尾盘捡漏'").fetchall()
                db.close()
                for pos in positions:
                    pos = dict(pos)
                    result = execute_sell(pos['stock_code'], pos['shares'], '尾盘捡漏-次日了结')
                    if result.get('success'):
                        print(f"[AUTO] 尾盘了结 {pos['stock_name']} PnL:{result.get('pnl',0):.2f}")
            except Exception as e:
                print(f"[AUTO] 尾盘了结异常: {e}")

    scheduler.add_job(late_day_dip_scan, 'cron', hour=14, minute=40, id='late_day_dip',
                      coalesce=True, misfire_grace_time=300)
    scheduler.add_job(next_day_sell_dips, 'cron', hour=9, minute=34, id='next_day_sell_dips',
                      coalesce=True, misfire_grace_time=300)
    scheduler.add_job(after_close, 'cron', hour=15, minute=10, id='after_close', coalesce=True, misfire_grace_time=3600)

    def sync_daily_kline():
        with app.app_context():
            try:
                from ..data.importer import _do_sync_daily_prices
                result = _do_sync_daily_prices()
                print(f"[AUTO] K线日同步: synced={result.get('synced',0)}")
            except Exception as e:
                print(f"[AUTO] K线日同步失败: {e}")

    def weekly_stock_refresh():
        with app.app_context():
            try:
                from ..data.importer import _do_import_all_stocks
                result = _do_import_all_stocks()
                print(f"[AUTO] 周度股票刷新: stocks={result.get('stocks',0)}")
            except Exception as e:
                print(f"[AUTO] 周度股票刷新失败: {e}")

    # 「为你精选」候选池刷新条件（与 static/js/screener.js 默认一致）
    SCREENER_CONDITIONS = {
        'level1': {'exclude_st': True, 'max_price': 100, 'exclude_loss_years': 2, 'revenue_growth_positive': True},
        'level2': {'pe_min': 10, 'pe_max': 60, 'roe_min': 8, 'debt_max': 70, 'cashflow_positive': True},
        'level3': {'ma_cross': True, 'macd_cross': True, 'kdj_cross': False, 'rsi_oversold': False, 'volume_break': True},
        'skip_northbound': True,  # 定时任务跳过每只 10s 的 AKShare 阻塞调用，否则全市场跑不完
    }

    def refresh_screener():
        """交易日收盘后（K线同步之后）重跑评分选股，刷新 screener_results。"""
        if not fetcher.is_trading_day():
            return
        with app.app_context():
            try:
                from ..data.screener import run_screener
                results = run_screener(SCREENER_CONDITIONS)
                print(f"[AUTO] 精选刷新: {len(results)} 只 (top {min(len(results),30)} 已入库)")
            except Exception as e:
                print(f"[AUTO] 精选刷新失败: {e}")

    def screener_startup_catchup():
        """启动补偿：交易日启动时若今日无结果，立即跑一次，避免精选停在旧交易日。"""
        if not fetcher.is_trading_day():
            return
        with app.app_context():
            try:
                today = datetime.now().strftime('%Y-%m-%d')
                db = get_db()
                try:
                    row = db.execute(
                        "SELECT COUNT(*) AS n FROM screener_results WHERE date=?", (today,)
                    ).fetchone()
                finally:
                    db.close()
                if row and row['n']:
                    print(f"[AUTO] 精选启动补偿: 今日已有 {row['n']} 只，跳过")
                    return
                from ..data.screener import run_screener
                results = run_screener(SCREENER_CONDITIONS)
                print(f"[AUTO] 精选启动补偿: 今日缺失，已刷新 {len(results)} 只")
            except Exception as e:
                print(f"[AUTO] 精选启动补偿失败: {e}")

    def regime_analysis():
        """9:25 — run regime detection and log it for the day."""
        if not fetcher.is_trading_day():
            return
        with app.app_context():
            try:
                from .market_regime import detect_regime
                regime = detect_regime()
                print(f"[AUTO] 行情判断: {regime['regime']} ADX={regime['adx']} "
                      f"均线={regime['ma_alignment']} 涨跌比={regime['breadth']}% "
                      f"→ 推荐策略={regime['recommended_strategy']}")
            except Exception as e:
                print(f"[AUTO] 行情判断异常: {e}")

    def midday_regime_check():
        """11:30 — mid-session re-check of regime, could switch strategy."""
        if not fetcher.is_trading_day():
            return
        with app.app_context():
            try:
                from .market_regime import detect_regime, get_active_strategy_mode
                _, regime = get_active_strategy_mode()
                print(f"[AUTO] 午盘行情复查: {regime['regime']} 趋势分={regime['trending_score']} 震荡分={regime['ranging_score']}")
            except Exception as e:
                print(f"[AUTO] 午盘复查异常: {e}")

    def sentiment_fetch():
        """8:30 / 21:00 — fetch and analyze market sentiment from Xueqiu."""
        with app.app_context():
            try:
                from ..data.sentiment_fetcher import fetch_all_sentiment_sources
                from .sentiment import run_sentiment_analysis

                texts = fetch_all_sentiment_sources()
                if texts:
                    result = run_sentiment_analysis(texts)
                    print(f"[AUTO] 情绪分析: 分={result['score']} 阶段={result['phase_label']} "
                          f"逆向信号={result['contrarian']['action']} "
                          f"仓位调整={result['contrarian']['position_adjustment']:+.0%} "
                          f"({len(texts)}条数据)")
                else:
                    print("[AUTO] 情绪分析: 无数据源")
            except Exception as e:
                print(f"[AUTO] 情绪分析失败: {e}")

    scheduler.add_job(regime_analysis, 'cron', hour=9, minute=25, id='regime_analysis',
                      coalesce=True, misfire_grace_time=300)
    scheduler.add_job(midday_regime_check, 'cron', hour=11, minute=30, id='midday_regime',
                      coalesce=True, misfire_grace_time=300)

    scheduler.add_job(sentiment_fetch, 'cron', hour=8, minute=30, id='sentiment_morning',
                      coalesce=True, misfire_grace_time=600)
    scheduler.add_job(sentiment_fetch, 'cron', hour=21, minute=0, id='sentiment_evening',
                      coalesce=True, misfire_grace_time=600)

    scheduler.add_job(sync_daily_kline, 'cron', hour=15, minute=30, id='sync_daily_kline',
                      coalesce=True, misfire_grace_time=3600)
    # 收盘 K 线同步(15:30)之后 5 分钟刷新「为你精选」候选池
    scheduler.add_job(refresh_screener, 'cron', hour=15, minute=35, id='refresh_screener',
                      coalesce=True, misfire_grace_time=3600)
    # 启动后 30 秒做一次补偿刷新(交易日若今日无结果，立即补跑)
    from datetime import timedelta
    scheduler.add_job(screener_startup_catchup, 'date',
                      run_date=datetime.now() + timedelta(seconds=30),
                      id='screener_startup_catchup', coalesce=True, misfire_grace_time=600)
    scheduler.add_job(weekly_stock_refresh, 'cron', day_of_week='sat', hour=10, minute=0,
                      id='weekly_stock_refresh', coalesce=True, misfire_grace_time=3600)

    def weekly_xgb_retrain():
        with app.app_context():
            try:
                import shutil, os as _os
                from .ml.xgb_scorer import train_model, MODEL_PATH
                if _os.path.exists(MODEL_PATH):
                    shutil.copy2(MODEL_PATH, MODEL_PATH + '.bak')
                result = train_model()
                print(f"[AUTO] XGB周度重训: trained={result.get('trained')} "
                      f"n={result.get('n_samples')} acc={result.get('accuracy')}")
            except Exception as e:
                print(f"[AUTO] XGB重训失败: {e}")

    scheduler.add_job(weekly_xgb_retrain, 'cron', day_of_week='sat', hour=16, minute=30,
                      id='weekly_xgb_retrain', coalesce=True, misfire_grace_time=3600)

    def weekly_ic_refresh():
        with app.app_context():
            try:
                from .ml.ic_tracker import get_ic_report
                report = get_ic_report(force_refresh=True)
                summary = report.get('summary', {})
                print(f"[AUTO] IC周度刷新: IC均值={summary.get('ic_mean')} IR={summary.get('ir')} "
                      f"质量={summary.get('quality')}")
            except Exception as e:
                print(f"[AUTO] IC刷新失败: {e}")

    scheduler.add_job(weekly_ic_refresh, 'cron', day_of_week='sat', hour=17, minute=0,
                      id='weekly_ic_refresh', coalesce=True, misfire_grace_time=3600)

    # ── 账户2: 板块动量轮动 ───────────────────────────────────────────────
    def acct2_scan():
        """每30分钟扫描一次板块动量，执行账户2买卖。"""
        if not fetcher.is_trading_day() or not fetcher.is_trading_time():
            return
        with app.app_context():
            _run_acct2_scan()

    def acct2_snapshot():
        """收盘后保存账户2资产快照。"""
        if not fetcher.is_trading_day():
            return
        with app.app_context():
            _save_acct2_snapshot()

    scheduler.add_job(acct2_scan, 'interval', minutes=30, id='acct2_scan',
                      max_instances=1, coalesce=True, misfire_grace_time=120)
    scheduler.add_job(acct2_snapshot, 'cron', hour=15, minute=15, id='acct2_snapshot',
                      coalesce=True, misfire_grace_time=3600)

def _run_morning_scan():
    """账户1改用板块动量策略，与账户2逻辑一致."""
    global _last_scan_time
    _last_scan_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    risk = check_risk_limits()
    if risk['halt']:
        print(f"[AUTO] 风控暂停: {risk['reason']}")
        return

    can_buy, reason = should_buy()
    if not can_buy:
        print(f"[AUTO] 不买入: {reason}")
        return

    # 账户1使用板块动量选股
    from .strategies.sector_momentum import get_sector_momentum_candidates, SECTOR_ACCT2_PARAMS
    candidates = get_sector_momentum_candidates()
    if not candidates:
        print("[AUTO] 板块动量选股无结果")
        return

    from .account import get_account, get_positions
    acc = get_account()
    positions = get_positions()
    existing_codes = {p['stock_code'] for p in positions}

    per_amount = acc['total_asset'] * SECTOR_ACCT2_PARAMS['per_position_pct']
    max_buy = SECTOR_ACCT2_PARAMS['max_positions']

    bought = 0
    for c in candidates:
        if len(positions) + bought >= max_buy:
            break
        if c['stock_code'] in existing_codes:
            continue
        result = execute_buy(c['stock_code'], amount=per_amount,
                            reason=f"板块动量-{c['sector']}(涨{c['change_pct']}%量比{c['vol_ratio']})",
                            strategy_type='板块动量')
        if result.get('success'):
            print(f"[AUTO] 买入 {c['stock_name']} [{c['sector']}] @{result['price']} ×{result['shares']}股")
            existing_codes.add(c['stock_code'])
            bought += 1
        else:
            print(f"[AUTO] 买入失败 {c['stock_name']}: {result.get('error')}")

def _run_monitor():
    if not fetcher.is_trading_time():
        return

    global _last_scan_time
    _last_scan_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    alerts = []
    try:
        from .engine import check_stop_conditions
        alerts = check_stop_conditions()
    except Exception as e:
        print(f"[AUTO] 监控异常: {e}")

    for alert in alerts:
        result = execute_sell(alert['stock_code'], alert['shares'], f'自动-{alert["type"]}')
        if result.get('success'):
            print(f"[AUTO] {alert['type']}卖出 {alert['stock_name']} PnL:{result.get('pnl',0):.2f}")

def _run_closing():
    positions = []
    try:
        from .account import get_positions
        positions = get_positions()
    except:
        pass

    for pos in positions:
        can, reason = should_sell(pos)
        if can:
            execute_sell(pos['stock_code'], pos['shares'], f'收盘-{reason}')

def _run_after_close():
    from ..review.daily import generate_daily_review
    try:
        generate_daily_review()
        print("[AUTO] 每日复盘已生成")
    except Exception as e:
        print(f"[AUTO] 复盘生成失败: {e}")

    # Save daily index snapshot for return curve comparison
    try:
        from ..data.fetcher import save_daily_index_snapshot
        save_daily_index_snapshot()
        print("[AUTO] 指数快照已保存")
    except Exception as e:
        print(f"[AUTO] 指数快照保存失败: {e}")


def _run_acct2_scan():
    """账户2板块动量轮动扫描（每30分钟）。"""
    from .strategies.sector_momentum import (
        get_sector_momentum_candidates, should_exit_sector_position,
        SECTOR_ACCT2_PARAMS,
    )
    from .engine2 import (
        get_account2, get_positions2, execute_buy2, execute_sell2, refresh_prices2,
    )

    refresh_prices2()

    # ── 止损/止盈/板块退出 ────────────────────────────────────────────
    positions = get_positions2()
    for pos in positions:
        should_exit, reason = should_exit_sector_position(pos)
        if should_exit:
            r = execute_sell2(pos['stock_code'], reason=f'自动2-{reason}')
            if r.get('success'):
                print(f"[ACCT2] 卖出 {pos['stock_name']} PnL:{r.get('pnl',0):.2f} 原因:{reason}")
            else:
                print(f"[ACCT2] 卖出失败 {pos['stock_name']}: {r.get('error')}")

    # ── 买入候选 ────────────────────────────────────────────────────
    acc = get_account2()
    positions = get_positions2()
    pos_value = sum(p['current_price'] * p['shares'] for p in positions)
    total = acc.get('total_asset', 0)
    if total <= 0:
        return
    total_pos_pct = pos_value / total
    max_pos = SECTOR_ACCT2_PARAMS['max_positions']

    if len(positions) >= max_pos or total_pos_pct >= 0.90:
        print(f"[ACCT2] 仓位已满 ({len(positions)}只 {total_pos_pct*100:.0f}%)，跳过买入")
        return

    existing_codes = {p['stock_code'] for p in positions}
    candidates = get_sector_momentum_candidates()
    per_amount = total * SECTOR_ACCT2_PARAMS['per_position_pct']

    bought = 0
    for c in candidates:
        if len(positions) + bought >= max_pos:
            break
        if c['stock_code'] in existing_codes:
            continue
        r = execute_buy2(c['stock_code'], amount=per_amount,
                         reason=f'板块动量-{c["sector"]}(涨{c["change_pct"]}%量比{c["vol_ratio"]})',
                         sector=c['sector'])
        if r.get('success'):
            print(f"[ACCT2] 买入 {c['stock_name']} [{c['sector']}] @{r['price']} ×{r['shares']}股")
            existing_codes.add(c['stock_code'])
            bought += 1
        else:
            print(f"[ACCT2] 买入失败 {c['stock_name']}: {r.get('error')}")


def _save_acct2_snapshot():
    """保存账户2每日资产快照。"""
    from .engine2 import get_account2, refresh_prices2
    from ..db import get_db
    from datetime import datetime

    refresh_prices2()
    acc = get_account2()
    if not acc:
        return

    db = get_db()
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        pos_mv = db.execute(
            "SELECT COALESCE(SUM(current_price*shares),0) as mv FROM positions2 WHERE status='holding'"
        ).fetchone()['mv']
        total = acc['total_asset']
        cash = acc['cash']
        init = acc['initial_capital']
        prev = db.execute(
            "SELECT total_asset FROM asset_snapshot2 WHERE date < ? ORDER BY date DESC LIMIT 1", (today,)
        ).fetchone()
        prev_asset = prev['total_asset'] if prev else init
        daily_ret = round((total - prev_asset) / prev_asset * 100, 2) if prev_asset else 0
        cum_ret = round((total - init) / init * 100, 2) if init else 0
        db.execute("""INSERT OR REPLACE INTO asset_snapshot2
            (date, total_asset, cash, position_value, daily_return_pct, cumulative_return_pct, created_at)
            VALUES (?,?,?,?,?,?,datetime('now','localtime'))""",
            (today, total, cash, pos_mv, daily_ret, cum_ret))
        db.commit()
        print(f"[ACCT2] 快照: 总资产={total:.0f} 日收益={daily_ret:+.2f}% 累计={cum_ret:+.2f}%")
    finally:
        db.close()
