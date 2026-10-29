# 首投守护者：策略分类与风险标签系统
# 用于前端策略选择器的分组展示和风险提示

STRATEGY_CATEGORIES = {
    '趋势跟踪': {
        'strategies': [
            '均线多头突破',
            '通道突破',
            '均线回踩',
            '海龟通道突破',
            '趋势买点'
        ],
        'desc': '基于价格趋势的中长线策略，适合新手学习风险控制',
        'risk_label': '中等风险',
        'risk_color': '#22D3EE',
        'recommended_for_beginners': True
    },
    '情绪周期': {
        'strategies': [
            '龙头2进3板',
            '卡位龙头',
            '补涨龙',
            '延续性龙头',
            '盘面强弱',
            '超跌反弹'
        ],
        'desc': 'A股情绪驱动的短线策略量化回测——学习博弈逻辑，不建议新手实盘',
        'risk_label': '⚠️ 高风险',
        'risk_color': '#FBBF24',
        'warning': '情绪策略高度依赖市场环境与流动性，历史胜率不代表未来可复现。适合学习短线博弈逻辑，不适合新手实盘。',
        'recommended_for_beginners': False
    },
    '基本面筛选': {
        'strategies': [
            'ROE选股',
            '营收增长',
            '现金流健康',
            '基本面因子'
        ],
        'desc': '财务指标驱动，适合中长期持有',
        'risk_label': '低-中风险',
        'risk_color': '#10B981',
        'recommended_for_beginners': True
    },
    '板块轮动': {
        'strategies': [
            '板块动量',
            '行业轮动',
            '板块轮动策略'
        ],
        'desc': '分散化配置策略，降低个股风险',
        'risk_label': '中等风险',
        'risk_color': '#22D3EE',
        'recommended_for_beginners': True
    }
}

def get_strategy_category(strategy_name):
    """根据策略名称返回所属分类"""
    for category, meta in STRATEGY_CATEGORIES.items():
        if strategy_name in meta['strategies']:
            return {
                'category': category,
                'risk_label': meta['risk_label'],
                'risk_color': meta['risk_color'],
                'desc': meta['desc'],
                'warning': meta.get('warning'),
                'recommended': meta.get('recommended_for_beginners', False)
            }
    # 未分类的策略默认为趋势跟踪
    return {
        'category': '趋势跟踪',
        'risk_label': '中等风险',
        'risk_color': '#22D3EE',
        'desc': '基于价格趋势的策略',
        'warning': None,
        'recommended': False
    }

def get_all_categories():
    """返回所有分类供前端使用"""
    return {
        cat: {
            'desc': meta['desc'],
            'risk_label': meta['risk_label'],
            'risk_color': meta['risk_color'],
            'warning': meta.get('warning'),
            'strategies': meta['strategies']
        }
        for cat, meta in STRATEGY_CATEGORIES.items()
    }

def get_category_meta(strategy_name):
    """API端点专用：返回单个策略的分类信息"""
    return get_strategy_category(strategy_name)
