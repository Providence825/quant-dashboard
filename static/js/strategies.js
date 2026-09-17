function escQ(str) { return String(str).replace(/'/g, "\\'"); }

const Strategies = {
  async load() {
    const signals = await api('/api/strategy/signals');
    if (!signals) return;

    // Short-term strategies
    this._renderList('dragonLeaders', signals['龙头战法'] || [], '龙头战法');
    this._renderList('lateDayDips', signals['尾盘捡漏'] || [], '尾盘捡漏');
    this._renderList('vwapSignals', signals['分时回归'] || [], '分时回归');
    this._renderList('antiAlgoSignals', signals['逆向做T'] || [], '逆向做T');

    // Trend strategies
    this._renderList('maBreakouts', signals['均线多头突破'] || [], '均线多头突破');
    this._renderList('channelBreakouts', signals['通道突破'] || [], '通道突破');
    this._renderList('maPullbacks', signals['均线回踩'] || [], '均线回踩');
    this._renderList('turtleBreakouts', signals['海龟通道突破'] || [], '海龟通道突破');

    // 来去由心 strategies
    this._renderList('buyPoint1Signals', signals['趋势买点1·底部建仓'] || [], '趋势买点1·底部建仓');
    this._renderList('buyPoint2Signals', signals['趋势买点2·M60突破'] || [], '趋势买点2·M60突破');
    this._renderList('buyPoint3Signals', signals['趋势买点3·回踩重仓'] || [], '趋势买点3·回踩重仓');
    this._renderList('sectorFrontlineSignals', signals['板块最强前排'] || [], '板块最强前排');

    // 从零大A strategies
    this._renderList('keyLevelBreakouts', signals['关键位突破'] || [], '关键位突破');
    this._renderList('falseBreakouts', signals['假突破检测'] || [], '假突破检测');
    this._renderList('continuityDragons', signals['延续性龙头'] || [], '延续性龙头');
    this._renderList('marketStrengthRank', signals['盘面强弱'] || [], '盘面强弱');
    this._renderList('scientificAdds', signals['科学加仓'] || [], '科学加仓');

    // Load regime and cycle
    this._loadRegime();
    this._loadLaiQuCycle();
  },

  async _loadLaiQuCycle() {
    const cycle = await api('/api/strategy/lai_qu/cycle');
    if (!cycle) return;

    const el = document.getElementById('laiquCycleStatus');
    if (el) {
      el.style.color = cycle.cycle_color || 'var(--accent)';
      el.textContent = cycle.cycle_label || '混沌';
    }

    const detail = document.getElementById('laiquCycleDetail');
    if (detail && cycle.cycle_label) {
      const phaseOrder = ['点火', '混沌', '发酵', '分歧', '一致', '加速', '退潮'];
      const phaseBar = phaseOrder.map(p => {
        const isCurrent = p === cycle.cycle_label;
        return `<span style="display:inline-block;padding:2px 6px;margin:0 1px;border-radius:4px;
          ${isCurrent ? 'background:' + (cycle.cycle_color || '#888') + ';color:#000;font-weight:700' : 'color:#555'};
          font-size:10px">${p}</span>`;
      }).join('');

      detail.innerHTML = `
        <div style="margin-bottom:6px">${phaseBar}</div>
        <div>${cycle.cycle_desc || ''} &nbsp;|&nbsp;
        ${cycle.should_trade ? '<span style="color:var(--buy)">允许开仓</span>' : '<span style="color:var(--sell)">暂停开仓</span>'}
        ${cycle.max_position_pct ? ' | 仓位上限:' + (cycle.max_position_pct * 100).toFixed(0) + '%' : ''}
        ${cycle.preferred_strategy ? ' | 偏好:' + (cycle.preferred_strategy === 'trend' ? '趋势波段' : '短线博弈') : ''}
        </div>
        ${cycle.action_hint ? '<div style="margin-top:2px;color:var(--warn)">' + cycle.action_hint + '</div>' : ''}
        ${cycle.details && cycle.details.length ? '<div style="margin-top:2px;font-size:10px">' + cycle.details.join(' · ') + '</div>' : ''}
      `;
    }
  },

  async _loadRegime() {
    const regime = await api('/api/market/regime');
    if (!regime) return;
    const el = document.getElementById('regimeStatus');
    if (!el) return;

    const labels = {
      'trending_up': '上升趋势',
      'trending_down': '下降趋势',
      'ranging': '震荡整理',
      'transitional': '方向不明'
    };
    const colors = {
      'trending_up': 'var(--buy)',
      'trending_down': 'var(--sell)',
      'ranging': 'var(--warn)',
      'transitional': 'var(--text2)'
    };
    const strategyLabel = regime.recommended_strategy === 'trend' ? '趋势波段策略' : '短线策略';

    el.innerHTML = `<span style="color:${colors[regime.regime] || 'var(--text2)'};font-weight:700">
      ${labels[regime.regime] || regime.regime}</span>
      <span style="font-size:11px;color:var(--text2);margin-left:8px">
      ADX:${regime.adx} | 涨跌比:${regime.breadth}% | 均线:${regime.ma_alignment}
      </span>
      <span style="font-size:11px;color:var(--accent);margin-left:8px">
      → ${strategyLabel}
      </span>`;
  },

  _renderList(elemId, items, strategyType) {
    const el = document.getElementById(elemId);
    if (!el) return;

    if (!items || items.length === 0) {
      el.innerHTML = '<div style="color:var(--text2);padding:12px">暂无信号</div>';
      return;
    }

    const badgeMap = {
      '龙头战法': ['\u{1F409}', 'var(--accent)'],
      '尾盘捡漏': ['\u{1F4C9}', 'var(--buy)'],
      '分时回归': ['\u{267B}', 'var(--warn)'],
      '均线多头突破': ['\u{1F4C8}', 'var(--accent)'],
      '通道突破': ['\u{1F680}', 'var(--gold)'],
      '均线回踩': ['\u{1F4CC}', 'var(--buy)'],
      '海龟通道突破': ['\u{1F422}', 'var(--gold)'],
      '趋势买点1·底部建仓': ['\u{1F50D}', 'var(--buy)'],
      '趋势买点2·M60突破': ['\u{1F680}', 'var(--gold)'],
      '趋势买点3·回踩重仓': ['\u{1F3AF}', 'var(--warn)'],
      '板块最强前排': ['\u{1F3C6}', 'var(--accent)'],
      '关键位突破': ['🔐', 'var(--gold)'],
      '假突破检测': ['⚠', 'var(--sell)'],
      '延续性龙头': ['🐉', 'var(--accent)'],
      '盘面强弱': ['📊', 'var(--buy)'],
      '科学加仓': ['➕', 'var(--buy)'],
      '逆向做T': ['\u{267B}', 'var(--warn)'],
      '卡位龙头': ['\u{1F451}', 'var(--gold)'],
      '补涨龙': ['\u{1F409}', 'var(--accent)'],
      '龙头2进3': ['\u{1F31F}', 'var(--gold)'],
    };

    const rows = items.slice(0, 8).map((s, i) => {
      const chg = parseFloat(s.change_pct) || 0;
      const chgClass = chg > 0 ? 'up' : chg < 0 ? 'down' : '';
      const price = parseFloat(s.price) || 0;
      const [badgeIcon, badgeColor] = badgeMap[s.strategy] || ['\u{1F4C8}', 'var(--text2)'];
      const badge = `<span style="color:${badgeColor};font-weight:700">${badgeIcon}</span>`;

      const buyBtn = `<button onclick="Strategies.buySignal('${escQ(s.stock_code)}','${escQ(s.stock_name)}','${escQ(s.strategy || strategyType)}')"
        style="padding:2px 10px;background:var(--accent);color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:12px">买入</button>`;

      let detail = '';
      if (s.signal_detail && typeof s.signal_detail === 'object') {
        detail = Object.entries(s.signal_detail).map(([k, v]) => `${k}:${v}`).join(' | ');
      }
      if (s.signal) detail = s.signal;
      if (s.deviation_pct) detail = `偏离VWAP ${s.deviation_pct}%`;
      if (s.direction) detail = s.direction;

      return `<tr style="border-bottom:1px solid rgba(255,255,255,0.05);cursor:pointer"
        onclick="KlineModal.open('${escQ(s.stock_code)}','${escQ(s.stock_name)}')">
        <td style="padding:6px 0">${i+1}. ${badge} <span style="color:var(--text)">${s.stock_name}</span>
          <span style="font-size:11px;color:var(--text2)"> ${s.stock_code}</span></td>
        <td style="text-align:right;font-weight:600" class="${chgClass}">${price > 0 ? '¥'+price.toFixed(2) : '-'}</td>
        <td style="text-align:right;font-weight:600" class="${chgClass}">${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%</td>
        <td style="text-align:right;font-size:11px;color:var(--text2);max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${detail}</td>
        <td style="text-align:right">${buyBtn}</td>
      </tr>`;
    }).join('');

    el.innerHTML = `<table style="width:100%;border-collapse:collapse">
      <thead><tr style="border-bottom:1px solid rgba(255,255,255,0.1)">
        <th style="padding:6px 0;text-align:left;font-size:11px;color:var(--text2)">股票</th>
        <th style="padding:6px 0;text-align:right;font-size:11px;color:var(--text2)">现价</th>
        <th style="padding:6px 0;text-align:right;font-size:11px;color:var(--text2)">涨跌幅</th>
        <th style="padding:6px 0;text-align:right;font-size:11px;color:var(--text2)">信号详情</th>
        <th style="padding:6px 0;text-align:right;font-size:11px;color:var(--text2)">操作</th>
      </tr></thead>
      <tbody>${rows}</tbody></table>`;
  },

  async buySignal(code, name, strategyType) {
    const amount = strategyType === '尾盘捡漏' ? 50000 : 100000;
    const res = await api('/api/trade/buy', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        stock_code: code,
        amount: amount,
        reason: strategyType + '信号买入',
        strategy_type: strategyType
      })
    });
    if (res && res.success) {
      notify(`${name} 买入成功 ${res.shares}股 @${res.price} [${strategyType}]`, 'buy');
    } else {
      notify(`买入失败: ${res?.error || '未知'}`, 'alert');
    }
  }
};

// ── ML 综合评分面板 ────────────────────────────────────────────────────
const MLPanel = {
  async load() {
    await Promise.all([
      this._loadKelly(),
      this._loadWinrates(),
      this._loadStats(),
      this._loadIC(),
    ]);
  },

  async refresh() {
    document.getElementById('mlKellyPanel').innerHTML = '刷新中...';
    await this.load();
    notify('ML面板已刷新', 'info');
  },

  async refreshIC() {
    document.getElementById('mlICFactor').innerHTML = '刷新中...';
    document.getElementById('mlICSummary').innerHTML = '刷新中...';
    await this._loadIC(true);
    notify('IC报告已刷新', 'info');
  },

  async _loadKelly() {
    const el = document.getElementById('mlKellyPanel');
    if (!el) return;
    const data = await api('/api/ml/kelly');
    if (!data || !data.success) {
      el.innerHTML = `<div style="color:var(--text2);padding:12px">${data?.error || '暂无数据（先运行一次回测积累信号）'}</div>`;
      return;
    }
    const items = data.data || [];
    if (!items.length) {
      el.innerHTML = '<div style="color:var(--text2);padding:12px">暂无ML评分信号</div>';
      return;
    }

    const regimeLabel = { risk_on: '风险偏好↑', neutral: '中性', risk_off: '风险规避↓' };
    const regimeColor = { risk_on: 'var(--buy)', neutral: 'var(--warn)', risk_off: 'var(--sell)' };

    const rows = items.map((s, i) => {
      const pUp = (s.p_up * 100).toFixed(1);
      const kellyPct = (s.kelly_f * 100).toFixed(1);
      const sourceColor = s.source === 'xgb' ? 'var(--buy)' : 'var(--accent)';
      const sourceLabel = s.source === 'xgb' ? 'XGB' : '贝叶斯';
      const pColor = s.p_up >= 0.6 ? 'var(--buy)' : s.p_up >= 0.5 ? 'var(--warn)' : 'var(--sell)';
      const winRate = s.win_rate ? (s.win_rate * 100).toFixed(1) + '%' : '-';
      const n = s.sample_count || 0;
      return `<tr style="border-bottom:1px solid rgba(255,255,255,0.05);cursor:pointer"
        onclick="KlineModal.open('${escQ(s.stock_code)}','${escQ(s.stock_name)}')">
        <td style="padding:6px 0">${i+1}. <span style="color:var(--text)">${s.stock_name}</span>
          <span style="font-size:10px;color:var(--text2)"> ${s.stock_code}</span></td>
        <td style="text-align:center;font-size:10px;color:var(--text2)">${s.strategy}</td>
        <td style="text-align:right;font-weight:700;color:${pColor}">${pUp}%</td>
        <td style="text-align:right;font-weight:700;color:var(--gold)">${kellyPct}%</td>
        <td style="text-align:center;font-size:10px;color:${sourceColor}">${sourceLabel}
          <span style="color:var(--text2)">(${n}条)</span></td>
        <td style="text-align:right">
          <button onclick="event.stopPropagation();Strategies.buySignal('${escQ(s.stock_code)}','${escQ(s.stock_name)}','${escQ(s.strategy)}')"
            style="padding:2px 8px;background:var(--accent);color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:11px">买入</button>
        </td>
      </tr>`;
    }).join('');

    const regLabel = regimeLabel[data.regime] || data.regime;
    const regColor = regimeColor[data.regime] || 'var(--text2)';

    el.innerHTML = `
      <div style="margin-bottom:8px;font-size:11px;color:var(--text2)">
        当前市场: <span style="color:${regColor};font-weight:700">${regLabel}</span>
        <span style="margin-left:8px">(${data.regime_detail || ''})</span>
      </div>
      <table style="width:100%;border-collapse:collapse">
        <thead><tr style="border-bottom:1px solid rgba(255,255,255,0.1)">
          <th style="padding:6px 0;text-align:left;font-size:11px;color:var(--text2)">股票</th>
          <th style="padding:6px 0;text-align:center;font-size:11px;color:var(--text2)">策略</th>
          <th style="padding:6px 0;text-align:right;font-size:11px;color:var(--text2)">p_up↑</th>
          <th style="padding:6px 0;text-align:right;font-size:11px;color:var(--gold)">凯利仓位</th>
          <th style="padding:6px 0;text-align:center;font-size:11px;color:var(--text2)">数据源</th>
          <th style="padding:6px 0;text-align:right;font-size:11px;color:var(--text2)">操作</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
  },

  async _loadWinrates() {
    const el = document.getElementById('mlWinratePanel');
    if (!el) return;
    const data = await api('/api/ml/winrates');
    if (!data || !data.success || !data.data.length) {
      el.innerHTML = '<div style="color:var(--text2);padding:12px">暂无胜率数据（先运行回测）</div>';
      return;
    }
    const rows = data.data.map(r => {
      const wr = (r.win_rate * 100).toFixed(1);
      const kelly = (r.kelly_f * 100).toFixed(1);
      const wrColor = r.win_rate >= 0.55 ? 'var(--buy)' : r.win_rate >= 0.45 ? 'var(--warn)' : 'var(--sell)';
      const regimeColor = { risk_on: 'var(--buy)', neutral: 'var(--text2)', risk_off: 'var(--sell)' };
      return `<tr style="border-bottom:1px solid rgba(255,255,255,0.04)">
        <td style="padding:4px 0;font-size:11px;color:var(--text)">${r.strategy}</td>
        <td style="text-align:center;font-size:10px;color:${regimeColor[r.regime]||'var(--text2)'}">${r.regime}</td>
        <td style="text-align:right;font-weight:700;color:${wrColor}">${wr}%</td>
        <td style="text-align:right;font-size:11px;color:var(--gold)">${kelly}%</td>
        <td style="text-align:right;font-size:10px;color:var(--text2)">${r.sample_count}</td>
      </tr>`;
    }).join('');
    el.innerHTML = `<table style="width:100%;border-collapse:collapse">
      <thead><tr style="border-bottom:1px solid rgba(255,255,255,0.1)">
        <th style="padding:4px 0;text-align:left;font-size:10px;color:var(--text2)">策略</th>
        <th style="padding:4px 0;text-align:center;font-size:10px;color:var(--text2)">市场状态</th>
        <th style="padding:4px 0;text-align:right;font-size:10px;color:var(--text2)">胜率</th>
        <th style="padding:4px 0;text-align:right;font-size:10px;color:var(--gold)">凯利仓位</th>
        <th style="padding:4px 0;text-align:right;font-size:10px;color:var(--text2)">样本数</th>
      </tr></thead>
      <tbody>${rows}</tbody></table>`;
  },

  async _loadStats() {
    const el = document.getElementById('mlSignalStats');
    const lbl = document.getElementById('mlStatsLabel');
    if (!el) return;
    const data = await api('/api/ml/signal-stats');
    if (!data || !data.success) {
      el.innerHTML = '<div style="color:var(--text2);padding:12px">暂无统计</div>';
      return;
    }
    const pct = data.total_signals > 0
      ? Math.round(data.labeled_signals / data.total_signals * 100) : 0;
    const xgbReady = data.xgb_ready;
    if (lbl) lbl.textContent = `已积累 ${data.labeled_signals} 条标注 | ${xgbReady ? '✅ XGBoost就绪' : `⏳ 还需${100 - data.labeled_signals}条`}`;

    const bars = (data.by_strategy || []).map(r => {
      const wr = r.wins + r.losses > 0 ? (r.wins / (r.wins + r.losses) * 100).toFixed(0) : '-';
      return `<tr style="border-bottom:1px solid rgba(255,255,255,0.04)">
        <td style="padding:3px 0;font-size:11px;color:var(--text)">${r.strategy}</td>
        <td style="text-align:right;font-size:10px;color:var(--text2)">${r.n}</td>
        <td style="text-align:right;font-size:10px;color:var(--buy)">${r.wins}</td>
        <td style="text-align:right;font-size:10px;color:var(--sell)">${r.losses}</td>
        <td style="text-align:right;font-size:10px;color:${parseFloat(wr) >= 50 ? 'var(--buy)' : 'var(--sell)'}">${wr}%</td>
      </tr>`;
    }).join('');

    const trainBtn = xgbReady
      ? `<button onclick="MLPanel.trainXGB()" style="margin-top:10px;padding:4px 14px;background:var(--buy);color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:12px">训练 XGBoost 模型</button>`
      : `<div style="margin-top:8px;font-size:11px;color:var(--text2)">积累到100条已标注信号后可训练 XGBoost</div>`;

    el.innerHTML = `
      <div style="margin-bottom:8px">
        <span style="font-size:13px;color:var(--text)">总信号: <strong>${data.total_signals}</strong></span>
        <span style="margin-left:10px;font-size:13px;color:var(--buy)">已标注: <strong>${data.labeled_signals}</strong></span>
        <span style="margin-left:10px;font-size:11px;color:var(--text2)">(${pct}%)</span>
      </div>
      <div style="background:rgba(255,255,255,0.05);height:6px;border-radius:3px;margin-bottom:10px">
        <div style="width:${pct}%;height:100%;background:var(--buy);border-radius:3px;transition:width 0.3s"></div>
      </div>
      ${data.by_strategy && data.by_strategy.length ? `
      <table style="width:100%;border-collapse:collapse">
        <thead><tr style="border-bottom:1px solid rgba(255,255,255,0.1)">
          <th style="padding:3px 0;text-align:left;font-size:10px;color:var(--text2)">策略</th>
          <th style="padding:3px 0;text-align:right;font-size:10px;color:var(--text2)">样本</th>
          <th style="padding:3px 0;text-align:right;font-size:10px;color:var(--buy)">盈</th>
          <th style="padding:3px 0;text-align:right;font-size:10px;color:var(--sell)">亏</th>
          <th style="padding:3px 0;text-align:right;font-size:10px;color:var(--text2)">胜率</th>
        </tr></thead>
        <tbody>${bars}</tbody>
      </table>` : ''}
      ${trainBtn}`;
  },

  async trainXGB() {
    const el = document.getElementById('mlSignalStats');
    if (el) el.innerHTML = '训练中，请稍候...';
    const res = await api('/api/ml/train', { method: 'POST' });
    if (res && res.success && res.result && res.result.trained) {
      notify(`XGBoost训练完成: 准确率 ${(res.result.accuracy * 100).toFixed(1)}% | ${res.result.n_samples}条样本`, 'buy');
    } else {
      notify(res?.result?.reason || res?.error || '训练失败', 'alert');
    }
    await this._loadStats();
  },

  async _loadIC(forceRefresh = false) {
    const elFactor = document.getElementById('mlICFactor');
    const elSummary = document.getElementById('mlICSummary');
    if (!elFactor || !elSummary) return;

    const url = '/api/ml/ic-report' + (forceRefresh ? '?refresh=1' : '');
    const data = await api(url);

    if (!data || !data.success) {
      const msg = `<div style="color:var(--text2);padding:12px">${data?.error || '暂无数据（先运行一次回测积累信号）'}</div>`;
      elFactor.innerHTML = msg;
      elSummary.innerHTML = msg;
      return;
    }

    // ── 因子 IC 表 ────────────────────────────────────────────────────
    const fic = data.factor_ic || {};
    if (fic.error) {
      elFactor.innerHTML = `<div style="color:var(--text2);padding:12px">${fic.error}</div>`;
    } else {
      const qColor = q => q === '强' ? 'var(--buy)' : q === '有效' ? 'var(--warn)' : q === '反向' ? 'var(--sell)' : 'var(--text2)';
      const rows = Object.entries(fic).map(([k, v]) => {
        const icNum = (v.ic * 100).toFixed(2);
        const icColor = v.ic > 0.05 ? 'var(--buy)' : v.ic < 0 ? 'var(--sell)' : 'var(--text2)';
        const sig = v.pval < 0.05 ? '<span style="color:var(--buy);font-size:9px">*</span>' : '';
        return `<tr style="border-bottom:1px solid rgba(255,255,255,0.04)">
          <td style="padding:4px 0;font-size:11px;color:var(--text)">${k}</td>
          <td style="text-align:right;font-weight:700;color:${icColor}">${icNum}%${sig}</td>
          <td style="text-align:center;font-size:10px;color:${qColor(v.quality)}">${v.quality}</td>
          <td style="text-align:right;font-size:10px;color:var(--text2)">${v.n}</td>
        </tr>`;
      }).join('');
      elFactor.innerHTML = `
        <table style="width:100%;border-collapse:collapse">
          <thead><tr style="border-bottom:1px solid rgba(255,255,255,0.1)">
            <th style="text-align:left;font-size:10px;color:var(--text2);padding:4px 0">因子</th>
            <th style="text-align:right;font-size:10px;color:var(--text2)">IC</th>
            <th style="text-align:center;font-size:10px;color:var(--text2)">评级</th>
            <th style="text-align:right;font-size:10px;color:var(--text2)">样本</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
        <div style="margin-top:6px;font-size:10px;color:var(--text2)">* p&lt;0.05 统计显著</div>`;
    }

    // ── 汇总 + 策略维度 + IC 时序迷你图 ──────────────────────────────
    const s = data.summary || {};
    const irColor = s.ir > 0.5 ? 'var(--buy)' : s.ir > 0.3 ? 'var(--warn)' : 'var(--sell)';
    const icMeanColor = s.ic_mean > 0.05 ? 'var(--buy)' : s.ic_mean < 0 ? 'var(--sell)' : 'var(--text2)';

    const strats = (data.strategy_ic || []).slice(0, 6).map(r => {
      const c = r.ic > 0.05 ? 'var(--buy)' : r.ic < 0 ? 'var(--sell)' : 'var(--text2)';
      return `<tr style="border-bottom:1px solid rgba(255,255,255,0.04)">
        <td style="padding:3px 0;font-size:11px;color:var(--text);max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${r.strategy}</td>
        <td style="text-align:right;font-weight:700;color:${c}">${(r.ic*100).toFixed(2)}%</td>
        <td style="text-align:right;font-size:10px;color:var(--text2)">${r.n}</td>
      </tr>`;
    }).join('');

    // Sparkline for IC series
    const series = (data.ic_series || []).slice(-20);
    let spark = '';
    if (series.length >= 4) {
      const vals = series.map(r => r.ic);
      const mn = Math.min(...vals), mx = Math.max(...vals);
      const range = mx - mn || 0.001;
      const W = 200, H = 32;
      const pts = vals.map((v, i) => {
        const x = (i / (vals.length - 1)) * W;
        const y = H - ((v - mn) / range) * H;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      }).join(' ');
      const zeroY = H - ((0 - mn) / range) * H;
      spark = `<div style="margin:8px 0 4px">
        <svg viewBox="0 0 ${W} ${H}" style="width:100%;height:32px;display:block">
          <line x1="0" y1="${zeroY.toFixed(1)}" x2="${W}" y2="${zeroY.toFixed(1)}" stroke="rgba(255,255,255,0.15)" stroke-width="1" stroke-dasharray="3,3"/>
          <polyline points="${pts}" fill="none" stroke="var(--accent)" stroke-width="1.5"/>
        </svg>
        <div style="font-size:9px;color:var(--text2);text-align:right">← ${series[0]?.period} 至 ${series[series.length-1]?.period}</div>
      </div>`;
    }

    elSummary.innerHTML = `
      <div style="display:flex;gap:20px;margin-bottom:10px">
        <div><div style="font-size:10px;color:var(--text2)">IC均值</div>
          <div style="font-size:18px;font-weight:700;color:${icMeanColor}">${(s.ic_mean*100).toFixed(2)}%</div></div>
        <div><div style="font-size:10px;color:var(--text2)">IR</div>
          <div style="font-size:18px;font-weight:700;color:${irColor}">${s.ir != null ? s.ir.toFixed(3) : '—'}</div></div>
        <div style="flex:1"><div style="font-size:10px;color:var(--text2)">综合评级</div>
          <div style="font-size:12px;font-weight:600;color:${irColor};margin-top:4px">${s.quality}</div></div>
      </div>
      ${spark}
      ${strats ? `<table style="width:100%;border-collapse:collapse;margin-top:6px">
        <thead><tr style="border-bottom:1px solid rgba(255,255,255,0.1)">
          <th style="text-align:left;font-size:10px;color:var(--text2);padding:3px 0">策略</th>
          <th style="text-align:right;font-size:10px;color:var(--text2)">IC</th>
          <th style="text-align:right;font-size:10px;color:var(--text2)">样本</th>
        </tr></thead>
        <tbody>${strats}</tbody>
      </table>` : ''}`;
  },
};
