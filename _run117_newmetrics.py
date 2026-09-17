# -*- coding: utf-8 -*-
import sqlite3, json, os
from datetime import datetime

DB = os.path.join('data', 'quant.db')
c = sqlite3.connect(DB)
c.row_factory = sqlite3.Row
row = c.execute("SELECT result_json FROM backtest_runs WHERE id=117").fetchone()
r = json.loads(row['result_json'])
eq = r['equity']  # list of {date, total_asset}

dates = [datetime.strptime(e['date'], '%Y-%m-%d') for e in eq]
vals = [float(e['total_asset']) for e in eq]

# ---- 1. 月度收益 + 最大连续亏损月数 ----
# 每个自然月取最后一个交易日净值, 月收益 = 本月末/上月末 - 1
month_end = {}  # 'YYYY-MM' -> (date, val), keep last seen per month
for d, v in zip(dates, vals):
    key = d.strftime('%Y-%m')
    month_end[key] = v  # later overwrites -> last trading day value
months = sorted(month_end.keys())
# baseline = initial capital for first month return
init_cap = float(r['params'].get('initial_capital', 1000000)) if isinstance(r.get('params'), dict) else 1000000.0
monthly_ret = []
prev = vals[0]  # start from first equity point (~init)
# Better: use init capital as the pre-first-month base
prev = init_cap
for m in months:
    v = month_end[m]
    ret = v / prev - 1
    monthly_ret.append((m, ret * 100))
    prev = v

neg_months = [m for m, ret in monthly_ret if ret < 0]
# max consecutive negative months
max_streak = cur = 0
streak_period = []
best_period = []
for m, ret in monthly_ret:
    if ret < 0:
        cur += 1
        streak_period.append(m)
        if cur > max_streak:
            max_streak = cur
            best_period = list(streak_period)
    else:
        cur = 0
        streak_period = []

print("=== 月度收益 (%) ===")
for m, ret in monthly_ret:
    flag = '  <-- 负' if ret < 0 else ''
    print(f"  {m}: {ret:+.2f}%{flag}")
print(f"\n总月数: {len(monthly_ret)}, 亏损月数: {len(neg_months)}")
print(f"最大连续亏损月数: {max_streak}  期间: {best_period}")

# ---- 2. 最大回撤 + 修复天数 ----
peak = vals[0]
peak_i = 0
max_dd = 0.0
trough_i = 0
mdd_peak_i = 0
for i, v in enumerate(vals):
    if v > peak:
        peak = v
        peak_i = i
    dd = v / peak - 1
    if dd < max_dd:
        max_dd = dd
        trough_i = i
        mdd_peak_i = peak_i

# recovery: first day after trough where equity >= peak value at mdd_peak_i
peak_val = vals[mdd_peak_i]
recovery_i = None
for i in range(trough_i, len(vals)):
    if vals[i] >= peak_val:
        recovery_i = i
        break

print(f"\n=== 最大回撤 ===")
print(f"最大回撤: {max_dd*100:.2f}%")
print(f"前高日: {dates[mdd_peak_i].date()} (净值 {peak_val:,.0f})")
print(f"谷底日: {dates[trough_i].date()} (净值 {vals[trough_i]:,.0f})")
dd_days = (dates[trough_i] - dates[mdd_peak_i]).days
print(f"回撤下跌历时: {dd_days} 自然日 ({trough_i - mdd_peak_i} 交易日)")
if recovery_i is not None:
    rec_days = (dates[recovery_i] - dates[trough_i]).days
    total_days = (dates[recovery_i] - dates[mdd_peak_i]).days
    print(f"修复日: {dates[recovery_i].date()} (净值 {vals[recovery_i]:,.0f})")
    print(f"回撤修复天数(谷底->回到前高): {rec_days} 自然日 ({recovery_i - trough_i} 交易日)")
    print(f"完整水下时长(前高->再创前高): {total_days} 自然日 ({recovery_i - mdd_peak_i} 交易日)")
else:
    end_days = (dates[-1] - dates[trough_i]).days
    print(f"截至回测结束({dates[-1].date()})仍未回到前高, 已历时 {end_days} 自然日")
    print(f"期末净值 {vals[-1]:,.0f} vs 前高 {peak_val:,.0f}, 距前高还差 {(peak_val/vals[-1]-1)*100:.2f}%")

c.close()
