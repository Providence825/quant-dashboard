from server.db import get_db

db = get_db()
tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print("=== 数据库所有表 ===")
for t in tables:
    print(t[0])

print("\n=== 查找账户相关数据 ===")
# 检查是否有account相关的函数/模块直接返回数据
from server.trading.account import get_account
acc1 = get_account(1)
acc2 = get_account(2)

print(f"\n账户1: {acc1}")
print(f"\n账户2: {acc2}")

db.close()
