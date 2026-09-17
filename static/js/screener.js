let screenerRunning = false;
let screenerResultsCache = [];

function escQ(str) { return String(str).replace(/'/g, "\\'"); }

async function loadScreener() {
  const data = await api('/api/screen/candidates');
  if (data && data.length) {
    screenerResultsCache = data;
  }
  renderScreenerResults(data);
}

async function runScreener() {
  if (screenerRunning) return;
  screenerRunning = true;
  document.getElementById('screenerStatus').innerHTML = '<span style="color:#ffab00">⏳ 筛选中...</span>';
  try {
    const data = await api('/api/screen/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        level1: { exclude_st: true, max_price: 100, exclude_loss_years: 2, revenue_growth_positive: true },
        level2: { pe_min: 10, pe_max: 60, roe_min: 8, debt_max: 70, cashflow_positive: true },
        level3: { ma_cross: true, macd_cross: true, kdj_cross: false, rsi_oversold: false, volume_break: true }
      })
    });
    screenerResultsCache = data || [];
    document.getElementById('screenerStatus').innerHTML =
      `<span style="color:#00e676">✓ 筛选完成，共 ${data?.length || 0} 只</span>`;
    renderScreenerResults(data);
  } catch(e) {
    document.getElementById('screenerStatus').innerHTML = '<span style="color:#ff1744">✗ 筛选出错</span>';
  }
  screenerRunning = false;
}

function renderScreenerResults(data) {
  if (!data || !Array.isArray(data) || !data.length) {
    document.getElementById('screenerTable').innerHTML =
      '<div style="color:var(--text2);padding:20px;text-align:center">暂无选股结果，点击上方按钮执行筛选</div>';
    return;
  }
  document.getElementById('screenerTable').innerHTML = `
    <table><thead><tr><th>排名</th><th>代码</th><th>名称</th><th>评分</th><th>现价</th><th>涨跌幅</th><th>选中原因</th><th>操作</th></tr></thead>
    <tbody>${data.map((s, i) => {
      const chg = parseFloat(s.change_pct) || 0;
      const chgClass = chg > 0 ? 'up' : chg < 0 ? 'down' : '';
      return `
      <tr>
        <td>${i + 1}</td>
        <td class="screener-stock" data-code="${s.stock_code}">${s.stock_code}</td>
        <td class="screener-stock" data-code="${s.stock_code}">${s.stock_name}</td>
        <td style="color:#ffab00;font-weight:700">${s.score?.toFixed(1) || '-'}</td>
        <td class="${chgClass}">${s.price ? '¥' + parseFloat(s.price).toFixed(2) : '-'}</td>
        <td class="${chgClass}" style="font-weight:700">${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%</td>
        <td style="max-width:180px;overflow:hidden;text-overflow:ellipsis;font-size:11px">${s.reasons || ''}</td>
        <td><button class="btn btn-primary btn-sm" onclick="event.stopPropagation();buyFromScreener('${escQ(s.stock_code)}', '${escQ(s.stock_name)}', ${s.price || 0})">买入</button></td>
      </tr>`;
    }).join('')}</tbody></table>`;
}

const ScreenerLogicModal = {
  openByCode(code) {
    const item = screenerResultsCache.find(s => s.stock_code === code);
    if (item) this.open(item);
  },

  open(item) {
    const overlay = document.getElementById('screenerLogicModal');
    document.getElementById('logicModalTitle').textContent =
      `选股逻辑 — ${item.stock_name}(${item.stock_code})`;

    const ld = item.level_details;
    let bodyHtml = '';

    // Stock header with score
    const chg = parseFloat(item.change_pct) || 0;
    const chgStr = (chg >= 0 ? '+' : '') + chg.toFixed(2) + '%';
    const chgColor = chg >= 0 ? 'var(--up)' : 'var(--down)';

    bodyHtml += `
      <div class="logic-stock-header">
        <div>
          <div class="logic-stock-name">${item.stock_name} <span style="font-size:14px;color:${chgColor}">${chgStr}</span></div>
          <div class="logic-stock-code">${item.stock_code} · 现价 ¥${item.price?.toFixed(2) || '-'}</div>
        </div>
        <div class="logic-stock-score">
          <div class="score-num">${item.score?.toFixed(0) || '-'}</div>
          <div class="score-label">综合评分</div>
        </div>
      </div>`;

    // Level details
    if (ld) {
      ['level1', 'level2', 'level3'].forEach(levelKey => {
        const level = ld[levelKey];
        if (!level) return;
        bodyHtml += `<div class="logic-level">
          <div class="logic-level-header">${level.name}</div>`;
        (level.checks || []).forEach(check => {
          let icon, iconClass;
          if (check.passed) {
            icon = '✓'; iconClass = 'pass';
          } else {
            icon = '✗'; iconClass = 'fail';
          }
          bodyHtml += `
            <div class="logic-check-row">
              <span class="logic-check-icon ${iconClass}">${icon}</span>
              <span class="logic-check-name">${check.name}</span>
              <span class="logic-check-detail">${check.detail || ''}</span>
            </div>`;
        });
        bodyHtml += `</div>`;
      });
    }

    // Score breakdown
    if (item.score_items && Object.keys(item.score_items).length) {
      bodyHtml += `<div class="logic-score-breakdown">
        <div class="logic-score-title">评分明细</div>`;
      for (const [name, pts] of Object.entries(item.score_items)) {
        bodyHtml += `<div class="logic-score-item">
          <span>${name}</span>
          <span class="score-val">+${pts}</span>
        </div>`;
      }
      bodyHtml += `<div class="logic-score-item" style="border-top:1px solid rgba(255,255,255,0.06);margin-top:4px;padding-top:6px">
        <span style="font-weight:700">合计</span>
        <span class="score-val" style="font-size:15px">${item.score?.toFixed(0)}分</span>
      </div></div>`;
    }

    // Also show flat reasons
    if (item.reasons) {
      bodyHtml += `<div style="margin-top:12px;padding:10px 14px;background:rgba(255,255,255,0.02);border-radius:8px;font-size:12px;color:var(--text2)">
        <span style="color:var(--gold-light);font-weight:700">选中原因: </span>${item.reasons}
      </div>`;
    }

    document.getElementById('logicModalBody').innerHTML = bodyHtml;
    overlay.style.display = 'flex';
  },

  close() {
    document.getElementById('screenerLogicModal').style.display = 'none';
  }
};

// Click delegation for screener stock cells
document.addEventListener('click', (e) => {
  const cell = e.target.closest('.screener-stock');
  if (!cell) return;
  const code = cell.dataset.code;
  if (code) ScreenerLogicModal.openByCode(code);
});

document.getElementById('screenerLogicModal')?.addEventListener('click', (e) => {
  if (e.target.id === 'screenerLogicModal') ScreenerLogicModal.close();
});

async function buyFromScreener(stockCode, stockName, price) {
  const amount = prompt(`买入 ${stockName}(${stockCode}) 现价 ${price}\n输入买入金额（元）：`, '160000');
  if (!amount) return;
  const result = await api('/api/trade/buy', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ stock_code: stockCode, amount: parseFloat(amount), reason: '策略选股买入' })
  });
  if (result && result.success) {
    notify(`买入 ${stockName} 成功`, 'buy');
  } else {
    notify(`买入失败: ${result?.error || '未知错误'}`, 'buy');
  }
}
