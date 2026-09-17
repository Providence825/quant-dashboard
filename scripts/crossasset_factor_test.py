#!/usr/bin/env python3
"""
Cross-asset factor test: Does overnight US return predict next-day A-share concept return?

Test hypothesis: US stocks in concept X up overnight → A-share stocks in concept X up next day.
No look-ahead bias: US close (04:00 Beijing) is known before A-share opens (09:30 Beijing).

Run: python scripts/crossasset_factor_test.py

Metrics:
- IC (Pearson corr between US signal and A-share next-day return across 8 concepts per day)
- ICIR = mean(IC) / std(IC)  -- > 0.5 is meaningful
- IS/OOS: first 60% dates = in-sample, last 40% = out-of-sample
"""

import sys, os, time, math, statistics
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

# ── US stock → concept mapping (from crossasset.py US_POOL) ─────────────
# symbol: Sina US K-line symbol (no gb_ prefix)
US_CONCEPT_MAP = {
    'nvda':  ['AI算力·光模块CPO', 'PCB', '服务器·算力', '半导体·芯片·设备'],
    'amd':   ['半导体·芯片·设备', '服务器·算力'],
    'tsm':   ['半导体·芯片·设备'],
    'avgo':  ['AI算力·光模块CPO', '半导体·芯片·设备'],
    'mu':    ['半导体·芯片·设备'],
    'intc':  ['半导体·芯片·设备', '服务器·算力'],
    'qcom':  ['半导体·芯片·设备', '果链·消费电子'],
    'asml':  ['半导体·芯片·设备'],
    'arm':   ['半导体·芯片·设备'],
    'mrvl':  ['AI算力·光模块CPO', '半导体·芯片·设备'],
    'smci':  ['服务器·算力'],
    'amat':  ['半导体·芯片·设备'],
    'lrcx':  ['半导体·芯片·设备'],
    'msft':  ['软件·AI应用', '服务器·算力'],
    'googl': ['软件·AI应用'],
    'meta':  ['软件·AI应用'],
    'aapl':  ['果链·消费电子'],
    'amzn':  ['服务器·算力'],
    'pltr':  ['软件·AI应用'],
    'orcl':  ['软件·AI应用', '服务器·算力'],
    'crm':   ['软件·AI应用'],
    'adbe':  ['软件·AI应用'],
    'tsla':  ['新能源车·锂电池', '人形机器人'],
    'nio':   ['新能源车·锂电池'],
    'rivn':  ['新能源车·锂电池'],
}

CONCEPT_STOCKS = {
    'AI算力·光模块CPO': ['300308', '300502', '002281', '300394'],
    'PCB':              ['002463', '002916', '600183', '002938'],
    '服务器·算力':      ['601138', '000977', '603019', '000938'],
    '半导体·芯片·设备': ['688981', '002371', '688012', '603986', '688008', '688396', '688521', '688766', '300661', '603501'],
    '果链·消费电子':    ['002475', '002241', '300433', '002456'],
    '新能源车·锂电池':  ['300750', '002594', '601689', '002050', '002812', '300014', '002460'],
    '人形机器人':       ['002472', '002527', '300124', '688017'],
    '软件·AI应用':      ['688111', '002230', '300496'],
}
CONCEPTS = list(CONCEPT_STOCKS.keys())

# ── Data fetch ───────────────────────────────────────────────────────────

def _prefix(code):
    return 'sh' if code.startswith('6') else 'sz'

def fetch_ashare_kline(code, days=1000):
    url = 'https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData'
    try:
        r = requests.get(url, params={'symbol': f'{_prefix(code)}{code}', 'scale': 240, 'datalen': days}, timeout=10)
        data = r.json()
        return {k['day'][:10]: float(k['close']) for k in data if k.get('day') and k.get('close')}
    except Exception as e:
        print(f'  A-share {code} error: {e}')
        return {}

US_KLINE_URL = 'https://stock.finance.sina.com.cn/usstock/api/json_v2.php/US_MinKService.getDailyK'

def fetch_us_kline(sym):
    try:
        r = requests.get(US_KLINE_URL, params={'symbol': sym}, timeout=15)
        data = r.json()
        return {k['d'][:10]: float(k['c']) for k in data if k.get('d') and k.get('c')}
    except Exception as e:
        print(f'  US {sym} error: {e}')
        return {}

def daily_returns(price_dict):
    """{date: close} → {date: pct_chg}"""
    dates = sorted(price_dict)
    ret = {}
    for i in range(1, len(dates)):
        prev, cur = price_dict[dates[i-1]], price_dict[dates[i]]
        if prev > 0:
            ret[dates[i]] = (cur - prev) / prev * 100
    return ret

# ── IC calculation ───────────────────────────────────────────────────────

def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs)/n, sum(ys)/n
    num = sum((x-mx)*(y-my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x-mx)**2 for x in xs))
    dy = math.sqrt(sum((y-my)**2 for y in ys))
    if dx < 1e-9 or dy < 1e-9:
        return None
    return num / (dx * dy)

# ── Main ─────────────────────────────────────────────────────────────────

def main():
    print('=== Cross-asset factor test: US overnight → A-share concept next-day ===\n')

    # 1. Fetch A-share prices
    print(f'Fetching A-share K-line for {sum(len(v) for v in CONCEPT_STOCKS.values())} stocks...')
    ashare_prices = {}  # code -> {date: close}
    for concept, codes in CONCEPT_STOCKS.items():
        for code in codes:
            if code not in ashare_prices:
                ashare_prices[code] = fetch_ashare_kline(code)
                time.sleep(0.15)
    print(f'  Got data for {sum(1 for v in ashare_prices.values() if v)} stocks')

    # 2. Fetch US prices
    us_syms = list(US_CONCEPT_MAP.keys())
    print(f'\nFetching US K-line for {len(us_syms)} stocks...')
    us_prices = {}  # sym -> {date: close}
    for sym in us_syms:
        us_prices[sym] = fetch_us_kline(sym)
        time.sleep(0.2)
    print(f'  Got data for {sum(1 for v in us_prices.values() if v)} stocks')

    # 3. Build returns
    ashare_ret = {code: daily_returns(p) for code, p in ashare_prices.items()}
    us_ret = {sym: daily_returns(p) for sym, p in us_prices.items()}

    # Build US trading date set
    us_dates_set = set()
    for ret in us_ret.values():
        us_dates_set.update(ret.keys())
    us_dates_sorted = sorted(us_dates_set)

    # Build A-share trading dates from most common stock
    pivot = max(ashare_ret, key=lambda c: len(ashare_ret[c]))
    ashare_dates = sorted(ashare_ret[pivot].keys())

    # 4. Align and compute concept signals/responses
    def last_us_date(adate):
        # Last US trading day strictly before adate
        idx = us_dates_sorted
        lo, hi = 0, len(idx) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if idx[mid] < adate:
                lo = mid
            else:
                hi = mid - 1
        if idx[lo] < adate:
            return idx[lo]
        return None

    records = []  # list of {date, signals: {concept: float}, responses: {concept: float}}

    for adate in ashare_dates:
        t_us = last_us_date(adate)
        if t_us is None:
            continue

        # US concept signals: mean return of mapped US stocks on t_us
        signals = {}
        for concept in CONCEPTS:
            contrib = [us_ret[sym][t_us] for sym, concepts in US_CONCEPT_MAP.items()
                       if concept in concepts and sym in us_ret and t_us in us_ret[sym]]
            if contrib:
                signals[concept] = sum(contrib) / len(contrib)

        # A-share concept responses: mean return on adate
        responses = {}
        for concept, codes in CONCEPT_STOCKS.items():
            vals = [ashare_ret[c][adate] for c in codes if c in ashare_ret and adate in ashare_ret[c]]
            if vals:
                responses[concept] = sum(vals) / len(vals)

        # Only keep days where all 8 concepts have both signal and response
        if len(signals) == len(CONCEPTS) and len(responses) == len(CONCEPTS):
            records.append({'date': adate, 'signals': signals, 'responses': responses})

    print(f'\nAligned trading days: {len(records)} (A-share days with full US signal)')
    if len(records) < 40:
        print('Not enough data for meaningful test.')
        return

    # 5. Per-day IC
    ics = []
    for rec in records:
        xs = [rec['signals'][c] for c in CONCEPTS]
        ys = [rec['responses'][c] for c in CONCEPTS]
        ic = pearson(xs, ys)
        if ic is not None:
            ics.append((rec['date'], ic))

    if not ics:
        print('No IC values computed.')
        return

    # 6. IS / OOS split (60/40)
    split = int(len(ics) * 0.6)
    is_ics = [ic for _, ic in ics[:split]]
    oos_ics = [ic for _, ic in ics[split:]]

    def stats(vals, label):
        mn = statistics.mean(vals)
        sd = statistics.stdev(vals) if len(vals) > 1 else 0
        icir = mn / sd if sd > 0 else 0
        pos_pct = sum(1 for v in vals if v > 0) / len(vals) * 100
        t_stat = mn / (sd / math.sqrt(len(vals))) if sd > 0 else 0
        print(f'\n{label} (n={len(vals)}, {ics[0][0] if label.startswith("IS") else ics[split][0]} ~ {ics[split-1][0] if label.startswith("IS") else ics[-1][0]}):')
        print(f'  Mean IC : {mn:+.4f}  (t={t_stat:+.2f})')
        print(f'  Std IC  : {sd:.4f}')
        print(f'  ICIR    : {icir:+.3f}')
        print(f'  IC > 0  : {pos_pct:.1f}%')

    print('\n' + '='*60)
    print('RESULTS')
    print('='*60)
    stats(is_ics, 'IS  (in-sample,  60%)')
    stats(oos_ics, 'OOS (out-of-sample, 40%)')

    all_ic_vals = [ic for _, ic in ics]
    mn = statistics.mean(all_ic_vals)
    sd = statistics.stdev(all_ic_vals) if len(all_ic_vals) > 1 else 0
    icir = mn / sd if sd > 0 else 0
    print(f'\nOverall: Mean IC={mn:+.4f}, ICIR={icir:+.3f}, n={len(all_ic_vals)}')

    # 7. Concept breakdown (OOS)
    print('\n--- OOS concept-level mean return when US signal > 0 vs <= 0 ---')
    long_ret, short_ret = {c: [] for c in CONCEPTS}, {c: [] for c in CONCEPTS}
    for rec in [records[i] for i in range(split, len(records))]:
        for c in CONCEPTS:
            if c in rec['signals'] and c in rec['responses']:
                if rec['signals'][c] > 0:
                    long_ret[c].append(rec['responses'][c])
                else:
                    short_ret[c].append(rec['responses'][c])
    for c in CONCEPTS:
        lg = statistics.mean(long_ret[c]) if long_ret[c] else float('nan')
        sh = statistics.mean(short_ret[c]) if short_ret[c] else float('nan')
        diff = lg - sh if not (math.isnan(lg) or math.isnan(sh)) else float('nan')
        print(f'  {c[:18]:18s}  signal>0 avg={lg:+.3f}%  signal<=0 avg={sh:+.3f}%  diff={diff:+.3f}%')

    print('\n' + '='*60)
    verdict = 'PASS (IC>0 IS & OOS)' if statistics.mean(is_ics) > 0 and statistics.mean(oos_ics) > 0 else \
              'FAIL (OOS IC<=0)' if statistics.mean(oos_ics) <= 0 else \
              'MARGINAL (IS>0 but check OOS carefully)'
    print(f'VERDICT: {verdict}')
    if abs(icir) < 0.3:
        print('Note: ICIR <0.3, signal too weak to trade reliably.')
    print('='*60)


if __name__ == '__main__':
    main()
