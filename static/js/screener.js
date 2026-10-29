// 首投守护者：选股推荐功能已禁用
// 保留空实现以防其他模块调用报错

let screenerRunning = false;
let screenerResultsCache = [];

function escQ(str) { return String(str).replace(/'/g, "\\'"); }

async function loadScreener() {
  // 功能已禁用
  renderScreenerDisabled();
}

async function runScreener() {
  // 功能已禁用
  renderScreenerDisabled();
}

function renderScreenerResults(data) {
  // 功能已禁用
  renderScreenerDisabled();
}

function renderScreenerDisabled() {
  const el = document.getElementById('screenerTable');
  if (el) {
    el.innerHTML = `
      <div style="padding:40px 20px;text-align:center;color:var(--text2)">
        <div style="font-size:48px;margin-bottom:16px">📚</div>
        <div style="font-size:16px;font-weight:600;margin-bottom:8px">首投守护者不提供个股推荐</div>
        <div style="font-size:13px;line-height:1.6;max-width:400px;margin:0 auto">
          我们的定位是投资者教育工具，帮助你学习如何验证策略、评估风险。<br>
          推荐股票的人不为你的亏损负责——学会自己判断，才是真正的守护。
        </div>
        <div style="margin-top:24px">
          <a href="#" onclick="switchTab('education');return false" class="btn btn-primary">
            前往投教课程
          </a>
        </div>
      </div>`;
  }
  const status = document.getElementById('screenerStatus');
  if (status) {
    status.innerHTML = '<span style="color:#ffab00">⚠️ 功能已禁用</span>';
  }
}

const ScreenerLogicModal = {
  openByCode(code) {
    // 功能已禁用
  },

  open(item) {
    // 功能已禁用
  },

  close() {
    const modal = document.getElementById('screenerLogicModal');
    if (modal) modal.style.display = 'none';
  }
};

// Click delegation for screener stock cells - 已禁用
document.addEventListener('click', (e) => {
  const cell = e.target.closest('.screener-stock');
  if (!cell) return;
  // 功能已禁用，不再弹窗
});

document.getElementById('screenerLogicModal')?.addEventListener('click', (e) => {
  if (e.target.id === 'screenerLogicModal') ScreenerLogicModal.close();
});

async function buyFromScreener(stockCode, stockName, price) {
  // 功能已禁用
  alert('首投守护者不提供个股推荐与交易功能，请使用模拟账户学习交易流程。');
  return;
}
