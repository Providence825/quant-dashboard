"""
补充情绪历史数据 - 为Demo演示生成近45日合理情绪走势

策略：基于真实市场涨跌比推算历史情绪，模拟市场情绪周期特征
- 从当前真实涨跌比往前推，加入合理波动
- 保持情绪周期特征（点火→发酵→一致→加速→退潮→混沌）
- 确保至少45日数据，让sparkline可见
"""

from datetime import datetime, timedelta
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from server.db import get_db
from server.trading.sentiment import _classify_phase, detect_lai_qu_cycle
from server.trading.market_regime import detect_regime
import json
import random


def generate_sentiment_history(days=45):
    """生成合理的情绪历史数据"""
    db = get_db()

    # 获取当前真实市场状态
    try:
        regime = detect_regime()
        current_breadth = regime.get('breadth', 50)
        current_adx = regime.get('adx', 20)
        current_ret = regime.get('ret_20d', 0)
    except:
        current_breadth = 50
        current_adx = 20
        current_ret = 0

    # 当前情绪评分（从涨跌比推算）
    current_score = round((current_breadth - 50) * 2, 1)

    print(f"当前市场状态: 涨跌比 {current_breadth:.1f}% -> 情绪评分 {current_score}")

    # 检查已有数据
    existing = db.execute(
        'SELECT date FROM daily_sentiment ORDER BY date DESC'
    ).fetchall()
    existing_dates = {row[0] for row in existing}

    # 生成情绪周期曲线（模拟真实市场情绪波动）
    # 使用正弦波 + 噪声 + 趋势项
    today = datetime.now()
    records = []

    for i in range(days - 1, -1, -1):
        date = (today - timedelta(days=i)).strftime('%Y-%m-%d')

        if date in existing_dates:
            continue  # 跳过已有数据

        # 情绪周期模型：
        # 1. 基础周期：30天一个完整周期（点火→加速→退潮）
        cycle_phase = (days - i) % 30 / 30  # 0~1

        # 2. 正弦波分量（-40~+40幅度）
        wave = 40 * (1 - abs(cycle_phase - 0.5) * 2)  # 中间高两头低

        # 3. 趋势项：逐渐向当前score靠拢
        trend_weight = i / days  # 越接近今天权重越大
        trend = current_score * (1 - trend_weight)

        # 4. 随机噪声 ±10
        noise = random.uniform(-10, 10)

        # 合成评分
        score = max(-100, min(100, wave + trend + noise))
        score = round(score, 1)

        # 映射到phase
        phase = _classify_phase(score)

        # 模拟lai_qu周期
        breadth_sim = 50 + score / 2  # 反推涨跌比
        cycle = detect_lai_qu_cycle(score, phase, breadth_sim, current_adx, 0)

        # 插入数据库
        db.execute(
            """INSERT OR REPLACE INTO daily_sentiment
               (date, sentiment_score, phase, contrarian_action, contrarian_strength,
                position_adjustment, stop_adjustment, bullish_hits, bearish_hits,
                source_count, details_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (date, score, phase,
             'neutral', 0, 0, 1.0,  # contrarian信号简化
             0, 0, 0,  # 舆情采样数设为0（标记为模拟数据）
             json.dumps({'generated': True, 'cycle': cycle['cycle']}, ensure_ascii=False))
        )

        records.append((date, score, phase, cycle['cycle_label']))

        if (days - i) % 10 == 0:
            print(f"生成 {date}: score={score:+.1f} phase={phase} cycle={cycle['cycle_label']}")

    db.commit()
    db.close()

    print(f"\n[OK] 补充完成，共生成 {len(records)} 条历史数据")
    if records:
        print(f"数据范围: {records[0][0]} 至 {records[-1][0]}")

    return len(records)


if __name__ == '__main__':
    count = generate_sentiment_history(45)
    print(f"\n执行完毕。现在DB中应有至少45日情绪数据，sparkline可显示。")
