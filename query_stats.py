from server.db import get_db

db = get_db()
rows = db.execute("""
    SELECT strategy,
           COUNT(*) as cnt,
           SUM(CASE WHEN pnl_pct>0 THEN 1 ELSE 0 END) as wins,
           AVG(pnl_pct) as avg,
           SUM(pnl_amount) as total
    FROM trade_log
    WHERE direction='sell'
    GROUP BY strategy
""").fetchall()
db.close()

for r in rows:
    s = dict(r)
    wr = s['wins']/s['cnt']*100 if s['cnt']>0 else 0
    print(f"{s['strategy']:20s} 交易{s['cnt']:3d}次 胜率{wr:5.1f}% 平均{s['avg']:6.2f}% 累计{s['total']:8.0f}")
