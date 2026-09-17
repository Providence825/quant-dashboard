from ..data import fetcher
from .account import (get_account, get_positions, calc_max_buy_amount,
                       MAX_POSITION_PCT, MAX_TOTAL_POSITION)
from .strategies.sector_momentum import get_sector_momentum_candidates
import os

# 账户1改用板块动量策略 (sector_momentum), 不再使用原有的 short_term/trend/lai_qu/congling
ACTIVE_STRATEGY = 'sector_momentum'

def set_strategy_mode(mode):
    global ACTIVE_STRATEGY
    ACTIVE_STRATEGY = mode

def get_effective_strategy():
    """账户1固定使用板块动量策略."""
    return 'sector_momentum'

def should_buy():
    """账户1板块动量策略买入判断 - 简化版，去除情绪闸门."""
    if not fetcher.is_trading_time():
        return False, '非交易时间'

    acc = get_account()
    positions = get_positions()
    pos_value = sum(p['current_price'] * p['shares'] for p in positions)
    total_pos_pct = pos_value / acc['total_asset'] if acc['total_asset'] > 0 else 0

    if total_pos_pct >= MAX_TOTAL_POSITION:
        return False, f'仓位已达上限 {total_pos_pct*100:.0f}%'

    max_buy = calc_max_buy_amount()
    if max_buy < 10000:
        return False, f'可用资金不足 (剩余{max_buy:.0f})'

    from ..db import get_db
    db = get_db()
    try:
        today_trades = db.execute("SELECT COUNT(*) as cnt FROM trade_log WHERE date(created_at)=date('now','localtime') AND direction='buy'").fetchone()
        daily_loss = db.execute("SELECT COALESCE(SUM(pnl_amount),0) as loss FROM trade_log WHERE date(created_at)=date('now','localtime')").fetchone()
    finally:
        db.close()

    today_trades_cnt = today_trades['cnt']

    if today_trades_cnt >= 8:
        return False, '今日已买入8只，不再开仓'
    if daily_loss['loss'] < -acc['total_asset'] * 0.03:
        return False, '单日亏损超3%，暂停开仓'

    return True, '可以买入'

def _measured_move_target(stock_code, entry_price):
    """
    Brooks Measured Move: target = entry + (entry - swing_low_before_entry).
    Swing low = lowest close in the 40 bars prior to the last 5 bars (pre-run base).
    Returns target price, or None if data unavailable.
    """
    kline = fetcher.get_kline_data(stock_code, days=60)
    if not kline or len(kline) < 15:
        return None
    # Use bars before the recent run (skip last 5) to find the base swing low
    lookback_bars = kline[-(min(45, len(kline))):-5]
    if not lookback_bars:
        return None
    swing_low = min(k['close'] for k in lookback_bars)
    first_leg = entry_price - swing_low
    if first_leg <= 0:
        return None
    return round(entry_price + first_leg, 2)


def should_sell(position):
    cost = position['avg_cost']
    current = position['current_price']
    highest = position['highest_price']
    change_pct = (current / cost - 1)
    from_high = (current / highest - 1) if highest > 0 else 0

    # Use strategy-specific params (check both short-term and trend param sets)
    stype = position.get('strategy_type', 'default')
    trend_strategies = ['均线多头突破', '通道突破', '均线回踩', '海龟通道突破']
    lai_qu_strategies = ['趋势买点1·底部建仓', '趋势买点2·M60突破', '趋势买点3·回踩重仓',
                         '龙头2进3板', '卡位龙头', '补涨龙']
    congling_strategies = ['关键位突破', '假突破检测', '延续性龙头', '盘面强弱', '科学加仓']
    if stype in lai_qu_strategies:
        params = get_lai_qu_params(stype)
    elif stype in congling_strategies:
        params = get_congling_params(stype)
    elif stype in trend_strategies:
        params = get_trend_params(stype)
    else:
        params = get_short_term_params(stype)

    STOP_LOSS = float(os.getenv('STOP_LOSS_PCT', params['stop_loss_pct']))
    TAKE_PROFIT = float(os.getenv('TAKE_PROFIT_PCT', params['take_profit_pct']))
    TRAILING_STOP = float(os.getenv('TRAILING_STOP_PCT', params['trailing_stop_pct']))

    if change_pct <= -STOP_LOSS:
        return True, f'{stype}止损 ({change_pct*100:.1f}%)'

    # Measured Move take-profit for lai_qu trend strategies
    mm_strategies = ('趋势买点2·M60突破', '趋势买点3·回踩重仓')
    if stype in mm_strategies:
        try:
            mm_target = _measured_move_target(position['stock_code'], cost)
            if mm_target and current >= mm_target:
                return True, f'{stype}MM止盈 目标{mm_target:.2f} 当前{current:.2f}'
            # Trailing stop above MM target
            if mm_target and highest >= mm_target and from_high <= -TRAILING_STOP:
                return True, f'{stype}MM移动止盈 (最高{highest:.2f}回撤{from_high*100:.1f}%)'
        except Exception:
            pass  # Fall through to default take-profit

    if change_pct >= TAKE_PROFIT:
        return True, f'{stype}止盈 ({change_pct*100:.1f}%)'
    if highest > cost * (1 + TAKE_PROFIT) and from_high <= -TRAILING_STOP:
        return True, f'{stype}移动止盈 (最高{highest:.2f}回撤{from_high*100:.1f}%)'

    from datetime import datetime
    hold_days = (datetime.now() - datetime.strptime(position['buy_date'], '%Y-%m-%d')).days
    MAX_HOLD = int(os.getenv('MAX_HOLD_DAYS', params['max_hold_days']))
    if hold_days >= MAX_HOLD:
        return True, f'{stype}到期清仓 (持有{hold_days}天)'

    # Dragon-specific exit: turnover overheated
    if stype == '龙头战法' and params.get('exit_on_turnover'):
        stocks = fetcher.get_stock_list()
        for s in (stocks or []):
            if s['代码'] == position['stock_code']:
                turnover = float(s.get('换手率', 0))
                if turnover > params['exit_on_turnover']:
                    return True, f'龙头过热(换手{turnover}%>{params["exit_on_turnover"]}%)'
                break

    # Dragon-specific exit: below MA5
    if stype == '龙头战法' and params.get('exit_below_ma5'):
        kline = fetcher.get_kline_data(position['stock_code'], days=10)
        if kline and len(kline) >= 5:
            ma5 = sum(k['close'] for k in kline[-5:]) / 5
            if current < ma5:
                return True, f'龙头破MA5({current:.2f}<{ma5:.2f})'

    # Late-day dip: next-day auto sell
    if stype == '尾盘捡漏' and params.get('next_day_sell'):
        if hold_days >= 1 and fetcher.is_trading_time():
            return True, f'尾盘捡漏次日了结(持有{hold_days}天)'

    # Trend: MA breakout exit on MA20 breakdown
    if stype == '均线多头突破' and params.get('exit_on_ma_break'):
        kline = fetcher.get_kline_data(position['stock_code'], days=30)
        if kline and len(kline) >= 20:
            ma20 = sum(k['close'] for k in kline[-20:]) / 20
            if current < ma20 * 0.97:
                return True, f'均线多头破MA20({current:.2f}<{ma20:.2f})'

    # Trend: channel breakout exit at channel mid
    if stype in ('通道突破', '海龟通道突破') and params.get('exit_on_channel_mid'):
        kline = fetcher.get_kline_data(position['stock_code'], days=30)
        if kline and len(kline) >= 22:
            channel_high = max(k['high'] for k in kline[-21:-1])
            channel_low = min(k['low'] for k in kline[-21:-1])
            channel_mid = (channel_high + channel_low) / 2
            if current < channel_mid:
                return True, f'{stype}回落中轨({current:.2f}<{channel_mid:.2f})'

    # Trend: if market regime switched from trending to ranging, exit trend positions faster
    try:
        from .market_regime import get_active_strategy_mode
        active_mode, _ = get_active_strategy_mode()
        if stype in trend_strategies and active_mode == 'short_term':
            if change_pct > 0.02:  # Take profit if profitable when regime shifts
                return True, f'市场转震荡-趋势仓止盈({change_pct*100:.1f}%)'
    except:
        pass

    # ── 来去由心 specific exits ──────────────────────────────────────
    # Buy Point 2: exit if falls below M60 for 3+ days
    if stype == '趋势买点2·M60突破' and params.get('exit_below_ma60'):
        kline = fetcher.get_kline_data(position['stock_code'], days=70)
        if kline and len(kline) >= 63:
            closes = [k['close'] for k in kline]
            ma60 = sum(closes[-60:]) / 60
            below_count = sum(1 for c in closes[-3:] if c < ma60 * 0.99)
            if below_count >= 3:
                return True, f'M60破位{below_count}日({current:.2f}<{ma60:.2f})'

    # Buy Point 3: exit if falls below M20
    if stype == '趋势买点3·回踩重仓' and params.get('exit_below_ma20'):
        kline = fetcher.get_kline_data(position['stock_code'], days=30)
        if kline and len(kline) >= 20:
            ma20 = sum(k['close'] for k in kline[-20:]) / 20
            if current < ma20 * 0.97:
                return True, f'M20破位({current:.2f}<{ma20:.2f})'

    # Buy Point 1: tighter stop (4% fallback)
    if stype == '趋势买点1·底部建仓':
        if change_pct <= -0.04:
            return True, f'底部仓位止损({change_pct*100:.1f}%)'

    # Dragon 2→3: quick exit if fails
    if stype == '龙头2进3板':
        if hold_days >= 2 and change_pct < -0.03:
            return True, f'2进3失败({change_pct*100:.1f}%)'

    return False, ''

def _get_sentiment():
    stocks = fetcher.get_stock_list()
    if not stocks:
        return 50
    up = sum(1 for s in stocks if float(s.get('涨跌幅', 0)) > 0)
    down = sum(1 for s in stocks if float(s.get('涨跌幅', 0)) < 0)
    total = max(up + down, 1)
    return min(100, max(0, round(up / total * 100)))


def get_buy_candidates(strategy_mode=None):
    """账户1固定使用板块动量选股."""
    candidates = []
    sector_cands = get_sector_momentum_candidates()
    for c in sector_cands:
        candidates.append({
            'stock_code': c['stock_code'],
            'stock_name': c['stock_name'],
            'score': c['score'],
            'price': c['price'],
            'change_pct': c['change_pct'],
            'reasons': f"板块动量-{c['sector']}(涨{c['change_pct']}%量比{c['vol_ratio']})",
            'strategy_type': '板块动量',
        })
    return candidates
