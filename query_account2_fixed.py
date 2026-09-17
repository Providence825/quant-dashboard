from server.db import get_db

db = get_db()

print("=== trade_log2表结构 ===")
schema = db.execute("PRAGMA table_info(trade_log2)").fetchall()
for col in schema:
    print(dict(col))

print("\n=== 账户2整体交易统计 ===")
total = db.execute("SELECT COUNT(*) as cnt, SUM(CASE WHEN pnl_pct>0 THEN 1 ELSE 0 END) as wins, AVG(pnl_pct) as avg, SUM(pnl_amount) as total FROM trade_log2 WHERE direction='sell'").fetchone()
t = dict(total)
print(f"总交易: {t['cnt']}次")
print(f"胜率: {t['wins']/t['cnt']*100:.1f}%")
print(f"平均盈亏: {t['avg']:.2f}%")
print(f"累计盈亏: {t['total']:.0f}元")

print("\n=== 最近10笔交易 ===")
recent = db.execute("SELECT stock_code, stock_name, pnl_pct, pnl_amount, trigger_reason, created_at FROM trade_log2 WHERE direction='sell' ORDER BY created_at DESC LIMIT 10").fetchall()
for r in recent:
    rd = dict(r)
    print(f"{rd['created_at'][:10]} {rd['stock_code']} {rd['stock_name']:6s} {rd['pnl_pct']:6.2f}% {rd['pnl_amount']:7.0f}元 {rd['trigger_reason']}")

db.close()
