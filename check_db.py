import sqlite3

conn = sqlite3.connect('data/quant.db')
conn.row_factory = sqlite3.Row

# 全局K线日期范围
r = conn.execute("SELECT MIN(date) as min_d, MAX(date) as max_d, COUNT(DISTINCT date) as days, COUNT(*) as rows FROM stock_kline_daily").fetchone()
print(f"K线范围: {r['min_d']} ~ {r['max_d']}  ({r['days']} 交易日, {r['rows']} 行)")

# 指数K线
r2 = conn.execute("SELECT MIN(date) as min_d, MAX(date) as max_d FROM index_kline_daily").fetchone()
print(f"指数K线范围: {r2['min_d']} ~ {r2['max_d']}")

# 覆盖股票数
cnt = conn.execute("SELECT COUNT(DISTINCT stock_code) FROM stock_kline_daily").fetchone()[0]
print(f"覆盖股票: {cnt} 只")
conn.close()
