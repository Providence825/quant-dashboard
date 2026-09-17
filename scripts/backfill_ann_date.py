#!/usr/bin/env python3
"""One-time backfill: compute ann_date for all existing stock_fundamentals rows."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from server.db import get_db, init_db
from server.data.fundamentals import _calc_ann_date

init_db()
conn = get_db()
rows = conn.execute(
    "SELECT stock_code, report_date FROM stock_fundamentals WHERE ann_date IS NULL"
).fetchall()

print(f"Backfilling ann_date for {len(rows)} rows...")
updated = 0
for r in rows:
    ann = _calc_ann_date(r['report_date'])
    conn.execute(
        "UPDATE stock_fundamentals SET ann_date=? WHERE stock_code=? AND report_date=?",
        (ann, r['stock_code'], r['report_date'])
    )
    updated += 1

conn.commit()
conn.close()
print(f"Done: {updated} rows updated.")
