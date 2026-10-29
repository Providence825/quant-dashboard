"""持仓诊断模块 —— 为慧投盾参赛版提供四维 AI 诊断能力

四大诊断维度:
1. 持仓健康度诊断 — 分析单只股票的持仓时长、成本价 vs 当前价、行业景气度
2. 风险预警 — 结合板块、情绪、市场制度给出风险提示
3. 持仓建议 — 是否该止盈、加仓、减仓,给出理由
4. 组合优化 — 分析持仓结构是否集中、是否需要再平衡

依赖:
- DeepSeek API (通过 llm.stream_deepseek)
- 市场数据 (data.fetcher)
- 数据库 (db)
"""

from datetime import datetime, timedelta
from . import llm
from .data import fetcher
from .db import get_db


HEALTH_SYSTEM_PROMPT = """你是「慧投盾」的持仓健康度诊断专家。

用户提交了一只持仓股票的完整数据,你的任务是像医生体检一样给出健康度评估。

输出格式(严格JSON):
{
  "health_score": 85,  // 健康度评分 0-100
  "holding_days_comment": "持有时长点评...",
  "cost_vs_price_comment": "成本价与现价对比分析...",
  "sector_momentum_comment": "所在板块景气度分析...",
  "overall_summary": "综合健康度总结(100字内)",
  "alerts": ["预警1", "预警2"]  // 如果有异常,列出关键风险点
}

评分标准:
- 90-100: 优秀,持仓状态健康,浮盈稳定,板块向好
- 70-89: 良好,整体稳健,但有小风险需关注
- 50-69: 中等,存在一定风险或浮亏,需谨慎
- 30-49: 较差,浮亏较大或板块转弱,建议重点关注
- 0-29: 危险,严重浮亏或板块崩盘,建议止损

语气要求:
- 客观中立,不制造焦虑也不盲目乐观
- 术语要附带人话解释
- 不使用"必涨/稳赚/赶紧清仓"等指令式表述
- 这是模拟盘教学系统,不构成真实投资建议"""


RISK_SYSTEM_PROMPT = """你是「慧投盾」的风险预警专家。

基于用户的持仓组合数据和当前市场环境,给出风险预警分析。

输出格式(严格JSON):
{
  "risk_level": "中等",  // 低/中等/高/极高
  "sector_risk": "板块集中度风险分析...",
  "sentiment_risk": "市场情绪风险分析...",
  "regime_risk": "市场制度/趋势风险分析...",
  "specific_warnings": ["具体预警1", "具体预警2"],
  "suggestions": ["建议1", "建议2"]
}

风险等级判断标准:
- 低: 分散持仓,市场平稳,无明显风险信号
- 中等: 部分集中或市场波动加大,需适度关注
- 高: 高度集中或市场转弱,建议减仓或对冲
- 极高: 严重集中+市场恐慌,建议大幅降低仓位

语气要求:
- 专业克制,基于数据而非情绪
- 给出可操作的建议,不只是吓唬
- 避免"马上清仓/立刻止损"等绝对化表述"""


ACTION_SYSTEM_PROMPT = """你是「慧投盾」的持仓操作建议专家。

基于单只股票的持仓数据和技术面,给出操作建议。

输出格式(严格JSON):
{
  "action": "持有观察",  // 止盈/加仓/减仓/持有观察/止损
  "confidence": 75,  // 建议的置信度 0-100
  "reason": "给出此建议的核心理由(150字内)",
  "target_price": 12.50,  // 建议的目标价(止盈/止损位),可为null
  "timeline": "1-2周",  // 建议的观察周期
  "risk_reminder": "风险提示(50字内)"
}

操作类型说明:
- 止盈: 已达预期收益,建议锁定利润
- 加仓: 回调到位且趋势仍在,可考虑加码
- 减仓: 短期涨幅过大或出现滞涨,建议减持部分
- 持有观察: 当前状态正常,无需调整
- 止损: 破位或基本面恶化,建议离场

语气要求:
- 给建议而非命令,尊重用户自主决策
- 理由要具体可验证,不能只说"技术面走弱"
- 必须包含风险提示,这是教学系统"""


PORTFOLIO_SYSTEM_PROMPT = """你是「慧投盾」的投资组合优化专家。

基于用户的整体持仓结构,给出再平衡和优化建议。

输出格式(严格JSON):
{
  "concentration_score": 65,  // 集中度评分 0-100,越低越集中
  "diversification_comment": "分散化程度分析...",
  "rebalance_needed": true,  // 是否需要再平衡
  "rebalance_actions": [
    {"code": "600519", "action": "减持", "reason": "占比过高"},
    {"sector": "新能源", "action": "增配", "reason": "低配且景气上行"}
  ],
  "risk_concentration": ["集中度风险点1", "集中度风险点2"],
  "optimization_summary": "组合优化总结(200字内)"
}

集中度评分标准:
- 90-100: 极度分散,单只不超5%,多板块
- 70-89: 分散良好,风险可控
- 50-69: 中等集中,部分持仓偏重
- 30-49: 高度集中,少数个股或板块占比过大
- 0-29: 极度集中,风险极高

语气要求:
- 基于现代投资组合理论(MPT)给出专业建议
- 考虑相关性、波动率、夏普比率等指标
- 不只说"要分散",要给出具体的优化方向"""


def diagnose_single_holding(holding_data: dict, market_data: dict) -> dict:
    """诊断单只持仓的健康度

    Args:
        holding_data: {
            'code': '600519',
            'name': '贵州茅台',
            'cost': 1650.00,
            'shares': 100,
            'buy_date': '2026-08-15',
            'current_price': 1720.00,
            'sector': '白酒'
        }
        market_data: {
            'regime': 'RISK_ON',
            'sentiment': 0.65,
            'sector_momentum': {'白酒': 0.12}
        }

    Returns:
        健康度诊断结果 dict
    """
    code = holding_data['code']
    cost = holding_data['cost']
    current_price = holding_data.get('current_price')
    buy_date = holding_data.get('buy_date')
    sector = holding_data.get('sector', '未知')

    # 计算持有天数
    holding_days = 0
    if buy_date:
        try:
            buy_dt = datetime.strptime(buy_date, '%Y-%m-%d')
            holding_days = (datetime.now() - buy_dt).days
        except ValueError as e:
            print(f"[WARN] 日期格式错误 {buy_date}: {e}")

    # 计算盈亏
    pnl_pct = ((current_price - cost) / cost * 100) if current_price and cost else 0

    # 获取板块动量
    sector_momentum = market_data.get('sector_momentum', {}).get(sector, 0)

    # 构建 prompt
    prompt = f"""持仓数据:
股票: {holding_data.get('name', '')}({code})
成本价: {cost:.2f}
当前价: {current_price:.2f}
浮动盈亏: {pnl_pct:+.2f}%
持有天数: {holding_days}天
所在板块: {sector}
板块近期动量: {sector_momentum:+.2f}%

市场环境:
市场制度: {market_data.get('regime', 'UNKNOWN')}
市场情绪: {market_data.get('sentiment', 0.5):.2f}

请给出健康度诊断。"""

    # 调用 DeepSeek
    result_text = ''
    for chunk in llm.stream_deepseek(prompt, HEALTH_SYSTEM_PROMPT, temperature=0.5, max_tokens=800):
        result_text += chunk

    # 解析 JSON
    import json
    result_text = result_text.strip()
    if '```json' in result_text:
        result_text = result_text.split('```json')[1].split('```')[0].strip()
    elif '```' in result_text:
        result_text = result_text.split('```')[1].split('```')[0].strip()

    try:
        diagnosis = json.loads(result_text)
        diagnosis['code'] = code
        diagnosis['name'] = holding_data.get('name', code)
        return diagnosis
    except json.JSONDecodeError:
        # 降级返回
        return {
            'code': code,
            'name': holding_data.get('name', code),
            'health_score': 60,
            'overall_summary': 'AI 分析异常,请稍后重试',
            'alerts': []
        }


def diagnose_portfolio_risk(holdings: list, market_data: dict) -> dict:
    """诊断整体组合的风险预警

    Args:
        holdings: 持仓列表
        market_data: 市场数据

    Returns:
        风险预警结果 dict
    """
    # 统计板块分布
    sector_dist = {}
    total_value = 0
    for h in holdings:
        sector = h.get('sector', '未知')
        value = h.get('current_price', 0) * h.get('shares', 0)
        sector_dist[sector] = sector_dist.get(sector, 0) + value
        total_value += value

    sector_pcts = {k: v/total_value*100 for k, v in sector_dist.items()} if total_value > 0 else {}

    # 构建 prompt
    prompt = f"""持仓组合数据:
持仓数量: {len(holdings)}只
总市值: {total_value:.0f}元

板块分布:
{chr(10).join(f'- {sector}: {pct:.1f}%' for sector, pct in sorted(sector_pcts.items(), key=lambda x: -x[1]))}

市场环境:
市场制度: {market_data.get('regime', 'UNKNOWN')}
市场情绪: {market_data.get('sentiment', 0.5):.2f}
沪深300涨跌: {market_data.get('index_change', 0):+.2f}%

请给出风险预警分析。"""

    # 调用 DeepSeek
    result_text = ''
    for chunk in llm.stream_deepseek(prompt, RISK_SYSTEM_PROMPT, temperature=0.5, max_tokens=1000):
        result_text += chunk

    # 解析 JSON
    import json
    result_text = result_text.strip()
    if '```json' in result_text:
        result_text = result_text.split('```json')[1].split('```')[0].strip()
    elif '```' in result_text:
        result_text = result_text.split('```')[1].split('```')[0].strip()

    try:
        return json.loads(result_text)
    except json.JSONDecodeError:
        return {
            'risk_level': '中等',
            'specific_warnings': ['AI 分析异常,请稍后重试'],
            'suggestions': []
        }


def suggest_action(holding_data: dict, technical_data: dict) -> dict:
    """给出单只持仓的操作建议

    Args:
        holding_data: 持仓数据
        technical_data: 技术指标数据 (MA, RSI, 波动率等)

    Returns:
        操作建议结果 dict
    """
    code = holding_data['code']
    cost = holding_data['cost']
    current_price = holding_data.get('current_price')
    pnl_pct = ((current_price - cost) / cost * 100) if current_price and cost else 0

    # 构建 prompt
    prompt = f"""持仓数据:
股票: {holding_data.get('name', '')}({code})
成本价: {cost:.2f}
当前价: {current_price:.2f}
浮动盈亏: {pnl_pct:+.2f}%

技术指标:
MA5: {technical_data.get('ma5', 0):.2f}
MA20: {technical_data.get('ma20', 0):.2f}
MA60: {technical_data.get('ma60', 0):.2f}
RSI(14): {technical_data.get('rsi', 50):.0f}
年化波动率: {technical_data.get('volatility', 0):.1f}%
距60日高点回撤: {technical_data.get('drawdown', 0):.1f}%

请给出操作建议。"""

    # 调用 DeepSeek
    result_text = ''
    for chunk in llm.stream_deepseek(prompt, ACTION_SYSTEM_PROMPT, temperature=0.6, max_tokens=600):
        result_text += chunk

    # 解析 JSON
    import json
    result_text = result_text.strip()
    if '```json' in result_text:
        result_text = result_text.split('```json')[1].split('```')[0].strip()
    elif '```' in result_text:
        result_text = result_text.split('```')[1].split('```')[0].strip()

    try:
        action = json.loads(result_text)
        action['code'] = code
        action['name'] = holding_data.get('name', code)
        return action
    except json.JSONDecodeError:
        return {
            'code': code,
            'name': holding_data.get('name', code),
            'action': '持有观察',
            'confidence': 50,
            'reason': 'AI 分析异常,请稍后重试',
            'risk_reminder': '请人工判断'
        }


def optimize_portfolio(holdings: list, market_data: dict) -> dict:
    """给出投资组合优化建议

    Args:
        holdings: 持仓列表
        market_data: 市场数据

    Returns:
        组合优化建议 dict
    """
    # 计算持仓权重
    total_value = sum(h.get('current_price', 0) * h.get('shares', 0) for h in holdings)
    holdings_with_weight = []
    for h in holdings:
        value = h.get('current_price', 0) * h.get('shares', 0)
        weight = value / total_value * 100 if total_value > 0 else 0
        holdings_with_weight.append({
            'code': h['code'],
            'name': h.get('name', h['code']),
            'sector': h.get('sector', '未知'),
            'weight': weight,
            'pnl_pct': ((h.get('current_price', 0) - h['cost']) / h['cost'] * 100) if h.get('cost') else 0
        })

    # 构建 prompt
    holdings_str = '\n'.join(
        f"- {h['name']}({h['code']}): {h['weight']:.1f}%, {h['sector']}, 浮盈{h['pnl_pct']:+.2f}%"
        for h in sorted(holdings_with_weight, key=lambda x: -x['weight'])
    )

    prompt = f"""持仓组合:
{holdings_str}

市场环境:
市场制度: {market_data.get('regime', 'UNKNOWN')}
市场情绪: {market_data.get('sentiment', 0.5):.2f}

请给出组合优化建议。"""

    # 调用 DeepSeek
    result_text = ''
    for chunk in llm.stream_deepseek(prompt, PORTFOLIO_SYSTEM_PROMPT, temperature=0.6, max_tokens=1200):
        result_text += chunk

    # 解析 JSON
    import json
    result_text = result_text.strip()
    if '```json' in result_text:
        result_text = result_text.split('```json')[1].split('```')[0].strip()
    elif '```' in result_text:
        result_text = result_text.split('```')[1].split('```')[0].strip()

    try:
        return json.loads(result_text)
    except json.JSONDecodeError:
        return {
            'concentration_score': 60,
            'rebalance_needed': False,
            'rebalance_actions': [],
            'optimization_summary': 'AI 分析异常,请稍后重试'
        }


def get_comprehensive_diagnosis(holdings: list) -> dict:
    """获取持仓的全方位诊断报告

    Args:
        holdings: 持仓列表,每项包含 code, name, cost, shares, buy_date

    Returns:
        {
            'individual_health': [...],  // 每只股票的健康度诊断
            'risk_warning': {...},       // 整体风险预警
            'action_suggestions': [...], // 每只股票的操作建议
            'portfolio_optimization': {...}  // 组合优化建议
        }
    """
    if not holdings:
        return {
            'error': '暂无持仓数据',
            'individual_health': [],
            'risk_warning': {},
            'action_suggestions': [],
            'portfolio_optimization': {}
        }

    # 获取市场数据
    from .trading.market_regime import detect_regime
    from .trading.sentiment import get_current_sentiment

    regime = detect_regime()
    sentiment_data = get_current_sentiment()
    sentiment = sentiment_data.get('score', 0.5) if sentiment_data else 0.5

    # 获取沪深300涨跌
    try:
        hs300_data = fetcher.get_latest_price('000300')
        index_change = hs300_data.get('change_pct', 0) if hs300_data else 0
    except Exception as e:
        print(f"[WARN] 无法获取沪深300数据: {e}")
        index_change = 0

    # 获取板块动量 (简化版)
    sector_momentum = {}

    market_data = {
        'regime': regime,
        'sentiment': sentiment,
        'index_change': index_change,
        'sector_momentum': sector_momentum
    }

    # 为每只股票补充当前价格和技术指标
    db = get_db()
    enriched_holdings = []
    for h in holdings:
        code = h['code']
        try:
            # 获取最新价格
            latest = fetcher.get_latest_price(code)
            current_price = latest.get('close') if latest else h.get('cost', 0)

            # 获取技术指标
            rows = db.execute("""
                SELECT close, high, low FROM stock_kline_daily
                WHERE code = ? ORDER BY date DESC LIMIT 60
            """, (code,)).fetchall()

            if rows:
                closes = [r['close'] for r in rows]
                ma5 = sum(closes[:5]) / 5 if len(closes) >= 5 else closes[0]
                ma20 = sum(closes[:20]) / 20 if len(closes) >= 20 else closes[0]
                ma60 = sum(closes[:60]) / 60 if len(closes) >= 60 else closes[0]

                # 简化 RSI 计算
                rsi = 50.0  # 默认中性

                # 波动率
                import numpy as np
                returns = np.diff(closes) / closes[:-1] if len(closes) > 1 else [0]
                volatility = np.std(returns) * np.sqrt(252) * 100 if len(returns) > 0 else 0

                # 回撤
                highs = [r['high'] for r in rows]
                max_high = max(highs) if highs else current_price
                drawdown = (current_price - max_high) / max_high * 100
            else:
                ma5 = ma20 = ma60 = current_price
                rsi = 50.0
                volatility = 0
                drawdown = 0

            enriched_holdings.append({
                **h,
                'current_price': current_price,
                'technical': {
                    'ma5': ma5,
                    'ma20': ma20,
                    'ma60': ma60,
                    'rsi': rsi,
                    'volatility': volatility,
                    'drawdown': drawdown
                }
            })
        except Exception as e:
            import logging
            logging.warning(f"无法获取 {code} 数据: {e}")
            enriched_holdings.append({
                **h,
                'current_price': h.get('cost', 0),
                'technical': {'ma5': 0, 'ma20': 0, 'ma60': 0, 'rsi': 50, 'volatility': 0, 'drawdown': 0}
            })
    db.close()

    # 执行四维诊断
    individual_health = []
    action_suggestions = []

    for h in enriched_holdings:
        # 1. 健康度诊断
        health = diagnose_single_holding(h, market_data)
        individual_health.append(health)

        # 3. 操作建议
        action = suggest_action(h, h['technical'])
        action_suggestions.append(action)

    # 2. 风险预警
    risk_warning = diagnose_portfolio_risk(enriched_holdings, market_data)

    # 4. 组合优化
    portfolio_optimization = optimize_portfolio(enriched_holdings, market_data)

    return {
        'individual_health': individual_health,
        'risk_warning': risk_warning,
        'action_suggestions': action_suggestions,
        'portfolio_optimization': portfolio_optimization,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
