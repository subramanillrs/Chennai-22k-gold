// ============================================================
// MAIN APPLICATION ORCHESTRATOR & PWA LIFECYCLE
// ============================================================

function triggerPriceUpdatedGlow() {
  const el1 = $("hero1");
  const el8 = $("hero8");
  [el1, el8].forEach(el => {
    if (!el) return;
    el.classList.remove("price-updated");
    void el.offsetWidth;
    el.classList.add("price-updated");
    const cleanup = () => {
      el.classList.remove("price-updated");
      el.removeEventListener("animationend", cleanup);
    };
    el.addEventListener("animationend", cleanup, { once: true });
  });
}
window.triggerPriceUpdatedGlow = triggerPriceUpdatedGlow;

function setStatus(text, offline = false, syncing = false) {
  const elText = $("statusText");
  const elStatus = $("status");
  if (elText) elText.textContent = text;
  if (elStatus) {
    elStatus.classList.toggle("offline", offline);
    elStatus.classList.toggle("syncing", syncing);
    elStatus.classList.toggle("live-pulse", !offline && !syncing);
  }
}



// Quantitative Financial Signals Rendering
function renderSignals(signalsData) {
  if (!signalsData) return;
  window.__signals = signalsData;

  // 1. Sentiment Ring
  if (signalsData.sentiment) {
    const s = signalsData.sentiment;
    const score = Number(s.sentiment_score) || 50;
    if ($("sentimentScore")) $("sentimentScore").textContent = score;
    if ($("sentimentLabel")) {
      $("sentimentLabel").textContent = s.sentiment_label || "Neutral";
      $("sentimentLabel").className = `signal-tag ${String(s.sentiment_label).toLowerCase()}`;
    }
    if ($("sentimentHint")) $("sentimentHint").textContent = s.action_hint || "";
    if ($("signalSummaryBadge")) {
      $("signalSummaryBadge").textContent = (s.sentiment_label || "NEUTRAL").toUpperCase();
      $("signalSummaryBadge").className = `signal-tag ${String(s.sentiment_label).toLowerCase()}`;
    }
    const ring = $("sentimentRing");
    if (ring) {
      const offset = 251.2 * (1 - (score / 100));
      ring.style.strokeDashoffset = offset;
      ring.style.stroke = score >= 62 ? "var(--good)" : (score <= 40 ? "var(--bad)" : "var(--gold)");
    }
  }

  // 2. RSI Gauge
  if (signalsData.rsi) {
    const rsi = signalsData.rsi;
    const val = Number(rsi.rsi_14) || 50;
    if ($("rsiVal")) $("rsiVal").textContent = val.toFixed(2);
    if ($("rsiNeedle")) {
      const clampedLeft = Math.max(0, Math.min(100, val));
      $("rsiNeedle").style.left = `${clampedLeft}%`;
    }
    if ($("rsiSignalTag")) {
      const sig = rsi.rsi_signal || "HOLD";
      $("rsiSignalTag").textContent = sig;
      $("rsiSignalTag").className = `signal-tag ${sig.toLowerCase()}`;
    }
    if ($("rsiZone")) {
      const zoneName = rsi.rsi_zone || "neutral";
      const desc = zoneName === "oversold" ? "Oversold (Accumulation Zone)" : (zoneName === "overbought" ? "Overbought (Caution Zone)" : "Neutral Range");
      $("rsiZone").textContent = desc;
    }
  }

  // 3. EMA Status Strip
  if (signalsData.ema_crossover) {
    const ema = signalsData.ema_crossover;
    const mom = Number(ema.momentum) || 0;
    const momPct = Number(ema.momentum_pct) || 0;
    const sig = ema.signal || "neutral";
    if ($("emaSignalText")) {
      $("emaSignalText").textContent = `EMA 9: ${money(ema.ema_9)} · EMA 21: ${money(ema.ema_21)} (Momentum: ${mom >= 0 ? "+" : ""}${mom.toFixed(1)}/g, ${momPct.toFixed(2)}%)`;
    }
    if ($("emaAction")) {
      $("emaAction").textContent = sig.toUpperCase();
      $("emaAction").style.color = sig === "bullish" ? "var(--good)" : (sig === "bearish" ? "var(--bad)" : "var(--ink)");
    }
  }

  // 4. Holt-Winters Forecasts
  if (signalsData.forecast && live && live.rate_22k) {
    const fc = signalsData.forecast;
    const cur = Number(live.rate_22k);
    const updateFc = (elId, deltaId, price) => {
      if ($(elId) && price) {
        $(elId).textContent = money(price);
        const deltaPct = ((price - cur) / cur) * 100;
        if ($(deltaId)) {
          const isPos = deltaPct >= 0;
          $(deltaId).textContent = `${isPos ? "▲ +" : "▼ "}${deltaPct.toFixed(2)}%`;
          $(deltaId).className = `fc-delta ${isPos ? "positive" : "negative"}`;
        }
      }
    };
    updateFc("fc1d", "fc1dDelta", fc.forecast_1d);
    updateFc("fc3d", "fc3dDelta", fc.forecast_3d);
    updateFc("fc7d", "fc7dDelta", fc.forecast_7d);
  }

  if (typeof drawChart === "function") {
    requestAnimationFrame(drawChart);
  }
}



const dateText = s => {
  if (!s) return "—";
  const d = new Date(String(s) + "T00:00:00");
  return isNaN(d.getTime()) ? String(s) : d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
};

const timeText = s => {
  if (!s) return "—";
  const parts = String(s).split(":");
  if (parts.length < 2) return String(s);
  let hour = Number(parts[0]);
  if (!Number.isFinite(hour)) return String(s);
  const ap = hour >= 12 ? "PM" : "AM";
  hour = hour % 12 || 12;
  return hour + ":" + parts[1] + " " + ap;
};

const esc = s => String(s ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");

const formatLiveStatus = s => {
  let hhmm = "";
  if (s && typeof s === "string") {
    const parts = s.split(":");
    if (parts.length >= 2) {
      hhmm = `${parts[0].padStart(2, "0")}:${parts[1].padStart(2, "0")}`;
    }
  }
  if (!hhmm) {
    try {
      const parts = new Intl.DateTimeFormat("en-GB", {
        timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hourCycle: "h23"
      }).formatToParts(new Date());
      const h = parts.find(p => p.type === "hour")?.value || "";
      const m = parts.find(p => p.type === "minute")?.value || "";
      if (h && m) hhmm = `${h}:${m}`;
    } catch (_) {}
  }
  return hhmm ? `Live ${hhmm} IST` : "Live IST";
};
window.formatLiveStatus = formatLiveStatus;


function renderLive(d) {
  if (!d) return;
  live = d;
  const rate = Number(d.rate_22k);
  const rate8 = Number.isFinite(Number(d.rate_8g)) ? Number(d.rate_8g) : rate * 8;

  if ($("hero8")) $("hero8").textContent = money(rate8);
  if ($("today")) $("today").textContent = dateText(d.date);

  const isFreshToday = isLiveDataFresh(d);
  if ($("todayTime")) $("todayTime").textContent = timeText(d.time) + (isFreshToday ? "" : " · Previous Close");
  if ($("staleWarning")) $("staleWarning").hidden = isFreshToday;

  let currentSession = d.session;
  if (!currentSession) {
    if (d.time) {
      const hr = parseInt(String(d.time).split(":")[0], 10);
      currentSession = (hr >= 6 && hr < 14) ? "AM" : "PM";
    } else {
      currentSession = "PM";
    }
  }
  if ($("session")) $("session").textContent = currentSession + " Fix";

  const fineness22 = 0.916;
  const purity24Rate = Number(d.rate_24k) || (rate * (0.999 / fineness22));
  const purity18Rate = rate * (0.750 / fineness22);
  if ($("purity22")) $("purity22").textContent = money(rate) + "/g";
  if ($("purity24")) $("purity24").textContent = money(Math.round(purity24Rate)) + "/g";
  if ($("purity18")) $("purity18").textContent = money(Math.round(purity18Rate)) + "/g";

  let prevClose = Number(d.previous_close_22k);
  if (!Number.isFinite(prevClose) || prevClose <= 0) {
    if (typeof getPreviousClose === "function") {
      prevClose = getPreviousClose(d.date);
    }
  }
  if (!Number.isFinite(prevClose) || prevClose <= 0) {
    if (Number.isFinite(Number(d.previous_rate_22k)) && Number(d.previous_rate_22k) !== rate) {
      prevClose = Number(d.previous_rate_22k);
    }
  }

  let change1 = null;
  if (Number.isFinite(prevClose) && prevClose > 0) {
    change1 = rate - prevClose;
  } else if (Number.isFinite(Number(d.change)) && Number(d.change) !== 0) {
    change1 = Number(d.change);
  } else {
    change1 = 0;
  }
  const change8 = change1 * 8;

  const change1Text = change1 > 0 ? "+" + money(change1) : change1 < 0 ? "-" + money(Math.abs(change1)) : "Flat";
  const change1Class = "change-pill mini " + (change1 > 0 ? "up" : change1 < 0 ? "down" : "same");
  const elHero1Rate = $("hero1Rate");
  const elChange1 = $("change1");
  if (elHero1Rate && elChange1) {
    elHero1Rate.textContent = money(rate);
    elChange1.className = change1Class;
    elChange1.textContent = change1Text;
  } else if ($("hero1")) {
    $("hero1").innerHTML = `<span id="hero1Rate">${money(rate)}</span> <span id="change1" class="${change1Class}">${change1Text}</span>`;
  }

  if ($("change8")) {
    $("change8").textContent = change8 > 0 ? "▲ +" + money(change8) + " Today" : change8 < 0 ? "▼ -" + money(Math.abs(change8)) + " Today" : "No change";
    $("change8").className = "change-pill " + (change8 > 0 ? "up" : change8 < 0 ? "down" : "same");
  }

  renderTodayTimeline();
  updateSpreadDashboard(d, history);
  if (typeof renderPortfolio === "function") renderPortfolio();
  if (typeof window.refreshPortfolio === "function") window.refreshPortfolio();
  if (typeof window.checkTargetPrice === "function") window.checkTargetPrice();
  if (typeof window.calculateGoldSchemeVsSip === "function") window.calculateGoldSchemeVsSip();
  if (typeof auditJewellerBill === "function") auditJewellerBill();
  if (typeof calculateOldGoldMelt === "function") calculateOldGoldMelt();
}

function renderTodayTimeline() {
  if (!live) return;
  const today = live.date;
  const isFreshToday = isLiveDataFresh(live);

  if (!isFreshToday) {
    if ($("amRate")) $("amRate").textContent = "Pending";
    if ($("amTime")) $("amTime").textContent = "—";
    if ($("pmRate")) $("pmRate").textContent = "Pending";
    if ($("pmTime")) $("pmTime").textContent = "—";
    if ($("amCard")) $("amCard").classList.remove("is-active");
    if ($("pmCard")) $("pmCard").classList.remove("is-active");
    return;
  }

  // Only trust an explicit session tag from the source. Guessing a
  // session from clock hour is unreliable (fix times drift day to
  // day -- see monitoring_windows.json), so it's used only as a last
  // resort, and a record built that way is marked estimated rather
  // than presented as an authoritative fix.
  const sessionOf = h => {
    if (h.session) return String(h.session).toUpperCase();
    const hr = h.time ? parseInt(String(h.time).split(":")[0], 10) : null;
    if (hr === null || Number.isNaN(hr)) return null;
    return hr < 14 ? "AM" : "PM";
  };

  const todayHistory = history.filter(h => h.date === today);
  const amHist = todayHistory.find(h => sessionOf(h) === "AM");
  const pmHist = [...todayHistory].reverse().find(h => sessionOf(h) === "PM");

  let am = amHist ? { rate_22k: Number(amHist.rate_22k), time: amHist.time || "10:30", estimated: !amHist.session } : null;
  let pm = pmHist ? { rate_22k: Number(pmHist.rate_22k), time: pmHist.time || "17:00", estimated: !pmHist.session } : null;

  // The live feed itself is today's most recent tick -- if it isn't
  // already covered by history, fold it in under its own actual
  // session (never guessed from the other session's absence).
  const liveSession = sessionOf(live);
  if (liveSession === "AM" && !am) {
    am = { rate_22k: Number(live.rate_22k), time: live.time || "10:30", estimated: !live.session };
  }
  if (liveSession === "PM" && !pm) {
    pm = { rate_22k: Number(live.rate_22k), time: live.time || "17:00", estimated: !live.session };
  }
  // Deliberately NOT synthesizing a fake AM fix from previous_rate_22k
  // when only PM is known -- that was a guess presented as an
  // observed value. Show "Pending" instead of a fabricated number.

  const fmtRate = r => r && Number.isFinite(r.rate_22k) ? money(r.rate_22k) + (r.estimated ? " *" : "") : "Pending";

  if ($("amRate")) $("amRate").textContent = fmtRate(am);
  if ($("amTime")) $("amTime").textContent = am ? timeText(am.time) : "—";

  if ($("pmRate")) $("pmRate").textContent = fmtRate(pm);
  if ($("pmTime")) $("pmTime").textContent = pm ? timeText(pm.time) : "—";

  const isPmActive = Boolean(pm && Number.isFinite(pm.rate_22k));
  const isAmActive = Boolean(am && Number.isFinite(am.rate_22k) && !isPmActive);

  if ($("amCard")) $("amCard").classList.toggle("is-active", isAmActive);
  if ($("pmCard")) $("pmCard").classList.toggle("is-active", isPmActive);
  if (typeof renderFixHeatmap === "function") renderFixHeatmap();
}


if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("sw.js")
      .then(reg => {
        if (reg && typeof reg.update === "function") {
          reg.update().catch(() => {});
        }
      })
      .catch(e => console.warn("SW skipped:", e));
  });

  navigator.serviceWorker.addEventListener("message", (event) => {
    if (event.data && event.data.type === "LIVE_DATA_REFRESHED" && event.data.payload) {
      console.info("[ServiceWorker] Received fresh live data broadcast, updating UI");
      renderLive(event.data.payload);
      calculate();
    }
  });

  navigator.serviceWorker.addEventListener("controllerchange", () => {
    console.info("[ServiceWorker] New controller took over, rehydrating live rate");
    if (typeof loadLiveOnly === "function") loadLiveOnly(true).catch(() => {});
  });
}


(function setupPullToRefresh() {
  const PULL_THRESHOLD = 64, PULL_MAX = 90;
  const pulldown = $("pulldown"), pulldownText = $("pulldownText");
  let startY = null, dragging = false, ready = false;

  function atTop() { return (window.scrollY || 0) <= 0 && (document.scrollingElement ? document.scrollingElement.scrollTop : 0) <= 0; }

  function resetPulldown() {
    if (!pulldown) return;
    pulldown.classList.remove("visible", "ready", "loading");
    pulldown.style.transform = "";
    if (pulldownText) pulldownText.textContent = "Pull to refresh";
    startY = null; dragging = false; ready = false;
  }

  document.addEventListener("touchstart", event => {
    if (fetchBusy || event.target.closest(".table-wrap") || !atTop()) return;
    startY = event.touches[0].clientY;
    dragging = true; ready = false;
  }, { passive: true });

  document.addEventListener("touchmove", event => {
    if (!dragging || startY === null) return;
    if (!atTop()) { resetPulldown(); return; }

    const delta = event.touches[0].clientY - startY;
    if (delta <= 0) return;
    if (event.cancelable) event.preventDefault();

    const pulled = Math.min(delta * 0.5, PULL_MAX);
    if (pulldown) {
      pulldown.classList.add("visible");
      pulldown.style.transform = `translate(-50%, ${pulled - 70}px)`;
      ready = pulled >= PULL_THRESHOLD * 0.5;
      pulldown.classList.toggle("ready", ready);
    }
    if (pulldownText) pulldownText.textContent = ready ? "Release to sync" : "Pull to refresh";
    setStatus(ready ? "Release to sync market" : "Pulling to refresh…", false, true);
  }, { passive: false });

  document.addEventListener("touchend", () => {
    if (!dragging) return;
    if (ready && !fetchBusy) {
      if (pulldown) {
        pulldown.classList.add("loading");
        pulldown.classList.remove("ready");
        pulldown.style.transform = "translate(-50%, 14px)";
      }
      if (pulldownText) pulldownText.textContent = "Syncing…";
      manualFetch().finally(resetPulldown);
    } else {
      resetPulldown();
      if (live) setStatus(formatLiveStatus(live.time));
    }
    dragging = false; startY = null;
  }, { passive: true });

  document.addEventListener("touchcancel", resetPulldown, { passive: true });
})();


(async function init() {
  // 1. Zero-Latency Synchronous Bootstrap (<10ms perceived boot time)
  let bootstrapData = null;
  try {
    const bootEl = $("gold-bootstrap");
    if (bootEl && bootEl.textContent) {
      bootstrapData = JSON.parse(bootEl.textContent);
    }
  } catch (_) {}

  let savedLive = null;
  let savedHistory = null;
  try {
    savedLive = JSON.parse(localStorage.getItem("gold_live_backup") || "null");
    savedHistory = JSON.parse(localStorage.getItem("gold_history_backup") || "null");
  } catch (_) {}

  const bootLive = (bootstrapData && bootstrapData.live) ? bootstrapData.live : null;
  const bootTs = recordTimestamp(bootLive);
  const savedTs = recordTimestamp(savedLive);

  // Pick freshest cached candidate between gold-bootstrap and localStorage
  let initialLive = DEFAULT_LIVE;
  if (savedLive && savedTs > bootTs && Number.isFinite(Number(savedLive.rate_22k))) {
    initialLive = savedLive;
  } else if (bootLive && Number.isFinite(Number(bootLive.rate_22k))) {
    initialLive = bootLive;
  } else if (savedLive && Number.isFinite(Number(savedLive.rate_22k))) {
    initialLive = savedLive;
  }

  if (!bootstrapData) {
    if (savedLive && Number.isFinite(Number(savedLive.rate_22k))) {
      bootstrapData = { live: savedLive, history: savedHistory || [] };
    }
  } else if (initialLive === savedLive) {
    bootstrapData.live = savedLive;
    if (Array.isArray(savedHistory) && savedHistory.length >= (bootstrapData.history?.length || 0)) {
      bootstrapData.history = savedHistory;
    }
  }

  const initialHistory = (bootstrapData && Array.isArray(bootstrapData.history) && bootstrapData.history.length)
    ? bootstrapData.history
    : (savedHistory || DEFAULT_HISTORY);

  live = initialLive;
  history = normalize(initialHistory);

  // Synchronously render DOM on initial paint with zero spinner or layout shift
  renderLive(live);
  renderStats();
  calculate();
  updateSpreadDashboard();
  if (bootstrapData && bootstrapData.signals) {
    renderSignals(bootstrapData.signals);
  }
  if (typeof renderPortfolio === "function") renderPortfolio();
  if (typeof window.refreshPortfolio === "function") window.refreshPortfolio();

  // Freshness check: age in minutes & IST active trading hours
  const liveTs = recordTimestamp(initialLive);
  const ageMinutes = liveTs > 0 ? (Date.now() - liveTs) / (1000 * 60) : Infinity;

  const todayIST = getTodayISTDateStr();
  const isDateToday = Boolean(initialLive && initialLive.date === todayIST);

  const istParts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hourCycle: 'h23'
  }).formatToParts(new Date());
  const istH = Number(istParts.find(p => p.type === 'hour')?.value || 0);
  const isMarketHours = (istH >= 9 && istH < 22);

  // During active market hours, any cached rate older than 15 minutes or from yesterday is marked refreshing
  const isStale = ageMinutes > 15 || (!isDateToday && isMarketHours);

  if (isStale) {
    setStatus("Refreshing live rate…", false, true);
  } else {
    setStatus(live && live.time ? formatLiveStatus(live.time) : formatLiveStatus());
  }

  // UNCONDITIONAL FOREGROUND HYDRATION:
  // Regardless of staleness heuristic, ALWAYS fetch fresh live rate in parallel on app startup!
  // Fast-path execution (<50ms) ensures instant rate update on open #1.
  let priorityLivePromise = null;
  if (typeof loadLiveOnly === "function") {
    priorityLivePromise = loadLiveOnly(true);
  }

  // Await priority live refresh before running secondary background hydration
  if (priorityLivePromise) {
    try {
      await priorityLivePromise;
    } catch (_) {}
  }



  // Secondary IndexedDB cache hydration
  getCacheFromIndexedDB("gold_history").then(idbHist => {
    if (Array.isArray(idbHist) && idbHist.length > history.length) {
      history = normalize(idbHist);
      renderStats();
      updateSpreadDashboard();
    }
  });

  // 2. Stale-While-Revalidate: Silently fetch latest data in background without UI spinners
  try {
    await loadPublishedData(true);
  } catch (_) {}

  // AGENT 5: Auto-Heal Watchdog when app is opened
  if (typeof checkAndAutoTriggerWorker === "function") {
    checkAndAutoTriggerWorker(live).catch(() => {});
  }
})();

// --- Additive UI Motion, Scroll & Observers ---

(function(){
  'use strict';
  const $=s=>document.querySelector(s);
  const $$=s=>Array.from(document.querySelectorAll(s));

  // Scroll progress + masthead depth.
  const mast=$('.masthead');
  let progress=document.querySelector('.ae-progress');
  if(!progress){progress=document.createElement('div');progress.className='ae-progress';document.body.appendChild(progress)}
  function onScroll(){
    const y=window.scrollY||0;
    if(mast) mast.classList.toggle('is-scrolled',y>8);
    const max=Math.max(1,document.documentElement.scrollHeight-window.innerHeight);
    progress.style.width=Math.min(100,(y/max)*100)+'%';
  }
  window.addEventListener('scroll',onScroll,{passive:true});

  // Price/result feedback: animate only when a displayed value actually changes.
  function watch(id, cls){
    const el=document.getElementById(id); if(!el) return;
    let last=el.textContent;
    new MutationObserver(()=>{
      const next=el.textContent;
      if(next!==last && next.trim() && !/—|Analyzing|Calculating|Pending/.test(next)){
        el.classList.remove(cls); void el.offsetWidth; el.classList.add(cls);
      }
      last=next;
    }).observe(el,{childList:true,subtree:true,characterData:true});
  }
  watch('hero8','price-pulse'); watch('calcResult','result-pulse');

  // Make keyboard focus visibly intentional on keyboard navigation only.
  let keyboard=false;
  document.addEventListener('keydown',e=>{if(e.key==='Tab')keyboard=true},{passive:true});
  document.addEventListener('pointerdown',()=>keyboard=false,{passive:true});
  document.addEventListener('focusin',e=>{if(keyboard && e.target instanceof HTMLElement)e.target.dataset.aeFocus='1'});
  document.addEventListener('focusout',e=>{if(e.target instanceof HTMLElement)delete e.target.dataset.aeFocus});
  const focusStyle=document.createElement('style');
  focusStyle.textContent='[data-ae-focus="1"]{outline:2px solid rgba(184,134,36,.65)!important;outline-offset:3px!important}';
  document.head.appendChild(focusStyle);

  onScroll();
})();



(()=>{
  const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
  // Ambient spotlight effect removed per design update.
  // Reveal sections as they enter the viewport; no dependency on app data.
  const sections=$$('.section');
  sections.forEach(sec=>{sec.classList.add('ae-reveal');const m=document.createElement('span');m.className='ae-section-marker';m.setAttribute('aria-hidden','true');sec.appendChild(m)});
  if('IntersectionObserver' in window){
    const io=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting)e.target.classList.add('ae-in')}),{threshold:.08,rootMargin:'0px 0px -5%'});sections.forEach(s=>io.observe(s));
    const spy=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting){sections.forEach(s=>s.classList.remove('ae-current'));e.target.classList.add('ae-current')}}),{threshold:.35,rootMargin:'-15% 0px -55%'});sections.forEach(s=>spy.observe(s));
  }else sections.forEach(s=>s.classList.add('ae-in'));
  // Observe the hero price and animate only when its displayed value genuinely changes.
  const hero=$('#hero8');
  if(hero){let last=hero.textContent;new MutationObserver(()=>{const now=hero.textContent;if(now!==last){hero.classList.remove('ae-live-pulse');void hero.offsetWidth;hero.classList.add('ae-live-pulse');last=now}}).observe(hero,{childList:true,subtree:true,characterData:true})}
  // Make keyboard focus visible even where the legacy CSS is quiet.
  document.addEventListener('keydown',e=>{if(e.key==='Tab')document.documentElement.classList.add('ae-keyboard')},{once:false});
  // Double-click the chart to return to the default range (30D)
  const chart=$('#chart');
  if(chart) chart.addEventListener('dblclick',()=>{$('#ranges button[data-range="30"]')?.click()});
})();



(()=>{
  'use strict';
  const $=s=>document.querySelector(s);
  const $$=s=>Array.from(document.querySelectorAll(s));

  // Remove redundant legacy context fragments from older iterations.
  const legacySession=document.getElementById('session');
  if(legacySession){const panel=legacySession.closest('.panel'); if(panel) panel.remove();}

  // Chart intelligence rail: derives only from the same filtered history already used by drawChart().
  const chartPanel=$('.chart-panel');
  if(chartPanel && !$('#aiChartInsights')){
    const rail=document.createElement('div'); rail.id='aiChartInsights'; rail.className='ai-chart-insights';
    rail.innerHTML=`
      <div class="ai-insight"><span class="ai-insight-label">Trend</span><span class="ai-insight-value" id="aiTrend">—</span><span class="ai-insight-sub" id="aiTrendSub">Period direction</span></div>
      <div class="ai-insight"><span class="ai-insight-label">Range</span><span class="ai-insight-value" id="aiRange">—</span><span class="ai-insight-sub" id="aiRangeSub">High → low spread</span></div>
      <div class="ai-insight"><span class="ai-insight-label">Observations</span><span class="ai-insight-value" id="aiObs">—</span><span class="ai-insight-sub" id="aiObsSub">Published records</span></div>`;
    $('.chartmeta')?.before(rail);
  }

  function updateInsights(){
    if(typeof getFilteredHistory!=='function') return;
    const data=getFilteredHistory(typeof selectedRange!=='undefined'?selectedRange:30);
    if(!data||data.length<2) return;
    const vals=data.map(x=>Number(x.rate_22k)).filter(Number.isFinite); if(vals.length<2)return;
    const first=vals[0],last=vals[vals.length-1],delta=last-first,pct=first?(delta/first)*100:0;
    const hi=Math.max(...vals),lo=Math.min(...vals),spread=hi-lo;
    const trend=$('#aiTrend'), range=$('#aiRange'), obs=$('#aiObs');
    if(trend){trend.textContent=(delta>0?'Rising':delta<0?'Falling':'Flat')+' · '+(pct>=0?'+':'')+pct.toFixed(1)+'%';trend.className='ai-insight-value '+(delta>0?'positive':delta<0?'negative':'')}
    if($('#aiTrendSub')) $('#aiTrendSub').textContent=delta===0?'No net change across period':'From '+money(first)+'/g to '+money(last)+'/g';
    if(range){range.textContent=money(spread)+'/g';range.className='ai-insight-value'}
    if($('#aiRangeSub')) $('#aiRangeSub').textContent=money(lo)+' low · '+money(hi)+' high';
    if(obs) obs.textContent=vals.length.toLocaleString('en-IN');
  }
  window.updateInsights = updateInsights;
  const originalDraw=window.drawChart;
  // drawChart is a lexical function in this document, so observe canvas updates rather than replacing it.
  const chart=$('#chart');
  if(chart){
    const observer=new ResizeObserver(()=>setTimeout(updateInsights,0)); observer.observe(chart.parentElement);
    chart.addEventListener('pointerup',()=>setTimeout(updateInsights,0),{passive:true});
    chart.addEventListener('pointermove',()=>{if(window.matchMedia('(hover:hover)').matches) updateInsights()},{passive:true});
  }
  setTimeout(updateInsights,250);
  setTimeout(updateInsights,1200);

  // Use modern View Transitions when the browser supports them for theme changes and explicit section jumps.
  if(document.startViewTransition){
    document.addEventListener('click',e=>{
      const a=e.target.closest('a[href^="#"]'); if(!a)return;
      const id=a.getAttribute('href'); if(!id||id==='#')return;
      const target=document.querySelector(id); if(!target)return;
      e.preventDefault();
      document.startViewTransition(()=>target.scrollIntoView({behavior:'smooth',block:'start'}));
    });
  }

  // Card sheen effect removed per design update.
})();

