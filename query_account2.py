from server.db import get_db

db = get_db()

print("=== 账户2板块动量策略真实交易数据 ===")
rows = db.execute("""
    SELECT strategy,
           COUNT(*) as cnt,
           SUM(CASE WHEN pnl_pct>0 THEN 1 ELSE 0 END) as wins,
           AVG(pnl_pct) as avg,
           SUM(pnl_amount) as total
    FROM trade_log2
    WHERE direction='sell'
    GROUP BY strategy
""").fetchall()

for r in rows:
    s = dict(r)
    wr = s['wins']/s['cnt']*100 if s['cnt']>0 else 0
    print(f"{s['strategy']:20s} 交易{s['cnt']:3d}次 胜率{wr:5.1f}% 平均{s['avg']:6.2f}% 累计{s['total']:8.0f}")

print("\n=== 账户2整体统计 ===")
total = db.execute("SELECT COUNT(*) as cnt, SUM(CASE WHEN pnl_pct>0 THEN 1 ELSE 0 END) as wins, AVG(pnl_pct) as avg, SUM(pnl_amount) as total FROM trade_log2 WHERE direction='sell'").fetchone()
t = dict(total)
print(f"总交易: {t['cnt']}次")
print(f"胜率: {t['wins']/t['cnt']*100:.1f}%")
print(f"平均盈亏: {t['avg']:.2f}%")
print(f"累计盈亏: {t['total']:.0f}元")

db.close()
