var currentReviewDate = '';
var availableReviewDates = [];

async function loadJournal() {
  const data = await api('/api/journal/trades');
  if (!data || !Array.isArray(data)) return;
  document.getElementById('journalTable').innerHTML = data.length ? `
    <table><thead><tr><th>时间</th><th>代码</th><th>名称</th><th>方向</th><th>价格</th><th>数量</th><th>金额</th><th>盈亏</th><th>触发原因</th></tr></thead>
    <tbody>${data.map(t => `
      <tr>
        <td>${t.created_at}</td><td class="clickable-stock" data-code="${t.stock_code}">${t.stock_code}</td><td class="clickable-stock" data-code="${t.stock_code}">${t.stock_name}</td>
        <td class="${t.direction === 'buy' ? 'up' : 'down'}">${t.direction === 'buy' ? '买入' : '卖出'}</td>
        <td>${t.price.toFixed(2)}</td><td>${t.shares}股</td><td>${t.amount.toFixed(0)}</td>
        <td class="${t.pnl_amount >= 0 ? 'up' : 'down'}">${t.pnl_amount ? (t.pnl_amount >= 0 ? '+' : '') + t.pnl_amount.toFixed(2) : '-'}</td>
        <td>${t.trigger_reason || ''}</td>
      </tr>`).join('')}</tbody></table>` : '<div style="color:var(--text2);padding:20px;text-align:center">暂无交易记录</div>';
}

async function loadReview(dateOverride) {
  // Load available dates for navigation first
  if (!availableReviewDates.length) {
    const datesRes = await api('/api/review/dates');
    if (datesRes && Array.isArray(datesRes)) {
      // API returns DESC order, reverse to ASC so delta +/- matches calendar direction
      availableReviewDates = datesRes.slice().reverse();
    }
  }

  // Default to latest available review, not today
  const resolvedDate = dateOverride || currentReviewDate || (availableReviewDates.length ? availableReviewDates[availableReviewDates.length - 1] : '');
  const query = resolvedDate ? '?date=' + resolvedDate : '';

  const [daily, stats, curveData, suggestions, buyAnalysis] = await Promise.all([
    api('/api/review/daily' + query),
    api('/api/review/stats'),
    api('/api/account/curve'),
    api('/api/review/suggestions'),
    api('/api/review/buy_analysis' + query),
  ]);

  // Update current date
  if (daily && daily.date) {
    currentReviewDate = daily.date;
  } else if (resolvedDate) {
    currentReviewDate = resolvedDate;
  }

  // Update date picker and nav info
  var picker = document.getElementById('reviewDatePicker');
  if (picker && currentReviewDate) {
    picker.value = currentReviewDate;
  }
  var info = document.getElementById('reviewDateInfo');
  if (info && availableReviewDates.length) {
    info.textContent = '共 ' + availableReviewDates.length + ' 条复盘记录';
  }

  if (daily && daily.date) {
    document.getElementById('dailyReview').innerHTML =
      '<div style="margin-bottom:12px">' +
        '<span style="font-size:14px;font-weight:600;color:#fff">' + daily.date + '</span>' +
        '<span class="' + (daily.daily_return_pct >= 0 ? 'up' : 'down') + '" style="margin-left:12px;font-size:16px;font-weight:700">' +
          (daily.daily_return_pct >= 0 ? '+' : '') + daily.daily_return_pct + '%</span>' +
      '</div>' +
      '<div style="display:flex;gap:20px;margin-bottom:12px;font-size:12px">' +
        '<span>盈亏: <b class="' + (daily.daily_pnl >= 0 ? 'up' : 'down') + '">' + (daily.daily_pnl >= 0 ? '+' : '') + (daily.daily_pnl || 0).toFixed(2) + '</b></span>' +
        '<span>交易: <b>' + daily.total_trades + '</b>笔</span>' +
        '<span>胜率: <b>' + (daily.total_trades ? (daily.win_trades / daily.total_trades * 100).toFixed(0) : 0) + '%</b></span>' +
      '</div>' +
      '<div style="font-size:12px;color:var(--text2);line-height:1.6">' + (daily.review_text || '暂无复盘内容') + '</div>' +
      (daily.strategy_issues ? '<div style="margin-top:8px;font-size:12px"><span style="color:#ffab00">问题:</span> ' + daily.strategy_issues + '</div>' : '') +
      (daily.improvement_notes ? '<div style="margin-top:4px;font-size:12px"><span style="color:#00bfa5">改进:</span> ' + daily.improvement_notes + '</div>' : '') +
      (daily.review_text && daily.review_text.indexOf('自选股') >= 0 ?
        '<div style="margin-top:12px;padding:10px;background:rgba(245,166,35,0.06);border:1px solid rgba(245,166,35,0.15);border-radius:8px;font-size:12px;line-height:1.7">' +
          '<div style="color:var(--gold);font-weight:700;margin-bottom:4px">自选股回顾</div>' +
          daily.review_text.split('；').filter(function(p) { return p.indexOf('自选股') >= 0 || p.indexOf('最强') >= 0 || p.indexOf('最弱') >= 0; }).map(function(p) { return '<div>' + p + '</div>'; }).join('') +
        '</div>' : '');
  } else if (currentReviewDate) {
    document.getElementById('dailyReview').innerHTML =
      '<div style="color:var(--text2);padding:20px;text-align:center">' + currentReviewDate + ' 暂无复盘记录<br><small>该日期可能不是交易日，或复盘尚未生成</small></div>';
  } else {
    document.getElementById('dailyReview').innerHTML = '<div style="color:var(--text2);padding:20px;text-align:center">暂无复盘数据<br><small>系统将在每日15:10自动生成复盘</small></div>';
  }

  document.getElementById('strategySuggestions').innerHTML = suggestions?.suggestions?.length ?
    suggestions.suggestions.map(function(s) { return '<div style="padding:6px 0;font-size:12px;border-bottom:1px solid var(--border)">' + s + '</div>'; }).join('') :
    '<div style="color:var(--text2);padding:10px">暂无建议，积累更多交易数据后自动生成</div>';

  // --- 今日买入分析 ---
  var regimeMap = {trending_up:'趋势上行', trending_down:'趋势下行', ranging:'震荡', transitional:'过渡期', neutral:'中性'};
  var regimeEl = document.getElementById('buyAnalysisRegime');
  var btEl = document.getElementById('buyAnalysisTable');
  if (regimeEl && buyAnalysis) regimeEl.textContent = '当前市场: ' + (regimeMap[buyAnalysis.regime] || buyAnalysis.regime);
  if (btEl) {
    if (!buyAnalysis || !buyAnalysis.trades || !buyAnalysis.trades.length) {
      btEl.innerHTML = '<div style="color:var(--text2);padding:12px;text-align:center">当日无买入交易</div>';
    } else {
      btEl.innerHTML = '<table><thead><tr><th>代码</th><th>名称</th><th>策略</th><th>买点信号</th><th>价格</th><th>数量</th><th>历史胜率</th><th>仓位建议</th></tr></thead><tbody>' +
        buyAnalysis.trades.map(function(t) {
          var adviceClass = t.advice_color === 'up' ? 'up' : t.advice_color === 'down' ? 'down' : '';
          var adviceStyle = t.advice_color === 'warn' ? 'color:#ffab00;font-weight:600' : 'font-weight:600';
          return '<tr>' +
            '<td class="clickable-stock" data-code="' + t.stock_code + '">' + t.stock_code + '</td>' +
            '<td class="clickable-stock" data-code="' + t.stock_code + '">' + t.stock_name + '</td>' +
            '<td><span style="background:rgba(0,180,255,0.1);color:#4fc3f7;padding:2px 6px;border-radius:4px;font-size:11px">' + t.strategy + '</span></td>' +
            '<td style="font-size:11px;color:var(--text2)">' + t.entry_signal + '</td>' +
            '<td>' + t.price.toFixed(2) + '</td>' +
            '<td>' + t.shares + '股</td>' +
            '<td>' + (t.win_rate !== null ? t.win_rate + '%（' + t.sample_count + '笔）' : '<span style="color:var(--text2)">暂无</span>') + '</td>' +
            '<td class="' + adviceClass + '" style="' + adviceStyle + '">' + t.advice + '</td>' +
          '</tr>';
        }).join('') + '</tbody></table>';
    }
  }

  if (curveData && Array.isArray(curveData) && curveData.length >= 2) {
    var dates = curveData.map(function(d) { return d.date; });
    var dailyReturns = curveData.map(function(d) { return d.daily_return_pct || 0; });
    var cumulative = curveData.map(function(d) { return d.cumulative_return_pct || 0; });
    Charts.renderPnl(dates, dailyReturns, cumulative);
  }
}

function changeReviewDate(delta) {
  if (!availableReviewDates.length) {
    // Try to navigate by calendar date
    var d = new Date(currentReviewDate || new Date());
    d.setDate(d.getDate() + delta);
    var newDate = d.toISOString().slice(0, 10);
    loadReview(newDate);
    return;
  }
  var idx = availableReviewDates.indexOf(currentReviewDate);
  if (idx < 0) {
    // Current date not in list, find closest
    var target = currentReviewDate;
    if (delta < 0) {
      for (var i = availableReviewDates.length - 1; i >= 0; i--) {
        if (availableReviewDates[i] < target) { idx = i; break; }
      }
    } else {
      for (var i = 0; i < availableReviewDates.length; i++) {
        if (availableReviewDates[i] > target) { idx = i; break; }
      }
    }
    if (idx < 0) idx = delta < 0 ? 0 : availableReviewDates.length - 1;
  }
  var newIdx = idx + delta;
  if (newIdx >= 0 && newIdx < availableReviewDates.length) {
    loadReview(availableReviewDates[newIdx]);
  }
}

function jumpReviewDate() {
  var picker = document.getElementById('reviewDatePicker');
  if (picker && picker.value) {
    loadReview(picker.value);
  }
}

function goToTodayReview() {
  var today = new Date().toISOString().slice(0, 10);
  currentReviewDate = today;
  loadReview(today);
}
