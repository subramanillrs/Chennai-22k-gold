// ============================================================
// THEME MANAGER & BASE DOM SELECTOR
// ============================================================

const LIVE_URL = "data/live.json";
const HISTORY_URL = "data/history.json";
const HEALTH_URL = "data/health_status.json";
const WINDOWS_URL = "data/monitoring_windows.json";
const WORKER_URL = "https://gold-price-fetch.subramanilrs.workers.dev/";

let live = null;
let history = [];
// If the live payload's timestamp is older than this, treat it as
// stale even though its date field still says "today" -- catches SW
// cache fallback or a stalled pipeline serving an old same-day fetch.
const STALE_DATA_MAX_AGE_HOURS = 12;
let selectedRange = 30;
let fetchBusy = false;
let scrubIndex = -1;
let lastSyncTimestamp = 0;

const $ = id => document.getElementById(id);


(function setupThemeToggle() {
  const root = document.documentElement;
  const metaLight = document.querySelector('meta[name="theme-color"][media*="light"]');
  const metaDark = document.querySelector('meta[name="theme-color"][media*="dark"]');

  function applyTheme(theme) {
    const active = (theme === "oled" || theme === "dark") ? "oled" : "light";
    root.setAttribute("data-theme", active);
    const color = active === "oled" ? "#000000" : "#faf7f0";
    if (metaLight) metaLight.setAttribute("content", color);
    if (metaDark) metaDark.setAttribute("content", color);
    if (typeof drawChart === "function") requestAnimationFrame(drawChart);
    return active;
  }

  const saved = localStorage.getItem("gold_theme");
  applyTheme(saved || "light");

  const btn = $("themeToggle");
  if (btn) {
    btn.onclick = () => {
      if (typeof haptic === "function") haptic(8);
      const current = root.getAttribute("data-theme") || "light";
      const next = (current === "oled" || current === "dark") ? "light" : "oled";
      localStorage.setItem("gold_theme", next);
      applyTheme(next);
      if (typeof toast === "function") toast(next === "light" ? "Day Theme" : "Night Theme");
    };
  }

  const brandBadge = document.querySelector(".brand-badge");
  if (brandBadge) {
    brandBadge.style.cursor = "pointer";
    brandBadge.setAttribute("title", "Tap for 22K Gold Coin Acoustic Chime");
    brandBadge.onclick = () => {
      haptic(15);
      if (typeof playGoldCoinChime === "function") playGoldCoinChime(1.0);
    };
  }
})();
