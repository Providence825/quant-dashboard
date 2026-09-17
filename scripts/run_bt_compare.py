#!/usr/bin/env python3
"""Run two backtests (2024 bull vs 2026 weak) for trend strategy and print comparison."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.db import get_db, init_db
from server.trading.backtest import _run

init_db()

RUNS = [
    {'label': '2024牛市', 'start_date': '2024-01-01', 'end_date': '2024-12-31'},
    {'label': '2026弱市', 'start_date': '2026-01-01', 'end_date': '2026-06-30'},
]

BASE_PARAMS = {
    'strategy_mode': 'trend',
    'initial_capital': 1000000,
    'max_positions': 5,
    'universe_limit': 300,
    'risk_free_rate': 0.02,
    'market_filter': True,
    'sector_cap': 3,
}

for cfg in RUNS:
    params = {**BASE_PARAMS, **cfg}
    db = get_db()
    cur = db.execute(
        "INSERT INTO backtest_runs (params_json, status, progress_pct, started_at) "
        "VALUES (?, 'running', 0, datetime('now','localtime'))",
        (json.dumps(params, ensure_ascii=False),))
    db.commit()
    run_id = cur.lastrowid
    db.close()

    print(f"\n{'='*50}")
    print(f"回测 [{cfg['label']}]  run_id={run_id}")
    print(f"{'='*50}")
    _run(run_id, params)

    db = get_db()
    row = db.execute("SELECT result_json, error_message FROM backtest_runs WHERE id=?", (run_id,)).fetchone()
    db.close()

    if row['error_message']:
        print(f"ERROR: {row['error_message']}")
        continue

    r = json.loads(row['result_json'])
    trades = r.get('trades', [])
    pullback_trades = [t for t in trades if t.get('strategy') == '均线回踩']
    total_trades = len(pullback_trades)
    wins = [t for t in pullback_trades if t.get('pnl_pct', 0) > 0]
    win_rate = len(wins) / total_trades * 100 if total_trades else 0
    avg_pnl = sum(t.get('pnl_pct', 0) for t in pullback_trades) / total_trades if total_trades else 0

    print(f"总收益率   : {r.get('total_return_pct', 0):.2f}%")
    print(f"Sharpe     : {r.get('sharpe', 0):.2f}")
    print(f"最大回撤   : {r.get('max_drawdown_pct', 0):.2f}%")
    print(f"均线回踩   : {total_trades} 笔, 胜率 {win_rate:.1f}%, 均盈亏 {avg_pnl:.2f}%")
