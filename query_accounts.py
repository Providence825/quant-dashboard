from server.db import get_db

db = get_db()
schema = db.execute("PRAGMA table_info(accounts)").fetchall()
print("=== accounts表结构 ===")
for col in schema:
    print(dict(col))

print("\n=== 账户数据 ===")
acc = db.execute("SELECT * FROM accounts").fetchall()
for a in acc:
    print(dict(a))

db.close()
