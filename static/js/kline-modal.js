const KLINE_UP = '#ff3d5a';
const KLINE_DOWN = '#00e676';
const KLINE_GOLD = '#f5a623';

const KlineModal = {
  klineChart: null,
  macdChart: null,

  async open(code, name) {
    const overlay = document.getElementById('klineModal');
    document.getElementById('modalTitle').textContent = `${name} (${code}) - K线分析`;
    overlay.style.display = 'flex';

    const data = await api(`/api/stock/${code}/analysis?days=120`);
    if (!data || !data.klines || !data.klines.length) {
      notify('暂无K线数据', 'error');
      this.close();
      return;
    }
    this.data = data;

    setTimeout(() => {
      this.renderCandlestick();
      this.renderMacd();
    }, 100);
  },

  close() {
    const overlay = document.getElementById('klineModal');
    overlay.style.display = 'none';
    if (this.klineChart) { this.klineChart.dispose(); this.klineChart = null; }
    if (this.macdChart) { this.macdChart.dispose(); this.macdChart = null; }
    this.data = null;
  },

  renderCandlestick() {
    const dom = document.getElementById('modalKlineChart');
    if (this.klineChart) this.klineChart.dispose();
    this.klineChart = echarts.init(dom);

    const klines = this.data.klines;
    const dates = klines.map(k => k.date);
    const ohlc = klines.map(k => [k.open, k.close, k.low, k.high]);
    const volumes = klines.map(k => k.volume);
    const ma5 = klines.map(k => k.ma5);
    const ma10 = klines.map(k => k.ma10);
    const ma20 = klines.map(k => k.ma20);

    const volColors = klines.map(k =>
      k.close >= k.open ? KLINE_UP : KLINE_DOWN
    );

    const marks = (this.data.patterns || []).map(p => {
      const idx = dates.indexOf(p.date);
      if (idx < 0) return null;
      const k = klines[idx];
      const color = p.type === 'bullish' ? KLINE_GOLD : p.type === 'bearish' ? KLINE_DOWN : '#5b9eff';
      return {
        name: p.pattern,
        coord: [p.date, k.low],
        value: p.pattern,
        symbol: 'pin',
        symbolSize: 40,
        itemStyle: { color },
        label: { show: true, fontSize: 10, color: '#fff', formatter: '{c}', position: 'bottom', distance: 4 }
      };
    }).filter(Boolean);

    this.klineChart.setOption({
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        formatter: params => {
          const dp = Array.isArray(params) ? params : [params];
          let html = `<b>${dp[0].axisValue}</b><br/>`;
          const ohlcData = dp.find(p => p.seriesName === 'K线');
          if (ohlcData) {
            const d = ohlcData.data;
            html += `开: ${d[1]}<br/>收: ${d[2]}<br/>低: ${d[3]}<br/>高: ${d[4]}<br/>`;
          }
          dp.forEach(p => {
            if (p.seriesName.startsWith('MA') && p.value != null) {
              html += `${p.seriesName}: ${Number(p.value).toFixed(2)}<br/>`;
            }
            if (p.seriesName === '成交量') {
              html += `成交量: ${(p.value/10000).toFixed(0)}万手<br/>`;
            }
          });
          return html;
        }
      },
      axisPointer: {
        link: [{ xAxisIndex: 'all' }]
      },
      grid: [
        { left: 60, right: 20, top: 20, height: '60%' },
        { left: 60, right: 20, top: '76%', height: '18%' }
      ],
      xAxis: [
        { type: 'category', data: dates, gridIndex: 0, axisLabel: { show: false }, axisLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } } },
        { type: 'category', data: dates, gridIndex: 1, axisLabel: { color: '#8a8780', fontSize: 10 },
          axisLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } }, axisTick: { show: false } }
      ],
      yAxis: [
        { type: 'value', gridIndex: 0, scale: true, axisLabel: { color: '#8a8780', fontSize: 10 },
          splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } }, position: 'left' },
        { type: 'value', gridIndex: 1, scale: true, axisLabel: { color: '#8a8780', fontSize: 10, formatter: v => (v/10000).toFixed(0)+'w' },
          splitLine: { show: false }, position: 'left' }
      ],
      dataZoom: [
        { type: 'slider', xAxisIndex: [0,1], start: 50, end: 100, height: 18, bottom: 4,
          textStyle: { color: '#8a8780', fontSize: 10 }, borderColor: 'rgba(255,255,255,0.06)',
          backgroundColor: 'rgba(255,255,255,0.02)' }
      ],
      series: [
        {
          name: 'K线', type: 'candlestick', xAxisIndex: 0, yAxisIndex: 0,
          data: ohlc,
          itemStyle: { color: KLINE_UP, color0: KLINE_DOWN, borderColor: KLINE_UP, borderColor0: KLINE_DOWN },
          markPoint: marks.length ? { data: marks, symbolOffset: [0, -10] } : undefined
        },
        { name: 'MA5', type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: ma5,
          smooth: true, symbol: 'none', connectNulls: false,
          lineStyle: { color: '#ffffff', width: 1.2, opacity: 0.7 } },
        { name: 'MA10', type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: ma10,
          smooth: true, symbol: 'none', connectNulls: false,
          lineStyle: { color: KLINE_GOLD, width: 1.2, opacity: 0.7 } },
        { name: 'MA20', type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: ma20,
          smooth: true, symbol: 'none', connectNulls: false,
          lineStyle: { color: '#5b9eff', width: 1.2, opacity: 0.7 } },
        {
          name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: volumes,
          itemStyle: { color: params => volColors[params.dataIndex], borderColor: 'transparent' }
        }
      ]
    });
  },

  renderMacd() {
    const dom = document.getElementById('modalMacdChart');
    if (this.macdChart) this.macdChart.dispose();
    this.macdChart = echarts.init(dom);

    const klines = this.data.klines;
    const dates = klines.map(k => k.date);
    const dif = klines.map(k => k.macd_dif);
    const dea = klines.map(k => k.macd_dea);
    const hist = klines.map(k => k.macd_hist);

    this.macdChart.setOption({
      tooltip: {
        trigger: 'axis',
        formatter: params => {
          let html = `<b>${params[0].axisValue}</b><br/>`;
          params.forEach(p => {
            if (p.value != null) html += `${p.seriesName}: ${Number(p.value).toFixed(3)}<br/>`;
          });
          return html;
        }
      },
      grid: { left: 60, right: 20, top: 10, bottom: 25 },
      xAxis: { type: 'category', data: dates, axisLabel: { color: '#8a8780', fontSize: 10 },
        axisLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } }, axisTick: { show: false } },
      yAxis: { type: 'value', scale: true, axisLabel: { color: '#8a8780', fontSize: 10 },
        splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } } },
      series: [
        { name: 'DIF', type: 'line', data: dif, symbol: 'none',
          lineStyle: { color: '#ffffff', width: 1.2 } },
        { name: 'DEA', type: 'line', data: dea, symbol: 'none',
          lineStyle: { color: KLINE_GOLD, width: 1.2 } },
        { name: 'MACD', type: 'bar', data: hist.map((v, i) => ({
            value: v,
            itemStyle: { color: v >= 0 ? KLINE_UP : KLINE_DOWN, borderColor: 'transparent' }
          })),
          barWidth: '60%' }
      ]
    });
  }
};
