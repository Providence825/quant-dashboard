async function loadDashboard() {
  try {
    await Promise.all([loadIndices(), loadSentiment(), loadTop20(), loadAnomaly(), loadSectors(), loadTradeStatus(), loadOvernightUS(), loadCommodityBoard()]);
  } catch(e) {
    console.error('loadDashboard error:', e);
  }
}

function escOvus(s) { return String(s == null ? '' : s).replace(/'/g, ''); }

async function loadOvernightUS() {
  try {
    const data = await api('/api/crossasset/overnight');
    const box = document.getElementById('overnightUSContent');
    if (!box) return;
    if (!data || data.error || !Array.isArray(data.us) || !data.us.length) {
      box.innerHTML = '<span style="color:var(--text2);font-size:11px">隔夜美股数据暂不可用</span>';
      return;
    }
    const cells = data.us.map((u, i) => {
      const c = u.change_pct || 0;
      const cc = c >= 0 ? 'up' : 'down';
      const hasConcept = (u.concept_count || 0) > 0;
      const cls = hasConcept ? 'ovus-quote ovus-clickable ovus-has-concept' : 'ovus-quote ovus-clickable';
      const tip = hasConcept ? `title="查看 ${u.name} 关联A股 + 相关新闻"` : `title="查看 ${u.name} 相关新闻"`;
      return `<div class="${cls}" onclick="OvusDrill.open('${u.symbol}','${escOvus(u.name)}')" ${tip}>
        <span class="ovus-rank">${i+1}</span>
        <span class="ovus-name">${u.name} ›</span>
        <span class="${cc}">${c >= 0 ? '+' : ''}${c.toFixed(2)}%</span>
      </div>`;
    }).join('');

    box.innerHTML = `
      <div class="ovus-quotes">${cells}</div>
      <div class="ovus-note">${data.note || ''}</div>`;
  } catch(e) {
    console.error('loadOvernightUS error:', e);
  }
}

const OvusDrill = {
  async open(symbol, name) {
    const overlay = document.getElementById('ovusDrillModal');
    document.getElementById('ovusDrillTitle').textContent = `${name} → 关联A股龙头`;
    document.getElementById('ovusDrillBody').innerHTML = '<div style="color:var(--text2);padding:20px;text-align:center">加载中...</div>';
    overlay.style.display = 'flex';

    const data = await api(`/api/crossasset/drilldown?symbol=${encodeURIComponent(symbol)}`);
    const body = document.getElementById('ovusDrillBody');
    if (!data || data.error) {
      body.innerHTML = '<div style="color:var(--text2);padding:20px;text-align:center">加载失败</div>';
      return;
    }
    const stocks = Array.isArray(data.stocks) ? data.stocks : [];
    const news = Array.isArray(data.news) ? data.news : [];

    const chg = data.change_pct || 0;
    const chgClass = chg >= 0 ? 'up' : 'down';
    const csigs = data.concept_signals || {};
    const sigTags = (data.concepts||[]).map(c => {
      const sig = csigs[c];
      if (sig == null) return `<span class="ovus-drill-secs">${c}</span>`;
      const sc = sig >= 0 ? 'up' : 'down';
      return `<span class="ovus-drill-secs">${c} <span class="${sc}" style="font-size:10px">${sig >= 0 ? '+' : ''}${sig.toFixed(1)}%</span></span>`;
    }).join('');
    const head = `<div class="ovus-drill-head">
      <span>隔夜 ${data.name}</span>
      <span class="${chgClass}" style="font-weight:700;font-family:var(--font-mono)">${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%</span>
      ${sigTags}
    </div>`;

    const newsHtml = news.length ? `
      <div class="ovus-news">
        <div class="ovus-news-title">相关新闻 · 新浪财经 <span class="ovus-news-tag">仅供参考，不参与选股/交易</span></div>
        ${news.map(n => `<a class="ovus-news-item" href="${n.url}" target="_blank" rel="noopener">
          <span class="ovus-news-headline">${n.title}</span>
          <span class="ovus-news-meta">${n.media || ''} ${n.time ? '· '+n.time.slice(0,10) : ''}</span>
        </a>`).join('')}
      </div>` : `<div class="ovus-news"><div class="ovus-news-title">相关新闻 · 新浪财经</div>
        <div style="color:var(--text-muted);font-size:11px;padding:6px 0">暂无相关新闻</div></div>`;

    let stocksHtml;
    if (stocks.length) {
      const rows = stocks.map((s, i) => {
        const c = s.change_pct || 0;
        const cc = c >= 0 ? 'up' : 'down';
        const strat = (s.strategies || []).length
          ? `<span class="ovus-sig-badge">${s.strategies.join('/')}</span>` : '';
        const usSig = s.us_signal != null
          ? `<span class="${s.us_signal >= 0 ? 'up' : 'down'}" style="font-size:11px">${s.us_signal >= 0 ? '+' : ''}${s.us_signal.toFixed(1)}%</span>`
          : '<span style="color:var(--text2)">-</span>';
        return `<tr class="ovus-drill-row" onclick="KlineModal.open('${s.stock_code}','${escOvus(s.stock_name)}')">
          <td>${i+1}. ${s.stock_name} <span class="ovus-code">${s.stock_code}</span>${strat}</td>
          <td style="color:var(--text-muted);font-size:11px">${s.concept}</td>
          <td>${s.price ? '¥'+Number(s.price).toFixed(2) : '-'}</td>
          <td class="${cc}">${c >= 0 ? '+' : ''}${c.toFixed(2)}%</td>
          <td style="color:var(--text2)">${(s.vol_ratio||0).toFixed(2)}</td>
          <td style="font-weight:700;color:var(--accent)">${s.score}</td>
          <td>${usSig}</td>
        </tr>`;
      }).join('');
      stocksHtml = `<table class="ovus-drill-table">
          <thead><tr>
            <th>股票</th><th>概念</th><th>现价</th><th>涨跌</th><th>量比</th><th>评分</th><th title="该概念下所有映射美股的均值涨幅，与回测信号同口径">美股信号</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
        <div class="ovus-note" style="margin-top:14px">评分 = 涨跌%×5 + 量比×8（非交易时段量比为0，退化为按涨幅）。${data.note || ''}</div>`;
    } else {
      stocksHtml = `<div style="color:var(--text-muted);font-size:12px;padding:10px 0">该美股无明确A股概念映射，仅显示相关新闻。</div>`;
    }

    body.innerHTML = `${head}${newsHtml}${stocksHtml}`;
  },

  close() {
    document.getElementById('ovusDrillModal').style.display = 'none';
  }
};

async function loadCommodityBoard() {
  try {
    const data = await api('/api/crossasset/commodity');
    const box = document.getElementById('commodityContent');
    if (!data || !data.items || !data.items.length) {
      box.innerHTML = '<span style="color:var(--text2);font-size:12px">暂无商品行情</span>';
      return;
    }
    const cells = data.items.map((it, i) => {
      const c = it.change_pct || 0;
      const cc = c >= 0 ? 'up' : 'down';
      const hasConcept = (it.concept_count || 0) > 0;
      const sessionTag = it.session === 'intl'
        ? '<span class="commod-session-tag intl">领先</span>'
        : '<span class="commod-session-tag dom">同步</span>';
      const cls = hasConcept ? 'ovus-quote ovus-clickable ovus-has-concept' : 'ovus-quote ovus-clickable';
      const tip = hasConcept ? `title="查看 ${it.name} 关联A股 + 相关新闻"` : `title="查看 ${it.name} 相关新闻"`;
      return `<div class="${cls}" onclick="CommodityDrill.open('${it.symbol}','${escOvus(it.name)}')" ${tip}>
        <span class="ovus-rank">${i+1}</span>
        <span class="ovus-name">${it.name} ${sessionTag}›</span>
        <span class="${cc}">${c >= 0 ? '+' : ''}${c.toFixed(2)}%</span>
      </div>`;
    }).join('');
    box.innerHTML = `
      <div class="ovus-quotes">${cells}</div>
      <div class="ovus-note">${data.note || ''}</div>`;
  } catch(e) {
    console.error('loadCommodityBoard error:', e);
  }
}

const CommodityDrill = {
  async open(symbol, name) {
    const overlay = document.getElementById('commodityDrillModal');
    document.getElementById('commodityDrillTitle').textContent = `${name} → 关联A股龙头`;
    document.getElementById('commodityDrillBody').innerHTML = '<div style="color:var(--text2);padding:20px;text-align:center">加载中...</div>';
    overlay.style.display = 'flex';

    const data = await api(`/api/crossasset/commodity_drilldown?symbol=${encodeURIComponent(symbol)}`);
    const body = document.getElementById('commodityDrillBody');
    if (!data || data.error) {
      body.innerHTML = '<div style="color:var(--text2);padding:20px;text-align:center">加载失败</div>';
      return;
    }

    const news = data.news || [];
    const chg = data.change_pct || 0;
    const chgClass = chg >= 0 ? 'up' : 'down';
    const head = `<div class="ovus-drill-head">
      <span>${data.name}</span>
      <span class="${chgClass}" style="font-weight:700;font-family:var(--font-mono)">${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%</span>
      ${(data.concepts||[]).length ? `<span class="ovus-drill-secs">关联概念：${data.concepts.join(' · ')}</span>` : ''}
    </div>`;

    const newsHtml = news.length ? `
      <div class="ovus-news">
        <div class="ovus-news-title">相关新闻 · 新浪财经 <span class="ovus-news-tag">仅供参考，不参与选股/交易</span></div>
        ${news.map(n => `<a class="ovus-news-item" href="${n.url}" target="_blank" rel="noopener">
          <span class="ovus-news-headline">${n.title}</span>
          <span class="ovus-news-meta">${n.media || ''} ${n.time ? '· '+n.time.slice(0,10) : ''}</span>
        </a>`).join('')}
      </div>` : `<div class="ovus-news"><div class="ovus-news-title">相关新闻 · 新浪财经</div>
        <div style="color:var(--text-muted);font-size:11px;padding:6px 0">暂无相关新闻</div></div>`;

    let stocksHtml;
    if ((data.stocks || []).length) {
      const rows = data.stocks.map((s, i) => {
        const c = s.change_pct || 0;
        const cc = c >= 0 ? 'up' : 'down';
        const strat = (s.strategies || []).length
          ? `<span class="ovus-sig-badge">${s.strategies.join('/')}</span>` : '';
        return `<tr class="ovus-drill-row" onclick="KlineModal.open('${s.stock_code}','${escOvus(s.stock_name)}')">
          <td>${i+1}. ${s.stock_name} <span class="ovus-code">${s.stock_code}</span>${strat}</td>
          <td style="color:var(--text-muted);font-size:11px">${s.concept}</td>
          <td>${s.price ? '¥'+Number(s.price).toFixed(2) : '-'}</td>
          <td class="${cc}">${c >= 0 ? '+' : ''}${c.toFixed(2)}%</td>
          <td style="color:var(--text-muted)">${s.vol_ratio ? s.vol_ratio.toFixed(2) : '-'}</td>
          <td style="font-weight:700;color:var(--accent)">${s.score}</td>
        </tr>`;
      }).join('');
      stocksHtml = `<table class="ovus-drill-table">
          <thead><tr>
            <th>股票</th><th>概念</th><th>现价</th><th>涨跌</th><th>量比</th><th>评分</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
        <div class="ovus-note" style="margin-top:14px">评分 = 涨跌%×5 + 量比×8（非交易时段量比为0，退化为按涨幅）。${data.note || ''}</div>`;
    } else {
      stocksHtml = `<div style="color:var(--text-muted);font-size:12px;padding:10px 0">该品种无明确A股概念映射，仅显示相关新闻。</div>`;
    }

    body.innerHTML = `${head}${newsHtml}${stocksHtml}`;
  },

  close() {
    document.getElementById('commodityDrillModal').style.display = 'none';
  }
};

async function loadIndices() {
  try {
    const data = await api('/api/market/index');
    if (!data || data.error || !Array.isArray(data)) {
      document.getElementById('indicesContent').innerHTML = '<span style="color:#ff5252">指数数据加载失败</span>';
      console.error('loadIndices: invalid data', data);
      return;
    }
    document.getElementById('indicesContent').innerHTML = data.map(i =>
      `<div class="index-item">
        <span class="index-name">${i.name}</span>
        <span class="index-price">${i.price.toFixed(2)}</span>
        <span class="${i.change_pct >= 0 ? 'up' : 'down'}">${i.change_pct >= 0 ? '+' : ''}${i.change_pct.toFixed(2)}%</span>
      </div>`
    ).join('');
  } catch(e) {
    console.error('loadIndices error:', e);
    document.getElementById('indicesContent').innerHTML = '<span style="color:#ff5252">指数数据异常</span>';
  }
}

async function loadSentiment() {
  try {
    const [top50, sentData] = await Promise.all([
      api('/api/market/top50'),
      api('/api/sentiment/current'),
    ]);

    let upCount = 0, downCount = 0;
    if (Array.isArray(top50)) {
      upCount = top50.filter(s => s.涨跌幅 > 0).length;
      downCount = top50.filter(s => s.涨跌幅 < 0).length;
    }
    let breadth = 50;
    if (Array.isArray(top50) && top50.length > 0) {
      breadth = Math.min(100, Math.max(0, Math.round(50 + upCount - downCount)));
    }

    // Use real sentiment data if available
    const sentScore = sentData?.sentiment_score ?? breadth;
    const phaseLabel = sentData?.phase_label || '中性';
    const action = sentData?.contrarian_action || 'neutral';
    const posAdj = sentData?.position_adjustment || 0;

    const phaseColors = {
      'euphoria': '#ff3d5a', 'greed': '#ff6b35', 'optimism': '#ffc107',
      'neutral': '#888', 'caution': '#4fc3f7', 'fear': '#2979ff',
      'capitulation': '#00e676'
    };

    let actionText = '';
    if (action === 'reduce' || action === 'caution') {
      actionText = `<div style="color:var(--sell);font-size:11px;margin-top:2px">⚠ 逆向信号: 减仓防御</div>`;
    } else if (action === 'accumulate' || action === 'opportunity') {
      actionText = `<div style="color:var(--buy);font-size:11px;margin-top:2px">💡 逆向信号: 反人性买入机会</div>`;
    }

    document.getElementById('sentimentContent').innerHTML = `
      <div style="margin-bottom:12px">
        <div style="display:flex;justify-content:space-between;font-size:11px;color:var(--text2);margin-bottom:4px">
          <span>🙂 ${upCount} 涨</span>
          <span style="color:${phaseColors[sentData?.phase] || '#888'};font-weight:700">${phaseLabel}</span>
          <span>😟 ${downCount} 跌</span>
        </div>
        <div class="sentiment-meter">
          <div class="meter-bar">
            <div class="meter-dot" style="left:${Math.min(100,Math.max(0, sentScore+50))}%"></div>
          </div>
          <span style="font-weight:700;font-size:14px;color:${sentScore>40?'var(--sell)':sentScore<-40?'var(--buy)':'#fff'}">${sentScore>0?'+':''}${sentScore}</span>
        </div>
        ${actionText || ''}
        ${sentData?.stop_adjustment && sentData.stop_adjustment !== 1 ?
          `<div style="font-size:10px;color:var(--text2);margin-top:2px">止损调整: ${(sentData.stop_adjustment*100).toFixed(0)}%</div>` : ''}
      </div>
      <div style="font-size:10px;color:var(--text2);text-align:center">
        ${sentScore < -40 ? '恐慌至极 → 反向看多' :
          sentScore > 60 ? '极度亢奋 → 警惕见顶' :
          sentScore > 30 ? '偏贪婪 → 注意风险' :
          sentScore < -20 ? '偏恐惧 → 寻找机会' : '中性 — 正常交易'}
      </div>`;
  } catch(e) {}
}

async function loadTop20() {
  const data = await api('/api/market/top50');
  if (!data || !Array.isArray(data)) return;
  const top20 = data.slice(0, 20);
  document.getElementById('top20Table').innerHTML = `
    <table><thead><tr><th>代码</th><th>名称</th><th>现价</th><th>涨跌幅</th><th>换手率</th><th>量比</th></tr></thead>
    <tbody>${top20.map(s => `
      <tr>
        <td class="clickable-stock" data-code="${s.代码}">${s.代码}</td><td class="clickable-stock" data-code="${s.代码}">${s.名称}</td><td>${s.最新价}</td>
        <td class="${s.涨跌幅 >= 0 ? 'up' : 'down'}">${s.涨跌幅 >= 0 ? '+' : ''}${s.涨跌幅}%</td>
        <td>${s.换手率}%</td><td>${s.量比}</td>
      </tr>`).join('')}</tbody></table>`;
}

let _lastAnomalyCount = 0;

async function loadAnomaly() {
  const data = await api('/api/market/anomaly');
  if (!data || !Array.isArray(data)) return;

  if (data.length > _lastAnomalyCount && _lastAnomalyCount > 0) {
    notify(`检测到 ${data.length - _lastAnomalyCount} 只新股异动!`, 'alert');
  }
  _lastAnomalyCount = data.length;
  document.getElementById('anomalyTable').innerHTML = `
    <table><thead><tr><th>代码</th><th>名称</th><th>现价</th><th>涨跌幅</th><th>量比</th><th>类型</th></tr></thead>
    <tbody>${data.map(s => {
      let badgeClass = 'volume', badgeText = s.anomaly_type;
      if (s.anomaly_type === '涨速') { badgeClass = 'surge'; badgeText = '急涨'; }
      else if (s.anomaly_type === '急跌') { badgeClass = 'plunge'; badgeText = '急跌'; }
      return `
      <tr class="anomaly-row">
        <td class="clickable-stock" data-code="${s.代码}">${s.代码}</td><td class="clickable-stock" data-code="${s.代码}">${s.名称}</td><td>${s.最新价}</td>
        <td class="${s.涨跌幅 >= 0 ? 'up' : 'down'}" style="font-weight:700">${s.涨跌幅 >= 0 ? '+' : ''}${s.涨跌幅}%</td>
        <td>${s.量比}</td>
        <td><span class="anomaly-badge ${badgeClass}">${badgeText}</span></td>
      </tr>`}).join('')}</tbody></table>`;
}

async function loadSectors() {
  const data = await api('/api/market/sectors');
  if (data && typeof data === 'object' && !Array.isArray(data)) {
    Charts.renderSector(data);
  }
}

function _isLunchBreak() {
  const now = new Date();
  const t = now.getHours() * 100 + now.getMinutes();
  const day = now.getDay();
  if (day < 1 || day > 5) return false;
  return t >= 1130 && t < 1300;
}

function _tradingStatusText() {
  if (isTradingTime()) return '交易中';
  if (_isLunchBreak()) return '午休中';
  return '已收盘';
}

async function loadTradeStatus() {
  // Update header market status badge
  const msBadge = document.getElementById('marketStatus');
  if (msBadge) {
    const trading = isTradingTime();
    const lunch = _isLunchBreak();
    msBadge.textContent = trading ? '交易中' : (lunch ? '午休中' : '已收盘');
    msBadge.style.background = trading ? 'rgba(0,230,118,0.15)' : (lunch ? 'rgba(255,171,0,0.12)' : 'rgba(138,135,128,0.1)');
    msBadge.style.color = trading ? 'var(--down)' : (lunch ? '#ffab00' : 'var(--text2)');
  }

  // Update auto-trading status badge
  try {
    const sys = await api('/api/system/status');
    if (sys) {
      const autoBadge = document.getElementById('autoStatus');
      if (autoBadge) {
        autoBadge.textContent = sys.auto_trading ? '🔄 自动模式' : '⏸ 手动模式';
        autoBadge.style.color = sys.auto_trading ? '#00e676' : 'var(--text2)';
      }
    }
  } catch(e) {}

  let regimeHtml = '';
  try {
    const [regime, fxSnap] = await Promise.all([
      api('/api/market/regime').catch(() => null),
      api('/api/crossasset/fx').catch(() => null),
    ]);
    let fxLine = '';
    if (fxSnap && fxSnap.rate) {
      const fxColor = fxSnap.color_key === 'green' ? 'var(--buy)' : (fxSnap.color_key === 'red' ? 'var(--sell)' : 'var(--text2)');
      const chSign = fxSnap.change >= 0 ? '+' : '';
      fxLine = `<div>USDCNH: <span style="color:${fxColor};font-weight:600">${fxSnap.rate}(${fxSnap.direction} ${chSign}${fxSnap.change})</span> <span style="font-size:9px;opacity:.6">未验证</span></div>`;
    }
    if (regime) {
      const regimeLabels = {trending_up:'上升趋势',trending_down:'下降趋势',ranging:'震荡整理',transitional:'方向不明'};
      const regimeColors = {trending_up:'var(--buy)',trending_down:'var(--sell)',ranging:'var(--warn)',transitional:'var(--text2)'};
      const strategyLabel = regime.recommended_strategy === 'trend' ? '趋势波段' : '短线博弈';
      const rLabel = regimeLabels[regime.regime] || regime.regime;
      const rColor = regimeColors[regime.regime] || 'var(--text2)';
      const regimeEl = document.getElementById('regimeStatus');
      if (regimeEl) {
        const fxBit = (fxSnap && fxSnap.rate)
          ? ` &nbsp;|&nbsp; USDCNH <span style="color:${fxSnap.color_key==='green'?'var(--buy)':fxSnap.color_key==='red'?'var(--sell)':'var(--text2)'}">${fxSnap.rate}(${fxSnap.direction})</span><span style="font-size:9px;opacity:.6">未验证</span>`
          : '';
        regimeEl.innerHTML = `<span style="color:${rColor};font-weight:700">${rLabel}</span>${fxBit}`;
      }
      regimeHtml = `
        <div style="font-size:11px;color:var(--text2);margin-top:6px;border-top:1px solid var(--border);padding-top:6px">
          <div>行情: <span style="color:${rColor};font-weight:700">${rLabel}</span></div>
          <div>ADX:${regime.adx} | 涨跌比:${regime.breadth}%</div>
          <div>策略: <span style="color:var(--accent)">${strategyLabel}</span></div>
          ${fxLine}
        </div>`;
    }
  } catch(e) {}

  document.getElementById('tradeStatus').innerHTML = `
    <div style="text-align:center;padding:10px">
      <div style="font-size:28px;margin-bottom:4px">${isTradingTime() ? '●' : (_isLunchBreak() ? '◐' : '○')}</div>
      <div style="font-size:14px;font-weight:600;color:#fff">${_tradingStatusText()}</div>
      <div style="font-size:10px;color:var(--text2);margin-top:4px">A股 9:30-11:30 / 13:00-15:00</div>
      ${regimeHtml}
    </div>`;
}

function _renderNotes(data, containerId) {
  if (!data || !Array.isArray(data) || !data.length) {
    document.getElementById(containerId).innerHTML = '<span style="color:var(--text2)">点击上方按钮搜索最新内容</span>';
    return;
  }
  document.getElementById(containerId).innerHTML = data.map(n => {
    // Make URLs clickable
    const html = n.content
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/https?:\/\/[^\s\n]+/g, url => `<a href="${url}" target="_blank" style="color:var(--blue)">${url}</a>`)
      .replace(/\n/g, '<br>');
    return `<div style="padding:6px 0;border-bottom:1px solid var(--border)">
      <div style="color:var(--text2);font-size:10px;margin-bottom:2px">${n.created_at}</div>
      <div style="line-height:1.6;font-size:12px">${html}</div>
    </div>`;
  }).join('');
}

async function loadMarketNotes() {
  const data = await api('/api/notes?source=' + encodeURIComponent('机构一手调研（福总）'));
  _renderNotes(data, 'marketNotesList');
}

async function loadTradingNotes() {
  const data = await api('/api/notes?source=' + encodeURIComponent('B站·来去由心'));
  _renderNotes(data, 'tradingNotesList');
}

async function fetchFuZong() {
  const btn = document.getElementById('btnFetchFuzong');
  const status = document.getElementById('fuzongStatus');
  btn.disabled = true; btn.textContent = '搜索中...';
  status.innerHTML = '<span style="color:#ffab00">正在搜索福总最新观点...</span>';

  try {
    const resp = await api('/api/notes/fetch', { method: 'POST' });
    if (resp && resp.success) {
      status.innerHTML = `<span style="color:#00e676">✓ 找到 ${resp.fuzong} 条福总相关内容</span>`;
      loadMarketNotes();
    } else {
      status.innerHTML = `<span style="color:#ff1744">✗ ${resp?.error || '搜索失败'}</span>`;
    }
  } catch(e) {
    status.innerHTML = '<span style="color:#ff1744">✗ 网络错误</span>';
  }
  btn.disabled = false; btn.textContent = '搜索最新观点';
  setTimeout(() => { status.innerHTML = ''; }, 6000);
}

async function fetchLaiQu() {
  const btn = document.getElementById('btnFetchLaiqu');
  const status = document.getElementById('laiquStatus');
  btn.disabled = true; btn.textContent = '搜索中...';
  status.innerHTML = '<span style="color:#ffab00">正在搜索来去由心最新视频...</span>';

  try {
    const resp = await api('/api/notes/fetch', { method: 'POST' });
    if (resp && resp.success) {
      status.innerHTML = `<span style="color:#00e676">✓ 找到 ${resp.laiqu} 条来去由心最新视频</span>`;
      loadTradingNotes();
    } else {
      status.innerHTML = `<span style="color:#ff1744">✗ ${resp?.error || '搜索失败'}</span>`;
    }
  } catch(e) {
    status.innerHTML = '<span style="color:#ff1744">✗ 网络错误</span>';
  }
  btn.disabled = false; btn.textContent = '搜索最新视频';
  setTimeout(() => { status.innerHTML = ''; }, 6000);
}

function isTradingTime() {
  const now = new Date();
  const h = now.getHours(), m = now.getMinutes();
  const t = h * 100 + m;
  const day = now.getDay();
  if (day < 1 || day > 5) return false;
  if (t < 930 || t > 1500) return false;
  if (t >= 1130 && t < 1300) return false; // 中午休市
  return true;
}
