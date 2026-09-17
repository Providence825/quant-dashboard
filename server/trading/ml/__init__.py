"""
ML升级层：贝叶斯胜率 + 凯利仓位 + XGBoost信号评分

使用方式：
  from .ml.regime_winrate import get_winrate_table, refresh_winrate_cache
  from .ml.kelly import kelly_position
  from .ml.xgb_scorer import score_signal, train_model
"""
