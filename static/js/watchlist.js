let _lastWatchAnomalies = [];

async function loadWatchlist() {
  const data = await api('/api/watchlist');
  if (!data || !Array.isArray(data)) return;

  if (!data.length) {
    document.getElementById('watchlistTable').innerHTML =
      '<span style="color:var(--text2)">暂无自选股票，在上方输入代码添加</span>';
    return;
  }

  document.getElementById('watchlistTable').innerHTML = `
    <table><thead><tr><th>代码</th><th>名称</th><th>现价</th><th>涨跌幅</th><th>量比</th><th>换手率</th><th>操作</th></tr></thead>
    <tbody>${data.map(s => {
      const change = parseFloat(s.change_pct) || 0;
      const absChange = Math.abs(change);
      const isAnomaly = absChange >= 2 || (parseFloat(s.volume_ratio) || 0) >= 3;
      const rowClass = isAnomaly ? 'watchlist-anomaly-row' : '';
      return `
      <tr class="${rowClass}">
        <td class="clickable-stock" data-code="${s.stock_code}">${s.stock_code}</td>
        <td class="clickable-stock" data-code="${s.stock_code}">${s.stock_name}</td>
        <td>${s.price || '-'}</td>
        <td class="${change >= 0 ? 'up' : 'down'}" style="font-weight:700">${change >= 0 ? '+' : ''}${change.toFixed(2)}%</td>
        <td>${s.volume_ratio || '-'}</td>
        <td>${s.turnover || '-'}%</td>
        <td><button class="btn btn-danger btn-sm" onclick="removeFromWatchlist('${s.stock_code}')">删除</button></td>
      </tr>`;
    }).join('')}</tbody></table>`;
}

async function addToWatchlist() {
  const input = document.getElementById('watchlistInput');
  const code = input.value.trim();
  if (!code) { notify('请输入股票代码'); return; }
  const result = await api('/api/watchlist/add', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ stock_code: code })
  });
  if (result && result.success) {
    notify(`${result.stock_name}(${code}) 已加入自选`, 'buy');
    input.value = '';
    loadWatchlist();
  } else {
    notify(result?.error || '添加失败', 'alert');
  }
}

async function removeFromWatchlist(code) {
  await api(`/api/watchlist/${code}`, { method: 'DELETE' });
  loadWatchlist();
}

document.getElementById('watchlistInput')?.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') addToWatchlist();
});

async function checkWatchlistAnomaly() {
  const data = await api('/api/watchlist/anomaly');
  if (!data || !Array.isArray(data) || !data.length) return;

  const newAnomalies = data.filter(a =>
    !_lastWatchAnomalies.some(p => p.stock_code === a.stock_code)
  );
  const cleared = _lastWatchAnomalies.filter(p =>
    !data.some(a => a.stock_code === p.stock_code)
  );

  if (newAnomalies.length > 0) {
    const banner = document.getElementById('superAlertBanner');
    const names = newAnomalies.map(a => `${a.stock_name} ${a.change_pct >= 0 ? '+' : ''}${a.change_pct.toFixed(1)}%`).join('、');
    banner.textContent = `自选异动: ${names}`;
    banner.style.display = 'block';
    clearTimeout(banner._timeout);
    banner._timeout = setTimeout(() => { banner.style.display = 'none'; }, 5000);

    newAnomalies.forEach(a => {
      const emoji = a.alert_type === '急涨' ? '🔴' : a.alert_type === '急跌' ? '🟢' : '🟡';
      notifyWL(`${emoji} 自选异动: ${a.stock_name}(${a.stock_code}) ${a.alert_type} ${a.change_pct >= 0 ? '+' : ''}${a.change_pct.toFixed(1)}%`);
    });
  }

  if (cleared.length > 0) {
    const banner = document.getElementById('superAlertBanner');
    if (data.length === 0) {
      banner.style.display = 'none';
    }
  }

  _lastWatchAnomalies = data;
}

function notifyWL(msg) {
  const n = document.createElement('div');
  n.className = 'notification watchlist-alert';
  n.innerHTML = '&#x26A0; ' + msg;
  document.body.appendChild(n);
  setTimeout(() => {
    n.style.opacity = '0';
    n.style.transform = 'translateX(120%)';
    n.style.transition = 'all .3s ease';
    setTimeout(() => n.remove(), 300);
  }, 4000);
}
