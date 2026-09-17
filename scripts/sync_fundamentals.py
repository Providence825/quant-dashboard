#!/usr/bin/env python3
"""
Bulk-sync fundamental financial data from AKShare into stock_fundamentals table.

Usage:
  python scripts/sync_fundamentals.py                     # all stocks, start_year=2023
  python scripts/sync_fundamentals.py --start-year 2022   # 3 years back
  python scripts/sync_fundamentals.py --codes 600519 000001
"""
import sys, os, time, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.db import get_db, init_db
from server.data.fundamentals import fetch_and_save


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--start-year', default='2023', help='起始年份，默认2023')
    parser.add_argument('--codes', nargs='*', help='指定股票代码(6位)，不填则同步全部')
    args = parser.parse_args()

    init_db()
    conn = get_db()

    if args.codes:
        # 兼容带市场前缀和不带前缀的输入
        codes = []
        for c in args.codes:
            if len(c) == 6:
                prefix = 'SH' if c.startswith('6') else 'SZ'
                codes.append(prefix + c)
            else:
                codes.append(c)
    else:
        rows = conn.execute('SELECT code FROM stocks ORDER BY code').fetchall()
        codes = [r['code'] for r in rows]

    total = len(codes)
    if total == 0:
        print('stocks表为空，先运行股票列表同步')
        conn.close()
        return

    print(f'同步基本面数据：{total} 只股票，起始年份 {args.start_year}')
    ok = err = skipped = 0

    for i, code in enumerate(codes, 1):
        try:
            n = fetch_and_save(conn, code, args.start_year)
            if n == 0:
                skipped += 1
            else:
                ok += 1
            if i % 50 == 0 or i == total:
                print(f'  [{i}/{total}] 成功={ok} 跳过={skipped} 失败={err}')
        except Exception as e:
            err += 1
            if err <= 10:
                print(f'  [{i}/{total}] {code} 失败: {e}')
        time.sleep(0.4)  # 避免被新浪限速

    conn.close()
    print(f'\n完成: {ok} 成功, {skipped} 无数据, {err} 失败')


if __name__ == '__main__':
    main()
