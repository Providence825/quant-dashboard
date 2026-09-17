/* fx.js —— 纯视觉层：粒子网络背景 + 鼠标追踪 + 滚动揭示。
   完全独立，不引用任何数据/接口/交易逻辑。
   任何异常都被 try/catch 吞掉，绝不影响页面数据显示。 */
(function () {
  'use strict';
  try {
    var reduce = window.matchMedia &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduce) return; // 用户系统关动画 → 全部跳过，内容保持可见

    /* ===== 1. 粒子网络背景 ===== */
    var canvas = document.createElement('canvas');
    canvas.id = 'fxCanvas';
    canvas.setAttribute('aria-hidden', 'true');
    var s = canvas.style;
    s.position = 'fixed'; s.top = '0'; s.left = '0';
    s.width = '100%'; s.height = '100%';
    s.pointerEvents = 'none'; s.zIndex = '0';
    document.body.insertBefore(canvas, document.body.firstChild);

    var ctx = canvas.getContext('2d');
    var W = 0, H = 0, dpr = Math.min(window.devicePixelRatio || 1, 2);
    var particles = [];
    var mouse = { x: -9999, y: -9999 };
    var LINK = 132, MOUSE_LINK = 170;

    function resize() {
      W = window.innerWidth; H = window.innerHeight;
      canvas.width = W * dpr; canvas.height = H * dpr;
      canvas.style.width = W + 'px'; canvas.style.height = H + 'px';
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      var target = Math.min(96, Math.floor((W * H) / 15000));
      particles = [];
      for (var i = 0; i < target; i++) {
        particles.push({
          x: Math.random() * W, y: Math.random() * H,
          vx: (Math.random() - 0.5) * 0.35,
          vy: (Math.random() - 0.5) * 0.35,
          r: Math.random() * 1.6 + 0.6
        });
      }
      buildShapes();
      buildGlyphs();
    }

    /* 背景飘浮字符：希腊字母 + 罗马数字（量化气质） */
    var GLYPHS = ['α','β','γ','δ','θ','λ','μ','π','σ','φ','ω','Σ','Δ','Ω','Ψ','∫','∑',
                  'Ⅰ','Ⅱ','Ⅲ','Ⅳ','Ⅴ','Ⅵ','Ⅶ','Ⅷ','Ⅸ','Ⅹ','Ⅻ'];
    var glyphs = [];
    function buildGlyphs() {
      var n = Math.max(8, Math.min(20, Math.floor((W * H) / 110000)));
      glyphs = [];
      for (var i = 0; i < n; i++) {
        glyphs.push({
          x: Math.random() * W, y: Math.random() * H,
          ch: GLYPHS[Math.floor(Math.random() * GLYPHS.length)],
          size: 16 + Math.random() * 40,
          vx: (Math.random() - 0.5) * 0.12,
          vy: (Math.random() - 0.5) * 0.12,
          indigo: Math.random() < 0.5,
          ph: Math.random() * Math.PI * 2   // 呼吸相位
        });
      }
    }
    function drawGlyphs(t) {
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      for (var i = 0; i < glyphs.length; i++) {
        var g = glyphs[i];
        g.x += g.vx; g.y += g.vy;
        if (g.x < -40) g.x = W + 40; if (g.x > W + 40) g.x = -40;
        if (g.y < -40) g.y = H + 40; if (g.y > H + 40) g.y = -40;
        var pulse = 0.06 + 0.05 * (0.5 + 0.5 * Math.sin(t * 0.0009 + g.ph));
        ctx.font = '700 ' + g.size + 'px "JetBrains Mono", monospace';
        ctx.fillStyle = g.indigo
          ? 'rgba(110,139,255,' + pulse + ')'
          : 'rgba(31,224,200,' + pulse + ')';
        ctx.fillText(g.ch, g.x, g.y);
      }
    }

    /* Genesis Block 风格：随机几何线框（三角/方/五边/六边），缓慢旋转漂移 */
    var shapes = [];
    function buildShapes() {
      var n = Math.max(5, Math.min(11, Math.floor((W * H) / 190000)));
      shapes = [];
      for (var i = 0; i < n; i++) {
        shapes.push({
          x: Math.random() * W, y: Math.random() * H,
          size: 46 + Math.random() * 120,
          sides: [3, 4, 5, 6][Math.floor(Math.random() * 4)],
          rot: Math.random() * Math.PI * 2,
          spin: (Math.random() - 0.5) * 0.0016,
          vx: (Math.random() - 0.5) * 0.16,
          vy: (Math.random() - 0.5) * 0.16,
          indigo: Math.random() < 0.5
        });
      }
    }
    function drawShapes() {
      for (var i = 0; i < shapes.length; i++) {
        var sh = shapes[i];
        sh.rot += sh.spin; sh.x += sh.vx; sh.y += sh.vy;
        var m = sh.size;
        if (sh.x < -m) sh.x = W + m; if (sh.x > W + m) sh.x = -m;
        if (sh.y < -m) sh.y = H + m; if (sh.y > H + m) sh.y = -m;
        ctx.save();
        ctx.translate(sh.x, sh.y); ctx.rotate(sh.rot);
        ctx.beginPath();
        for (var k = 0; k <= sh.sides; k++) {
          var ang = (Math.PI * 2 / sh.sides) * k - Math.PI / 2;
          var px = Math.cos(ang) * sh.size, py = Math.sin(ang) * sh.size;
          k === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
        }
        ctx.strokeStyle = sh.indigo ? 'rgba(110,139,255,0.28)' : 'rgba(31,224,200,0.24)';
        ctx.lineWidth = 1.2; ctx.stroke();
        // 顶点小点
        ctx.fillStyle = sh.indigo ? 'rgba(110,139,255,0.5)' : 'rgba(31,224,200,0.45)';
        for (var k2 = 0; k2 < sh.sides; k2++) {
          var a2 = (Math.PI * 2 / sh.sides) * k2 - Math.PI / 2;
          ctx.beginPath();
          ctx.arc(Math.cos(a2) * sh.size, Math.sin(a2) * sh.size, 1.8, 0, Math.PI * 2);
          ctx.fill();
        }
        ctx.restore();
      }
    }

    /* 滚动切换板块时的粒子聚集吸引点（临时，1.1s 衰减） */
    var attractor = null; // {x, y, until}
    function triggerGather(el) {
      var r = el.getBoundingClientRect();
      if (r.bottom < 0 || r.top > H) return;
      attractor = { x: r.left + r.width / 2, y: r.top + r.height / 2, until: performance.now() + 1100 };
    }

    function step(t) {
      ctx.clearRect(0, 0, W, H);
      drawGlyphs(t);
      drawShapes();
      var gather = attractor && t < attractor.until ? attractor : null;
      for (var i = 0; i < particles.length; i++) {
        var p = particles[i];
        p.x += p.vx; p.y += p.vy;
        if (p.x < 0 || p.x > W) p.vx *= -1;
        if (p.y < 0 || p.y > H) p.vy *= -1;

        // 滚动聚集：粒子被拉向刚进入视口的板块中心，短暂组成聚团
        if (gather) {
          var gdx = gather.x - p.x, gdy = gather.y - p.y;
          var gd = Math.sqrt(gdx * gdx + gdy * gdy);
          if (gd > 1) {
            var pull = Math.min(2.4, gd * 0.03);
            p.x += (gdx / gd) * pull;
            p.y += (gdy / gd) * pull;
          }
        }

        // 鼠标轻微吸引
        var mdx = mouse.x - p.x, mdy = mouse.y - p.y;
        var md = Math.sqrt(mdx * mdx + mdy * mdy);
        if (md < MOUSE_LINK && md > 0.1) {
          p.x += (mdx / md) * 0.28;
          p.y += (mdy / md) * 0.28;
          ctx.strokeStyle = 'rgba(31,224,200,' + (0.16 * (1 - md / MOUSE_LINK)) + ')';
          ctx.lineWidth = 0.7;
          ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(mouse.x, mouse.y); ctx.stroke();
        }

        // 粒子间连线
        for (var j = i + 1; j < particles.length; j++) {
          var q = particles[j];
          var dx = p.x - q.x, dy = p.y - q.y;
          var d = Math.sqrt(dx * dx + dy * dy);
          if (d < LINK) {
            var a = 0.10 * (1 - d / LINK);
            ctx.strokeStyle = (j % 5 === 0)
              ? 'rgba(110,139,255,' + a + ')'
              : 'rgba(31,224,200,' + a + ')';
            ctx.lineWidth = 0.6;
            ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(q.x, q.y); ctx.stroke();
          }
        }

        // 节点
        ctx.fillStyle = 'rgba(31,224,200,0.5)';
        ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2); ctx.fill();
      }
    }

    var running = true, rafId = null;
    function loop(t) { if (running) { step(t || performance.now()); rafId = requestAnimationFrame(loop); } }

    window.addEventListener('resize', resize);
    window.addEventListener('mousemove', function (e) { mouse.x = e.clientX; mouse.y = e.clientY; });
    window.addEventListener('mouseout', function () { mouse.x = -9999; mouse.y = -9999; });
    document.addEventListener('visibilitychange', function () {
      running = !document.hidden;
      if (running && rafId === null) loop();
      else if (!running) { cancelAnimationFrame(rafId); rafId = null; }
    });

    resize();
    loop();

    /* ===== 2. 滚动揭示（Stack & Reveal on Scroll 风格）=====
       只有 JS 成功运行到这里才给 body 加 fx-on，CSS 才会把卡片初始隐藏。
       → 万一脚本失败，卡片默认可见，数据不受影响。 */
    if ('IntersectionObserver' in window) {
      document.body.classList.add('fx-on');
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (en) {
          if (en.isIntersecting) {
            en.target.classList.add('fx-in');
            triggerGather(en.target);   // 板块进入视口 → 粒子聚集
            io.unobserve(en.target);
          }
        });
      }, { threshold: 0.08, rootMargin: '0px 0px -6% 0px' });

      var watch = function () {
        document.querySelectorAll('.tab-content.active .card:not(.fx-in)')
          .forEach(function (c) { io.observe(c); });
      };
      watch();
      // 切 tab 时给新页卡片重新挂观察（tab 用户点击才触发，非 5s 刷新）
      document.querySelectorAll('.tab').forEach(function (t) {
        t.addEventListener('click', function () { setTimeout(watch, 60); });
      });
    }

    /* ===== 3. 上下滚动切换板块 → 粒子聚集组成 =====
       滚动时取视口中央的卡片，切到新卡片就触发一次聚集。 */
    var lastGatherEl = null, scrollTick = false;
    function onScroll() {
      if (scrollTick) return;
      scrollTick = true;
      requestAnimationFrame(function () {
        scrollTick = false;
        var mid = H / 2, best = null, bestDist = 1e9;
        document.querySelectorAll('.tab-content.active .card').forEach(function (c) {
          var r = c.getBoundingClientRect();
          if (r.bottom < 0 || r.top > H) return;
          var dist = Math.abs((r.top + r.bottom) / 2 - mid);
          if (dist < bestDist) { bestDist = dist; best = c; }
        });
        if (best && best !== lastGatherEl) {
          lastGatherEl = best;
          triggerGather(best);
        }
      });
    }
    window.addEventListener('scroll', onScroll, { passive: true });
  } catch (e) { /* 视觉层失败静默，不影响数据 */ }
})();
