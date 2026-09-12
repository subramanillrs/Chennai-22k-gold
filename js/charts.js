// ============================================================
// PRICE HISTORY CHARTS, SPLINES & INTERACTIVE SCRUB
// ============================================================

let chartViewMode = "spline";

// --- Chart View Mode Switch & Accordion Resilience ---
(function setupChartControls() {
  const modeSplineBtn = $("modeSplineBtn");
  const modeSpreadBtn = $("modeSpreadBtn");

  if (modeSplineBtn && modeSpreadBtn) {
    modeSplineBtn.addEventListener("click", () => {
      chartViewMode = "spline";
      modeSplineBtn.classList.add("active");
      modeSpreadBtn.classList.remove("active");
      if (typeof haptic === "function") haptic(10);
      requestAnimationFrame(drawChart);
    });

    modeSpreadBtn.addEventListener("click", () => {
      chartViewMode = "spread";
      modeSpreadBtn.classList.add("active");
      modeSplineBtn.classList.remove("active");
      if (typeof haptic === "function") haptic(10);
      requestAnimationFrame(drawChart);
    });
  }

  // Accordion fix: Redraw canvas on any <details> toggle to prevent blank canvas
  document.querySelectorAll("details").forEach(details => {
    details.addEventListener("toggle", () => {
      requestAnimationFrame(() => {
        if (typeof drawChart === "function") drawChart();
        if (typeof window.refreshCompareVisual === "function") window.refreshCompareVisual();
        if (typeof window.refreshPortfolio === "function") window.refreshPortfolio();
      });
    });
  });

  // Attach ResizeObserver to chartWrap container
  const chartWrap = $("chartWrap") || $("chart")?.parentElement;
  if (chartWrap && window.ResizeObserver) {
    const ro = new ResizeObserver(entries => {
      for (const entry of entries) {
        if (entry.contentRect.width > 0 && entry.contentRect.height > 0) {
          requestAnimationFrame(() => {
            if (typeof drawChart === "function") drawChart();
          });
        }
      }
    });
    ro.observe(chartWrap);
  }
})();


function getFilteredHistory(range) {
  if (!history.length) return [];
  const daily = dailyBenchmarks(history);
  if (range === "all") return daily;
  const days = Number(range);
  const cutoff = new Date(Date.now() - days * 24 * 60 * 60 * 1000);
  const cutoffStr = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit' }).format(cutoff);
  const filtered = daily.filter(h => h.date >= cutoffStr);
  return filtered.length >= 2 ? filtered : daily.slice(-Math.max(2, Math.min(daily.length, days)));
}

function updateFintechMetrics() {
  if (!history.length || !live) return;
  // currentRate is the live tick (possibly an intraday AM value, not
  // yet a closed daily benchmark). That's fine as the "now" side of a
  // return calculation -- it genuinely is the latest known price --
  // but the "past" side must never accidentally include TODAY's own
  // not-yet-closed benchmark, or a short lookback (e.g. 7-day) could
  // end up comparing live against itself and understating the move.
  const currentRate = Number(live.rate_22k);
  const today = getTodayISTDateStr();

  const calcReturnByDays = (days) => {
    const targetDate = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(Date.now() - days * 24 * 60 * 60 * 1000));
    const daily = dailyBenchmarks(history);
    const pastRecords = daily.filter(h => h.date <= targetDate && h.date < today);
    if (!pastRecords.length) return null;
    const pastVal = Number(pastRecords[pastRecords.length - 1].rate_22k);
    return pastVal ? ((currentRate - pastVal) / pastVal) * 100 : null;
  };

  [{ id: "ret1W", d: 7 }, { id: "ret1M", d: 30 }, { id: "ret3M", d: 90 }, { id: "ret6M", d: 180 }, { id: "ret1Y", d: 365 }, { id: "ret3Y", d: 1095 }].forEach(h => {
    const ret = calcReturnByDays(h.d);
    if ($(h.id)) $(h.id).textContent = ret === null ? "—" : (ret >= 0 ? "+" : "") + ret.toFixed(1) + "%";
  });

  // Exclude today's own (possibly incomplete) benchmark from the
  // 30-day average -- it's being compared against currentRate just
  // below, so including it would let today count twice.
  const recent30 = getFilteredHistory(30).filter(i => i.date < today);
  const vals30 = recent30.map(i => Number(i.rate_22k));
  const sma = vals30.length ? vals30.reduce((a, b) => a + b, 0) / vals30.length : null;
  const smaDiff = sma !== null ? currentRate - sma : null, smaPct = sma ? (smaDiff / sma) * 100 : null;

  if ($("smaValue")) $("smaValue").textContent = sma !== null ? money(sma) : "₹ —";
  if ($("smaPill")) {
    if (sma !== null) {
      $("smaPill").className = "change-pill " + (smaDiff >= 0 ? "up" : "down");
      $("smaPill").textContent = (smaDiff >= 0 ? "▲ +" : "▼ -") + money(Math.abs(smaDiff)) + ` (${smaPct.toFixed(1)}%)`;
    } else {
      $("smaPill").className = "change-pill";
      $("smaPill").textContent = "—";
    }
  }
}

function drawSpline(ctx, pts) {
  const n = pts.length;
  if (n < 2) return;
  if (n === 2) {
    ctx.beginPath();
    ctx.moveTo(pts[0].x, pts[0].y);
    ctx.lineTo(pts[1].x, pts[1].y);
    return;
  }
  const dx = new Float64Array(n - 1);
  const m = new Float64Array(n - 1);
  for (let i = 0; i < n - 1; i++) {
    dx[i] = pts[i + 1].x - pts[i].x;
    m[i] = (pts[i + 1].y - pts[i].y) / (dx[i] || 1e-6);
  }
  const d = new Float64Array(n);
  d[0] = m[0];
  d[n - 1] = m[n - 2];
  for (let i = 1; i < n - 1; i++) {
    if (m[i - 1] * m[i] <= 0) {
      d[i] = 0;
    } else {
      d[i] = (m[i - 1] + m[i]) / 2;
    }
  }
  for (let i = 0; i < n - 1; i++) {
    if (Math.abs(m[i]) < 1e-9) {
      d[i] = 0;
      d[i + 1] = 0;
    } else {
      const alpha = d[i] / m[i];
      const beta = d[i + 1] / m[i];
      const dist = alpha * alpha + beta * beta;
      if (dist > 9) {
        const tau = 3 / Math.sqrt(dist);
        d[i] = tau * alpha * m[i];
        d[i + 1] = tau * beta * m[i];
      }
    }
  }
  ctx.beginPath();
  ctx.moveTo(pts[0].x, pts[0].y);
  for (let i = 0; i < n - 1; i++) {
    const h = dx[i] / 3;
    ctx.bezierCurveTo(
      pts[i].x + h,
      pts[i].y + d[i] * h,
      pts[i + 1].x - h,
      pts[i + 1].y - d[i + 1] * h,
      pts[i + 1].x,
      pts[i + 1].y
    );
  }
}

function drawChart() {
  const canvas = $("chart");
  if (!canvas || !canvas.parentElement) return;
  const width = canvas.parentElement.clientWidth, height = canvas.parentElement.clientHeight, dpr = window.devicePixelRatio || 1;
  if (!width || !height) return;
  canvas.width = Math.round(width * dpr); canvas.height = Math.round(height * dpr);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);

  const data = getFilteredHistory(selectedRange);
  if ($("chartCount")) $("chartCount").textContent = data.length.toLocaleString("en-IN") + " records";

  const isDark = document.documentElement.getAttribute("data-theme") === "dark" ||
    (!document.documentElement.getAttribute("data-theme") && window.matchMedia("(prefers-color-scheme: dark)").matches);

  const styles = getComputedStyle(document.body);
  const colorGold = (styles.getPropertyValue("--gold").trim()) || (isDark ? "#d4ab63" : "#a97f34");
  const colorTextTertiary = (styles.getPropertyValue("--ink-faint").trim()) || (isDark ? "#786d5c" : "#a89d88");

  if (data.length < 2) return;

  const values = data.map(i => Number(i.rate_22k));
  const min0 = values.reduce((a, b) => Math.min(a, b), Infinity);
  const max0 = values.reduce((a, b) => Math.max(a, b), -Infinity);
  const pad = Math.max(60, (max0 - min0) * 0.16);
  const min = min0 - pad, max = max0 + pad;

  const L = 52, R = 14, T = 22, B = 24;
  const plotW = width - L - R, plotH = height - T - B;

  const py = val => T + (1 - ((val - min) / (max - min))) * plotH;
  const points = values.map((val, i) => ({ x: L + (i / (values.length - 1)) * plotW, y: py(val) }));

  // 1. Horizontal Grid Lines + Price Labels
  ctx.font = "600 10px var(--font-sans)";
  ctx.textAlign = "right";
  ctx.lineWidth = 1;

  for (let i = 0; i <= 4; i++) {
    const gy = T + (plotH * i / 4);
    ctx.strokeStyle = isDark ? "rgba(255, 255, 255, 0.05)" : "rgba(148, 163, 184, 0.14)";
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.moveTo(L, gy);
    ctx.lineTo(width - R, gy);
    ctx.stroke();

    const gridVal = max - ((max - min) * i / 4);
    ctx.fillStyle = colorTextTertiary;
    ctx.fillText(Math.round(gridVal).toLocaleString("en-IN"), L - 8, gy + 3.5);
  }

  // Period Open Baseline (reference line only — no label)
  const openY = points[0].y;
  ctx.strokeStyle = isDark ? "rgba(212, 171, 99, 0.24)" : "rgba(169, 127, 52, 0.22)";
  ctx.lineWidth = 1;
  ctx.setLineDash([3, 3]);
  ctx.beginPath();
  ctx.moveTo(L, openY);
  ctx.lineTo(width - R, openY);
  ctx.stroke();
  ctx.setLineDash([]);

  if (typeof chartViewMode !== "undefined" && chartViewMode === "spread") {
    // AM/PM Session Spread Bar View
    const dayMap = new Map();
    data.forEach(r => {
      const d = r.date;
      if (!dayMap.has(d)) dayMap.set(d, { date: d, am: null, pm: null, rates: [] });
      const entry = dayMap.get(d);
      const val = Number(r.rate_22k);
      entry.rates.push(val);
      const isAm = r.session === "AM" || (r.time && parseInt(String(r.time).split(":")[0], 10) < 14);
      if (isAm && entry.am === null) entry.am = val;
      else entry.pm = val;
    });

    const days = Array.from(dayMap.values());
    const barW = Math.max(8, Math.min(28, (plotW / Math.max(1, days.length)) * 0.72));

    days.forEach((day, i) => {
      const cx = L + (i / Math.max(1, days.length - 1)) * plotW;
      const amVal = day.am ?? day.rates[0];
      const pmVal = day.pm ?? day.rates[day.rates.length - 1];
      const isUp = pmVal >= amVal;
      const dayHigh = Math.max(...day.rates, amVal, pmVal);
      const dayLow = Math.min(...day.rates, amVal, pmVal);
      const yHigh = py(dayHigh);
      const yLow = py(dayLow);
      const yOpen = py(amVal);
      const yClose = py(pmVal);
      const yBodyTop = Math.min(yOpen, yClose);
      const yBodyBot = Math.max(yOpen, yClose);
      const barH = Math.max(4, yBodyBot - yBodyTop);

      const strokeColor = isUp ? (isDark ? "#7bd39a" : "#337a4c") : (isDark ? "#e0897c" : "#ad3d30");
      const fillColor = isUp
        ? (isDark ? "rgba(123, 211, 154, 0.4)" : "rgba(51, 122, 76, 0.35)")
        : (isDark ? "rgba(224, 137, 124, 0.4)" : "rgba(173, 61, 48, 0.35)");

      // 1. Candlestick Wick (High to Low)
      ctx.strokeStyle = strokeColor;
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      ctx.moveTo(cx, yHigh);
      ctx.lineTo(cx, yLow);
      ctx.stroke();

      // 2. Candlestick Body (Open to Close)
      ctx.fillStyle = fillColor;
      ctx.strokeStyle = strokeColor;
      ctx.lineWidth = 1.4;
      const r = Math.min(3, barW / 4);
      ctx.beginPath();
      ctx.moveTo(cx - barW / 2 + r, yBodyTop);
      ctx.arcTo(cx + barW / 2, yBodyTop, cx + barW / 2, yBodyTop + barH, r);
      ctx.arcTo(cx + barW / 2, yBodyTop + barH, cx - barW / 2, yBodyTop + barH, r);
      ctx.arcTo(cx - barW / 2, yBodyTop + barH, cx - barW / 2, yBodyTop, r);
      ctx.arcTo(cx - barW / 2, yBodyTop, cx + barW / 2, yBodyTop, r);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
    });
  } else {
    // 3. Monotone Spline Fill Gradient
    drawSpline(ctx, points);
    ctx.lineTo(points[points.length - 1].x, height - B);
    ctx.lineTo(points[0].x, height - B);
    ctx.closePath();

    const fillGrad = ctx.createLinearGradient(0, T, 0, height - B);
    if (isDark) {
      fillGrad.addColorStop(0, "rgba(212, 171, 99, 0.26)");
      fillGrad.addColorStop(0.4, "rgba(212, 171, 99, 0.10)");
      fillGrad.addColorStop(0.8, "rgba(212, 171, 99, 0.02)");
      fillGrad.addColorStop(1, "rgba(212, 171, 99, 0)");
    } else {
      fillGrad.addColorStop(0, "rgba(169, 127, 52, 0.20)");
      fillGrad.addColorStop(0.45, "rgba(169, 127, 52, 0.07)");
      fillGrad.addColorStop(0.85, "rgba(169, 127, 52, 0.015)");
      fillGrad.addColorStop(1, "rgba(169, 127, 52, 0)");
    }
    ctx.fillStyle = fillGrad;
    ctx.fill();

    // 4. Dual-Stroke Spline: Underlying Ambient Glow + Crisp Line
    drawSpline(ctx, points);
    ctx.strokeStyle = isDark ? "rgba(212, 171, 99, 0.25)" : "rgba(169, 127, 52, 0.2)";
    ctx.lineWidth = 4.5;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.stroke();

    drawSpline(ctx, points);
    ctx.strokeStyle = colorGold;
    ctx.lineWidth = 2.2;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.stroke();

    // 5. Session Data Dots — removed for cleaner look

    // 6. High & Low Callout Badges (Pinned to Peak and Valley)
    if (data.length >= 3) {
      let maxIdx = 0, minIdx = 0;
      for (let i = 1; i < values.length; i++) {
        if (values[i] > values[maxIdx]) maxIdx = i;
        if (values[i] < values[minIdx]) minIdx = i;
      }

      const drawCallout = (pt, label, isPeak) => {
        const pillW = 54, pillH = 17;
        const bx = Math.max(L + 2, Math.min(width - R - pillW - 2, pt.x - pillW / 2));
        const by = isPeak ? Math.max(T - 18, pt.y - pillH - 6) : Math.min(height - B - pillH - 2, pt.y + 6);

        ctx.fillStyle = isDark ? "rgba(20, 17, 13, 0.85)" : "rgba(255, 255, 255, 0.88)";
        ctx.strokeStyle = isPeak
          ? (isDark ? "rgba(123, 211, 154, 0.45)" : "rgba(51, 122, 76, 0.35)")
          : (isDark ? "rgba(224, 137, 124, 0.45)" : "rgba(173, 61, 48, 0.35)");
        ctx.lineWidth = 1;

        const r = 4;
        ctx.beginPath();
        ctx.moveTo(bx + r, by);
        ctx.arcTo(bx + pillW, by, bx + pillW, by + pillH, r);
        ctx.arcTo(bx + pillW, by + pillH, bx, by + pillH, r);
        ctx.arcTo(bx, by + pillH, bx, by, r);
        ctx.arcTo(bx, by, bx + pillW, by, r);
        ctx.closePath();
        ctx.fill();
        ctx.stroke();

        ctx.font = "700 8.5px var(--font-sans)";
        ctx.textAlign = "center";
        ctx.fillStyle = isPeak
          ? (isDark ? "#7bd39a" : "#337a4c")
          : (isDark ? "#e0897c" : "#ad3d30");
        ctx.fillText(label, bx + pillW / 2, by + 11.5);
      };

      if (maxIdx !== minIdx) {
        drawCallout(points[maxIdx], "▲ " + money(max0), true);
        drawCallout(points[minIdx], "▼ " + money(min0), false);
      }
    }
  }

    // 6b. Support, Resistance & Pivot Reference Lines
    if (window.__signals && window.__signals.support_resistance) {
      const sr = window.__signals.support_resistance;
      const py = val => T + (1 - ((val - min) / (max - min))) * plotH;

      if (sr.resistance && sr.resistance >= min && sr.resistance <= max) {
        const ry = py(sr.resistance);
        ctx.strokeStyle = "rgba(234, 179, 8, 0.65)";
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.moveTo(L, ry);
        ctx.lineTo(width - R, ry);
        ctx.stroke();
        ctx.fillStyle = "rgba(234, 179, 8, 0.9)";
        ctx.font = "600 8.5px var(--font-sans)";
        ctx.textAlign = "right";
        ctx.fillText(`Resist ${money(sr.resistance)}`, width - R - 6, ry - 4);
      }

      if (sr.pivot && sr.pivot >= min && sr.pivot <= max) {
        const pvy = py(sr.pivot);
        ctx.strokeStyle = "rgba(148, 163, 184, 0.55)";
        ctx.lineWidth = 1;
        ctx.setLineDash([2, 2]);
        ctx.beginPath();
        ctx.moveTo(L, pvy);
        ctx.lineTo(width - R, pvy);
        ctx.stroke();
        ctx.fillStyle = isDark ? "#a89d88" : "#6b6255";
        ctx.font = "600 8.5px var(--font-sans)";
        ctx.textAlign = "right";
        ctx.fillText(`Pivot ${money(sr.pivot)}`, width - R - 6, pvy - 4);
      }

      if (sr.support && sr.support >= min && sr.support <= max) {
        const sy = py(sr.support);
        ctx.strokeStyle = "rgba(59, 130, 246, 0.65)";
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.moveTo(L, sy);
        ctx.lineTo(width - R, sy);
        ctx.stroke();
        ctx.fillStyle = "rgba(59, 130, 246, 0.9)";
        ctx.font = "600 8.5px var(--font-sans)";
        ctx.textAlign = "right";
        ctx.fillText(`Support ${money(sr.support)}`, width - R - 6, sy + 11);
      }
      ctx.setLineDash([]);
    }


  // 7. Interactive Scrub Crosshairs & Tooltip
  const activeIdx = (scrubIndex >= 0 && scrubIndex < data.length) ? scrubIndex : data.length - 1;
  const activePt = points[activeIdx];

  if (scrubIndex >= 0) {
    // Vertical Crosshair
    ctx.strokeStyle = colorGold;
    ctx.lineWidth = 1.2;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(activePt.x, T);
    ctx.lineTo(activePt.x, height - B);
    ctx.stroke();

    // Horizontal Crosshair to Y Axis
    ctx.beginPath();
    ctx.moveTo(L, activePt.y);
    ctx.lineTo(activePt.x, activePt.y);
    ctx.stroke();
    ctx.setLineDash([]);

    // Y Axis Scrub Price Pill
    const priceText = money(values[activeIdx]);
    ctx.font = "700 9.5px var(--font-sans)";
    const pW = ctx.measureText(priceText).width + 8;
    ctx.fillStyle = colorGold;
    ctx.fillRect(L - pW - 2, activePt.y - 7.5, pW, 15);
    ctx.fillStyle = isDark ? "#100e0a" : "#ffffff";
    ctx.textAlign = "center";
    ctx.fillText(priceText, L - 2 - pW / 2, activePt.y + 3.5);
  }

  // Active Point Circle
  ctx.fillStyle = colorGold;
  ctx.beginPath();
  ctx.arc(activePt.x, activePt.y, scrubIndex >= 0 ? 5.5 : 4, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = styles.getPropertyValue("--paper-raised").trim() || (isDark ? "#1c1912" : "#ffffff");
  ctx.lineWidth = 2.5;
  ctx.stroke();

  if ($("chartStart")) $("chartStart").textContent = "From: " + dateText(data[0].date);
  if ($("chartEnd")) $("chartEnd").textContent = "To: " + dateText(data[data.length - 1].date);

  const delta = values[values.length - 1] - values[0];
  const pct = values[0] ? (delta / values[0] * 100) : 0;

  if (scrubIndex >= 0) {
    if ($("chartMetricLabel")) $("chartMetricLabel").textContent = "Selected Benchmark";
    if ($("periodChange")) {
      $("periodChange").textContent = money(values[activeIdx]) + "/g";
      $("periodChange").className = "";
    }
  } else {
    if ($("chartMetricLabel")) $("chartMetricLabel").textContent = "Period Performance";
    if ($("periodChange")) {
      $("periodChange").textContent = (delta >= 0 ? "+" : "") + money(delta) + ` (${(pct >= 0 ? "+" : "")}${pct.toFixed(1)}%)`;
      $("periodChange").className = delta > 0 ? "positive" : delta < 0 ? "negative" : "";
    }
  }
  if ($("periodHigh")) $("periodHigh").textContent = money(max0);
  if ($("periodLow")) $("periodLow").textContent = money(min0);
  if (typeof window.updateInsights === "function") window.updateInsights();
}

(function setupChartScrub() {
  const canvas = $("chart");
  if (!canvas) return;
  const handle = e => {
    const data = getFilteredHistory(selectedRange);
    if (data.length < 2) return;
    const r = canvas.getBoundingClientRect();
    const clientX = e.touches ? e.touches[0].clientX : e.clientX;
    const x = clientX - r.left;
    const L = 52, plotW = r.width - L - 12;
    const ratio = Math.max(0, Math.min(1, (x - L) / plotW));
    const idx = Math.round(ratio * (data.length - 1));
    if (idx !== scrubIndex) {
      scrubIndex = idx;
      haptic(5, 1200);
      drawChart();
    }
    if (typeof window.showChartTip === "function") window.showChartTip(clientX, idx);
  };
  const end = () => {
    if (scrubIndex !== -1) {
      scrubIndex = -1;
      drawChart();
    }
    if (typeof window.hideChartTip === "function") window.hideChartTip();
  };
  canvas.addEventListener("touchstart", handle, { passive: true });
  canvas.addEventListener("touchmove", handle, { passive: true });
  canvas.addEventListener("touchend", end);
  canvas.addEventListener("mousemove", e => { if (e.buttons === 1) handle(e); });
  canvas.addEventListener("mouseup", end);
  canvas.addEventListener("mouseleave", end);
})();


function positionRangeThumb() {
  const thumb = $("rangesThumb");
  const activeBtn = document.querySelector("#ranges button.active");
  if (!thumb || !activeBtn) return;
  const buttons = [...document.querySelectorAll("#ranges button")];
  const idx = buttons.indexOf(activeBtn);
  thumb.style.transform = `translateX(${idx * 100}%)`;
}

document.querySelectorAll("#ranges button").forEach(b => b.onclick = () => {
  haptic(8);
  document.querySelectorAll("#ranges button").forEach(x => x.classList.remove("active"));
  b.classList.add("active");
  positionRangeThumb();
  selectedRange = b.dataset.range === "all" ? "all" : Number(b.dataset.range);
  drawChart();
  if (typeof window.updateInsights === "function") window.updateInsights();
});
positionRangeThumb();
window.addEventListener("resize", positionRangeThumb);

window.addEventListener("resize", () => { if (typeof drawChart === "function") drawChart(); });
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { if (typeof drawChart === "function") drawChart(); });

// Interactive Tooltip and Scrub Crosshairs
(() => {
  'use strict';
  const byId = id => document.getElementById(id);
  const chart=byId('chart'), wrap=byId('chartWrap'), tip=byId('chartTooltip');
  const tipDate=byId('chartTipDate'), tipRate=byId('chartTipRate'), tipSession=byId('chartTipSession');
  let activeHover=-1;

  function sessionLabel(rec){
    if(rec?.session) return String(rec.session).toUpperCase();
    const h=rec?.time?parseInt(String(rec.time).split(':')[0],10):NaN;
    return Number.isFinite(h)&&h<14?'AM':'PM';
  }
  function showTip(clientX, idx){
    if(!chart||!wrap||!tip||typeof getFilteredHistory!=='function')return;
    const data=getFilteredHistory(typeof selectedRange!=='undefined'?selectedRange:30);
    if(!data.length||idx<0||idx>=data.length)return;
    const r=chart.getBoundingClientRect(), wr=wrap.getBoundingClientRect();
    const L=52, plotW=Math.max(1,r.width-L-12);
    const x=Math.max(L,Math.min(r.width-12,clientX-r.left));
    const left=Math.max(75,Math.min(wr.width-75, x));
    tip.style.left=left+'px';

    const vals=data.map(i=>Number(i.rate_22k));
    const min0=vals.reduce((a,b)=>Math.min(a,b),Infinity);
    const max0=vals.reduce((a,b)=>Math.max(a,b),-Infinity);
    const pad=Math.max(60,(max0-min0)*0.16);
    const min=min0-pad, max=max0+pad;
    const T=22, B=24, plotH=r.height-T-B;
    const ptY=T+(1-((vals[idx]-min)/(max-min)))*plotH;
    tip.style.top=Math.max(68, ptY)+'px';

    const rec=data[idx], rate=Number(rec.rate_22k);
    const timeFormatted=rec.time?(typeof timeText==='function'?timeText(rec.time):rec.time):'';
    tipDate.textContent=(typeof dateText==='function'?dateText(rec.date):rec.date)+(timeFormatted?' · '+timeFormatted:'');
    tipRate.textContent=typeof money==='function'?money(rate)+'/g':'₹ '+rate.toLocaleString('en-IN')+'/g';
    if (typeof chartViewMode !== 'undefined' && chartViewMode === 'spread') {
      const dayRows = (typeof history !== 'undefined' ? history : []).filter(x => x.date === rec.date);
      const am = dayRows.find(x => x.session === 'AM' || (x.time && parseInt(x.time, 10) < 14));
      const pm = [...dayRows].reverse().find(x => x.session === 'PM' || (x.time && parseInt(x.time, 10) >= 14));
      if (am && pm) {
        const sDiff = Number(pm.rate_22k) - Number(am.rate_22k);
        tipSession.textContent = `AM: ${money(am.rate_22k)} · PM: ${money(pm.rate_22k)} (${sDiff >= 0 ? '+' : ''}${money(sDiff)})`;
      } else {
        tipSession.textContent = 'Session Benchmark: ' + money(rate);
      }
    } else {
      tipSession.textContent=sessionLabel(rec)+' benchmark';
    }
    tip.hidden=false; activeHover=idx;
  }
  function hideTip(){if(tip)tip.hidden=true;activeHover=-1;}
  window.showChartTip=showTip;
  window.hideChartTip=hideTip;

  function hover(e){
    if(!chart||!wrap||typeof getFilteredHistory!=='function')return;
    const data=getFilteredHistory(typeof selectedRange!=='undefined'?selectedRange:30); if(data.length<2)return;
    const r=chart.getBoundingClientRect();
    const clientX=e.touches?e.touches[0].clientX:e.clientX;
    const x=clientX-r.left;
    const L=52, plotW=Math.max(1,r.width-L-12); const ratio=Math.max(0,Math.min(1,(x-L)/plotW));
    const idx=Math.round(ratio*(data.length-1));
    if(idx!==scrubIndex){scrubIndex=idx;drawChart();}
    showTip(clientX,idx);
  }
  function endScrub(){
    if(scrubIndex!==-1){scrubIndex=-1;drawChart();}
    hideTip();
  }

  if(chart){
    chart.addEventListener('pointermove',e=>{if(e.pointerType==='mouse'||e.buttons===1) hover(e);},{passive:true});
    chart.addEventListener('pointerdown',hover,{passive:true});
    chart.addEventListener('pointerup',endScrub,{passive:true});
    chart.addEventListener('pointerleave',endScrub,{passive:true});
    chart.addEventListener('pointercancel',endScrub,{passive:true});
  }
})();
