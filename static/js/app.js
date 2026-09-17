let activeTab = 'dashboard';
const REFRESH_MS = 5000;
let refreshTimer = null;
let autoTradeEnabled = false;

document.addEventListener('DOMContentLoaded', () => {
  initTabs();
  updateClock();
  const clockTimer = setInterval(updateClock, 1000);
  window.addEventListener('beforeunload', () => clearInterval(clockTimer));
  loadDashboard();
  startRefresh();
  if (typeof echarts !== 'undefined') {
    Charts.initReturnCurve('assetChart');
    Charts.initPnl('pnlChart');
  }
  window.addEventListener('resize', () => Charts.resize());

  // Fallback: if indices still show loading after 8s, show error hint
  setTimeout(() => {
    const el = document.getElementById('indicesContent');
    if (el && el.textContent.includes('加载中')) {
      el.innerHTML = '<span style="color:#ffab00">数据加载超时 — 按 F12 查看 Console 错误，或 Ctrl+Shift+R 强制刷新</span>';
    }
  }, 8000);

  document.addEventListener('click', (e) => {
    const cell = e.target.closest('.clickable-stock');
    if (!cell) return;
    const code = cell.dataset.code;
    if (code) KlineModal.open(code, cell.textContent.trim());
  });

  document.getElementById('klineModal').addEventListener('click', (e) => {
    if (e.target.id === 'klineModal') KlineModal.close();
  });
});

function initTabs() {
  document.querySelectorAll('.tab').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeTab = btn.dataset.tab;
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
      const pane = document.getElementById('tab-' + activeTab);
      pane.classList.add('active');
      playTabAnim(pane);
      switchTab(activeTab);
    });
  });
  // 初始激活的 dashboard 也播一次进场动画
  const initial = document.querySelector('.tab-content.active');
  if (initial) playTabAnim(initial);
}

// 进场 stagger 只在 tab 激活时播一次：短暂加 .tab-anim，动画结束即移除，
// 这样 5s 刷新用 innerHTML 重建卡片时不会再匹配选择器、不会重播淡出。
function playTabAnim(pane) {
  pane.classList.add('tab-anim');
  setTimeout(() => pane.classList.remove('tab-anim'), 700);
}

// fx-on 模式下卡片初始 opacity:0，靠 fx.js 的 IntersectionObserver 加 .fx-in 才显现。
// 但 5s 刷新会 innerHTML 重建卡片节点，新节点不在 observer 名下 → 永远停在 opacity:0
// → 整行消失。渲染后立即给可见区卡片补上 .fx-in，保证数据永远可见。
function revealCards(container) {
  if (!document.body.classList.contains('fx-on')) return;
  const root = container || document;
  root.querySelectorAll('.card:not(.fx-in)').forEach(c => c.classList.add('fx-in'));
}

function switchTab(tab) {
  switch(tab) {
    case 'dashboard': loadDashboard(); break;
    case 'watchlist': loadWatchlist(); break;
    case 'positions': loadPositions(); break;
    case 'screener': loadScreener(); break;
    case 'journal': loadJournal(); break;
    case 'review': loadReview(); break;
    case 'datacenter': DataCenter.load(); break;
    case 'strategies': Strategies.load(); MLPanel.load(); break;
    case 'backtest': Backtest.load(); break;
  }
  Charts.resize();
}

function startRefresh() {
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = setInterval(() => {
    if (activeTab === 'dashboard') { loadDashboard(); loadTradeStatus(); }
    else if (activeTab === 'positions') loadPositions();
    else if (activeTab === 'strategies') Strategies.load();
    checkWatchlistAnomaly();
  }, REFRESH_MS);
}

function updateClock() {
  const now = new Date();
  document.getElementById('clock').textContent =
    now.toLocaleString('zh-CN', { hour12: false });
}

function notify(msg, type) {
  const n = document.createElement('div');
  n.className = 'notification';
  if (type === 'alert') n.classList.add('alert');
  if (type === 'buy') n.style.borderColor = 'rgba(0,230,118,0.5)';
  if (type === 'sell') n.style.borderColor = 'rgba(255,61,90,0.5)';
  if (type === 'success') n.style.borderColor = 'rgba(0,191,165,0.5)';
  if (type === 'error') n.style.borderColor = 'rgba(255,61,90,0.7)';
  n.innerHTML = type === 'alert' ? '&#x26A0; ' + msg : msg;
  document.body.appendChild(n);
  setTimeout(() => {
    n.style.opacity = '0';
    n.style.transform = 'translateX(120%)';
    n.style.transition = 'all .3s ease';
    setTimeout(() => n.remove(), 300);
  }, 3500);
}

async function api(url, opts = {}) {
  try {
    const controller = new AbortController();
    const timeoutMs = opts.timeout || 90000;
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    const res = await fetch(url, { ...opts, signal: controller.signal, cache: 'no-store' });
    clearTimeout(timer);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch(e) {
    if (e.name === 'AbortError') {
      console.error('API timeout:', url);
    } else {
      console.error('API error:', url, e);
    }
    return null;
  }
}
