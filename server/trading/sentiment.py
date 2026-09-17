"""
Sentiment analysis engine — quantifies market emotion and generates contrarian signals.

Key principles (股市反人性):
1. Extreme greed → nearing top → reduce positions / tighten stops
2. Extreme fear → nearing bottom → increase buying / loosen stops
3. Sentiment cycles lead price cycles by 1-3 days

Sentiment score: -100 (extreme fear/capitulation) to +100 (extreme euphoria/greed)

Cycle phases (情绪周期):
  Euphoria (80~100)  →  Complacency (40~80)  →  Denial (0~40)
  →  Panic (-40~0)  →  Capitulation (-80~-40)  →  Despair (-100~-80)
  →  Hope (-80~-40)  →  Optimism (-40~0)  →  Belief (0~40)  →  Thrill (40~80)
"""

import re
import os
import time
from datetime import datetime, timedelta
from ..db import get_db

# Cache for expensive detect_regime() call — refreshed every 120s
_regime_cache = None
_regime_cache_ts = 0
_REGIME_CACHE_TTL = 120


# ── Chinese sentiment keywords ────────────────────────────────────────

BULLISH_KEYWORDS = {
    '涨停': 3, '翻倍': 3, '起飞': 3, '暴涨': 3, '大牛': 3,
    '满仓': 2.5, '梭哈': 3, '抄底成功': 2.5, '赚翻了': 3, '主升浪': 3,
    '突破': 1.5, '利好': 1.5, '加仓': 2, 'all in': 3, '杠杆': 2,
    '牛股': 2.5, '躺赚': 3, '财富自由': 3, '跑步入场': 3, '闭眼买': 3,
    '稳赚': 2.5, '抢筹': 2, '涨停板': 2.5, '打板': 2, '龙头': 2,
    '大涨': 1.5, '稳步上涨': 1, '慢牛': 1.5, '长牛': 2,
    '底部确认': 2, '反转': 1.5, '放量突破': 2, '金叉': 1.5,
}

BEARISH_KEYWORDS = {
    '跌停': 3, '腰斩': 3, '崩盘': 3, '爆仓': 3, '归零': 3,
    '清仓': 2.5, '割肉': 2.5, '亏损': 2, '套路': 1.5, '收割': 2,
    '绝望': 3, '不玩了': 3, '退市': 3, '熔断': 3, '股灾': 3,
    '暴跌': 2.5, '血亏': 3, '亏麻了': 3, '销户': 3, '踩踏': 2.5,
    '大跌': 1.5, '破位': 2, '阴跌': 2, '出逃': 2, '套牢': 2,
    '止损': 1.5, '避险': 1.5, '黑天鹅': 2.5, '恐慌': 2.5,
    '雷了': 2, '踩雷': 2, 'ST': 2, '退市风险': 2.5,
}

# Phrases that indicate sentiment extremes (反向指标强度)
EXTREME_GREED_PHRASES = [
    (r'(全仓|满仓|梭哈).*(干|冲|买)', 4),
    (r'(赚翻|翻倍|十倍|暴富)', 3.5),
    (r'(跑步入场|闭眼买|无脑买)', 4),
    (r'(这次不一样|永久持有|死了都不卖)', 4),
    (r'(卖房炒股|借钱炒股|贷款炒股)', 5),
    (r'(悟道了|开窍了|终于懂了)', 3),
    (r'(财富自由|财务自由)', 3.5),
    (r'(打死也不卖|打死不卖)', 3.5),
]

EXTREME_FEAR_PHRASES = [
    (r'(销户|不玩了|退市吧)', 4),
    (r'(这辈子.*不.*炒股|永远.*不碰)', 3.5),
    (r'(亏麻了|血亏|倾家荡产)', 3.5),
    (r'(诈骗市场|赌场|收割机)', 3),
    (r'(再跌.*不活了|活不下去)', 5),
    (r'(为国接盘|救市|护盘)', 2.5),
    (r'(回到.*年前|跌回.*年前)', 2.5),
    (r'(绝望了|没救了|没希望)', 3.5),
]


def analyze_text_sentiment(texts):
    """
    Analyze sentiment from a list of text snippets.
    Returns score -100 to +100, and metadata.
    """
    if not texts:
        return 0, {'bullish_count': 0, 'bearish_count': 0, 'extreme_signals': []}

    total_bull = 0
    total_bear = 0
    bull_hits = 0
    bear_hits = 0
    extreme_signals = []

    for text in texts:
        text_lower = text.lower()

        # Count keyword hits
        for kw, weight in BULLISH_KEYWORDS.items():
            if kw in text:
                total_bull += weight
                bull_hits += 1

        for kw, weight in BEARISH_KEYWORDS.items():
            if kw in text:
                total_bear += weight
                bear_hits += 1

        # Check extreme phrases
        for pattern, weight in EXTREME_GREED_PHRASES:
            if re.search(pattern, text):
                extreme_signals.append({'direction': 'extreme_greed', 'weight': weight, 'match': text[:80]})
                total_bull += weight * 2

        for pattern, weight in EXTREME_FEAR_PHRASES:
            if re.search(pattern, text):
                extreme_signals.append({'direction': 'extreme_fear', 'weight': weight, 'match': text[:80]})
                total_bear += weight * 2

    # Normalize to -100~100
    total_signals = total_bull + total_bear
    if total_signals == 0:
        raw_score = 0
    else:
        raw_score = (total_bull - total_bear) / total_signals * 100

    # Scale: compress extreme values
    score = round(max(-100, min(100, raw_score)), 1)

    return score, {
        'bullish_hits': bull_hits,
        'bearish_hits': bear_hits,
        'bullish_score': round(total_bull, 2),
        'bearish_score': round(total_bear, 2),
        'extreme_signals': extreme_signals,
        'text_count': len(texts),
    }


def detect_sentiment_cycle(current_score, history):
    """
    Identify where we are in the sentiment cycle.
    Returns cycle phase and contrarian signal strength.
    """
    phase = _classify_phase(current_score)

    # Track momentum
    if history and len(history) >= 3:
        recent = [h['score'] for h in history[-3:]]
        momentum = recent[-1] - recent[0]  # 3-period change
    else:
        momentum = 0

    contrarian = _generate_contrarian_signal(current_score, phase, momentum, history)

    return {
        'phase': phase,
        'score': current_score,
        'momentum': round(momentum, 1),
        'contrarian_signal': contrarian,
    }


def _classify_phase(score):
    if score >= 80:
        return 'euphoria'       # 极度亢奋
    elif score >= 40:
        return 'greed'          # 贪婪
    elif score >= 10:
        return 'optimism'       # 乐观
    elif score >= -10:
        return 'neutral'        # 中性
    elif score >= -40:
        return 'caution'        # 谨慎
    elif score >= -80:
        return 'fear'           # 恐惧
    else:
        return 'capitulation'   # 投降式抛售


PHASE_LABELS = {
    'euphoria': '极度亢奋',
    'greed': '贪婪',
    'optimism': '乐观',
    'neutral': '中性',
    'caution': '谨慎',
    'fear': '恐惧',
    'capitulation': '投降式抛售',
}


def _generate_contrarian_signal(score, phase, momentum, history):
    """
    Generate contrarian trading signals based on sentiment extremes.

    Core logic (反人性):
    - Extreme greed → reduce risk, tighten stops, don't open new positions
    - Extreme fear → increase risk tolerance, look for bargains, widen stops
    - Rapid sentiment shift → potential reversal incoming
    """
    signal = {
        'action': 'neutral',
        'strength': 0,
        'reason': '',
        'position_adjustment': 0,  # -1.0 to +1.0 position adjustment
        'stop_adjustment': 0,       # multiplier on stop-loss distance
    }

    # Euphoria: strong contrarian SELL signal
    if phase == 'euphoria':
        signal['action'] = 'reduce'
        signal['strength'] = min(100, abs(score)) * 0.8
        signal['reason'] = '市场极度亢奋，散户一致看多，反人性减仓'
        signal['position_adjustment'] = -0.5  # Reduce positions by 50%
        signal['stop_adjustment'] = 0.6  # Tighten stops

        if momentum > 30:
            signal['reason'] += '；情绪加速赶顶，建议大幅减仓'
            signal['position_adjustment'] = -0.7

    # Greed: moderate contrarian signal
    elif phase == 'greed':
        signal['action'] = 'caution'
        signal['strength'] = abs(score) * 0.5
        signal['reason'] = '市场偏贪婪，控制仓位，收紧止损'
        signal['position_adjustment'] = -0.2
        signal['stop_adjustment'] = 0.8

        if momentum > 20:
            signal['reason'] += '；情绪持续升温，注意风险'
            signal['position_adjustment'] = -0.3

    # Fear: contrarian BUY signal
    elif phase == 'fear':
        signal['action'] = 'opportunity'
        signal['strength'] = abs(score) * 0.5
        signal['reason'] = '市场恐惧蔓延，反人性寻找低估机会'
        signal['position_adjustment'] = 0.15
        signal['stop_adjustment'] = 1.2  # Widen stops for volatility

        if momentum < -20:
            signal['reason'] += '；恐慌加速赶底，可分批建仓'
            signal['position_adjustment'] = 0.25

    # Capitulation: strong contrarian BUY signal
    elif phase == 'capitulation':
        signal['action'] = 'accumulate'
        signal['strength'] = min(100, abs(score)) * 0.8
        signal['reason'] = '散户投降式抛售，恐惧至极，反人性重仓买入'
        signal['position_adjustment'] = 0.4  # Increase positions
        signal['stop_adjustment'] = 1.5  # Wide stops for bottom volatility

    # Check for sentiment divergence (sentiment shifts rapidly)
    if history and len(history) >= 5:
        five_days_ago = history[-5]['score']
        if score - five_days_ago > 50:  # Rapid shift to greed
            signal['reason'] += '；情绪5日暴升>50点，警惕短期见顶'
            if signal['position_adjustment'] > 0:
                signal['position_adjustment'] *= 0.5
        elif five_days_ago - score > 50:  # Rapid shift to fear
            signal['reason'] += '；情绪5日暴跌>50点，关注超跌反弹'
            if signal['position_adjustment'] < 0:
                signal['position_adjustment'] *= 0.5

    return signal


def save_daily_sentiment(score, details, cycle_result, source_texts=None):
    """Save sentiment snapshot to DB."""
    db = get_db()
    today = datetime.now().strftime('%Y-%m-%d')

    import json
    try:
        db.execute(
            """INSERT OR REPLACE INTO daily_sentiment
               (date, sentiment_score, phase, contrarian_action, contrarian_strength,
                position_adjustment, stop_adjustment, bullish_hits, bearish_hits,
                source_count, details_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (today, score,
             cycle_result['phase'],
             cycle_result['contrarian_signal']['action'],
             cycle_result['contrarian_signal']['strength'],
             cycle_result['contrarian_signal']['position_adjustment'],
             cycle_result['contrarian_signal']['stop_adjustment'],
             details.get('bullish_hits', 0),
             details.get('bearish_hits', 0),
             details.get('text_count', 0),
             json.dumps(details, ensure_ascii=False))
        )
        db.commit()
    finally:
        db.close()


def get_sentiment_history(days=90):
    """Get historical sentiment data."""
    db = get_db()
    try:
        rows = db.execute(
            "SELECT * FROM daily_sentiment ORDER BY date DESC LIMIT ?", (days,)
        ).fetchall()
    finally:
        db.close()
    return [dict(r) for r in reversed(rows)]


# ── 来去由心 7-phase emotion cycle ────────────────────────────────────

LAI_QU_CYCLES = {
    'ignition':      {'label': '点火',   'order': 0, 'desc': '恐慌至极→反向看多，寻找底部机会'},
    'chaos':         {'label': '混沌',   'order': 1, 'desc': '方向不明→等待，不操作'},
    'fermentation':  {'label': '发酵',   'order': 2, 'desc': '趋势萌发→谨慎建仓'},
    'divergence':    {'label': '分歧',   'order': 3, 'desc': '多空分歧→精选标的，控制仓位'},
    'consensus':     {'label': '一致',   'order': 4, 'desc': '趋势确立→积极做多'},
    'acceleration':  {'label': '加速',   'order': 5, 'desc': '情绪加速→持仓待涨或准备退出'},
    'ebb':           {'label': '退潮',   'order': 6, 'desc': '动能衰减→减仓防守'},
}

LAI_QU_CYCLE_COLORS = {
    'ignition':      '#00e676',
    'chaos':         '#888',
    'fermentation':  '#4fc3f7',
    'divergence':    '#ffc107',
    'consensus':     '#ff6b35',
    'acceleration':  '#ff3d5a',
    'ebb':           '#e040fb',
}


def detect_lai_qu_cycle(sentiment_score=0, phase='neutral', breadth=50, adx=20, ret_20d=0):
    """
    Map sentiment score + market regime data to 来去由心's 7-phase cycle.

    点火:  score < -30, fear/capitulation, contrarian buy zone
    混沌:  abs(score) < 15, low ADX, no clear direction
    发酵:  score 10-30, ADX rising, breadth improving
    分歧:  score mixed, ADX > 20 but breadth near 50
    一致:  score 30-60, ADX > 25, bullish alignment
    加速:  score > 55, momentum surging, euphoria risk
    退潮:  score dropping fast or breadth collapsing

    Returns dict with cycle name, label, trading params.
    """
    cycle = 'chaos'
    details = []

    # Ignition: extreme fear → contrarian opportunity
    if sentiment_score < -30 or phase in ('fear', 'capitulation'):
        cycle = 'ignition'
        details.append('情绪冰点')
        if ret_20d < -5:
            details.append('超跌反弹预期')

    # Chaos: no clear signal
    elif abs(sentiment_score) < 15 and adx < 20:
        cycle = 'chaos'
        details.append('多空均衡')

    # Fermentation: early trend forming
    elif 10 <= sentiment_score <= 35 and adx >= 18 and breadth > 52:
        cycle = 'fermentation'
        details.append('趋势萌芽')
        if adx >= 22:
            details.append('ADX确认走强')

    # Divergence: trend exists but breadth mixed
    elif adx > 22 and 45 <= breadth <= 55:
        cycle = 'divergence'
        details.append('多空分歧加大')

    # Consensus: strong trend, confident
    elif 30 <= sentiment_score <= 65 and adx > 25 and breadth > 55:
        cycle = 'consensus'
        details.append('趋势确立')
        if ret_20d > 3:
            details.append('中期强势')

    # Acceleration: euphoria building
    elif sentiment_score > 55 or (phase == 'euphoria'):
        cycle = 'acceleration'
        details.append('情绪加速')
        if sentiment_score > 75:
            details.append('警惕见顶')

    # Ebb: momentum fading
    elif sentiment_score > 15 and breadth < 45:
        cycle = 'ebb'
        details.append('赚钱效应衰减')
    elif sentiment_score < -10 and breadth < 40:
        cycle = 'ebb'
        details.append('恐慌退潮')

    params = get_cycle_trading_params(cycle)
    params['cycle'] = cycle
    params['cycle_label'] = LAI_QU_CYCLES[cycle]['label']
    params['cycle_desc'] = LAI_QU_CYCLES[cycle]['desc']
    params['cycle_color'] = LAI_QU_CYCLE_COLORS[cycle]
    params['cycle_order'] = LAI_QU_CYCLES[cycle]['order']
    params['details'] = details

    return params


def get_cycle_trading_params(cycle):
    """Return position sizing, strategy preference, and stop params per cycle phase."""
    configs = {
        'ignition': {
            'should_trade': True,
            'max_position_pct': 0.45,
            'preferred_strategy': 'trend',
            'stop_multiplier': 1.4,
            'position_notes': '分批建仓，每次不超过1/3',
            'action_hint': '反人性买入，寻找超跌质优股',
        },
        'chaos': {
            'should_trade': False,
            'max_position_pct': 0.15,
            'preferred_strategy': None,
            'stop_multiplier': 1.0,
            'position_notes': '观望为主，不开新仓',
            'action_hint': '等待方向明确',
        },
        'fermentation': {
            'should_trade': True,
            'max_position_pct': 0.40,
            'preferred_strategy': 'trend',
            'stop_multiplier': 1.1,
            'position_notes': '试探性建仓，关注M60突破',
            'action_hint': '买点1·底部建仓 / 买点2·M60突破',
        },
        'divergence': {
            'should_trade': True,
            'max_position_pct': 0.50,
            'preferred_strategy': 'trend',
            'stop_multiplier': 1.0,
            'position_notes': '精选标的，控制单票仓位',
            'action_hint': '买点2·M60突破（精选）',
        },
        'consensus': {
            'should_trade': True,
            'max_position_pct': 0.85,
            'preferred_strategy': 'trend',
            'stop_multiplier': 0.9,
            'position_notes': '趋势确立，可重仓出击',
            'action_hint': '买点3·回踩重仓 / 板块最强前排',
        },
        'acceleration': {
            'should_trade': True,
            'max_position_pct': 0.70,
            'preferred_strategy': 'short_term',
            'stop_multiplier': 0.6,
            'position_notes': '加速期持仓为主，收紧止损',
            'action_hint': '持有 + 移动止盈，不开新仓',
        },
        'ebb': {
            'should_trade': False,
            'max_position_pct': 0.25,
            'preferred_strategy': None,
            'stop_multiplier': 0.7,
            'position_notes': '减仓防守，保护利润',
            'action_hint': '逐步止盈，等待下一轮点火',
        },
    }
    return configs.get(cycle, configs['chaos'])


def get_current_sentiment():
    """Get today's sentiment analysis with lai_qu cycle."""
    global _regime_cache, _regime_cache_ts

    today = datetime.now().strftime('%Y-%m-%d')
    db = get_db()
    try:
        row = db.execute(
            "SELECT * FROM daily_sentiment WHERE date=? ORDER BY id DESC LIMIT 1", (today,)
        ).fetchone()
    finally:
        db.close()

    if row:
        d = dict(row)
        d['phase_label'] = PHASE_LABELS.get(d['phase'], d['phase'])
        # Attach lai_qu cycle
        try:
            from .market_regime import detect_regime
            now = time.time()
            if _regime_cache is None or (now - _regime_cache_ts) > _REGIME_CACHE_TTL:
                _regime_cache = detect_regime()
                _regime_cache_ts = now
            regime = _regime_cache
            cycle = detect_lai_qu_cycle(
                d.get('sentiment_score', 0),
                d.get('phase', 'neutral'),
                regime.get('breadth', 50),
                regime.get('adx', 20),
                regime.get('ret_20d', 0),
            )
            d.update({f'lai_qu_{k}': v for k, v in cycle.items()})
        except Exception:
            d['lai_qu_cycle'] = 'chaos'
            d['lai_qu_cycle_label'] = '混沌'
        return d

    # No DB record today → compute live sentiment from market breadth
    try:
        from .market_regime import detect_regime
        now = time.time()
        if _regime_cache is None or (now - _regime_cache_ts) > _REGIME_CACHE_TTL:
            _regime_cache = detect_regime()
            _regime_cache_ts = now
        regime = _regime_cache
        breadth = regime.get('breadth', 50)
        ret_20d = regime.get('ret_20d', 0)

        # Derive sentiment from breadth + recent return
        # breadth 70+ → optimism/greed, breadth 30- → fear
        if breadth >= 70:
            score = 40 + (breadth - 70) * 1.5  # 40~85
        elif breadth >= 55:
            score = 10 + (breadth - 55) * 2    # 10~40
        elif breadth >= 45:
            score = -10 + (breadth - 45) * 2   # -10~10
        elif breadth >= 30:
            score = -40 + (breadth - 30) * 2   # -40~-10
        else:
            score = -80 + breadth               # -80~-50

        # Adjust by 20d return
        if ret_20d > 5:
            score += 10
        elif ret_20d < -5:
            score -= 10

        score = max(-100, min(100, score))
        phase = _classify_phase(score)

        cycle = detect_lai_qu_cycle(
            score, phase,
            regime.get('breadth', 50),
            regime.get('adx', 20),
            regime.get('ret_20d', 0),
        )

        return {
            'date': today,
            'sentiment_score': round(score, 1),
            'phase': phase,
            'phase_label': PHASE_LABELS.get(phase, phase),
            'contrarian_action': 'neutral',
            'contrarian_strength': 0,
            'position_adjustment': 0,
            'stop_adjustment': 1.0,
            'bullish_hits': 0,
            'bearish_hits': 0,
            'source_count': 0,
            **{f'lai_qu_{k}': v for k, v in cycle.items()},
        }
    except Exception:
        return {
            'date': today,
            'sentiment_score': 0,
            'phase': 'neutral',
            'phase_label': '中性',
            'contrarian_action': 'neutral',
            'contrarian_strength': 0,
            'position_adjustment': 0,
            'stop_adjustment': 1.0,
            'bullish_hits': 0,
            'bearish_hits': 0,
            'source_count': 0,
            'lai_qu_cycle': 'chaos',
            'lai_qu_cycle_label': '混沌',
            'lai_qu_should_trade': False,
        }


def run_sentiment_analysis(texts):
    """
    Full pipeline: analyze texts → detect cycle → generate contrarian signal → save.
    Returns analysis result dict.
    """
    score, details = analyze_text_sentiment(texts)
    history = get_sentiment_history(30)
    cycle = detect_sentiment_cycle(score, history)
    save_daily_sentiment(score, details, cycle, texts)

    return {
        'score': score,
        'phase': cycle['phase'],
        'phase_label': PHASE_LABELS.get(cycle['phase'], cycle['phase']),
        'momentum': cycle['momentum'],
        'contrarian': cycle['contrarian_signal'],
        'details': details,
    }
