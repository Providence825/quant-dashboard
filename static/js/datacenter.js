const DataCenter = {
  _polling: null,

  async load() {
    const stats = await api('/api/data/stats');
    const status = await api('/api/data/import/status');

    document.getElementById('dataStats').innerHTML = stats ? `
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
        <div><span style="color:var(--text)">股票数量</span><br>
          <span style="font-size:28px;font-weight:700;color:var(--accent)">${stats.stock_count.toLocaleString()}</span></div>
        <div><span style="color:var(--text)">K线记录</span><br>
          <span style="font-size:28px;font-weight:700;color:var(--accent)">${(stats.kline_count/10000).toFixed(1)}万</span></div>
        <div><span style="color:var(--text)">最新K线</span><br>
          <span style="font-size:28px;font-weight:700;color:var(--accent)">${stats.latest_kline_date || '--'}</span></div>
      </div>
    ` : '暂无数据，请先导入股票列表';

    if (status && status.task) {
      document.getElementById('syncStatus').innerHTML = `
        <div style="font-size:14px">
          <p><span style="color:var(--text)">任务:</span> ${status.task} |
          <span style="color:${status.status==='running'?'var(--accent)':'var(--text2)'}">${status.status}</span></p>
          ${status.total_items ? `<p><span style="color:var(--text)">进度:</span> ${status.processed_items} / ${status.total_items} (${status.progress_pct}%)</p>` : ''}
          ${status.error ? `<p style="color:var(--sell)">错误: ${status.error}</p>` : ''}
        </div>
      `;
    } else {
      document.getElementById('syncStatus').innerHTML = '<span style="color:var(--text2)">无进行中的任务</span>';
    }

    // Auto-poll if a job is running
    if (status && status.status === 'running') {
      if (!this._polling) {
        this._polling = setInterval(() => DataCenter.load(), 3000);
      }
    } else {
      if (this._polling) {
        clearInterval(this._polling);
        this._polling = null;
      }
    }
  },

  // Kick off a background import/sync job, then poll status via load().
  async _kickoff(url, opts, label) {
    document.getElementById('importProgress').innerHTML =
      `${label}已在后台开始，进度见下方「同步状态」…`;
    const res = await api(url, opts);
    if (res && res.success) {
      notify(`${label}已在后台启动`, 'success');
    } else {
      document.getElementById('importProgress').innerHTML =
        `<span style="color:var(--sell)">${label}启动失败: ${res?.error || '未知错误'}</span>`;
      notify((res && res.error) || `${label}启动失败`, 'alert');
    }
    this.load();
  },

  async importStocks() {
    this._kickoff('/api/data/import/stocks', { method: 'POST' }, '导入股票列表');
  },

  async importKline() {
    this._kickoff('/api/data/import/kline', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ days: 250 })
    }, '导入K线');
  },

  async syncDaily() {
    this._kickoff('/api/data/sync/daily', { method: 'POST' }, '增量同步');
  }
};
