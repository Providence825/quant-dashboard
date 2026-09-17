"""解释生成智能体 —— 接入 DeepSeek 大模型。

只在后端读取 API Key（环境变量 DEEPSEEK_API_KEY），绝不下发前端。
对外暴露两个能力：
  - build_prompt(stock, risk)  把个股量化信号 + 用户风险画像拼成 prompt
  - stream_explain(stock, risk) 生成器，逐块 yield DeepSeek 输出（SSE 透传）
调用失败时抛异常，由路由层转成 JSON 错误，前端静默回退本地模板。
"""
import os
import json
import requests

DEEPSEEK_URL = 'https://api.deepseek.com/chat/completions'


def _cfg():
    key = os.getenv('DEEPSEEK_API_KEY', '').strip()
    model = os.getenv('DEEPSEEK_MODEL', 'deepseek-chat').strip() or 'deepseek-chat'
    return key, model


def is_enabled():
    return bool(os.getenv('DEEPSEEK_API_KEY', '').strip())


SYSTEM_PROMPT = (
    "你是「慧投盾」的解释生成智能体，服务对象是第一次买股票的普通人（首投小白）。"
    "你的任务：把量化引擎给出的个股信号，用大白话讲清楚它为什么被选出、风险在哪、"
    "以及和用户风险承受力是否匹配。要求："
    "1) 全程用生活化比喻，不堆术语；出现 PE/ROE/MACD 等词要顺带一句人话解释。"
    "2) 结合用户的风险等级（C1保守~C5进取）给出「适不适合你」的判断。"
    "3) 客观中立，同时点明风险，绝不使用『必涨/稳赚/建议满仓买入』等诱导性表述。"
    "4) 这是模拟盘教学系统，不构成真实投资建议——结尾用一句自然的话提示风险。"
    "5) 全文 150~230 字，一段话讲完，语气像一位耐心的理财顾问。"
)

SYSTEM_PROMPT_HOLD = (
    "你是「慧投盾」的持仓体检智能体，服务对象是第一次买股票的普通人（首投小白）。"
    "用户报上一只他【已经买入并持有】的股票，含成本价、现价、浮动盈亏和技术信号。"
    "你的任务不是判断『要不要买』（他已经买了），而是像医生体检一样给这个持仓做诊断。要求："
    "1) 先点评当前浮盈/浮亏状态，语气平稳，不制造焦虑也不盲目乐观。"
    "2) 结合技术信号（趋势/均线/距高点回撤/波动率/RSI）说明这只票现在处于什么状态、"
    "健康还是有隐患；出现术语要顺带一句人话解释。"
    "3) 给出【持有纪律】层面的提醒：比如是否已偏离成本较多需注意止损、是否高位追高、"
    "该关注哪个信号；结合用户风险等级（C1保守~C5进取）说这个仓位对他重不重。"
    "4) 绝不使用『必涨/稳赚/赶紧加仓/马上清仓』等指令式诱导表述，只做体检式提示。"
    "5) 这是模拟盘教学系统，不构成真实投资建议——结尾用一句自然的话提示风险与独立判断。"
    "6) 全文 150~230 字，一段话讲完，语气像一位耐心、克制的理财顾问。"
)


def build_prompt(stock, risk, mode='pick'):
    stock = stock or {}
    risk = risk or {}
    name = stock.get('name') or stock.get('stock_name') or stock.get('code') or '该股'
    code = stock.get('code') or stock.get('stock_code') or ''
    pe = stock.get('pe_ttm')
    roe = stock.get('roe')
    chg = stock.get('change_pct')
    price = stock.get('price') or stock.get('close')
    reasons = stock.get('reasons') or stock.get('reason') or ''
    rcode = risk.get('code') or 'C3'
    rlv = risk.get('lv') or '平衡型'
    rpos = risk.get('pos') or ''

    lines = [f"个股：{name}（{code}）"]
    if price is not None:
        lines.append(f"现价：{price}")
    if chg is not None:
        lines.append(f"今日涨跌：{chg}%")
    if pe is not None:
        lines.append(f"PE(TTM)：{pe}")
    if roe is not None:
        lines.append(f"ROE：{roe}%")

    if mode == 'hold':
        cost = stock.get('cost')
        pnl = stock.get('pnl_pct')
        dd = stock.get('drawdown_pct')
        vol = stock.get('volatility_pct')
        trend = stock.get('trend')
        rsi = stock.get('rsi')
        qscore = stock.get('quant_score')
        if cost is not None:
            lines.append(f"用户成本价：{cost}")
        if pnl is not None:
            lines.append(f"当前浮动盈亏：{pnl:+.2f}%")
        if dd is not None:
            lines.append(f"距 60 日高点回撤：{dd:.1f}%")
        if vol is not None:
            lines.append(f"年化波动率：{vol:.1f}%")
        if trend:
            lines.append(f"趋势状态：{trend}")
        if rsi is not None:
            lines.append(f"RSI(14)：{rsi:.0f}")
        if qscore is not None:
            lines.append(f"量化策略综合打分：{qscore}/100")
        if reasons:
            lines.append(f"技术信号：{reasons}")
        lines.append(f"用户风险画像：{rcode} {rlv}" + (f"，仓位约束：{rpos}" if rpos else ""))
        lines.append("请据此为这位首投用户的【持仓】做一次体检式解读。")
    else:
        if reasons:
            lines.append(f"量化引擎选中理由（原始信号）：{reasons}")
        lines.append(f"用户风险画像：{rcode} {rlv}" + (f"，仓位约束：{rpos}" if rpos else ""))
        lines.append("请据此为这位首投用户生成一段深度解读。")
    return "\n".join(lines)


def stream_explain(stock, risk, mode='pick'):
    """生成器：逐块 yield 纯文本增量。上层用 SSE 包装。mode='hold' 走持仓体检话术。"""
    key, model = _cfg()
    if not key:
        raise RuntimeError('DEEPSEEK_API_KEY 未配置')
    system = SYSTEM_PROMPT_HOLD if mode == 'hold' else SYSTEM_PROMPT
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': build_prompt(stock, risk, mode)},
        ],
        'temperature': 0.7,
        'max_tokens': 600,
        'stream': True,
    }
    headers = {
        'Authorization': f'Bearer {key}',
        'Content-Type': 'application/json',
    }
    with requests.post(DEEPSEEK_URL, headers=headers, json=payload,
                       stream=True, timeout=(10, 60)) as resp:
        resp.raise_for_status()
        for raw in resp.iter_lines(decode_unicode=True):
            if not raw:
                continue
            if not raw.startswith('data:'):
                continue
            data = raw[5:].strip()
            if data == '[DONE]':
                break
            try:
                obj = json.loads(data)
                delta = obj['choices'][0].get('delta', {})
                piece = delta.get('content')
                if piece:
                    yield piece
            except (ValueError, KeyError, IndexError):
                continue


ASSESSMENT_SYSTEM_PROMPT = """你是「慧投盾」投资者适当性评估的AI分析师。
用户刚完成了一套15道题的风险测评问卷，其中部分题目用户选择了"其他"并提供了自定义文字说明。

你的任务：
1. 综合分析用户的标准答案+自定义文字内容
2. 评估其真实的风险承受能力、投资经验、心理特征
3. 输出一份300-500字的投资者画像报告

报告要求：
- 第1段：总体定位（保守/稳健/平衡/进取/激进），核心特征（2-3条）
- 第2段：优势与风险点（基于问卷暴露的认知偏差、情绪倾向、知识盲区）
- 第3段：建议的投资方向和应该避免的陷阱
- 语气专业但亲和，像资深理财顾问在做一对一咨询
- 不使用"您"这类书面敬语，用"你"保持自然

禁止事项：
- 不给具体个股推荐
- 不使用"稳赚不赔"等绝对化表述
- 不贩卖焦虑或过度鼓励冒险"""


def analyze_assessment(quiz_data):
    """分析用户测评答案，生成AI投资者画像。

    Args:
        quiz_data: {
            'questions': [{'q': '题目', 'answer': '标准答案', 'custom': '自定义文字或None'}],
            'standard_score': float,  # 标准评分(1-4)
            'risk_level': 'C1-C5'
        }

    Returns:
        {'profile': '画像报告文本(300-500字)', 'ai_score': float(1-4)}
    """
    key, model = _cfg()
    if not key:
        raise RuntimeError('DEEPSEEK_API_KEY 未配置')

    # 构建prompt
    prompt_parts = ['用户测评数据：\n']
    prompt_parts.append(f"标准评分模型给出的风险等级：{quiz_data.get('risk_level', 'C3')}")
    prompt_parts.append(f"标准评分：{quiz_data.get('standard_score', 2.5)}/4.0\n")
    prompt_parts.append("问卷回答详情：")

    for i, item in enumerate(quiz_data.get('questions', []), 1):
        prompt_parts.append(f"\nQ{i}. {item.get('q', '')}")
        prompt_parts.append(f"   标准答案：{item.get('answer', '')}")
        if item.get('custom'):
            prompt_parts.append(f"   用户补充：{item['custom']}")

    prompt_parts.append("\n请生成投资者画像报告。")

    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': ASSESSMENT_SYSTEM_PROMPT},
            {'role': 'user', 'content': '\n'.join(prompt_parts)},
        ],
        'temperature': 0.8,
        'max_tokens': 800,
    }

    headers = {
        'Authorization': f'Bearer {key}',
        'Content-Type': 'application/json',
    }

    resp = requests.post(DEEPSEEK_URL, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    result = resp.json()

    profile_text = result['choices'][0]['message']['content']

    # 简单推断AI调整后的评分（基于报告关键词）
    ss = quiz_data.get('standard_score')
    ai_score = 2.5 if ss is None else float(ss)
    if '保守' in profile_text or '谨慎' in profile_text:
        ai_score = max(1.0, ai_score - 0.3)
    elif '激进' in profile_text or '冒险' in profile_text:
        ai_score = min(4.0, ai_score + 0.3)

    return {
        'profile': profile_text,
        'ai_score': round(ai_score, 2)
    }


def analyze_custom_answer(question, dimension, hint, options, user_answer):
    """分析测评题的自定义答案，给出1-4分的风险评分。

    Args:
        question: 题目文本
        dimension: 测评维度（如"风险承受能力"）
        hint: 题目提示信息
        options: 标准选项列表
        user_answer: 用户自定义输入的文字

    Returns:
        {'score': float(1-4), 'explanation': '简短分析(50字内)'}
    """
    key, model = _cfg()
    if not key:
        raise RuntimeError('DEEPSEEK_API_KEY 未配置')

    system_prompt = """你是「慧投盾」投资者适当性评估的AI分析师。
用户在做风险测评时，对某道题选择了"其他"并提供了自定义回答。

你的任务：
1. 理解题目的测评意图和标准选项
2. 分析用户自定义回答的含义
3. 给出1-4分的风险评分（1=最保守/低风险承受力，4=最进取/高风险承受力）
4. 用50字以内解释评分理由

输出格式（严格JSON）：
{"score": 2.5, "explanation": "评分理由..."}

评分标准：
- 1.0-1.5: 强烈厌恶风险，优先保本，几乎不能接受波动
- 1.5-2.5: 偏保守，接受小幅波动，注重本金安全
- 2.5-3.5: 平衡型，能接受中等波动换取收益，风险与收益并重
- 3.5-4.0: 进取型，追求高收益，能承受较大波动甚至短期亏损"""

    prompt = f"""测评维度：{dimension}

题目：{question}

提示：{hint}

标准选项：
{chr(10).join(f'{i+1}. {opt}' for i, opt in enumerate(options))}

用户自定义回答：
{user_answer}

请分析用户回答并给出评分。"""

    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': prompt},
        ],
        'temperature': 0.3,  # 低温度保证评分一致性
        'max_tokens': 200,
    }

    headers = {
        'Authorization': f'Bearer {key}',
        'Content-Type': 'application/json',
    }

    resp = requests.post(DEEPSEEK_URL, headers=headers, json=payload, timeout=20)
    resp.raise_for_status()
    result = resp.json()

    content = result['choices'][0]['message']['content'].strip()

    # 提取JSON（处理可能的markdown代码块包裹）
    if '```json' in content:
        content = content.split('```json')[1].split('```')[0].strip()
    elif '```' in content:
        content = content.split('```')[1].split('```')[0].strip()

    try:
        parsed = json.loads(content)
        score = float(parsed.get('score', 2.5))
        # 确保分数在1-4范围内
        score = max(1.0, min(4.0, score))
        explanation = parsed.get('explanation', '分析完成')

        return {
            'score': round(score, 1),
            'explanation': explanation[:100]  # 限制长度
        }
    except (json.JSONDecodeError, ValueError, KeyError):
        # 解析失败，返回默认中等分数
        return {
            'score': 2.5,
            'explanation': 'AI分析异常，使用默认评分'
        }

