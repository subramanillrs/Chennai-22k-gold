// ============================================================
// FINANCIAL CALCULATORS: QUOTATION, BILL AUDITOR, XIRR SCHEMES & PORTFOLIO
// ============================================================

function calculate() {
  if (!live || !$("calcMode")) return;
  const rate = Number(live.rate_22k);
  if (!rate) return;

  const mode = $("calcMode").value;
  const weight = Math.max(0, Number($("weight")?.value) || 0);
  const budget = Math.max(0, Number($("budget")?.value) || 0);
  const makingPct = Math.max(0, Number($("making")?.value) || 0);
  const gstPct = Math.max(0, Number($("gstRate")?.value) || 0);
  const flatFee = Math.max(0, Number($("flatFee")?.value) || 0);
  const oldWeight = Math.max(0, Number($("oldWeight")?.value) || 0);
  const oldPurity = Number($("oldPurity")?.value) || 22;
  const purityFraction = ({ 18: 0.750, 20: 0.840, 22: 0.916, 24: 0.999 })[oldPurity] || 0.916;
  const oldGoldCredit = oldWeight > 0 ? oldWeight * rate * (purityFraction / 0.916) : 0;

  if (mode === "value") {
    if ($("weightField")) $("weightField").style.display = "flex";
    if ($("budgetField")) $("budgetField").style.display = "none";
    if ($("weightChipsGroup")) $("weightChipsGroup").style.display = "flex";
  } else {
    if ($("weightField")) $("weightField").style.display = "none";
    if ($("budgetField")) $("budgetField").style.display = "flex";
    if ($("weightChipsGroup")) $("weightChipsGroup").style.display = "none";
  }

  if ($("receiptMakingLabel")) $("receiptMakingLabel").textContent = `Making Charges (${makingPct}%):`;
  if ($("receiptGstLabel")) $("receiptGstLabel").textContent = `GST (${gstPct}%):`;
  if ($("receiptOldGoldLine")) $("receiptOldGoldLine").style.display = oldGoldCredit > 0 ? "flex" : "none";
  if (oldGoldCredit > 0 && $("receiptOldGold")) $("receiptOldGold").textContent = "- " + money(oldGoldCredit);

  if (mode === "value") {
    const goldVal = rate * weight;
    const makeAmt = goldVal * (makingPct / 100);
    const sub = goldVal + makeAmt + (weight > 0 ? flatFee : 0);
    const gstAmt = sub * (gstPct / 100);
    const grandTotal = Math.max(0, sub + gstAmt - oldGoldCredit);

    if ($("receiptBase")) $("receiptBase").textContent = money(goldVal);
    if ($("receiptMaking")) $("receiptMaking").textContent = money(makeAmt);
    if ($("receiptGst")) $("receiptGst").textContent = money(gstAmt);
    if ($("receiptFee")) $("receiptFee").textContent = money(weight > 0 ? flatFee : 0);
    if ($("receiptTotalLabel")) $("receiptTotalLabel").textContent = "Net Payable Amount";
    if ($("calcResult")) $("calcResult").textContent = money(grandTotal);
    if ($("calcSub")) $("calcSub").textContent = `For ${weight.toLocaleString("en-IN")}g gold at ₹ ${rate.toLocaleString("en-IN")}/g benchmark`;
  } else {
    const totalFunds = budget + oldGoldCredit;
    const applicableFee = totalFunds > flatFee ? flatFee : 0;
    const effB = totalFunds > applicableFee ? (totalFunds - applicableFee) / (1 + gstPct / 100) : 0;
    const goldBase = effB > 0 ? effB / (1 + makingPct / 100) : 0;
    const grams = rate > 0 ? goldBase / rate : 0;
    const makeAmt = goldBase * (makingPct / 100);
    const actualFee = grams > 0 ? applicableFee : 0;
    const sub = goldBase + makeAmt + actualFee;
    const gstAmt = sub * (gstPct / 100);

    if ($("receiptBase")) $("receiptBase").textContent = money(goldBase);
    if ($("receiptMaking")) $("receiptMaking").textContent = money(makeAmt);
    if ($("receiptGst")) $("receiptGst").textContent = money(gstAmt);
    if ($("receiptFee")) $("receiptFee").textContent = money(actualFee);
    if ($("receiptTotalLabel")) $("receiptTotalLabel").textContent = "Purchasable Gold Weight";
    if ($("calcResult")) $("calcResult").textContent = grams.toFixed(3) + " g";
    if ($("calcSub")) $("calcSub").textContent = `Fits budget ${money(budget)} after taxes & deductions`;
  }
}

function positionCalcModeThumb() {
  const thumb = $("calcModeThumb");
  const buttons = [...document.querySelectorAll(".calc-mode-btn")];
  const idx = buttons.findIndex(b => b.classList.contains("active"));
  if (thumb && idx >= 0) thumb.style.transform = `translateX(${idx * 100}%)`;
}

document.querySelectorAll(".calc-mode-btn").forEach(btn => {
  btn.onclick = () => {
    haptic(10);
    document.querySelectorAll(".calc-mode-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    positionCalcModeThumb();
    if ($("calcMode")) $("calcMode").value = btn.dataset.mode;
    calculate();
  };
});
positionCalcModeThumb();

document.querySelectorAll("#weightChips .chip").forEach(c => c.onclick = () => {
  haptic(10);
  document.querySelectorAll("#weightChips .chip").forEach(x => x.classList.remove("active"));
  c.classList.add("active");
  if ($("weight")) $("weight").value = c.dataset.val;
  if ($("calcMode")) $("calcMode").value = "value";
  document.querySelectorAll(".calc-mode-btn").forEach(b => b.classList.toggle("active", b.dataset.mode === "value"));
  positionCalcModeThumb();
  calculate();
});

document.querySelectorAll("#makingChips .chip").forEach(c => c.onclick = () => {
  if (c.textContent.includes("Coin") && typeof playGoldCoinChime === "function") {
    playGoldCoinChime(1.0);
    haptic(15);
  } else {
    haptic(10);
  }
  document.querySelectorAll("#makingChips .chip").forEach(x => x.classList.remove("active"));
  c.classList.add("active");
  if ($("making")) $("making").value = c.dataset.val;
  calculate();
});

if ($("copyQuoteBtn")) {
  $("copyQuoteBtn").onclick = async () => {
    haptic(15);
    if (!live) return;
    const mode = $("calcMode")?.value || "value";
    const oldAmt = Number($("oldWeight")?.value) > 0 ? ($("receiptOldGold")?.textContent || "") : "None";
    let txt = "";

    if (mode === "value") {
      txt = `📜 GOLD PURCHASE ESTIMATE\nDate: ${dateText(live.date)}\n----------------------\n• Base Rate: ${money(live.rate_22k)}/g\n• Weight: ${$("weight")?.value || 8}g\n• Making (${$("making")?.value || 8}%): ${$("receiptMaking")?.textContent || "₹ 0"}\n• GST (${$("gstRate")?.value || 3}%): ${$("receiptGst")?.textContent || "₹ 0"}\n• Exchange: ${oldAmt}\n----------------------\nNET TOTAL: ${$("calcResult")?.textContent || "—"}`;
    } else {
      txt = `📜 GOLD BUDGET ESTIMATE\nDate: ${dateText(live.date)}\n----------------------\n• Base Rate: ${money(live.rate_22k)}/g\n• Budget: ${money($("budget")?.value || 0)}\n• Making (${$("making")?.value || 8}%): ${$("receiptMaking")?.textContent || "₹ 0"}\n• GST (${$("gstRate")?.value || 3}%): ${$("receiptGst")?.textContent || "₹ 0"}\n• Exchange: ${oldAmt}\n----------------------\nESTIMATED GOLD WEIGHT: ${$("calcResult")?.textContent || "—"}`;
    }

    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(txt);
      } else {
        const area = document.createElement("textarea");
        area.value = txt;
        document.body.appendChild(area);
        area.select();
        document.execCommand("copy");
        document.body.removeChild(area);
      }
      toast("Quotation Copied!");
    } catch (_) {
      toast("Copy Failed");
    }
  };
}

function renderStats() {
  if (!history.length) return;
  const daily = dailyBenchmarks(history);
  const vals = daily.map(i => Number(i.rate_22k));
  const hi = vals.reduce((a, b) => Math.max(a, b), -Infinity);
  const lo = vals.reduce((a, b) => Math.min(a, b), Infinity);

  if ($("high")) $("high").textContent = money(hi);
  if ($("low")) $("low").textContent = money(lo);
  if ($("highDate")) $("highDate").textContent = dateText(daily.find(i => Number(i.rate_22k) === hi)?.date);
  if ($("lowDate")) $("lowDate").textContent = dateText(daily.find(i => Number(i.rate_22k) === lo)?.date);
  if ($("historyCount")) $("historyCount").textContent = history.length.toLocaleString("en-IN") + " records";

  if ($("historyBody")) {
    const dailyRecords = dailyBenchmarks(history);
    if ($("historyCount")) $("historyCount").textContent = dailyRecords.length.toLocaleString("en-IN") + " records";
    $("historyBody").innerHTML = dailyRecords.reverse().slice(0, 300).map(i => `<tr><td>${esc(dateText(i.date))}</td><td>${money(i.rate_22k)}</td><td>${money(i.rate_22k*8)}</td></tr>`).join("");
  }

  if ($("dateA") && !$("dateA").value) $("dateA").value = history[0]?.date || "";
  if ($("dateB") && !$("dateB").value) $("dateB").value = history[history.length-1]?.date || "";

  compareDates();
  updateFintechMetrics();
  computeLastMovement();
  drawChart();
}

function compareDates() {
  if (!$("dateA") || !$("dateB") || !$("compareResult")) return;
  const daily = dailyBenchmarks(history);
  const a = daily.find(i => i.date === $("dateA").value);
  const b = daily.find(i => i.date === $("dateB").value);

  if (!a || !b) {
    $("compareResult").innerHTML = `<span class="compare-result-top">Select valid dates</span><span class="compare-result-sub">—</span>`;
    return;
  }
  const diff = b.rate_22k - a.rate_22k, pct = a.rate_22k ? (diff / a.rate_22k * 100) : 0;
  const isPos = diff > 0, isNeg = diff < 0;

  $("compareResult").innerHTML = `
    <span class="compare-result-top">${money(a.rate_22k)} → ${money(b.rate_22k)}</span>
    <span class="compare-result-sub ${isPos ? 'positive' : isNeg ? 'negative' : ''}">
      ${diff >= 0 ? '+' : ''}${money(diff)}/g (${diff >= 0 ? '+' : ''}${pct.toFixed(2)}%)
    </span>
  `;
  if (typeof window.refreshCompareVisual === "function") window.refreshCompareVisual();
}


["dateA", "dateB"].forEach(id => {
  if ($(id)) $(id).addEventListener("change", compareDates);
});

["weight", "budget", "making", "gstRate", "flatFee", "oldWeight", "oldPurity"].forEach(id => {
  if ($(id)) $(id).addEventListener("input", calculate);
});

$("weight")?.addEventListener("input", e => {
  const w = Number(e.target.value);
  document.querySelectorAll("#weightChips .chip").forEach(c => c.classList.toggle("active", Number(c.dataset.val) === w));
});
$("making")?.addEventListener("input", e => {
  const m = Number(e.target.value);
  document.querySelectorAll("#makingChips .chip").forEach(c => c.classList.toggle("active", Number(c.dataset.val) === m));
});
window.addEventListener("resize", positionCalcModeThumb);


(() => {
  const byId = id => document.getElementById(id);
  const compareA=byId('dateA'),compareB=byId('dateB'),visual=byId('compareVisual');
  function refreshCompareVisual(){
    if(!compareA||!compareB||!visual||typeof history==='undefined')return;
    const a=compareA.value,b=compareB.value; if(!a||!b){visual.hidden=true;return;}
    const rows=history.filter(x=>x.date===a||x.date===b);
    const ra=rows.filter(x=>x.date===a).map(x=>Number(x.rate_22k)).filter(Number.isFinite);
    const rb=rows.filter(x=>x.date===b).map(x=>Number(x.rate_22k)).filter(Number.isFinite);
    if(!ra.length||!rb.length){visual.hidden=true;return;}
    const va=ra[ra.length-1],vb=rb[rb.length-1],delta=vb-va,pct=va?(delta/va)*100:0;
    const lo=Math.min(va,vb),hi=Math.max(va,vb),span=Math.max(1,hi-lo);
    const isFlat=Math.abs(hi-lo)<0.01;
    const pa=isFlat?50:((va-lo)/span)*100;
    const pb=isFlat?50:((vb-lo)/span)*100;
    visual.hidden=false;
    byId('compareVisualPct').textContent=(pct>=0?'+':'')+pct.toFixed(1)+'%';
    byId('compareVisualPct').style.color=delta>=0?'var(--good)':'var(--bad)';
    byId('compareVisualA').textContent=(typeof dateText==='function'?dateText(a):a)+' · '+(typeof money==='function'?money(va):'₹ '+va.toLocaleString('en-IN'));
    byId('compareVisualB').textContent=(typeof dateText==='function'?dateText(b):b)+' · '+(typeof money==='function'?money(vb):'₹ '+vb.toLocaleString('en-IN'));
    byId('compareTrackDotA').style.left=pa+'%'; byId('compareTrackDotB').style.left=pb+'%';
    byId('compareTrackFill').style.width=Math.abs(pb-pa)+'%';
    byId('compareTrackFill').style.left=Math.min(pa,pb)+'%';
  }
  window.refreshCompareVisual=refreshCompareVisual;
  [compareA,compareB].forEach(el=>el?.addEventListener('change',refreshCompareVisual));
  setTimeout(refreshCompareVisual,700);

  // Make the calculator feel responsive: mark invalid numeric states immediately and announce outputs politely.
  ['weight','budget','making','gstRate','flatFee','oldWeight'].forEach(id=>{
    const el=byId(id); if(!el)return;
    el.addEventListener('input',()=>{
      const n=Number(el.value); const invalid=el.value!==''&&(!Number.isFinite(n)||n<0);
      el.setAttribute('aria-invalid',String(invalid));
    });
  });
  const result=byId('calcResult'); if(result)result.setAttribute('aria-live','polite');

})();


// --- UPGRADE 7: Local Target Price Alarm Watchdog & Browser Notification Bridge ---
(function setupTargetWatcher() {
  const toggleBtn = document.getElementById("targetToggleBtn");
  const card = document.getElementById("targetCard");
  const closeBtn = document.getElementById("targetCloseBtn");
  const input = document.getElementById("targetInput");
  const setBtn = document.getElementById("setTargetBtn");
  const clearBtn = document.getElementById("clearTargetBtn");
  const badge = document.getElementById("targetBadge");
  const banner = document.getElementById("targetAlertBanner");
  const bannerHeading = document.getElementById("targetAlertHeading");
  const bannerText = document.getElementById("targetAlertText");
  const dismissBtn = document.getElementById("targetAlertDismiss");
  const notifBtn = document.getElementById("targetNotifPermBtn");
  const notifIcon = document.getElementById("targetNotifIcon");
  const notifStatusText = document.getElementById("targetNotifStatusText");
  const dirDipBtn = document.getElementById("dirDipBtn");
  const dirSpikeBtn = document.getElementById("dirSpikeBtn");
  const unit1gBtn = document.getElementById("unit1gBtn");
  const unit8gBtn = document.getElementById("unit8gBtn");
  const chipCurrent = document.getElementById("chipCurrentRate");
  const chipMinus100 = document.getElementById("chipMinus100");
  const chipPlus100 = document.getElementById("chipPlus100");
  const alertsContainer = document.getElementById("targetAlertsContainer");
  const alertsCountEl = document.getElementById("targetAlertsCount");
  const alertsList = document.getElementById("targetAlertsList");

  const STORAGE_KEY = "gold_target_alerts";
  const LEGACY_KEY = "gold_price_target";

  let selectedDir = "dip";
  let selectedUnit = "1g";
  const triggeredSessionSet = new Set();

  function loadAlerts() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const arr = JSON.parse(raw);
        if (Array.isArray(arr)) return arr;
      }
      // Migrate legacy single target
      const legacy = Number(localStorage.getItem(LEGACY_KEY));
      if (legacy && legacy > 0) {
        const migrated = [{
          target_rate: legacy,
          direction: "dip",
          created_at: new Date().toISOString(),
          active: true,
          unit: legacy >= 30000 ? "8g" : "1g"
        }];
        localStorage.setItem(STORAGE_KEY, JSON.stringify(migrated));
        return migrated;
      }
    } catch (_) {}
    return [];
  }

  function saveAlerts(arr) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(arr));
      const firstActive = arr.find(a => a.active);
      if (firstActive) {
        localStorage.setItem(LEGACY_KEY, String(firstActive.target_rate));
      } else {
        localStorage.removeItem(LEGACY_KEY);
      }
    } catch (_) {}
  }

  // 1. Haptic pulse (navigator.vibrate([100, 50, 100]))
  function triggerHaptic() {
    if (typeof navigator !== "undefined" && "vibrate" in navigator) {
      try { navigator.vibrate([100, 50, 100]); } catch (_) {}
    }
  }

  // 2. Synthesizer chime (calling Agent 3 chime)
  function playSynthesizerChime(direction = "dip") {
    // Primary: Agent 3 Web Audio Gold Coin Acoustic Chime
    if (typeof window.playGoldCoinChime === "function") {
      try {
        const p1 = direction === "spike" ? 1.15 : 0.95;
        const p2 = direction === "spike" ? 1.35 : 1.10;
        window.playGoldCoinChime(p1);
        setTimeout(() => {
          try { window.playGoldCoinChime(p2); } catch (_) {}
        }, 140);
        return;
      } catch (_) {}
    }
    // Secondary: Global hook fallback
    if (typeof window.playChime === "function") {
      try { window.playChime(direction); return; } catch (_) {}
    }
    if (typeof window.agent3Chime === "function" && window.agent3Chime !== playSynthesizerChime) {
      try { window.agent3Chime(direction); return; } catch (_) {}
    }
    // Bulletproof Web Audio API dual-harmonic synth
    try {
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      if (!AudioContextClass) return;
      const ctx = window.audioCtx || new AudioContextClass();
      if (ctx.state === "suspended") ctx.resume().catch(() => {});
      const now = ctx.currentTime;
      const freqs = direction === "spike" ? [659.25, 830.61, 987.77, 1318.51] : [587.33, 739.99, 880.00, 1174.66];
      freqs.forEach((freq, idx) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = "sine";
        osc.frequency.setValueAtTime(freq, now + idx * 0.07);
        gain.gain.setValueAtTime(0.0001, now + idx * 0.07);
        gain.gain.linearRampToValueAtTime(0.09, now + idx * 0.07 + 0.015);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + idx * 0.07 + 0.38);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start(now + idx * 0.07);
        osc.stop(now + idx * 0.07 + 0.4);
      });
    } catch (_) {}
  }

  // 4. Web Notification API (if permission granted)
  function sendBrowserNotification(title, body, tag) {
    if (typeof window === "undefined" || !("Notification" in window) || Notification.permission !== "granted") {
      return;
    }
    const options = {
      body,
      icon: "icon-192.png",
      badge: "icon-192.png",
      tag: tag || "gold-target-alarm",
      renotify: true
    };
    try {
      if (navigator.serviceWorker && navigator.serviceWorker.ready) {
        navigator.serviceWorker.ready.then(reg => {
          reg.showNotification(title, options).catch(() => {
            try { new Notification(title, options); } catch (_) {}
          });
        }).catch(() => {
          try { new Notification(title, options); } catch (_) {}
        });
      } else {
        new Notification(title, options);
      }
    } catch (_) {}
  }

  function updateNotificationButtonUI() {
    if (!notifBtn) return;
    if (!("Notification" in window)) {
      notifBtn.hidden = true;
      return;
    }
    if (Notification.permission === "granted") {
      notifBtn.classList.add("granted");
      if (notifIcon) notifIcon.textContent = "✓";
      if (notifStatusText) notifStatusText.textContent = "Push Active";
      notifBtn.title = "Browser notifications active";
    } else if (Notification.permission === "denied") {
      notifBtn.classList.remove("granted");
      if (notifIcon) notifIcon.textContent = "🔕";
      if (notifStatusText) notifStatusText.textContent = "Push Blocked";
      notifBtn.title = "Push notifications blocked in browser settings";
    } else {
      notifBtn.classList.remove("granted");
      if (notifIcon) notifIcon.textContent = "🔔";
      if (notifStatusText) notifStatusText.textContent = "Enable Push";
      notifBtn.title = "Enable browser notifications for price alarms";
    }
  }

  if (notifBtn) {
    notifBtn.addEventListener("click", async () => {
      if (!("Notification" in window)) {
        if (typeof toast === "function") toast("Browser notifications not supported");
        return;
      }
      if (Notification.permission === "granted") {
        if (typeof toast === "function") toast("Browser notifications already enabled");
        return;
      }
      try {
        const perm = await Notification.requestPermission();
        updateNotificationButtonUI();
        if (perm === "granted") {
          if (typeof toast === "function") toast("🔔 Target price notifications enabled!");
          sendBrowserNotification("Chennai 22K Gold Watchdog Active", "You will receive instant alerts when your target price triggers.", "watchdog-init");
        } else {
          if (typeof toast === "function") toast("Notification permission denied");
        }
      } catch (_) {}
    });
  }

  // Direction & Unit selection
  if (dirDipBtn && dirSpikeBtn) {
    dirDipBtn.addEventListener("click", () => {
      selectedDir = "dip";
      dirDipBtn.classList.add("active");
      dirSpikeBtn.classList.remove("active");
      if (typeof haptic === "function") haptic(8);
    });
    dirSpikeBtn.addEventListener("click", () => {
      selectedDir = "spike";
      dirSpikeBtn.classList.add("active");
      dirDipBtn.classList.remove("active");
      if (typeof haptic === "function") haptic(8);
    });
  }

  if (unit1gBtn && unit8gBtn) {
    unit1gBtn.addEventListener("click", () => {
      selectedUnit = "1g";
      unit1gBtn.classList.add("active");
      unit8gBtn.classList.remove("active");
      if (input && live) {
        input.placeholder = `e.g. ${live.rate_22k || 14200}`;
      }
      if (typeof haptic === "function") haptic(8);
    });
    unit8gBtn.addEventListener("click", () => {
      selectedUnit = "8g";
      unit8gBtn.classList.add("active");
      unit1gBtn.classList.remove("active");
      if (input && live) {
        const r8 = live.rate_8g || (live.rate_22k ? live.rate_22k * 8 : 113600);
        input.placeholder = `e.g. ${r8}`;
      }
      if (typeof haptic === "function") haptic(8);
    });
  }

  // Quick chips
  function updateQuickChips() {
    if (!live || !Number.isFinite(Number(live.rate_22k))) return;
    const r1 = Number(live.rate_22k);
    const r8 = Number(live.rate_8g) || r1 * 8;
    const base = selectedUnit === "8g" ? r8 : r1;
    const unitText = selectedUnit === "8g" ? "/8g" : "/g";
    if (chipCurrent) chipCurrent.textContent = `₹${base.toLocaleString("en-IN")}${unitText}`;
    if (chipMinus100) chipMinus100.textContent = selectedUnit === "8g" ? "-₹800 Dip" : "-₹100 Dip";
    if (chipPlus100) chipPlus100.textContent = selectedUnit === "8g" ? "+₹800 Spike" : "+₹100 Spike";
  }

  if (chipCurrent && input) {
    chipCurrent.addEventListener("click", () => {
      if (!live) return;
      const base = selectedUnit === "8g" ? (Number(live.rate_8g) || live.rate_22k * 8) : Number(live.rate_22k);
      input.value = base;
      if (typeof haptic === "function") haptic(8);
    });
  }
  if (chipMinus100 && input) {
    chipMinus100.addEventListener("click", () => {
      if (!live) return;
      const is8g = selectedUnit === "8g";
      const base = is8g ? (Number(live.rate_8g) || live.rate_22k * 8) : Number(live.rate_22k);
      const delta = is8g ? 800 : 100;
      input.value = Math.max(0, base - delta);
      selectedDir = "dip";
      if (dirDipBtn) { dirDipBtn.classList.add("active"); dirSpikeBtn?.classList.remove("active"); }
      if (typeof haptic === "function") haptic(8);
    });
  }
  if (chipPlus100 && input) {
    chipPlus100.addEventListener("click", () => {
      if (!live) return;
      const is8g = selectedUnit === "8g";
      const base = is8g ? (Number(live.rate_8g) || live.rate_22k * 8) : Number(live.rate_22k);
      const delta = is8g ? 800 : 100;
      input.value = base + delta;
      selectedDir = "spike";
      if (dirSpikeBtn) { dirSpikeBtn.classList.add("active"); dirDipBtn?.classList.remove("active"); }
      if (typeof haptic === "function") haptic(8);
    });
  }

  // Watchdog Evaluator Engine
  function checkWatchdog(liveData = live) {
    updateNotificationButtonUI();
    updateQuickChips();
    const alerts = loadAlerts();
    const activeAlerts = alerts.filter(a => a.active);

    if (toggleBtn) {
      toggleBtn.classList.toggle("has-target", activeAlerts.length > 0);
    }
    if (alertsContainer) {
      alertsContainer.hidden = alerts.length === 0;
    }
    if (alertsCountEl) {
      alertsCountEl.textContent = activeAlerts.length;
    }

    if (!liveData || !Number.isFinite(Number(liveData.rate_22k))) {
      if (badge) badge.textContent = activeAlerts.length ? `${activeAlerts.length} alarm(s) set · waiting for live rate…` : "No price alarms active";
      if (banner && !banner.dataset.stay) banner.hidden = true;
      renderAlertsList(alerts, null, null);
      return;
    }

    const r1 = Number(liveData.rate_22k);
    const r8 = Number.isFinite(Number(liveData.rate_8g)) ? Number(liveData.rate_8g) : r1 * 8;

    let breachedAlert = null;
    let breachedCurrent = 0;
    let breachedUnit = "/g";

    // Evaluate all active alarms
    alerts.forEach((alert) => {
      if (!alert.active) return;
      const is8g = alert.unit === "8g" || (!alert.unit && alert.target_rate >= 30000);
      const currentRate = is8g ? r8 : r1;
      const unitLabel = is8g ? "/8g" : "/g";
      const isDip = alert.direction === "dip";
      const conditionMet = isDip ? (currentRate <= alert.target_rate) : (currentRate >= alert.target_rate);

      if (conditionMet) {
        breachedAlert = alert;
        breachedCurrent = currentRate;
        breachedUnit = unitLabel;

        const sessionKey = `${alert.target_rate}_${alert.direction}_${currentRate}`;
        if (!triggeredSessionSet.has(sessionKey)) {
          triggeredSessionSet.add(sessionKey);
          // 1. Haptic pulse (navigator.vibrate([100, 50, 100]))
          triggerHaptic();
          // 2. Synthesizer chime (calling Agent 3 chime)
          playSynthesizerChime(alert.direction);
          // 4. Web Notification API (if permission granted)
          const isSpike = alert.direction === "spike";
          const title = isSpike ? "📈 Chennai 22K Gold Spike Alert!" : "🎯 Chennai 22K Gold Dip Target Reached!";
          const body = `Chennai 22K is currently ₹${currentRate.toLocaleString("en-IN")}${unitLabel}. Your ${alert.direction} target was ${isSpike ? "≥" : "≤"} ₹${alert.target_rate.toLocaleString("en-IN")}.`;
          sendBrowserNotification(title, body, `gold-alert-${alert.target_rate}-${alert.direction}`);
        }
      }
    });

    // 3. Visual celebratory notification banner
    if (breachedAlert && banner) {
      const isSpike = breachedAlert.direction === "spike";
      if (bannerHeading) {
        bannerHeading.textContent = isSpike ? "🚀 Gold Spike Target Reached!" : "🎉 Gold Dip Target Reached!";
      }
      if (bannerText) {
        bannerText.textContent = `Chennai 22K is ₹ ${breachedCurrent.toLocaleString("en-IN")}${breachedUnit} (Target was ${isSpike ? "≥" : "≤"} ₹ ${breachedAlert.target_rate.toLocaleString("en-IN")})`;
      }
      banner.hidden = false;
      banner.classList.add("celebrating");
    } else if (banner && !banner.dataset.stay) {
      banner.classList.remove("celebrating");
      banner.hidden = true;
    }

    // Update Summary Badge
    if (badge) {
      if (!activeAlerts.length) {
        badge.textContent = "No price alarms active";
      } else if (breachedAlert) {
        badge.textContent = `🎉 Target ₹ ${breachedAlert.target_rate.toLocaleString("en-IN")} reached! (₹ ${breachedCurrent.toLocaleString("en-IN")})`;
      } else {
        const nearest = activeAlerts.map(a => {
          const is8g = a.unit === "8g" || (!a.unit && a.target_rate >= 30000);
          const cr = is8g ? r8 : r1;
          const diff = a.direction === "dip" ? cr - a.target_rate : a.target_rate - cr;
          return { ...a, diff, cr, unitLabel: is8g ? "/8g" : "/g" };
        }).sort((a, b) => a.diff - b.diff)[0];

        if (nearest) {
          const sym = nearest.direction === "spike" ? "≥" : "≤";
          badge.textContent = `Target: ${sym} ₹ ${nearest.target_rate.toLocaleString("en-IN")}${nearest.unitLabel} · ₹ ${Math.abs(nearest.diff).toLocaleString("en-IN")} away`;
        }
      }
    }

    renderAlertsList(alerts, r1, r8);
  }

  function renderAlertsList(alerts, r1, r8) {
    if (!alertsList) return;
    alertsList.innerHTML = "";
    if (!alerts.length) return;

    alerts.forEach((alert, index) => {
      const is8g = alert.unit === "8g" || (!alert.unit && alert.target_rate >= 30000);
      const currentRate = r1 ? (is8g ? r8 : r1) : null;
      const unitLabel = is8g ? "/8g" : "/g";
      const isDip = alert.direction === "dip";
      const isBreached = currentRate && alert.active && (isDip ? currentRate <= alert.target_rate : currentRate >= alert.target_rate);

      let distanceText = "";
      if (currentRate) {
        const diff = isDip ? currentRate - alert.target_rate : alert.target_rate - currentRate;
        distanceText = isBreached ? "🎉 Reached!" : `${Math.abs(diff).toLocaleString("en-IN")} away`;
      }

      const item = document.createElement("div");
      item.className = `target-alert-item ${isBreached ? "is-breached" : ""}`;
      item.innerHTML = `
        <div class="target-alert-left">
          <span class="alert-dir-pill ${alert.direction}">${isDip ? "Dip ≤" : "Spike ≥"}</span>
          <span class="alert-rate-val">₹ ${alert.target_rate.toLocaleString("en-IN")}${unitLabel}</span>
          ${distanceText ? `<span class="alert-distance">(${distanceText})</span>` : ""}
        </div>
        <div class="target-alert-right">
          <button type="button" class="alert-toggle-btn ${alert.active ? "on" : ""}" title="Toggle active status">
            ${alert.active ? "Active" : "Paused"}
          </button>
          <button type="button" class="alert-del-btn" title="Delete alert">✕</button>
        </div>
      `;

      // Toggle active status
      item.querySelector(".alert-toggle-btn").addEventListener("click", () => {
        alerts[index].active = !alerts[index].active;
        saveAlerts(alerts);
        if (typeof haptic === "function") haptic(10);
        checkWatchdog();
      });

      // Delete alert
      item.querySelector(".alert-del-btn").addEventListener("click", () => {
        alerts.splice(index, 1);
        saveAlerts(alerts);
        if (typeof toast === "function") toast("Alert removed");
        if (typeof haptic === "function") haptic(10);
        checkWatchdog();
      });

      alertsList.appendChild(item);
    });
  }

  // Toggle card visibility
  if (toggleBtn && card) {
    toggleBtn.addEventListener("click", () => {
      card.hidden = !card.hidden;
      if (!card.hidden) {
        updateQuickChips();
        updateNotificationButtonUI();
        if (input && !input.value && live) {
          const base = selectedUnit === "8g" ? (live.rate_8g || live.rate_22k * 8) : live.rate_22k;
          input.placeholder = `e.g. ${base}`;
        }
      }
    });
  }

  if (closeBtn && card) closeBtn.addEventListener("click", () => { card.hidden = true; });

  if (dismissBtn && banner) {
    dismissBtn.addEventListener("click", () => {
      banner.hidden = true;
      banner.dataset.stay = "";
      banner.classList.remove("celebrating");
    });
  }

  // Set Target Alarm button
  if (setBtn && input) {
    setBtn.addEventListener("click", () => {
      const val = Number(input.value);
      if (!val || val <= 0) {
        if (typeof toast === "function") toast("Enter a valid target price");
        return;
      }

      // Auto-adjust unit based on magnitude if needed
      const unit = val >= 30000 ? "8g" : selectedUnit;
      const alerts = loadAlerts();

      // Check if duplicate alert exists
      const existingIdx = alerts.findIndex(a => a.target_rate === val && a.direction === selectedDir);
      if (existingIdx >= 0) {
        alerts[existingIdx].active = true;
        alerts[existingIdx].unit = unit;
      } else {
        alerts.push({
          target_rate: val,
          direction: selectedDir,
          created_at: new Date().toISOString(),
          active: true,
          unit: unit
        });
      }

      saveAlerts(alerts);
      input.value = "";
      if (typeof toast === "function") {
        const dirLabel = selectedDir === "dip" ? "Dip (≤)" : "Spike (≥)";
        toast(`Alarm set: ${dirLabel} ₹ ${val.toLocaleString("en-IN")}/${unit}`);
      }
      if (typeof haptic === "function") haptic(20);

      // Prompt for Web Notification if not yet requested
      if ("Notification" in window && Notification.permission === "default") {
        Notification.requestPermission().then(updateNotificationButtonUI).catch(() => {});
      }

      checkWatchdog();
    });
  }

  // Clear All button
  if (clearBtn) {
    clearBtn.addEventListener("click", () => {
      saveAlerts([]);
      if (input) input.value = "";
      if (typeof toast === "function") toast("All target alarms cleared");
      if (typeof haptic === "function") haptic(15);
      checkWatchdog();
    });
  }

  // Service Worker background sync listener
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.addEventListener("message", (event) => {
      if (event.data && event.data.type === "LIVE_RATE_HYDRATED") {
        checkWatchdog(event.data.live);
      }
    });
  }

  // Tab visibility watchdog trigger
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      checkWatchdog();
    }
  });

  // Global hooks
  window.checkTargetPrice = checkWatchdog;
  window.checkTargetAlerts = checkWatchdog;
  window.playAlertChime = playSynthesizerChime;
  window.agent3Chime = window.agent3Chime || playSynthesizerChime;

  setTimeout(checkWatchdog, 400);
})();


// --- UPGRADE 3: CSV History Export ---
(function setupCsvExport() {
  const btn = document.getElementById("exportCsvBtn");
  if (!btn) return;
  btn.addEventListener("click", () => {
    const records = typeof history !== "undefined" && history.length ? history : (typeof DEFAULT_HISTORY !== "undefined" ? DEFAULT_HISTORY : []);
    if (!records.length) {
      if (typeof toast === "function") toast("No records available to export");
      return;
    }
    // Deduplicate history entries by date + session + rate to ensure clean export
    const seen = new Set();
    const dedupedRecords = [];
    for (const r of [...records].reverse()) {
      const key = `${r.date}_${r.session || ""}_${r.rate_22k}`;
      if (!seen.has(key)) {
        seen.add(key);
        dedupedRecords.push(r);
      }
    }
    dedupedRecords.reverse();

    const headers = ["Date", "Session", "Time", "Rate_22K_Per_Gram", "Rate_8g_Sovereign", "Est_24K_Per_Gram", "Est_18K_Per_Gram"];
    const rows = dedupedRecords.map(r => {
      const r22 = Number(r.rate_22k) || 0;
      const r8 = Number(r.rate_8g) || r22 * 8;
      const r24 = Math.round(r22 * (0.999 / 0.916));
      const r18 = Math.round(r22 * (0.750 / 0.916));
      return [
        r.date || "",
        r.session || "",
        r.time || "",
        r22,
        r8,
        r24,
        r18
      ].map(v => '"' + String(v).replace(/"/g, '""') + '"').join(",");
    });
    const csvContent = "\uFEFF" + [headers.join(","), ...rows].join("\r\n");
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const today = (typeof live !== "undefined" && live && live.date) ? live.date : new Date().toISOString().slice(0, 10);
    a.href = url;
    a.download = `gold-22k-chennai-history-${today}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 2000);
    if (typeof toast === "function") toast("Historical records exported as CSV");
  });
})();


// --- UPGRADE 2: Gold Portfolio & ROI Savings Ledger ---
(function setupPortfolio() {
  const dateInput = document.getElementById("portDate");
  const weightInput = document.getElementById("portWeight");
  const rateInput = document.getElementById("portRate");
  const noteInput = document.getElementById("portNote");
  const addBtn = document.getElementById("portAddBtn");
  const tableBody = document.getElementById("portBody");
  const chipsWrap = document.getElementById("portWeightChips");

  // Summary elements
  const totalGramsEl = document.getElementById("portTotalGrams");
  const totalSovEl = document.getElementById("portTotalSov");
  const totalInvestedEl = document.getElementById("portTotalInvested");
  const avgBuyRateEl = document.getElementById("portAvgBuyRate");
  const totalCurrentEl = document.getElementById("portTotalCurrent");
  const netProfitEl = document.getElementById("portNetProfit");
  const cagrEl = document.getElementById("portCagrText");
  const headerSummaryEl = document.getElementById("portfolioHeaderSummary");

  let lots = [];
  try {
    lots = JSON.parse(localStorage.getItem("gold_portfolio_lots") || "[]");
  } catch(_) { lots = []; }

  // Set default date to today
  if (dateInput) {
    const todayStr = (typeof live !== "undefined" && live && live.date) ? live.date : new Date().toISOString().slice(0, 10);
    dateInput.value = todayStr;
    autoFillRateForDate(todayStr);
    dateInput.addEventListener("change", () => autoFillRateForDate(dateInput.value));
  }

  function autoFillRateForDate(dStr) {
    if (!rateInput || !dStr) return;
    if (typeof history !== "undefined" && history.length) {
      const recordsForDate = history.filter(h => h.date === dStr);
      if (recordsForDate.length > 0) {
        const pmMatch = recordsForDate.slice().reverse().find(h => h.session === "PM" || (h.time && parseInt(String(h.time).split(":")[0], 10) >= 14));
        const match = pmMatch || recordsForDate[recordsForDate.length - 1];
        if (match && match.rate_22k) {
          rateInput.value = match.rate_22k;
          return;
        }
      }
    }
    if (typeof live !== "undefined" && live && live.rate_22k && (!dStr || dStr === live.date)) {
      rateInput.value = live.rate_22k;
    }
  }

  // Weight chip buttons
  if (chipsWrap) {
    chipsWrap.addEventListener("click", e => {
      const chip = e.target.closest(".chip");
      if (!chip || !weightInput) return;
      chipsWrap.querySelectorAll(".chip").forEach(c => c.classList.remove("active"));
      chip.classList.add("active");
      weightInput.value = chip.dataset.val;
    });
  }

  function saveLots() {
    try {
      localStorage.setItem("gold_portfolio_lots", JSON.stringify(lots));
    } catch(_) {}
    renderPortfolio();
  }

  function renderPortfolio() {
    if (!tableBody) return;
    const currentRate = (typeof live !== "undefined" && live && Number(live.rate_22k)) ? Number(live.rate_22k) : 6850;

    if (!lots.length) {
      tableBody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:16px 0; color:var(--ink-faint);">No purchases saved yet. Add your first gold purchase above!</td></tr>`;
      if (totalGramsEl) totalGramsEl.textContent = "0.0g";
      if (totalSovEl) totalSovEl.textContent = "0 Sovereigns";
      if (totalInvestedEl) totalInvestedEl.textContent = "₹ 0";
      if (avgBuyRateEl) avgBuyRateEl.textContent = "₹ 0/g avg";
      if (totalCurrentEl) totalCurrentEl.textContent = "₹ 0";
      if (netProfitEl) { netProfitEl.textContent = "₹ 0 (0.0%)"; netProfitEl.className = "profit-val"; }
      if (cagrEl) cagrEl.textContent = "—";
      if (headerSummaryEl) headerSummaryEl.textContent = "0.0g tracked";
      return;
    }

    let totWeight = 0;
    let totCost = 0;
    let totVal = 0;
    let weightedDays = 0;
    const nowMs = Date.now();

    tableBody.innerHTML = "";
    lots.forEach((lot, idx) => {
      const w = Number(lot.weight) || 0;
      const r = Number(lot.rate) || 0;
      const cost = w * r;
      const cur = w * currentRate;
      const pnl = cur - cost;
      const pnlPct = cost > 0 ? (pnl / cost) * 100 : 0;
      const isUp = pnl >= 0;

      totWeight += w;
      totCost += cost;
      totVal += cur;

      const pDate = new Date(lot.date || nowMs);
      const days = Math.max(1, Math.round((nowMs - pDate.getTime()) / (1000 * 60 * 60 * 24)));
      weightedDays += days * cost;

      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><strong>${lot.date || "—"}</strong><br><small style="color:var(--ink-faint);">${lot.note || "Holding lot"}</small></td>
        <td><b>${w.toFixed(2)}g</b><br><small style="color:var(--ink-soft);">${(w / 8).toFixed(2)} Sov</small></td>
        <td>₹ ${r.toLocaleString("en-IN")}<br><small style="color:var(--ink-faint);">₹ ${Math.round(cost).toLocaleString("en-IN")}</small></td>
        <td><b>₹ ${Math.round(cur).toLocaleString("en-IN")}</b></td>
        <td style="color:${isUp ? "var(--good)" : "var(--bad)"}; font-weight:700;">${isUp ? "+" : ""}₹ ${Math.round(pnl).toLocaleString("en-IN")}<br><small>${isUp ? "+" : ""}${pnlPct.toFixed(1)}%</small></td>
        <td><button class="port-del-btn" data-idx="${idx}" type="button" title="Delete purchase lot">✕</button></td>
      `;
      tableBody.appendChild(tr);
    });

    // Compute aggregate metrics
    const netPnl = totVal - totCost;
    const netPnlPct = totCost > 0 ? (netPnl / totCost) * 100 : 0;
    const avgDays = totCost > 0 ? weightedDays / totCost : 1;
    let cagr = 0;
    if (totCost > 0 && totVal > 0 && avgDays >= 30) {
      cagr = (Math.pow(totVal / totCost, 365 / avgDays) - 1) * 100;
    }

    if (totalGramsEl) totalGramsEl.textContent = totWeight.toFixed(2) + "g";
    if (totalSovEl) totalSovEl.textContent = (totWeight / 8).toFixed(2) + " Sovereigns";
    if (totalInvestedEl) totalInvestedEl.textContent = typeof money === "function" ? money(totCost) : "₹ " + Math.round(totCost).toLocaleString("en-IN");
    if (avgBuyRateEl) avgBuyRateEl.textContent = totWeight > 0 ? `₹ ${Math.round(totCost / totWeight).toLocaleString("en-IN")}/g avg` : "₹ 0/g";
    if (totalCurrentEl) totalCurrentEl.textContent = typeof money === "function" ? money(totVal) : "₹ " + Math.round(totVal).toLocaleString("en-IN");
    if (netProfitEl) {
      netProfitEl.textContent = (netPnl >= 0 ? "+" : "") + (typeof money === "function" ? money(netPnl) : "₹ " + Math.round(netPnl).toLocaleString("en-IN")) + ` (${netPnlPct >= 0 ? "+" : ""}${netPnlPct.toFixed(1)}%)`;
      netProfitEl.className = "profit-val " + (netPnl >= 0 ? "positive" : "negative");
    }
    if (cagrEl) {
      cagrEl.textContent = avgDays >= 30 ? `${cagr >= 0 ? "+" : ""}${cagr.toFixed(1)}% p.a. CAGR (${Math.round(avgDays)}d avg)` : `${netPnlPct >= 0 ? "+" : ""}${netPnlPct.toFixed(1)}% net gain`;
    }
    if (headerSummaryEl) {
      headerSummaryEl.textContent = `${totWeight.toFixed(1)}g · ${netPnl >= 0 ? "+" : ""}₹ ${Math.round(netPnl).toLocaleString("en-IN")}`;
    }
  }

  // Add purchase button
  if (addBtn) {
    addBtn.addEventListener("click", () => {
      const w = Number(weightInput ? weightInput.value : 0);
      const r = Number(rateInput ? rateInput.value : 0);
      const d = (dateInput ? dateInput.value : "") || new Date().toISOString().slice(0, 10);
      const n = ((noteInput ? noteInput.value : "") || "").trim();

      if (!w || w <= 0) {
        if (typeof toast === "function") toast("Please enter a valid gold weight");
        return;
      }
      if (!r || r <= 0) {
        if (typeof toast === "function") toast("Please enter a valid buy rate per gram");
        return;
      }

      lots.push({
        id: Date.now().toString(36) + Math.random().toString(36).slice(2, 6),
        date: d,
        weight: w,
        rate: r,
        note: n || "Purchase lot",
        createdAt: new Date().toISOString()
      });
      saveLots();
      if (typeof toast === "function") toast(`Saved ${w}g purchase to portfolio!`);
      if (noteInput) noteInput.value = "";
    });
  }

  // Delete button delegation
  if (tableBody) {
    tableBody.addEventListener("click", e => {
      const btn = e.target.closest(".port-del-btn");
      if (!btn) return;
      const idx = Number(btn.dataset.idx);
      if (Number.isFinite(idx) && idx >= 0 && idx < lots.length) {
        lots.splice(idx, 1);
        saveLots();
        if (typeof toast === "function") toast("Purchase lot removed");
      }
    });
  }

  window.refreshPortfolio = renderPortfolio;
  renderPortfolio();
  setTimeout(renderPortfolio, 500);
})();

// Jeweller Bill Auditor (Agent 8)
(() => {
  // ============================================================
  function auditJewellerBill() {
    const rates = (typeof getCurrentMarketRates === "function") ? getCurrentMarketRates() : { r22: 14270 };
    const rate = rates.r22;
    const w = parseFloat($("auditWeight") ? $("auditWeight").value : 16) || 0;
    const quotedBill = parseFloat($("auditShopPrice") ? $("auditShopPrice").value : 0) || 0;
    const shopVaPct = parseFloat($("auditVaPct") ? $("auditVaPct").value : 14) || 0;
    const designType = $("auditType") ? $("auditType").value : "plain";

    // Standard fair VA percentages by jewellery type in Chennai
    const fairVaMap = { plain: 10.5, antique: 16.0, temple: 18.0, coin: 2.0 };
    const benchmarkVa = fairVaMap[designType] || 12.0;

    const goldVal = Math.round(w * rate);
    const fairMaking = Math.round(goldVal * (benchmarkVa / 100));
    const gstVal = Math.round((goldVal + fairMaking) * 0.03);
    const hallmarkFee = 45;
    const fairTotal = goldVal + fairMaking + gstVal + hallmarkFee;

    // What shop is charging based on user-entered shopVaPct
    const shopMaking = Math.round(goldVal * (shopVaPct / 100));
    const shopGst = Math.round((goldVal + shopMaking) * 0.03);
    const shopCalculatedTotal = goldVal + shopMaking + shopGst + hallmarkFee;
    const effectiveShopPrice = quotedBill > 0 ? quotedBill : shopCalculatedTotal;

    if ($("auditGoldVal")) $("auditGoldVal").textContent = money(goldVal);
    if ($("auditFairMaking")) {
      const vaComparison = shopVaPct > 0 ? ` (${benchmarkVa}% fair vs ${shopVaPct}% shop)` : ` (${benchmarkVa}%)`;
      $("auditFairMaking").textContent = money(fairMaking) + vaComparison;
    }
    if ($("auditGstFee")) $("auditGstFee").textContent = money(gstVal + hallmarkFee);
    if ($("auditFairTotal")) $("auditFairTotal").textContent = money(fairTotal);

    // Overcharge evaluation comparing shop charge (quoted bill or shopVaPct-derived bill) vs fair benchmark
    const badge = $("meterBadge");
    const tip = $("auditBargainTip");
    if (effectiveShopPrice > 0 && badge && tip) {
      const diff = effectiveShopPrice - fairTotal;
      const diffPct = (diff / fairTotal) * 100;
      const vaDiff = shopVaPct - benchmarkVa;

      if (diff <= 50 || diffPct <= 0.5) {
        badge.className = "meter-badge fair";
        badge.textContent = "Fair Deal";
        tip.innerHTML = `✅ <strong>Excellent Deal:</strong> Quoted price matches the Chennai fair benchmark (${benchmarkVa}% VA). No excessive markup detected.`;
      } else if (diffPct <= 4.5 || (vaDiff > 0 && vaDiff <= 3.0)) {
        badge.className = "meter-badge moderate";
        badge.textContent = "Moderate Markup";
        const extraVaText = vaDiff > 0 ? ` (quoted ${shopVaPct}% VA is +${vaDiff.toFixed(1)}% above fair ${benchmarkVa}% benchmark)` : "";
        tip.innerHTML = `⚠️ <strong>Shop Markup:</strong> Quoted bill is <strong>+${money(diff)}</strong> above fair benchmark${extraVaText}. Ask the salesperson to waive ₹${Math.round(diff * 0.7)} from making charges.`;
      } else {
        badge.className = "meter-badge overpriced";
        badge.textContent = "Overpriced — Bargain!";
        const extraVaText = vaDiff > 0 ? ` with quoted ${shopVaPct}% VA (+${vaDiff.toFixed(1)}% above fair ${benchmarkVa}% benchmark)` : "";
        tip.innerHTML = `🚨 <strong>Overcharge Alert:</strong> Quoted price has <strong>+${money(diff)} (+${diffPct.toFixed(1)}%)</strong> excess margin${extraVaText}! Counter-offer with <strong>${money(fairTotal + 500)}</strong> or walk to an alternative showroom in T. Nagar / Sowcarpet.`;
      }
    }
  }

  ["auditWeight", "auditType", "auditShopPrice", "auditVaPct"].forEach(id => {
    const el = $(id);
    if (el) {
      el.addEventListener("input", auditJewellerBill);
      el.addEventListener("change", auditJewellerBill);
    }
  });
  auditJewellerBill();
  window.auditJewellerBill = auditJewellerBill;
})();

// Old Gold Melt Valuation (Agent 9)
(() => {
  // ============================================================
  function calculateOldGoldMelt() {
    const rates = (typeof getCurrentMarketRates === "function") ? getCurrentMarketRates() : { r22: 14270 };
    const rate = rates.r22;
    const w = parseFloat($("meltWeight") ? $("meltWeight").value : 24) || 0;
    const purityKey = $("meltPurity") ? $("meltPurity").value : "916";

    const purityFractions = { "999": 0.999, "916": 0.916, "850": 0.850, "750": 0.750 };
    const purity = purityFractions[purityKey] || 0.916;

    // Melt Loss tolerance standard in Chennai trade: 1.5%
    const meltLossGrams = w * 0.015;
    const netGrams = Math.max(0, w - meltLossGrams);
    const pure22kEquiv = (netGrams * purity) / 0.916;

    const exchangeVal = Math.round(pure22kEquiv * rate);
    // Cash payout standard: 98% of benchmark (2% cash liquidity spread)
    const cashVal = Math.round(exchangeVal * 0.98);

    if ($("meltPureGrams")) $("meltPureGrams").textContent = pure22kEquiv.toFixed(2) + "g (22K equiv)";
    if ($("meltLossGrams")) $("meltLossGrams").textContent = "-" + meltLossGrams.toFixed(2) + "g (1.5%)";
    if ($("meltCashVal")) $("meltCashVal").textContent = money(cashVal);
    if ($("meltExchangeVal")) $("meltExchangeVal").textContent = money(exchangeVal) + " (100%)";
  }

  ["meltWeight", "meltPurity"].forEach(id => {
    const el = $(id);
    if (el) {
      el.addEventListener("input", calculateOldGoldMelt);
      el.addEventListener("change", calculateOldGoldMelt);
    }
  });
  calculateOldGoldMelt();
  window.calculateOldGoldMelt = calculateOldGoldMelt;
})();

// 11-Month Jeweller Scheme vs Gold SIP (Agent 10 - Newton Raphson XIRR)
(() => {
  // ============================================================
  function calculateGoldSchemeVsSip() {
    const rate = (live && Number(live.rate_22k)) ? Number(live.rate_22k) : 14270;
    const monthlyAmt = parseFloat($("schemeMonthlyAmount") ? $("schemeMonthlyAmount").value : 10000) || 10000;
    const profile = $("schemeJewellerProfile") ? $("schemeJewellerProfile").value : "grt";
    const vaPct = parseFloat($("schemeVaPct") ? $("schemeVaPct").value : 14) || 14;
    const growthPct = parseFloat($("schemeGrowthPct") ? $("schemeGrowthPct").value : 10) || 10;

    const monthlyFactor = Math.pow(1.0 + growthPct / 100.0, 1.0 / 12.0);
    const monthlyPrices = [];
    for (let i = 0; i < 11; i++) {
      monthlyPrices.push(rate * Math.pow(monthlyFactor, i));
    }
    const maturityPrice = rate * Math.pow(monthlyFactor, 12);
    const totalPaid = monthlyAmt * 11;

    // Weight Scheme accumulation (GRT / Lalitha)
    let weightGrams = 0;
    for (let i = 0; i < 11; i++) {
      weightGrams += monthlyAmt / monthlyPrices[i];
    }
    const weightVaSavings = Math.round(weightGrams * maturityPrice * (vaPct / 100));
    const weightJewelleryVal = Math.round(weightGrams * maturityPrice * (1 + vaPct / 100));

    // Cash Scheme accumulation (Tanishq / Kalyan)
    const cashVoucherVal = monthlyAmt * 12; // 1 month bonus paid by jeweller
    const cashGrams = cashVoucherVal / (maturityPrice * (1 + vaPct / 100));
    const cashBonus = monthlyAmt;

    // Direct Physical Coin SIP (2% minting + 3% GST on purchase)
    let coinGrams = 0;
    for (let i = 0; i < 11; i++) {
      coinGrams += monthlyAmt / (monthlyPrices[i] * 1.02 * 1.03);
    }
    const coinLiquidVal = Math.round(coinGrams * maturityPrice * 0.99); // 1% melt spread

    // Analytical Harmonic Mean Breakeven Price
    let invSum = 0;
    for (let i = 0; i < 11; i++) {
      invSum += 1.0 / monthlyPrices[i];
    }
    const harmonicMean = 11.0 / invSum;
    const breakevenPrice = Math.round((12.0 / 11.0) * harmonicMean);
    const breakevenPct = ((breakevenPrice - rate) / rate) * 100;

    // Real Newton-Raphson XIRR Solver over dated monthly cashflows
    function solveXIRR(cashflows, guess = 0.15, maxIter = 100, tol = 1e-6) {
      if (!Array.isArray(cashflows) || cashflows.length < 2) return 0;
      let r = guess;
      const t0 = new Date(cashflows[0].date).getTime();

      for (let iter = 0; iter < maxIter; iter++) {
        let npv = 0;
        let dNpv = 0;

        for (let i = 0; i < cashflows.length; i++) {
          const cf = cashflows[i];
          const t = (new Date(cf.date).getTime() - t0) / (365.25 * 86400000);
          const denom = Math.pow(1 + r, t);
          if (Math.abs(denom) < 1e-12) continue;

          npv += cf.amount / denom;
          dNpv -= (t * cf.amount) / (denom * (1 + r));
        }

        if (Math.abs(npv) < tol) return r;
        if (Math.abs(dNpv) < 1e-12) break;

        const nextR = r - npv / dNpv;
        if (!Number.isFinite(nextR)) break;
        if (Math.abs(nextR - r) < tol) return nextR;
        r = nextR;
      }
      return r;
    }

    const baseDate = new Date();
    const weightFlows = [];
    const cashFlows = [];
    const coinFlows = [];

    for (let m = 0; m < 11; m++) {
      const d = new Date(baseDate.getFullYear(), baseDate.getMonth() + m, 1);
      const dateStr = d.toISOString().split("T")[0];
      weightFlows.push({ date: dateStr, amount: -monthlyAmt });
      cashFlows.push({ date: dateStr, amount: -monthlyAmt });
      coinFlows.push({ date: dateStr, amount: -monthlyAmt });
    }

    const maturityDate = new Date(baseDate.getFullYear(), baseDate.getMonth() + 11, 1);
    const maturityDateStr = maturityDate.toISOString().split("T")[0];

    weightFlows.push({ date: maturityDateStr, amount: weightJewelleryVal });
    cashFlows.push({ date: maturityDateStr, amount: cashVoucherVal });
    coinFlows.push({ date: maturityDateStr, amount: coinLiquidVal });

    const weightXIRR = Math.max(0, solveXIRR(weightFlows) * 100).toFixed(1);
    const cashXIRR = Math.max(0, solveXIRR(cashFlows) * 100).toFixed(1);
    const coinXIRR = Math.max(0, solveXIRR(coinFlows) * 100).toFixed(1);

    const isWeightModel = (profile === "grt" || profile === "lalitha");
    const activeSchemeGrams = isWeightModel ? weightGrams : cashGrams;
    const activeSchemeXirr = isWeightModel ? weightXIRR : cashXIRR;

    if ($("schemeGoldGrams")) $("schemeGoldGrams").textContent = activeSchemeGrams.toFixed(3) + "g";
    if ($("schemeXirrVal")) $("schemeXirrVal").textContent = activeSchemeXirr + "% p.a.";
    if ($("schemeSipGrams")) $("schemeSipGrams").textContent = coinGrams.toFixed(3) + "g";
    if ($("schemeSipXirr")) $("schemeSipXirr").textContent = coinXIRR + "% p.a.";
    if ($("schemeTotalPaid")) $("schemeTotalPaid").textContent = money(totalPaid) + " (11 mo)";
    if ($("schemeVaSavings")) $("schemeVaSavings").textContent = isWeightModel ? money(weightVaSavings) : money(cashBonus) + " (Bonus)";
    if ($("schemeBreakevenRate")) $("schemeBreakevenRate").textContent = `${money(breakevenPrice)}/g (${breakevenPct >= 0 ? "+" : ""}${breakevenPct.toFixed(1)}%)`;

    const deltaGrams = activeSchemeGrams - coinGrams;
    const deltaPct = (deltaGrams / coinGrams) * 100;
    if ($("schemeAdvantageGrams")) {
      $("schemeAdvantageGrams").textContent = `${deltaGrams >= 0 ? "+" : ""}${deltaGrams.toFixed(3)}g (${deltaPct >= 0 ? "+" : ""}${deltaPct.toFixed(1)}%)`;
      $("schemeAdvantageGrams").style.color = deltaGrams >= 0 ? "var(--good)" : "var(--bad)";
    }

    const verdictBadge = $("schemeVerdictBadge");
    const verdictTip = $("schemeVerdictTip");
    if (verdictBadge && verdictTip) {
      if (isWeightModel) {
        verdictBadge.className = "meter-badge fair";
        verdictBadge.textContent = "Weight Scheme Wins";
        verdictTip.innerHTML = `⚖️ <strong>Quantitative Verdict:</strong> For jewellery buyers, the <strong>Weight-based Model (GRT/Lalitha)</strong> outperforms because it locks in gold weight every month (DCA) and waives making charges up to <strong>${vaPct}%</strong> at maturity. Breakeven against cash chits requires gold to reach <strong>${money(breakevenPrice)}/g</strong>.`;
      } else {
        verdictBadge.className = "meter-badge moderate";
        verdictBadge.textContent = "Cash Bonus Model";
        verdictTip.innerHTML = `⚠️ <strong>Cash Chit Analysis (Tanishq/Kalyan):</strong> You receive 1 month bonus (equivalent to ~${cashXIRR}% XIRR), but gold price is locked only at month 12. If gold rallies more than <strong>+${breakevenPct.toFixed(1)}%</strong>, a weight-based chit would have accumulated more grams!`;
      }
    }
  }

  ["schemeMonthlyAmount", "schemeJewellerProfile", "schemeVaPct", "schemeGrowthPct"].forEach(id => {
    const el = $(id);
    if (el) {
      el.addEventListener("input", calculateGoldSchemeVsSip);
      el.addEventListener("change", calculateGoldSchemeVsSip);
    }
  });
  calculateGoldSchemeVsSip();
  if (typeof window.calculateGoldSchemeVsSip !== "function") {
    window.calculateGoldSchemeVsSip = calculateGoldSchemeVsSip;
  }
  window.calculateGoldSchemeVsSip = calculateGoldSchemeVsSip;
})();
