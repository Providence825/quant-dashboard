import sqlite3
c = sqlite3.connect('quant.db')
print("=== TABLES ===")
for (n,) in c.execute("select name from sqlite_master where type='table'"):
    print(n)
print("=== COLUMNS per table ===")
for (n,) in c.execute("select name from sqlite_master where type='table'"):
    cols = [r[1] for r in c.execute(f"PRAGMA table_info({n})")]
    print(n, "->", cols)
