const CHART_UP = '#ff3d5a';
const CHART_DOWN = '#00e676';
const CHART_GOLD = '#f5a623';
const CHART_BLUE = '#5b9eff';
const CHART_MUTED = '#8a8780';
const CHART_GRID = 'rgba(255,255,255,0.05)';

const CATEGORY_COLORS = {
  '科技': '#5b9eff',
  '新能源': '#ff3d5a',
  '制造': '#f5a623',
  '消费': '#e040fb',
  '金融周期': '#00e676',
};

const Charts = {
  sectorCharts: {},
  asset: null,
  pnl: null,
  returnCurve: null,
  returnCurve2: null,

  initPnl(domId) {
    const dom = document.getElementById(domId);
    if (!dom || typeof echarts === 'undefined') return;
    this.pnl = echarts.init(dom);
    return this.pnl;
  },

  initReturnCurve(domId) {
    const dom = document.getElementById(domId);
    if (!dom || typeof echarts === 'undefined') return;
    this.returnCurve = echarts.init(dom);
    return this.returnCurve;
  },

  initReturnCurve2(domId) {
    const dom = document.getElementById(domId);
    if (!dom || typeof echarts === 'undefined') return;
    if (this.returnCurve2) { this.returnCurve2.dispose(); this.returnCurve2 = null; }
    this.returnCurve2 = echarts.init(dom);
    return this.returnCurve2;
  },

  renderReturnCurve2(data) {
    if (!this.returnCurve2) return;
    this.returnCurve2.resize();
    const SERIES_CONFIG = {
      'asset': { name: '账户2·板块动量', color: '#ff6d00', width: 3, area: true },
      'sh':    { name: '上证指数', color: '#ff5252', width: 1.5 },
      'sz':    { name: '深证成指', color: '#448aff', width: 1.5 },
      'cy':    { name: '创业板指', color: '#69f0ae', width: 1.5 },
      'kc':    { name: '科创50',   color: '#e040fb', width: 1.5 },
    };
    const series = Object.entries(SERIES_CONFIG).map(([key, cfg]) => {
      const values = data[key] || [];
      const s = {
        name: cfg.name, type: 'line', data: values, smooth: true,
        lineStyle: { color: cfg.color, width: cfg.width },
        itemStyle: { color: cfg.color }, symbol: 'none',
      };
      if (cfg.area) {
        s.lineStyle.shadowBlur = 8;
        s.lineStyle.shadowColor = 'rgba(255,109,0,0.3)';
        s.areaStyle = { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [{offset:0, color:'rgba(255,109,0,0.10)'},{offset:1, color:'rgba(255,109,0,0)'}] }};
      }
      return s;
    });
    this.returnCurve2.setOption({
      tooltip: {
        trigger: 'axis',
        formatter: function(params) {
          var html = '<b>' + params[0].axisValue + '</b><br/>';
          params.forEach(function(p) {
            var v = p.value || 0;
            var clr = v >= 0 ? CHART_UP : CHART_DOWN;
            html += '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' + p.color + ';margin-right:4px"></span>';
            html += p.seriesName + ': <b style="color:' + clr + '">' + (v >= 0 ? '+' : '') + v.toFixed(2) + '%</b><br/>';
          });
          return html;
        }
      },
      legend: {
        data: ['账户2·板块动量', '上证指数', '深证成指', '创业板指', '科创50'],
        bottom: 0, textStyle: { color: CHART_MUTED, fontSize: 11 },
      },
      grid: { left: 60, right: 30, top: 20, bottom: 40 },
      xAxis: { type: 'category', data: data.dates || [], axisLabel: { color: CHART_MUTED, fontSize: 10 } },
      yAxis: { type: 'value', name: '累计收益率%', nameTextStyle: { color: CHART_MUTED, fontSize: 10 },
        axisLabel: { color: CHART_MUTED, fontSize: 10, formatter: '{value}%' },
        splitLine: { lineStyle: { color: CHART_GRID } } },
      series: series
    });
  },

  renderSector(categories) {
    const container = document.getElementById('sectorCharts');
    if (!container) return;

    // Dispose old charts
    Object.values(this.sectorCharts).forEach(c => { try { c.dispose(); } catch(e) {} });
    this.sectorCharts = {};

    const catKeys = Object.keys(categories);
    if (!catKeys.length) return;

    // Build container HTML
    container.innerHTML = catKeys.map((cat, i) => {
      const color = CATEGORY_COLORS[cat] || CHART_MUTED;
      return `<div style="display:flex;flex-direction:column;min-width:0">
        <div style="font-size:11px;font-weight:700;color:${color};padding:6px 10px;letter-spacing:1px;text-transform:uppercase">
          ◆ ${cat}
        </div>
        <div id="sectorChart_${i}" style="height:200px"></div>
      </div>`;
    }).join('');

    // Use grid: 2 columns for 4+ categories, otherwise single row
    container.style.display = 'grid';
    container.style.gridTemplateColumns = catKeys.length >= 4
      ? 'repeat(2, 1fr)'
      : `repeat(${catKeys.length}, 1fr)`;
    container.style.gap = '12px';

    // Render each category treemap
    catKeys.forEach((cat, i) => {
      const dom = document.getElementById(`sectorChart_${i}`);
      if (!dom) return;
      const chart = echarts.init(dom);
      this.sectorCharts[cat] = chart;

      const data = categories[cat] || [];
      const maxAbs = Math.max(...data.map(d => Math.abs(d.change_pct)), 0.3);

      chart.setOption({
        tooltip: {
          formatter: p => {
            if (!p.data || !('change_pct' in p.data)) return p.name;
            const v = p.data.change_pct;
            return `<b>${p.name}</b><br/>涨跌幅: ${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;
          }
        },
        series: [{
          type: 'treemap',
          roam: false,
          nodeClick: false,
          breadcrumb: { show: false },
          top: 0, bottom: 0, left: 0, right: 0,
          label: {
            show: true,
            formatter: '{b}\n{c}%',
            fontSize: 10,
            fontWeight: 500,
            color: '#fff'
          },
          data: data.map(d => {
            const absVal = Math.abs(d.change_pct) || 0.3;
            const intensity = 0.35 + 0.65 * (absVal / maxAbs);
            const isUp = d.change_pct >= 0;
            // 霓虹红/绿 + 深色柔和填充：块体压暗淡雅，顶部霓虹高光当辉光
            const base = [14, 19, 26];                          // ≈ --surface2 深底
            const neon = isUp ? [255, 45, 85] : [0, 255, 157];  // 霓虹红 #FF2D55 / 霓虹绿 #00FF9D
            // 填充只走到霓虹色的一部分（柔和），不铺满饱和
            const soft = intensity * 0.62;
            const mix = (i) => Math.round(base[i] + (neon[i] - base[i]) * soft);
            const r = mix(0), g = mix(1), b = mix(2);
            // 顶部高光用霓虹原色，强度越高辉光越亮
            const hi = neon.join(',');
            return {
              name: d.name,
              value: absVal || 0.3,
              change_pct: d.change_pct,
              itemStyle: {
                color: {
                  type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
                  colorStops: [
                    { offset: 0, color: `rgba(${hi},${0.28 + intensity * 0.4})` },
                    { offset: 0.18, color: `rgb(${r},${g},${b})` },
                    { offset: 1, color: `rgb(${Math.round(r*0.66)},${Math.round(g*0.66)},${Math.round(b*0.66)})` }
                  ]
                },
                borderColor: 'rgba(5,7,10,0.55)', borderWidth: 2, borderRadius: 6,
                gapWidth: 2
              }
            };
          })
        }]
      });
    });
  },

  renderPnl(dates, dailyReturns, cumulative) {
    if (!this.pnl) return;
    this.pnl.resize();
    this.pnl.setOption({
      tooltip: { trigger: 'axis' },
      grid: { left: 60, right: 60, top: 20, bottom: 30 },
      xAxis: { type: 'category', data: dates, axisLabel: { color: CHART_MUTED, fontSize: 10 } },
      yAxis: [
        { type: 'value', name: '日收益%', nameTextStyle: { color: CHART_MUTED, fontSize: 10 },
          axisLabel: { color: CHART_MUTED, fontSize: 10, formatter: '{value}%' },
          splitLine: { lineStyle: { color: CHART_GRID } } },
        { type: 'value', name: '累计%', nameTextStyle: { color: CHART_MUTED, fontSize: 10 },
          axisLabel: { color: CHART_MUTED, fontSize: 10, formatter: '{value}%' } }
      ],
      series: [
        { name: '日收益', type: 'bar', data: dailyReturns.map(v => ({
            value: v, itemStyle: { color: v >= 0 ? CHART_UP : CHART_DOWN }
          })), barMaxWidth: 14 },
        { name: '累计收益', type: 'line', yAxisIndex: 1, data: cumulative, smooth: true,
          lineStyle: { color: CHART_GOLD, width: 2.5, shadowBlur: 8, shadowColor: 'rgba(245,166,35,0.3)' },
          itemStyle: { color: CHART_GOLD }, symbol: 'none' }
      ]
    });
  },

  renderReturnCurve(data) {
    if (!this.returnCurve) return;
    this.returnCurve.resize();
    const SERIES_CONFIG = {
      'asset': { name: '我的账户', color: CHART_GOLD, width: 3, area: true },
      'sh':    { name: '上证指数', color: '#ff5252', width: 1.5 },
      'sz':    { name: '深证成指', color: '#448aff', width: 1.5 },
      'cy':    { name: '创业板指', color: '#69f0ae', width: 1.5 },
      'kc':    { name: '科创50',   color: '#e040fb', width: 1.5 },
    };

    const series = Object.entries(SERIES_CONFIG).map(([key, cfg]) => {
      const values = data[key] || [];
      const s = {
        name: cfg.name, type: 'line', data: values, smooth: true,
        lineStyle: { color: cfg.color, width: cfg.width },
        itemStyle: { color: cfg.color }, symbol: 'none',
      };
      if (cfg.area) {
        s.lineStyle.shadowBlur = 8;
        s.lineStyle.shadowColor = 'rgba(245,166,35,0.3)';
        s.areaStyle = { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [{offset:0, color:'rgba(245,166,35,0.08)'},{offset:1, color:'rgba(245,166,35,0)'}] }};
      }
      return s;
    });

    this.returnCurve.setOption({
      tooltip: {
        trigger: 'axis',
        formatter: function(params) {
          var html = '<b>' + params[0].axisValue + '</b><br/>';
          params.forEach(function(p) {
            var v = p.value || 0;
            var clr = v >= 0 ? CHART_UP : CHART_DOWN;
            html += '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' + p.color + ';margin-right:4px"></span>';
            html += p.seriesName + ': <b style="color:' + clr + '">' + (v >= 0 ? '+' : '') + v.toFixed(2) + '%</b><br/>';
          });
          return html;
        }
      },
      legend: {
        data: ['我的账户', '上证指数', '深证成指', '创业板指', '科创50'],
        bottom: 0, textStyle: { color: CHART_MUTED, fontSize: 11 },
      },
      grid: { left: 60, right: 30, top: 20, bottom: 40 },
      xAxis: { type: 'category', data: data.dates || [], axisLabel: { color: CHART_MUTED, fontSize: 10 } },
      yAxis: { type: 'value', name: '累计收益率%', nameTextStyle: { color: CHART_MUTED, fontSize: 10 },
        axisLabel: { color: CHART_MUTED, fontSize: 10, formatter: '{value}%' },
        splitLine: { lineStyle: { color: CHART_GRID } } },
      series: series
    });
  },

  resize() {
    Object.values(this.sectorCharts).forEach(c => { try { c.resize(); } catch(e) {} });
    this.asset?.resize();
    this.pnl?.resize();
    this.returnCurve?.resize();
    this.returnCurve2?.resize();
  }
};
