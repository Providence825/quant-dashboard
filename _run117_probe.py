# -*- coding: utf-8 -*-
import sqlite3, json, os

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'quant.db')
c = sqlite3.connect(DB)
c.row_factory = sqlite3.Row

# List recent completed runs
print("=== recent backtest_runs ===")
for r in c.execute("SELECT id, status, started_at, completed_at, "
                    "length(result_json) as rjlen, error_message "
                    "FROM backtest_runs ORDER BY id DESC LIMIT 20"):
    print(dict(r))

# Inspect run 117 result_json top-level keys
row = c.execute("SELECT params_json, result_json FROM backtest_runs WHERE id=117").fetchone()
if row is None:
    print("\n!!! run 117 not found")
else:
    print("\n=== run117 params ===")
    print(row['params_json'])
    if row['result_json']:
        r = json.loads(row['result_json'])
        print("\n=== run117 result keys ===")
        print(list(r.keys()))
        # peek equity structure
        for k in ('equity', 'equity_curve', 'daily', 'nav', 'asset_curve'):
            if k in r:
                v = r[k]
                print(f"\nkey '{k}': type={type(v).__name__}, len={len(v) if hasattr(v,'__len__') else '?'}")
                print("first:", v[0] if isinstance(v, list) and v else v)
                print("last :", v[-1] if isinstance(v, list) and v else v)
c.close()
