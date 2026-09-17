"""
XGBoost 信号评分器。

架构：
  - 特征: signal_detail 字段（数值化）+ regime one-hot + 策略 one-hot
  - 目标: label（5日内是否上涨 >= 3%）
  - 输出: p_up（上涨概率 0-1），替代原始 score 字段

数据不足时（< MIN_SAMPLES 条已标注信号）回退到 regime_winrate 的贝叶斯胜率。

训练触发：
  - 回测结束后自动调用 train_if_ready()
  - 手动调用 train_model() 重新训练
"""
import json
import os
import pickle
from .signal_log import get_labeled_signals
from .regime_winrate import lookup_winrate

MIN_SAMPLES = 100
MODEL_PATH = os.path.join(os.path.dirname(__file__), 'xgb_model.pkl')
FEATURE_COLS_PATH = os.path.join(os.path.dirname(__file__), 'feature_cols.json')

_model = None
_feature_cols = None


def _extract_features(features_dict: dict, strategy: str, regime: str) -> dict:
    """将 signal_detail + strategy + regime 转换为数值特征字典。"""
    row = {}
    # 数值型字段：直接解析
    numeric_keys = [
        'vol_ratio', 'breakout_pct', 'trend_r2', 'touch_count',
        'bars_above', 'above_low_pct', 'turnover', 'pullback_pct',
        'rs_vs_market', 'rs_vs_sector', 'momentum_accel',
        'dist_to_ma', 'from_low', 'up_streak',
        'price_vs_ma20', 'price_vs_ma60',
    ]
    for k in numeric_keys:
        raw = features_dict.get(k, 0)
        if isinstance(raw, str):
            # strip % and + signs
            raw = raw.replace('%', '').replace('+', '').strip()
            try:
                raw = float(raw)
            except Exception:
                raw = 0.0
        try:
            row[k] = float(raw)
        except Exception:
            row[k] = 0.0

    # 策略 one-hot (最常见的15种)
    strategies = [
        '关键位突破', '假突破检测', '延续性龙头', '盘面强弱', '科学加仓',
        '趋势买点1·底部建仓', '趋势买点2·M60突破', '趋势买点3·回踩重仓',
        '龙头2进3板', '卡位龙头', '补涨龙', '板块最强前排',
        '均线多头突破', '通道突破', '均线回踩', '海龟通道突破',
    ]
    for s in strategies:
        row[f'strat_{s}'] = 1.0 if strategy == s else 0.0

    # regime one-hot
    regimes = ['risk_on', 'neutral', 'risk_off']
    for rg in regimes:
        row[f'regime_{rg}'] = 1.0 if regime == rg else 0.0

    return row


def train_model() -> dict:
    """
    训练 XGBoost 分类器。
    返回 {'trained': True/False, 'n_samples': int, 'accuracy': float}。
    """
    global _model, _feature_cols
    signals = get_labeled_signals(min_samples=MIN_SAMPLES)
    if not signals:
        return {'trained': False, 'n_samples': len(get_labeled_signals(min_samples=0)),
                'reason': f'需要至少 {MIN_SAMPLES} 条已标注信号，当前不足'}

    try:
        import xgboost as xgb
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import accuracy_score
    except ImportError:
        return {'trained': False, 'reason': 'xgboost 或 scikit-learn 未安装，pip install xgboost scikit-learn'}

    rows = []
    labels = []
    for sig in signals:
        feat = _extract_features(sig.get('features', {}), sig['strategy'], sig['regime'])
        rows.append(feat)
        labels.append(int(sig['label']))

    # 确保列一致
    all_keys = sorted({k for r in rows for k in r})
    X = [[r.get(k, 0.0) for k in all_keys] for r in rows]
    y = labels

    X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, random_state=42)
    clf = xgb.XGBClassifier(
        n_estimators=100, max_depth=4, learning_rate=0.1,
        use_label_encoder=False, eval_metric='logloss',
        random_state=42,
    )
    clf.fit(X_train, y_train)
    acc = accuracy_score(y_val, clf.predict(X_val))

    _model = clf
    _feature_cols = all_keys

    with open(MODEL_PATH, 'wb') as f:
        pickle.dump(clf, f)
    with open(FEATURE_COLS_PATH, 'w') as f:
        json.dump(all_keys, f)

    return {
        'trained': True,
        'n_samples': len(signals),
        'accuracy': round(acc, 4),
        'n_features': len(all_keys),
    }


def train_if_ready():
    """只在样本量够时训练，不报错。"""
    try:
        train_model()
    except Exception:
        pass


def _load_model():
    global _model, _feature_cols
    if _model is not None:
        return True
    if not os.path.exists(MODEL_PATH) or not os.path.exists(FEATURE_COLS_PATH):
        return False
    try:
        import xgboost  # noqa
        with open(MODEL_PATH, 'rb') as f:
            _model = pickle.load(f)
        with open(FEATURE_COLS_PATH) as f:
            _feature_cols = json.load(f)
        return True
    except Exception:
        return False


def score_signal(strategy: str, regime: str, features: dict) -> dict:
    """
    对单个信号评分。
    优先用 XGBoost 模型；模型不可用时回退到贝叶斯胜率。

    Returns:
        {'p_up': 0.62, 'kelly_f': 0.12, 'source': 'xgb'|'bayesian'}
    """
    if _load_model():
        try:
            feat_row = _extract_features(features, strategy, regime)
            x = [[feat_row.get(k, 0.0) for k in _feature_cols]]
            p_up = float(_model.predict_proba(x)[0][1])
            from .kelly import kelly_position
            wc = lookup_winrate(strategy, regime)
            kf = kelly_position(p_up, wc.get('avg_win_pct', 0.08), wc.get('avg_loss_pct', 0.05))
            return {'p_up': round(p_up, 4), 'kelly_f': kf, 'source': 'xgb'}
        except Exception:
            pass

    # 贝叶斯回退
    wc = lookup_winrate(strategy, regime)
    return {
        'p_up': round(wc['win_rate'], 4),
        'kelly_f': round(wc['kelly_f'], 4),
        'source': 'bayesian',
    }
