const Backtest = {
  _poll: null,
  _chart: null,

  async load() {
    this._renderRiskStatus();
    // Returning to the backtest tab: the equity chart may have been laid out
    // while hidden. Resize once the tab is visible so it isn't left blank.
    if (this._chart && !this._chart.isDisposed()) {
      requestAnimationFrame(() => this._chart.resize());
    }
  },

  async _renderRiskStatus() {
    const r = await api('/api/risk/status');
    const el = document.getElementById('riskStatus');
    if (!el) return;
    if (!r) { el.innerHTML = '<span style="color:var(--text2)">风控数据加载失败</span>'; return; }

    const b = r.breaker || {};
    const c = r.current || {};
    const m = r.metrics || {};
    const light = b.halt ? '🔴' : '🟢';
    const lightText = b.halt ? `<span style="color:var(--sell)">熔断触发:${b.reason || ''}</span>`
                             : '<span style="color:var(--buy)">正常 · 未触发熔断</span>';

    const dailyBad = c.daily_pnl < c.daily_loss_limit;
    const ddBad = c.drawdown_pct < c.drawdown_limit_pct;
    const consecBad = c.consecutive_losses >= (r.limits?.max_consecutive_losses || 3);
    const chip = (bad, label, val, limit) =>
      `<div style="padding:8px 12px;border-radius:8px;background:${bad?'rgba(255,61,90,0.12)':'rgba(0,230,118,0.08)'}">
        <div style="font-size:11px;color:var(--text2)">${label}</div>
        <div style="font-size:16px;font-weight:700;color:${bad?'var(--sell)':'var(--text)'}">${val}</div>
        <div style="font-size:10px;color:var(--text2)">限:${limit}</div></div>`;

    const attrib = m.strategy_attribution || [];
    const pnlColor = (v) => (v >= 0 ? 'var(--buy)' : 'var(--sell)');
    const attribHtml = attrib.length ? `
      <div style="font-size:12px;color:var(--text2);border-top:1px solid rgba(255,255,255,0.08);padding-top:8px;margin-top:8px">
        单策略归因(已平仓实盘成交):
        <div class="table-wrap" style="margin-top:6px"><table style="font-size:12px">
          <thead><tr><th>策略</th><th>笔数</th><th>胜率</th><th>总盈亏</th><th>盈亏比</th><th>贡献占比</th></tr></thead>
          <tbody>${attrib.map(a => `<tr>
            <td>${a.strategy}</td><td>${a.total_trades}</td><td>${a.win_rate}%</td>
            <td style="color:${pnlColor(a.total_pnl)}">${a.total_pnl>=0?'+':''}${a.total_pnl}</td>
            <td>${a.profit_factor}</td>
            <td style="color:${pnlColor(a.contribution_pct)};font-weight:700">${a.contribution_pct>=0?'+':''}${a.contribution_pct}%</td>
          </tr>`).join('')}</tbody></table></div>
      </div>` : '';

    el.innerHTML = `
      <div style="font-size:18px;margin-bottom:10px">${light} ${lightText}</div>
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:12px">
        ${chip(dailyBad, '当日盈亏', (c.daily_pnl>=0?'+':'')+c.daily_pnl, c.daily_loss_limit)}
        ${chip(ddBad, '当前回撤', c.drawdown_pct+'%', c.drawdown_limit_pct+'%')}
        ${chip(consecBad, '近期连亏', c.consecutive_losses+'笔', (r.limits?.max_consecutive_losses||3)+'笔')}
      </div>
      <div style="font-size:12px;color:var(--text2);border-top:1px solid rgba(255,255,255,0.08);padding-top:8px">
        实盘绩效(基于资产快照):
        夏普 <b style="color:var(--text)">${m.sharpe ?? '-'}</b> ·
        最大回撤 <b style="color:var(--text)">${m.max_drawdown_pct ?? '-'}%</b> ·
        胜率 <b style="color:var(--text)">${m.win_rate ?? '-'}%</b> ·
        盈亏比 <b style="color:var(--text)">${m.profit_factor ?? '-'}</b>
        ${m.insufficient_data ? '<span style="color:var(--warn)"> (实盘样本不足,建议看回测)</span>' : ''}
      </div>
      ${attribHtml}`;
  },

  async run() {
    const btn = document.getElementById('btRunBtn');
    const params = {
      start_date: document.getElementById('btStart').value,
      end_date: document.getElementById('btEnd').value,
      strategy_mode: document.getElementById('btMode').value,
      initial_capital: parseFloat(document.getElementById('btCapital').value) || 1000000,
      max_positions: parseInt(document.getElementById('btMaxPos').value) || 5,
      universe_limit: parseInt(document.getElementById('btUniverse').value) || 300,
      slippage: (parseFloat(document.getElementById('btSlippage').value) || 0) / 100,
      participation: parseFloat(document.getElementById('btParticipation').value) || 0,
      market_filter: document.getElementById('btMarketFilter').checked,
      ml_filter: document.getElementById('btMlFilter').checked,
    };
    if (!params.start_date || !params.end_date) { notify('请选择回测日期范围', 'alert'); return; }

    btn.disabled = true;
    document.getElementById('btStatus').textContent = '启动中...';
    const res = await api('/api/backtest/run', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params)
    });
    if (!res || !res.success) {
      notify('回测启动失败: ' + (res?.error || '未知'), 'alert');
      btn.disabled = false;
      document.getElementById('btStatus').textContent = '';
      return;
    }
    this._runId = res.run_id;
    this._pollStatus();
  },

  _pollStatus() {
    if (this._poll) clearInterval(this._poll);
    this._poll = setInterval(async () => {
      const st = await api('/api/backtest/status');
      if (!st) return;
      const prog = document.getElementById('btProgress');
      document.getElementById('btStatus').textContent = `运行中 ${st.progress_pct || 0}%`;
      prog.innerHTML = `<div style="height:6px;background:rgba(255,255,255,0.1);border-radius:3px;overflow:hidden">
        <div style="height:100%;width:${st.progress_pct||0}%;background:var(--accent);transition:width .3s"></div></div>`;
      if (st.status === 'done') {
        clearInterval(this._poll); this._poll = null;
        document.getElementById('btStatus').textContent = '完成';
        document.getElementById('btRunBtn').disabled = false;
        this._loadResult(st.run_id);
      } else if (st.status === 'error') {
        clearInterval(this._poll); this._poll = null;
        document.getElementById('btStatus').textContent = '出错';
        document.getElementById('btRunBtn').disabled = false;
        notify('回测出错: ' + (st.error || '未知'), 'alert');
      }
    }, 2000);
  },

  async _loadResult(runId) {
    const r = await api('/api/backtest/result/' + runId);
    if (!r || r.status !== 'done') {
      notify('回测结果加载失败', 'alert');
      return;
    }
    // Show cards FIRST so the chart container has a real width before ECharts
    // initializes — initializing inside a display:none box yields a 0×0 canvas
    // and a blank equity/drawdown chart.
    document.getElementById('btResultCard').style.display = '';
    document.getElementById('btTradesCard').style.display = '';
    this._renderMetrics(r.metrics || {}, r);
    this._renderAttribution((r.metrics || {}).strategy_attribution || []);
    this._renderTrades(r.trades || []);
    // Defer chart render one frame so layout settles and the box has dimensions.
    requestAnimationFrame(() => this._renderEquity(r.equity || [], r.metrics || {}));
  },

  _renderMetrics(m, r) {
    const el = document.getElementById('btMetrics');
    const fmt = (v, suf = '') => (v === null || v === undefined ? '-' : v + suf);
    const posNeg = (v) => (v >= 0 ? 'var(--buy)' : 'var(--sell)');
    const card = (label, val, color, sub) =>
      `<div class="card" style="padding:14px">
        <div style="font-size:11px;color:var(--text2)">${label}</div>
        <div style="font-size:22px;font-weight:700;color:${color || 'var(--text)'}">${val}</div>
        ${sub ? `<div style="font-size:10px;color:var(--text2);margin-top:2px">${sub}</div>` : ''}
      </div>`;

    el.innerHTML =
      card('总收益率', (m.total_return_pct >= 0 ? '+' : '') + fmt(m.total_return_pct, '%'), posNeg(m.total_return_pct || 0),
        `年化 ${fmt(m.annualized_return_pct, '%')}`) +
      card('夏普比率', fmt(m.sharpe), (m.sharpe || 0) >= 1 ? 'var(--buy)' : 'var(--text)',
        `索提诺 ${fmt(m.sortino)}`) +
      card('最大回撤', fmt(m.max_drawdown_pct, '%'), 'var(--sell)',
        `卡玛 ${fmt(m.calmar)}`) +
      card('波动率', fmt(m.volatility_pct, '%'), 'var(--text)', '年化') +
      card('胜率', fmt(m.win_rate, '%'), (m.win_rate || 0) >= 50 ? 'var(--buy)' : 'var(--text)',
        `${r.trade_count || 0} 笔成交`) +
      card('盈亏比', fmt(m.profit_factor), (m.profit_factor || 0) >= 1 ? 'var(--buy)' : 'var(--sell)',
        `平均盈亏 ${fmt(m.payoff_ratio)}`) +
      card('Kelly 仓位', fmt(m.kelly_pct, '%'), 'var(--accent)', '保守建议(≤50%)') +
      card('股票池', (r.universe_size || 0) + ' 只', 'var(--text)',
        m.insufficient_data ? '<span style="color:var(--warn)">样本不足</span>' : '近似回测');

    // fx-on 模式下 innerHTML 新建的 .card 初始 opacity:0，不在 fx.js observer 名下，
    // 会永远隐形（曲线容器不是 .card 故正常）。补 .fx-in 让指标卡立即可见。
    if (typeof revealCards === 'function') revealCards(el);

    const noteEl = document.getElementById('btNote');
    if (noteEl && r.note) noteEl.textContent = r.note;
  },

  _renderEquity(equity, m) {
    const box = document.getElementById('btEquityChart');
    if (!box) return;
    if (!equity.length) {
      if (this._chart && !this._chart.isDisposed()) { this._chart.dispose(); this._chart = null; }
      box.innerHTML = '<span class="hint-text">无权益数据</span>';
      return;
    }
    if (typeof echarts === 'undefined') return;
    // Recreate if the cached instance was disposed or its DOM node was replaced
    // (e.g. after an empty-data run wrote innerHTML into the box).
    if (this._chart && (this._chart.isDisposed() || this._chart.getDom() !== box)) {
      this._chart.dispose();
      this._chart = null;
    }
    if (!this._chart) { box.innerHTML = ''; this._chart = echarts.init(box); }
    const dates = equity.map(p => p.date);
    const assets = equity.map(p => Math.round(p.total_asset));
    // Backend already returns drawdown_series in percent (risk_metrics.py),
    // so use the values as-is — do NOT multiply by 100 again.
    const dd = (m.drawdown_series || []).map(v => +Number(v).toFixed(2));

    this._chart.setOption({
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis' },
      legend: { data: ['权益', '回撤%'], textStyle: { color: '#aeb7c4' } },
      grid: { left: 60, right: 55, top: 30, bottom: 40 },
      xAxis: { type: 'category', data: dates, axisLabel: { color: '#7d8794' } },
      yAxis: [
        { type: 'value', scale: true, axisLabel: { color: '#7d8794' }, splitLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } } },
        { type: 'value', max: 0, position: 'right', axisLabel: { color: '#7d8794', formatter: '{value}%' }, splitLine: { show: false } }
      ],
      series: [
        { name: '权益', type: 'line', data: assets, smooth: true, showSymbol: false,
          lineStyle: { color: '#3a86ff', width: 2 }, areaStyle: { color: 'rgba(58,134,255,0.12)' } },
        { name: '回撤%', type: 'line', yAxisIndex: 1, data: dd, showSymbol: false,
          lineStyle: { color: '#ff3d5a', width: 1 }, areaStyle: { color: 'rgba(255,61,90,0.10)' } }
      ]
    });
    this._chart.resize();
  },

  _renderAttribution(rows) {
    const card = document.getElementById('btAttrCard');
    const el = document.getElementById('btAttr');
    if (!card || !el) return;
    if (!rows.length) { card.style.display = 'none'; return; }
    card.style.display = '';
    const pnlColor = (v) => (v >= 0 ? 'var(--buy)' : 'var(--sell)');
    const trs = rows.map(a => `<tr>
      <td>${a.strategy}</td>
      <td>${a.total_trades}</td>
      <td>${a.win_rate}%</td>
      <td style="color:${pnlColor(a.total_pnl)}">${a.total_pnl >= 0 ? '+' : ''}${a.total_pnl}</td>
      <td>${a.profit_factor}</td>
      <td>${a.payoff_ratio}</td>
      <td style="color:${pnlColor(a.contribution_pct)};font-weight:700">${a.contribution_pct >= 0 ? '+' : ''}${a.contribution_pct}%</td>
    </tr>`).join('');
    el.innerHTML = `<table>
      <thead><tr><th>策略</th><th>笔数</th><th>胜率</th><th>总盈亏</th><th>盈亏比(PF)</th><th>平均盈亏比</th><th>贡献占比</th></tr></thead>
      <tbody>${trs}</tbody></table>`;
  },

  _renderTrades(trades) {
    const el = document.getElementById('btTrades');
    if (!trades.length) { el.innerHTML = '<span class="hint-text">无成交记录</span>'; return; }
    const rows = trades.slice(-500).reverse().map(t => {
      const isBuy = t.direction === 'buy';
      const pnl = t.pnl_amount;
      const pnlCell = (pnl === null || pnl === undefined)
        ? '<td style="color:var(--text2)">-</td>'
        : `<td style="color:${pnl >= 0 ? 'var(--buy)' : 'var(--sell)'}">${pnl >= 0 ? '+' : ''}${pnl}</td>`;
      return `<tr>
        <td>${t.date}</td>
        <td class="clickable-stock" data-code="${t.stock_code}" style="cursor:pointer">${t.stock_code}</td>
        <td>${t.stock_name || ''}</td>
        <td><span style="color:${isBuy ? 'var(--buy)' : 'var(--sell)'}">${isBuy ? '买入' : '卖出'}</span></td>
        <td>${t.price}</td>
        <td>${t.shares}</td>
        ${pnlCell}
        <td style="color:var(--text2);font-size:11px">${t.reason || ''}</td>
      </tr>`;
    }).join('');
    el.innerHTML = `<table>
      <thead><tr><th>日期</th><th>代码</th><th>名称</th><th>方向</th><th>价格</th><th>股数</th><th>盈亏</th><th>原因</th></tr></thead>
      <tbody>${rows}</tbody></table>`;
  },
};
