#!/usr/bin/env python3

import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

# ============================================================
# PATHS & CONSTANTS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

LIVE_FILE = DATA_DIR / "live.json"
HISTORY_FILE = DATA_DIR / "history.json"
WINDOW_FILE = DATA_DIR / "monitoring_windows.json"
ALERT_FILE = DATA_DIR / "alert_state.json"
SUMMARY_FILE = DATA_DIR / "summary.json"
HEALTH_FILE = DATA_DIR / "health_status.json"

SEED_FILE = BASE_DIR / "historical_monitor_seed.json"
if not SEED_FILE.exists():
    SEED_FILE = DATA_DIR / "historical_monitor_seed.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)
IST = ZoneInfo("Asia/Kolkata")

LIVECHENNAI_URL = "https://www.livechennai.com/gold_silverrate.asp"
GOODRETURNS_URL = "https://www.goodreturns.in/gold-rates/chennai.html"

POLL_SECONDS = 10
REQUEST_TIMEOUT = 20

AM_START = (9, 30)
AM_END = (12, 30)
PM_START = (16, 30)
PM_END = (19, 30)

FALLBACK_AM_TIME = AM_START
FALLBACK_PM_TIME = PM_START

HISTORY_LOOKBACK_DAYS = 30
PRE_WINDOW_MINUTES = 15
WINDOW_DURATION_MINUTES = 85
MIN_SAMPLES_FOR_PREDICTION = 3
MAX_SCHEDULE_WAIT_MINUTES = 90

AM_PREDICTION_MIN = (7, 0)
AM_PREDICTION_MAX = (13, 0)
PM_PREDICTION_MIN = (14, 0)
PM_PREDICTION_MAX = (21, 0)

MAX_DAILY_CHANGE_PCT = 8
SOURCE_AGREEMENT_TOLERANCE = 50

ALERT_STALE_HOURS = 20
ALERT_DISAGREE_HOURS = 3
ALERT_COOLDOWN_HOURS = 12

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/18.0 Safari/605.1.15"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-IN,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
)

# ============================================================
# UTILITIES
# ============================================================

def now_ist():
    return datetime.now(IST)


def valid_gold_rate(value):
    if value is None:
        return False
    try:
        val = int(value)
        return 5000 <= val <= 50000
    except (ValueError, TypeError):
        return False


def clean_number(text):
    if text is None:
        return None

    cleaned = (
        str(text)
        .replace(",", "")
        .replace("₹", "")
        .replace("Rs.", "")
        .replace("Rs", "")
        .replace("INR", "")
    )
    cleaned = re.sub(r"\b(?:24|22|18|20)\s*(?:k|carat|karat)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:1|4|8|10|100)\s*(?:g|gm|gram|grams)\b", " ", cleaned, flags=re.IGNORECASE)

    matches = re.findall(r"\d+(?:\.\d+)?", cleaned)
    for m in matches:
        try:
            val = int(float(m))
            if valid_gold_rate(val):
                return val
        except (ValueError, TypeError):
            continue

    return None


def load_json(path, default):
    try:
        if not path.exists():
            return default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        print(f"WARNING: Could not read {path}: {exc}")
        return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    temp.replace(path)


def _hours_since(iso_string, now):
    if not iso_string:
        return None
    try:
        then = datetime.fromisoformat(iso_string)
        if then.tzinfo is None:
            then = then.replace(tzinfo=IST)
        else:
            then = then.astimezone(IST)
        return (now - then).total_seconds() / 3600
    except Exception:
        return None

# ============================================================
# SCRAPERS
# ============================================================

def extract_livechennai_22k(soup):
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue

        header_cells = [c.get_text(" ", strip=True).lower() for c in rows[0].find_all(["th", "td"])]
        col_22k_idx = -1
        for idx, h in enumerate(header_cells):
            if ("22" in h or "standard" in h) and ("1" in h or "gm" in h or "gram" in h or "gold" in h):
                if "8" not in h and "24" not in h:
                    col_22k_idx = idx
                    break

        if col_22k_idx != -1 and len(rows) > 1:
            for r in rows[1:]:
                cells = r.find_all(["td", "th"])
                if col_22k_idx < len(cells):
                    val = clean_number(cells[col_22k_idx].get_text(" ", strip=True))
                    if valid_gold_rate(val):
                        return val

        for row in rows:
            row_text = row.get_text(" ", strip=True).lower()
            if ("22 k" in row_text or "22k" in row_text or "22 carat" in row_text) and "24" not in row_text:
                for cell in row.find_all(["td", "th"]):
                    val = clean_number(cell.get_text(" ", strip=True))
                    if valid_gold_rate(val):
                        return val

    page_text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    patterns = [
        r"Today(?:'s)?\s+22\s*K\s*(?:Rate|Gold)?[^0-9\r\n]{0,30}(?:₹|Rs\.?|INR)?\s*([\d,]+)",
        r"22\s*K(?:arat|orat)?\s*(?:\(1\s*g\)|1\s*gm?|1\s*gram|Gold|Rate)?[^0-9\r\n]{0,30}(?:₹|Rs\.?|INR)?\s*([\d,]+)",
        r"22\s*Carat\s+gold\s+rate[^0-9\r\n]{0,30}(?:₹|Rs\.?|INR)?\s*([\d,]+)",
        r"1\s*Gram\s*(?:\(22\s*K\)|22\s*K)[^0-9\r\n]{0,30}(?:₹|Rs\.?|INR)?\s*([\d,]+)",
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, page_text, flags=re.IGNORECASE):
            val = clean_number(match.group(1))
            if valid_gold_rate(val):
                return val

    return None


def fetch_livechennai():
    try:
        res = SESSION.get(LIVECHENNAI_URL, timeout=REQUEST_TIMEOUT)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")
        rate = extract_livechennai_22k(soup)
        if rate:
            return {
                "source": "LiveChennai",
                "rate_22k": int(rate),
                "url": LIVECHENNAI_URL,
                "fetched_at": now_ist().isoformat(),
            }
    except Exception as exc:
        print(f"LiveChennai scrape error: {exc}")
    return None


def extract_goodreturns_22k(soup):
    for table in soup.find_all("table"):
        table_context = ""
        prev = table.find_previous(["h1", "h2", "h3", "h4", "caption", "div"])
        if prev:
            table_context = prev.get_text(" ", strip=True).lower()
        table_text = table.get_text(" ", strip=True).lower()

        is_22k_table = ("22" in table_context or "22" in table_text) and "24" not in table_context

        for row in table.find_all("tr"):
            row_text = row.get_text(" ", strip=True).lower()
            if (is_22k_table and ("1 gram" in row_text or "1g" in row_text or "1 gm" in row_text)) or \
               (("22 k" in row_text or "22k" in row_text or "22 carat" in row_text) and "8" not in row_text):
                for cell in row.find_all(["td", "th"]):
                    val = clean_number(cell.get_text(" ", strip=True))
                    if valid_gold_rate(val):
                        return val

    page_text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    patterns = [
        r"22\s*K\s+Gold\s*/\s*g[^0-9\r\n]{0,30}(?:₹|Rs\.?|INR)?\s*([\d,]+)",
        r"22\s*(?:K|Carat|Karat)\s*Gold[^0-9\r\n]{0,50}(?:₹|Rs\.?|INR)?\s*([\d,]+)",
        r"1\s*Gram[^0-9\r\n]{0,30}(?:₹|Rs\.?|INR)?\s*([\d,]+)",
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, page_text, flags=re.IGNORECASE):
            val = clean_number(match.group(1))
            if valid_gold_rate(val):
                return val

    return None


def fetch_goodreturns():
    try:
        res = SESSION.get(GOODRETURNS_URL, timeout=REQUEST_TIMEOUT)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")
        rate = extract_goodreturns_22k(soup)
        if rate:
            return {
                "source": "GoodReturns",
                "rate_22k": int(rate),
                "url": GOODRETURNS_URL,
                "fetched_at": now_ist().isoformat(),
            }
    except Exception as exc:
        print(f"GoodReturns scrape error: {exc}")
    return None


def fetch_all_sources():
    with ThreadPoolExecutor(max_workers=2) as executor:
        f_live = executor.submit(fetch_livechennai)
        f_good = executor.submit(fetch_goodreturns)
        return f_live.result(), f_good.result()

# ============================================================
# CONSENSUS & VALIDATION
# ============================================================

def _rate_is_plausible(rate, previous_rate):
    if not isinstance(previous_rate, (int, float)) or previous_rate <= 0:
        return True
    return (abs(rate - previous_rate) / previous_rate * 100) <= MAX_DAILY_CHANGE_PCT


def select_rate(live, good, previous_rate=None):
    live_rate = live["rate_22k"] if live else None
    good_rate = good["rate_22k"] if good else None

    if live_rate is not None and good_rate is not None:
        diff = abs(live_rate - good_rate)
        if diff <= SOURCE_AGREEMENT_TOLERANCE:
            consensus_rate = round((live_rate + good_rate) / 2)
            if not _rate_is_plausible(consensus_rate, previous_rate) and previous_rate is not None:
                return {
                    "rate_22k": previous_rate,
                    "agreement": False,
                    "source": "Previous rate - consensus implausible",
                    "livechennai": live,
                    "goodreturns": good,
                }
            return {
                "rate_22k": consensus_rate,
                "agreement": True,
                "source": "LiveChennai + GoodReturns" if diff == 0 else "LiveChennai + GoodReturns (tolerance)",
                "livechennai": live,
                "goodreturns": good,
            }

        if previous_rate is not None:
            return {
                "rate_22k": previous_rate,
                "agreement": False,
                "source": "Previous rate - sources disagree",
                "livechennai": live,
                "goodreturns": good,
            }
        return {
            "rate_22k": live_rate,
            "agreement": False,
            "source": "LiveChennai - sources disagree",
            "livechennai": live,
            "goodreturns": good,
        }

    if live_rate is not None:
        if not _rate_is_plausible(live_rate, previous_rate) and previous_rate is not None:
            return {
                "rate_22k": previous_rate,
                "agreement": None,
                "source": "Previous rate - LiveChennai implausible",
                "livechennai": live,
                "goodreturns": good,
            }
        return {
            "rate_22k": live_rate,
            "agreement": None,
            "source": "LiveChennai",
            "livechennai": live,
            "goodreturns": good,
        }

    if good_rate is not None:
        if not _rate_is_plausible(good_rate, previous_rate) and previous_rate is not None:
            return {
                "rate_22k": previous_rate,
                "agreement": None,
                "source": "Previous rate - GoodReturns implausible",
                "livechennai": live,
                "goodreturns": good,
            }
        return {
            "rate_22k": good_rate,
            "agreement": None,
            "source": "GoodReturns",
            "livechennai": live,
            "goodreturns": good,
        }

    return None


def get_previous_rate():
    data = load_json(LIVE_FILE, {})
    if isinstance(data, dict):
        for k in ("rate_22k", "gold_22k", "rate"):
            val = data.get(k)
            if isinstance(val, (int, float)) and valid_gold_rate(val):
                return int(val)
    return None


def get_yesterday_close(today_str):
    records = extract_history_records(load_json(HISTORY_FILE, []))
    prior = [r for r in records if isinstance(r, dict) and r.get("date") and r.get("date") < today_str and valid_gold_rate(r.get("rate_22k"))]
    if prior:
        return int(prior[-1]["rate_22k"])
    return None


def session_for_time(dt, previous_session=None):
    hour = dt.hour + dt.minute / 60.0
    if 6.0 <= hour < 14.0:
        return "AM"
    if 14.0 <= hour <= 23.99:
        return "PM"
    return previous_session or "PM"

# ============================================================
# PERSISTENCE
# ============================================================

def extract_history_records(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("records", "history", "data"):
            val = data.get(k)
            if isinstance(val, list):
                return val
    return []


def save_history(rate, selected, changed):
    existing = load_json(HISTORY_FILE, [])
    records = extract_history_records(existing)
    current = now_ist()
    today = current.strftime("%Y-%m-%d")
    current_session = session_for_time(current)

    rec = {
        "date": today,
        "time": current.strftime("%H:%M:%S"),
        "timestamp": current.isoformat(),
        "session": current_session,
        "rate_22k": int(rate),
        "rate_8g": int(rate * 8),
        "changed": bool(changed),
        "source": selected.get("source", "Unknown"),
        "agreement": selected.get("agreement"),
        "livechennai_rate": selected["livechennai"]["rate_22k"] if selected.get("livechennai") else None,
        "goodreturns_rate": selected["goodreturns"]["rate_22k"] if selected.get("goodreturns") else None,
    }

    should_append = False
    if not records:
        should_append = True
    elif records[-1].get("date") != today:
        should_append = True
    elif records[-1].get("session") != current_session:
        should_append = True
    elif records[-1].get("rate_22k") != int(rate):
        should_append = True

    if should_append:
        records.append(rec)
    else:
        records[-1].update(
            {
                "time": rec["time"],
                "timestamp": rec["timestamp"],
                "source": rec["source"],
                "agreement": rec["agreement"],
                "livechennai_rate": rec["livechennai_rate"],
                "goodreturns_rate": rec["goodreturns_rate"],
            }
        )

    if isinstance(existing, dict):
        existing["records"] = records
        save_json(HISTORY_FILE, existing)
    else:
        save_json(HISTORY_FILE, records)


def save_live(rate, selected, changed):
    current = now_ist()
    live = load_json(LIVE_FILE, {})
    if not isinstance(live, dict):
        live = {}

    today = current.strftime("%Y-%m-%d")
    yesterday_close = get_yesterday_close(today)
    previous_rate = yesterday_close or live.get("previous_rate_22k") or live.get("rate_22k") or rate

    live["rate_22k"] = int(rate)
    live["rate_8g"] = int(rate * 8)
    live["currency"] = "INR"
    live["city"] = "Chennai"
    live["purity"] = "22K"
    live["date"] = today
    live["time"] = current.strftime("%H:%M:%S")
    live["timestamp"] = current.isoformat()
    live["session"] = session_for_time(current, live.get("session"))
    live["changed"] = bool(changed)
    live["previous_rate_22k"] = int(previous_rate)
    live["change"] = int(rate) - int(previous_rate)
    live["source"] = selected.get("source", "Unknown")
    live["agreement"] = selected.get("agreement")
    live["sources_agree"] = selected.get("agreement") is True
    live["sources"] = {
        "livechennai": selected.get("livechennai"),
        "goodreturns": selected.get("goodreturns"),
    }
    live["source_rates"] = [
        s["rate_22k"]
        for s in [selected.get("livechennai"), selected.get("goodreturns")]
        if s and valid_gold_rate(s.get("rate_22k"))
    ]
    live["source_update_times"] = [
        s["fetched_at"]
        for s in [selected.get("livechennai"), selected.get("goodreturns")]
        if s and s.get("fetched_at")
    ]
    live["last_checked"] = current.isoformat()
    live["last_checked_at"] = current.isoformat()

    save_json(LIVE_FILE, live)

# ============================================================
# ALERTS & HEALTH
# ============================================================

def send_alert(title, message):
    webhook = os.environ.get("ALERT_WEBHOOK_URL")
    if not webhook:
        print(f"ALERT: {title} — {message}")
        return

    body = f"{title}\n{message}"
    try:
        requests.post(webhook, json={"text": body, "content": body}, timeout=10)
        print(f"Alert sent: {title}")
    except Exception as exc:
        print(f"Failed to post alert: {exc}")


def run_health_check():
    now = now_ist()
    state = load_json(ALERT_FILE, {})
    if not isinstance(state, dict):
        state = {}

    live = load_json(LIVE_FILE, {})
    if not isinstance(live, dict):
        live = {}

    changed_state = False
    hours_since_checked = _hours_since(live.get("last_checked"), now)

    if hours_since_checked is not None and hours_since_checked >= ALERT_STALE_HOURS:
        last_stale_alert = _hours_since(state.get("last_stale_alert_at"), now)
        if last_stale_alert is None or last_stale_alert >= ALERT_COOLDOWN_HOURS:
            send_alert("Gold Rate Feed Stale", f"No rate update in {hours_since_checked:.1f} hours.")
            state["last_stale_alert_at"] = now.isoformat()
            changed_state = True
    elif state.get("last_stale_alert_at") is not None:
        state["last_stale_alert_at"] = None
        changed_state = True

    if live.get("agreement") is False:
        if not state.get("disagree_since"):
            state["disagree_since"] = now.isoformat()
            changed_state = True

        disagree_hours = _hours_since(state.get("disagree_since"), now) or 0
        if disagree_hours >= ALERT_DISAGREE_HOURS:
            last_disagree_alert = _hours_since(state.get("last_disagree_alert_at"), now)
            if last_disagree_alert is None or last_disagree_alert >= ALERT_COOLDOWN_HOURS:
                send_alert(
                    "Gold Rate Sources Disagreeing",
                    f"LiveChennai and GoodReturns have disagreed for {disagree_hours:.1f} hours.",
                )
                state["last_disagree_alert_at"] = now.isoformat()
                changed_state = True
    else:
        if state.get("disagree_since") is not None:
            state["disagree_since"] = None
            state["last_disagree_alert_at"] = None
            changed_state = True

    if changed_state:
        save_json(ALERT_FILE, state)

    disagree_duration = _hours_since(state.get("disagree_since"), now)
    if hours_since_checked is not None and hours_since_checked >= ALERT_STALE_HOURS:
        status = "stale"
    elif disagree_duration is not None and disagree_duration >= ALERT_DISAGREE_HOURS:
        status = "disagreeing"
    else:
        status = "ok"

    save_json(
        HEALTH_FILE,
        {
            "checked_at": now.isoformat(),
            "status": status,
            "hours_since_last_checked": round(hours_since_checked, 2) if hours_since_checked is not None else 0.0,
            "sources_agree": live.get("sources_agree", True),
            "disagree_since": state.get("disagree_since"),
            "webhook_configured": bool(os.environ.get("ALERT_WEBHOOK_URL")),
            "current_rate_22k": live.get("rate_22k"),
            "current_rate_date": live.get("date"),
        },
    )


def compute_and_save_summary():
    records = extract_history_records(load_json(HISTORY_FILE, []))
    valid = [
        (r["date"], int(r["rate_22k"]))
        for r in records
        if isinstance(r, dict) and valid_gold_rate(r.get("rate_22k")) and r.get("date")
    ]

    if not valid:
        return

    now = now_ist()
    current_month = now.strftime("%Y-%m")
    current_year = now.strftime("%Y")

    hi = max(valid, key=lambda x: x[1])
    lo = min(valid, key=lambda x: x[1])
    month_vals = [v for d, v in valid if d.startswith(current_month)]
    year_vals = [v for d, v in valid if d.startswith(current_year)]
    recent_30 = [v for _, v in valid[-30:]]

    def bucket(vals):
        if not vals:
            return {"average_22k": None, "high": None, "low": None}
        return {"average_22k": round(sum(vals) / len(vals)), "high": max(vals), "low": min(vals)}

    save_json(
        SUMMARY_FILE,
        {
            "generated_at": now.isoformat(),
            "all_time_high": {"rate_22k": hi[1], "date": hi[0]},
            "all_time_low": {"rate_22k": lo[1], "date": lo[0]},
            "current_month": {"month": current_month, **bucket(month_vals)},
            "current_year": {"year": current_year, **bucket(year_vals)},
            "last_30_records": bucket(recent_30),
            "total_records": len(valid),
        },
    )

# ============================================================
# MONITORING WINDOW PREDICTION
# ============================================================

def _parse_time_to_minutes(time_str):
    try:
        parts = str(time_str).split(":")
        return int(parts[0]) * 60 + int(parts[1])
    except Exception:
        return None


def _median(values):
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return (s[mid - 1] + s[mid]) / 2 if n % 2 == 0 else s[mid]


def _clamp_hm(hm, lo, hi):
    minutes = hm[0] * 60 + hm[1]
    clamped = max(lo[0] * 60 + lo[1], min(hi[0] * 60 + hi[1], minutes))
    return (clamped // 60, clamped % 60)


def predict_session_times(now=None):
    now = now or now_ist()
    cutoff = (now - timedelta(days=HISTORY_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    records = extract_history_records(load_json(HISTORY_FILE, []))

    am_m, pm_m = [], []
    for r in records:
        if not isinstance(r, dict) or (r.get("date") or "") < cutoff:
            continue
        mins = _parse_time_to_minutes(r.get("time"))
        if mins is None:
            continue
        if r.get("session") == "AM":
            am_m.append(mins)
        elif r.get("session") == "PM":
            pm_m.append(mins)

    if len(am_m) < MIN_SAMPLES_FOR_PREDICTION:
        for r in load_json(SEED_FILE, []):
            if isinstance(r, dict) and r.get("session") == "AM":
                m = _parse_time_to_minutes(r.get("time"))
                if m is not None:
                    am_m.append(m)

    if len(pm_m) < MIN_SAMPLES_FOR_PREDICTION:
        for r in load_json(SEED_FILE, []):
            if isinstance(r, dict) and r.get("session") == "PM":
                m = _parse_time_to_minutes(r.get("time"))
                if m is not None:
                    pm_m.append(m)

    res = {}
    if len(am_m) >= MIN_SAMPLES_FOR_PREDICTION:
        med = _median(am_m)
        res["AM"] = _clamp_hm((int(med // 60), int(med % 60)), AM_PREDICTION_MIN, AM_PREDICTION_MAX)
    else:
        res["AM"] = FALLBACK_AM_TIME

    if len(pm_m) >= MIN_SAMPLES_FOR_PREDICTION:
        med = _median(pm_m)
        res["PM"] = _clamp_hm((int(med // 60), int(med % 60)), PM_PREDICTION_MIN, PM_PREDICTION_MAX)
    else:
        res["PM"] = FALLBACK_PM_TIME

    return res


def _session_bounds(day, hm):
    dt = datetime(day.year, day.month, day.day, hm[0], hm[1], 0, tzinfo=IST)
    start = dt - timedelta(minutes=PRE_WINDOW_MINUTES)
    end = start + timedelta(minutes=WINDOW_DURATION_MINUTES)
    return start, end


def current_window(now=None):
    now = now or now_ist()
    day = now.date()
    p = predict_session_times(now)

    am_s, am_e = _session_bounds(day, p["AM"])
    pm_s, pm_e = _session_bounds(day, p["PM"])

    if am_s <= now < am_e:
        return {"name": "AM", "start": am_s, "end": am_e}
    if pm_s <= now < pm_e:
        return {"name": "PM", "start": pm_s, "end": pm_e}
    return None


def next_window(now=None):
    now = now or now_ist()
    day = now.date()
    p = predict_session_times(now)

    am_s, am_e = _session_bounds(day, p["AM"])
    pm_s, pm_e = _session_bounds(day, p["PM"])

    if now < am_s:
        return {"name": "AM", "start": am_s, "end": am_e}
    if now < pm_s:
        return {"name": "PM", "start": pm_s, "end": pm_e}

    tomorrow = day + timedelta(days=1)
    p_tom = predict_session_times(datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 0, tzinfo=IST))
    am_s_tom, am_e_tom = _session_bounds(tomorrow, p_tom["AM"])
    return {"name": "AM", "start": am_s_tom, "end": am_e_tom}


def save_window_info(window):
    p = predict_session_times(now_ist())
    save_json(
        WINDOW_FILE,
        {
            "timezone": "Asia/Kolkata",
            "updated_at": now_ist().isoformat(),
            "windows": {
                "AM": {
                    "predicted_fix_time": f"{p['AM'][0]:02d}:{p['AM'][1]:02d}",
                    "polling_starts": f"{PRE_WINDOW_MINUTES} min before",
                    "duration_minutes": WINDOW_DURATION_MINUTES,
                },
                "PM": {
                    "predicted_fix_time": f"{p['PM'][0]:02d}:{p['PM'][1]:02d}",
                    "polling_starts": f"{PRE_WINDOW_MINUTES} min before",
                    "duration_minutes": WINDOW_DURATION_MINUTES,
                },
            },
            "active_window": window["name"] if window else None,
            "poll_seconds": POLL_SECONDS,
        },
    )

# ============================================================
# MAIN PIPELINE
# ============================================================

def normal_fetch():
    prev_rate = get_previous_rate()
    live, good = fetch_all_sources()
    selected = select_rate(live, good, prev_rate)

    if not selected:
        return False

    rate = selected["rate_22k"]
    changed = prev_rate is not None and rate != prev_rate
    save_live(rate, selected, changed)
    save_history(rate, selected, changed)
    return True


def monitor_window(window):
    prev_rate = get_previous_rate()
    last_selected = None

    while True:
        now = now_ist()
        if now >= window["end"]:
            if last_selected:
                rate = last_selected["rate_22k"]
                save_live(rate, last_selected, False)
                save_history(rate, last_selected, False)
            save_window_info(None)
            return False

        live, good = fetch_all_sources()
        selected = select_rate(live, good, prev_rate)

        if selected:
            last_selected = selected
            rate = selected["rate_22k"]
            if prev_rate is not None and rate != prev_rate:
                save_live(rate, selected, True)
                save_history(rate, selected, True)
                save_window_info(None)
                return True
            save_live(rate, selected, False)

        remaining = (window["end"] - now_ist()).total_seconds()
        if remaining <= 0:
            if last_selected:
                rate = last_selected["rate_22k"]
                save_live(rate, last_selected, False)
                save_history(rate, last_selected, False)
            save_window_info(None)
            return False

        time.sleep(min(POLL_SECONDS, max(1, int(remaining))))


def main():
    now = now_ist()
    is_gha = os.environ.get("GITHUB_ACTIONS", "").lower() == "true"
    gha_event = os.environ.get("GITHUB_EVENT_NAME", "")
    force = os.environ.get("FORCE_FETCH", "").lower() == "true"

    if force:
        save_window_info(None)
        if not normal_fetch():
            sys.exit(1)
        return

    active = current_window(now)
    if active:
        save_window_info(active)
        monitor_window(active)
        return

    if is_gha and gha_event == "schedule":
        upcoming = next_window(now)
        wait_seconds = (upcoming["start"] - now).total_seconds()

        if wait_seconds <= MAX_SCHEDULE_WAIT_MINUTES * 60:
            time.sleep(max(0, int(wait_seconds)))
            active = current_window(now_ist())
            if active:
                save_window_info(active)
                monitor_window(active)
                return

    save_window_info(None)
    if not normal_fetch():
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
    except Exception as exc:
        print(f"FATAL: {exc}")
        sys.exit(1)
    finally:
        try:
            run_health_check()
        except Exception as exc:
            print(f"Health check failed: {exc}")
        try:
            compute_and_save_summary()
        except Exception as exc:
            print(f"Summary computation failed: {exc}")
