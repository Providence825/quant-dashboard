async function loadPositions() {
  const summary = await api('/api/account/summary');
  if (!summary) return;

  document.getElementById('accountCards').innerHTML = `
    <div class="card stat-card">
      <div class="label">总资产</div>
      <div class="value" style="color:#00bfa5">${(summary.total_asset / 10000).toFixed(2)}<span style="font-size:12px">万</span></div>
      <div class="sub ${summary.cumulative_return_pct >= 0 ? 'up' : 'down'}">${summary.cumulative_return_pct >= 0 ? '+' : ''}${summary.cumulative_return_pct}%</div>
    </div>
    <div class="card stat-card">
      <div class="label">可用资金</div>
      <div class="value" style="color:#fff">${(summary.available_cash / 10000).toFixed(2)}<span style="font-size:12px">万</span></div>
      <div class="sub">冻结 ${(summary.frozen / 10000).toFixed(2)}万</div>
    </div>
    <div class="card stat-card">
      <div class="label">持仓市值</div>
      <div class="value" style="color:#448aff">${(summary.position_value / 10000).toFixed(2)}<span style="font-size:12px">万</span></div>
      <div class="sub">${summary.position_count} 只股票</div>
    </div>
    <div class="card stat-card">
      <div class="label">初始资金</div>
      <div class="value" style="color:var(--text2)">${(summary.initial_capital / 10000).toFixed(0)}<span style="font-size:12px">万</span></div>
      <div class="sub">${new Date().toLocaleDateString('zh-CN')}</div>
    </div>`;
  revealCards(document.getElementById('accountCards'));

  const positions = summary.positions || [];
  document.getElementById('positionsTable').innerHTML = positions.length ? `
    <table><thead><tr><th>代码</th><th>名称</th><th>持仓</th><th>成本</th><th>现价</th><th>市值</th><th>盈亏</th><th>持有天数</th><th>操作</th></tr></thead>
    <tbody>${positions.map(p => {
      const profit = p.current_price ? ((p.current_price - p.avg_cost) / p.avg_cost * 100).toFixed(2) : 0;
      return `
      <tr>
        <td class="clickable-stock" data-code="${p.stock_code}">${p.stock_code}</td><td class="clickable-stock" data-code="${p.stock_code}">${p.stock_name}</td><td>${p.shares}股</td>
        <td>${p.avg_cost.toFixed(2)}</td><td>${p.current_price.toFixed(2)}</td>
        <td>${((p.current_price||0)*p.shares).toFixed(0)}</td>
        <td class="${profit >= 0 ? 'up' : 'down'}">${profit >= 0 ? '+' : ''}${profit}%</td>
        <td>${p.buy_date ? Math.floor((new Date() - new Date(p.buy_date)) / 86400000) : 0}天</td>
        <td><button class="btn btn-danger btn-sm" onclick="manualSell('${p.stock_code}', ${p.shares})">卖出</button></td>
      </tr>`;
    }).join('')}</tbody></table>` : '<div style="color:var(--text2);padding:20px;text-align:center">暂无持仓</div>';

  loadOrders();
  loadAssetCurve();
  loadPortfolioBeta();
  loadPortfolioWeights();
  loadPositions2();
}

async function loadOrders() {
  const data = await api('/api/account/orders');
  if (!data || !Array.isArray(data)) return;
  document.getElementById('ordersTable').innerHTML = data.length ? `
    <table><thead><tr><th>时间</th><th>代码</th><th>方向</th><th>价格</th><th>数量</th><th>状态</th><th>原因</th></tr></thead>
    <tbody>${data.map(o => `
      <tr>
        <td>${o.created_at}</td><td>${o.stock_code}</td>
        <td class="${o.direction === 'buy' ? 'up' : 'down'}">${o.direction === 'buy' ? '买入' : '卖出'}</td>
        <td>${o.price.toFixed(2)}</td><td>${o.shares}股</td>
        <td>${o.status === 'filled' ? '已成交' : o.status === 'pending' ? '委托中' : '已撤销'}</td>
        <td style="max-width:120px;overflow:hidden;text-overflow:ellipsis">${o.strategy_reason || ''}</td>
      </tr>`).join('')}</tbody></table>` : '<div style="color:var(--text2);padding:20px;text-align:center">暂无委托</div>';
}

async function loadAssetCurve() {
  const data = await api('/api/account/return-curve');
  if (!data || !data.dates || data.dates.length < 2) return;
  Charts.renderReturnCurve(data);
}

async function loadPortfolioBeta() {
  const el = document.getElementById('portfolioBetaPanel');
  if (!el) return;
  const data = await api('/api/portfolio/beta');
  if (!data || !data.success) {
    el.innerHTML = `<div style="color:var(--text2);padding:12px">${data?.error || '暂无数据'}</div>`;
    return;
  }

  const pb = data.portfolio_beta;
  const exp = data.exposure || {};
  const betaColor = pb > 1.2 ? 'var(--sell)' : pb < 0.6 ? 'var(--buy)' : 'var(--warn)';
  const regimeLabels = {
    strong_trending: '强趋势', trending: '趋势', weak_trending: '弱趋势',
    ranging: '震荡', risk_off: '避险', severe_risk_off: '强避险', unknown: '未知',
  };
  const regimeLabel = regimeLabels[exp.regime] || exp.regime || '未知';
  const expPct = exp.target_pct || `${Math.round((exp.multiplier||0.8)*100)}%`;

  const stocks = (data.stocks || []).map(s => {
    const bc = s.beta > 1.2 ? 'var(--sell)' : s.beta < 0.8 ? 'var(--buy)' : 'var(--text)';
    return `<tr style="border-bottom:1px solid rgba(255,255,255,0.04)">
      <td style="padding:4px 0;font-size:11px;color:var(--text)">${s.stock_name}</td>
      <td style="text-align:right;font-weight:700;color:${bc}">${s.beta.toFixed(2)}</td>
      <td style="text-align:right;font-size:11px;color:var(--text2)">${(s.weight*100).toFixed(1)}%</td>
    </tr>`;
  }).join('');

  el.innerHTML = `
    <div style="display:flex;gap:16px;margin-bottom:10px;flex-wrap:wrap">
      <div style="text-align:center">
        <div style="font-size:10px;color:var(--text2)">组合 Beta</div>
        <div style="font-size:22px;font-weight:700;color:${betaColor}">${pb.toFixed(2)}</div>
      </div>
      <div style="text-align:center">
        <div style="font-size:10px;color:var(--text2)">市场状态</div>
        <div style="font-size:16px;font-weight:700;color:var(--text)">${regimeLabel}</div>
      </div>
      <div style="text-align:center">
        <div style="font-size:10px;color:var(--text2)">目标暴露</div>
        <div style="font-size:16px;font-weight:700;color:var(--buy)">${expPct}</div>
      </div>
    </div>
    ${stocks ? `<table style="width:100%;border-collapse:collapse">
      <thead><tr style="border-bottom:1px solid rgba(255,255,255,0.1)">
        <th style="text-align:left;font-size:10px;color:var(--text2);padding:4px 0">持仓</th>
        <th style="text-align:right;font-size:10px;color:var(--text2)">Beta</th>
        <th style="text-align:right;font-size:10px;color:var(--text2)">权重</th>
      </tr></thead>
      <tbody>${stocks}</tbody>
    </table>` : ''}
    <div style="margin-top:6px;font-size:10px;color:var(--text2)">Beta&gt;1.2=高波动(红) · &lt;0.8=低波动(绿) · 暴露倍数已融入买入定仓</div>`;
}

async function loadPortfolioWeights() {
  const el = document.getElementById('portfolioWeightsPanel');
  if (!el) return;
  const data = await api('/api/portfolio/weights');
  if (!data || !data.success) {
    el.innerHTML = `<div style="color:var(--text2);padding:12px">${data?.error || '暂无数据'}</div>`;
    return;
  }
  const positions = data.positions || [];
  if (!positions.length) {
    el.innerHTML = '<div style="color:var(--text2);padding:12px">空仓，无需调仓</div>';
    return;
  }
  const s = data.summary || {};
  const statusColor = s.status === '均衡' ? 'var(--buy)' : 'var(--warn)';
  const rows = positions.map(p => {
    const devPct = (p.deviation * 100).toFixed(1);
    const devColor = p.action === '减仓' ? 'var(--sell)' : p.action === '加仓' ? 'var(--buy)' : 'var(--text2)';
    const barW = Math.min(Math.abs(p.deviation) * 400, 60);
    return `<tr style="border-bottom:1px solid rgba(255,255,255,0.04)">
      <td style="padding:5px 0;font-size:11px;color:var(--text)">${p.stock_name}</td>
      <td style="text-align:right;font-size:11px">${(p.actual_weight*100).toFixed(1)}%</td>
      <td style="text-align:right;font-size:11px;color:var(--text2)">${(p.ideal_weight*100).toFixed(1)}%</td>
      <td style="text-align:right;font-weight:700;color:${devColor}">${devPct >= 0 ? '+' : ''}${devPct}%</td>
      <td style="padding:5px 8px">
        <div style="display:inline-block;width:${barW}px;height:6px;background:${devColor};border-radius:3px;vertical-align:middle"></div>
      </td>
      <td style="text-align:center;font-size:11px;color:${devColor};font-weight:700">${p.action}</td>
    </tr>`;
  }).join('');
  el.innerHTML = `
    <div style="margin-bottom:8px;font-size:12px;color:var(--text2)">
      总市值 <b style="color:var(--text)">${(s.total_mv/10000).toFixed(2)}万</b>
      &nbsp;·&nbsp; 现金比 <b style="color:var(--text)">${(s.cash_ratio*100).toFixed(1)}%</b>
      &nbsp;·&nbsp; 状态 <b style="color:${statusColor}">${s.status}</b>
    </div>
    <table style="width:100%;border-collapse:collapse">
      <thead><tr style="border-bottom:1px solid rgba(255,255,255,0.1)">
        <th style="text-align:left;font-size:10px;color:var(--text2);padding:4px 0">名称</th>
        <th style="text-align:right;font-size:10px;color:var(--text2)">实际</th>
        <th style="text-align:right;font-size:10px;color:var(--text2)">理想</th>
        <th style="text-align:right;font-size:10px;color:var(--text2)">偏差</th>
        <th style="font-size:10px;color:var(--text2)"></th>
        <th style="text-align:center;font-size:10px;color:var(--text2)">建议</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

async function manualSell(stockCode, shares) {
  if (!confirm(`确认卖出 ${stockCode} ${shares}股？`)) return;
  const result = await api('/api/trade/sell', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ stock_code: stockCode, shares: shares, reason: '手动卖出' })
  });
  if (result && result.success) {
    notify(`卖出 ${stockCode} ${shares}股 成功`, 'sell');
    loadPositions();
  } else {
    notify(`卖出失败: ${result?.error || '未知错误'}`, 'sell');
  }
}

// ── 账户2 (板块动量) ──────────────────────────────────────────────────

async function loadPositions2() {
  try {
    const summary = await api('/api/account2/summary');
    if (!summary) return;

    document.getElementById('account2Cards').innerHTML = `
      <div class="card stat-card">
        <div class="label">总资产</div>
        <div class="value" style="color:#ff6d00">${(summary.total_asset / 10000).toFixed(2)}<span style="font-size:12px">万</span></div>
        <div class="sub ${summary.cumulative_return_pct >= 0 ? 'up' : 'down'}">${summary.cumulative_return_pct >= 0 ? '+' : ''}${summary.cumulative_return_pct}%</div>
      </div>
      <div class="card stat-card">
        <div class="label">可用资金</div>
        <div class="value" style="color:#fff">${(summary.available_cash / 10000).toFixed(2)}<span style="font-size:12px">万</span></div>
        <div class="sub">冻结 ${(summary.frozen / 10000).toFixed(2)}万</div>
      </div>
      <div class="card stat-card">
        <div class="label">持仓市值</div>
        <div class="value" style="color:#448aff">${(summary.position_value / 10000).toFixed(2)}<span style="font-size:12px">万</span></div>
        <div class="sub">${summary.position_count} 只股票</div>
      </div>
      <div class="card stat-card">
        <div class="label">初始资金</div>
        <div class="value" style="color:var(--text2)">${(summary.initial_capital / 10000).toFixed(0)}<span style="font-size:12px">万</span></div>
        <div class="sub">板块动量轮动</div>
      </div>`;
    revealCards(document.getElementById('account2Cards'));

    const positions = summary.positions || [];
    document.getElementById('positions2Table').innerHTML = positions.length ? `
      <table><thead><tr><th>代码</th><th>名称</th><th>板块</th><th>持仓</th><th>成本</th><th>现价</th><th>市值</th><th>盈亏</th><th>持有天数</th><th>操作</th></tr></thead>
      <tbody>${positions.map(p => {
        const profit = p.current_price ? ((p.current_price - p.avg_cost) / p.avg_cost * 100).toFixed(2) : 0;
        const holdDays = p.buy_date ? Math.floor((new Date() - new Date(p.buy_date)) / 86400000) : 0;
        return `
        <tr>
          <td class="clickable-stock" data-code="${p.stock_code}">${p.stock_code}</td>
          <td class="clickable-stock" data-code="${p.stock_code}">${p.stock_name}</td>
          <td style="color:var(--text2);font-size:11px">${p.sector || ''}</td>
          <td>${p.shares}股</td>
          <td>${p.avg_cost.toFixed(2)}</td>
          <td>${p.current_price.toFixed(2)}</td>
          <td>${((p.current_price||0)*p.shares).toFixed(0)}</td>
          <td class="${profit >= 0 ? 'up' : 'down'}">${profit >= 0 ? '+' : ''}${profit}%</td>
          <td>${holdDays}天</td>
          <td><button class="btn btn-danger btn-sm" onclick="manualSell2('${p.stock_code}', ${p.shares})">卖出</button></td>
        </tr>`;
      }).join('')}</tbody></table>` : '<div style="color:var(--text2);padding:20px;text-align:center">暂无持仓</div>';

    loadTrades2();
    loadAssetCurve2();
  } catch(e) {
    console.error('loadPositions2 error:', e);
  }
}

async function loadTrades2() {
  try {
    const data = await api('/api/account2/trades');
    if (!data || !Array.isArray(data)) return;
    document.getElementById('trades2Table').innerHTML = data.length ? `
      <table><thead><tr><th>时间</th><th>代码</th><th>板块</th><th>方向</th><th>价格</th><th>数量</th><th>盈亏</th><th>原因</th></tr></thead>
      <tbody>${data.slice(0, 50).map(t => {
        const pnl = t.pnl_amount || 0;
        const pnlPct = t.pnl_pct || 0;
        return `
        <tr>
          <td style="font-size:11px">${t.created_at.slice(5,16)}</td>
          <td>${t.stock_code}</td>
          <td style="color:var(--text2);font-size:11px">${t.sector || ''}</td>
          <td class="${t.direction === 'buy' ? 'up' : 'down'}">${t.direction === 'buy' ? '买' : '卖'}</td>
          <td>${t.price.toFixed(2)}</td>
          <td>${t.shares}</td>
          <td class="${pnl >= 0 ? 'up' : 'down'}">${t.direction === 'sell' ? (pnl >= 0 ? '+' : '') + pnl.toFixed(0) + '(' + (pnlPct >= 0 ? '+' : '') + pnlPct.toFixed(1) + '%)' : '-'}</td>
          <td style="max-width:150px;overflow:hidden;text-overflow:ellipsis;font-size:11px">${t.trigger_reason || ''}</td>
        </tr>`;
      }).join('')}</tbody></table>` : '<div style="color:var(--text2);padding:20px;text-align:center">暂无记录</div>';
  } catch(e) {
    console.error('loadTrades2 error:', e);
  }
}

async function loadAssetCurve2() {
  try {
    const data = await api('/api/account2/return-curve');
    if (!data || !data.dates || data.dates.length < 2) return;
    Charts.initReturnCurve2('asset2Chart');
    Charts.renderReturnCurve2(data);
  } catch(e) {
    console.error('loadAssetCurve2 error:', e);
  }
}

async function manualSell2(stockCode, shares) {
  if (!confirm(`确认从账户2卖出 ${stockCode} ${shares}股？`)) return;
  const result = await api('/api/account2/sell', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ stock_code: stockCode, shares: shares, reason: '手动卖出' })
  });
  if (result && result.success) {
    notify(`账户2卖出 ${stockCode} 成功`, 'sell');
    loadPositions2();
  } else {
    notify(`账户2卖出失败: ${result?.error || '未知错误'}`, 'sell');
  }
}
