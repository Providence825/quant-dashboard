"""
账户2专用策略: 板块动量轮动

逻辑:
- 每次扫描取当日强度 top-N 板块
- 每个板块选涨幅+量比综合评分最高的 top-K 只
- 止损5%/止盈12%/最长5日/移动止盈3%
- 板块跌出 top_threshold 名时提前退出
"""

SECTOR_ACCT2_PARAMS = {
    'stop_loss_pct':     0.05,
    'take_profit_pct':   0.12,
    'trailing_stop_pct': 0.03,
    'max_hold_days':     5,
    'top_sectors':       3,    # 监控前几个板块
    'stocks_per_sector': 2,    # 每板块最多持几只
    'max_positions':     8,    # 总仓上限
    'per_position_pct':  0.10, # 单笔占账户净值比例
    'sector_exit_rank':  6,    # 板块排名跌出第几位时清仓
    'min_change_pct':    1.0,  # 候选股当日最低涨幅
    'min_vol_ratio':     1.5,  # 候选股最低量比
    'min_price':         5.0,
}


def get_sector_momentum_candidates():
    """
    返回板块动量候选股:
    [{stock_code, stock_name, price, change_pct, vol_ratio, sector, sector_rank, score}]
    """
    from ...data.sectors import compute_sector_strength, stock_matches_sector
    from ...data import fetcher

    sectors = compute_sector_strength()
    if not sectors:
        return []

    params = SECTOR_ACCT2_PARAMS
    top_sectors = sectors[:params['top_sectors']]

    stocks = fetcher.get_stock_list()
    if not stocks:
        return []

    # 过滤ST/退市/低价
    def _ok(s):
        name = s.get('名称', '')
        price = float(s.get('最新价', 0))
        return price >= params['min_price'] and 'ST' not in name and '退' not in name

    candidates = []
    for rank, sec in enumerate(top_sectors):
        sec_name = sec['name']
        sec_stocks = []
        for s in stocks:
            if not _ok(s):
                continue
            if not stock_matches_sector(s.get('名称', ''), sec_name):
                continue
            change = float(s.get('涨跌幅', 0))
            vol_ratio = float(s.get('量比', 0))
            if change < params['min_change_pct']:
                continue
            if vol_ratio < params['min_vol_ratio']:
                continue
            score = round(change * 5 + vol_ratio * 8, 1)
            sec_stocks.append({
                'stock_code': s.get('代码', ''),
                'stock_name': s.get('名称', ''),
                'price': float(s.get('最新价', 0)),
                'change_pct': change,
                'vol_ratio': vol_ratio,
                'turnover': float(s.get('换手率', 0)),
                'sector': sec_name,
                'sector_rank': rank + 1,
                'score': score,
            })

        sec_stocks.sort(key=lambda x: x['score'], reverse=True)
        candidates.extend(sec_stocks[:params['stocks_per_sector']])

    candidates.sort(key=lambda x: x['score'], reverse=True)
    return candidates[:params['max_positions']]


def should_exit_sector_position(pos):
    """
    判断账户2持仓是否该清:
    - 止损/止盈/移动止盈/超时
    - 板块排名跌出 sector_exit_rank
    返回 (bool, reason_str)
    """
    params = SECTOR_ACCT2_PARAMS
    cost = pos['avg_cost']
    current = pos['current_price']
    highest = pos['highest_price']
    change_pct = (current / cost - 1)
    from_high = (current / highest - 1) if highest > 0 else 0

    if change_pct <= -params['stop_loss_pct']:
        return True, f'板块动量止损({change_pct*100:.1f}%)'
    if change_pct >= params['take_profit_pct']:
        return True, f'板块动量止盈({change_pct*100:.1f}%)'
    if highest > cost * (1 + params['take_profit_pct']) and from_high <= -params['trailing_stop_pct']:
        return True, f'板块动量移动止盈(最高{highest:.2f}回撤{from_high*100:.1f}%)'

    from datetime import datetime
    hold_days = (datetime.now() - datetime.strptime(pos['buy_date'], '%Y-%m-%d')).days
    if hold_days >= params['max_hold_days']:
        return True, f'板块动量到期({hold_days}天)'

    # 板块排名检查
    sector = pos.get('sector', '')
    if sector:
        from ...data.sectors import compute_sector_strength
        strength = compute_sector_strength()
        rank = next((i + 1 for i, s in enumerate(strength) if s['name'] == sector), 999)
        if rank > params['sector_exit_rank']:
            return True, f'{sector}板块排名跌至第{rank}(>{params["sector_exit_rank"]})'

    return False, ''
