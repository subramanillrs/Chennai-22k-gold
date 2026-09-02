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
# CHENNAI 22K GOLD RATE MONITOR
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

LIVE_FILE = DATA_DIR / "live.json"
HISTORY_FILE = DATA_DIR / "history.json"
WINDOW_FILE = DATA_DIR / "monitoring_windows.json"
ALERT_FILE = DATA_DIR / "alert_state.json"
SUMMARY_FILE = DATA_DIR / "summary.json"
HEALTH_FILE = DATA_DIR / "health_status.json"

# Fallback seed file search paths
SEED_FILE = BASE_DIR / "historical_monitor_seed.json"
if not SEED_FILE.exists():
    SEED_FILE = DATA_DIR / "historical_monitor_seed.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)

IST = ZoneInfo("Asia/Kolkata")

# ============================================================
# SOURCES
# ============================================================

LIVECHENNAI_URL = "https://www.livechennai.com/gold_silverrate.asp"
GOODRETURNS_URL = "https://www.goodreturns.in/gold-rates/chennai.html"

POLL_SECONDS = 10
REQUEST_TIMEOUT = 20

# ============================================================
# MONITORING WINDOWS
# ============================================================

AM_START = (9, 30)
AM_END = (12, 30)

PM_START = (16, 30)
PM_END = (19, 30)

FALLBACK_AM_TIME = AM_START
FALLBACK_PM_TIME = PM_START

HISTORY_LOOKBACK_DAYS = 30
PRE_WINDOW_MINUTES = 15
WINDOW_DURATION_MINUTES = 75
MIN_SAMPLES_FOR_PREDICTION = 3

AM_PREDICTION_MIN = (7, 0)
AM_PREDICTION_MAX = (13, 0)
PM_PREDICTION_MIN = (14, 0)
PM_PREDICTION_MAX = (21, 0)

MAX_DAILY_CHANGE_PCT = 8
SOURCE_AGREEMENT_TOLERANCE = 50

# ============================================================
# ALERTING / HEALTH CHECK
# ============================================================

ALERT_STALE_HOURS = 20
ALERT_DISAGREE_HOURS = 3
ALERT_COOLDOWN_HOURS = 12

# ============================================================
# HTTP SESSION
# ============================================================

SESSION = requests.Session()

SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) "
            "Version/18.0 Safari/605.1.15"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/xml;q=0.9,*/*;q=0.8"
        ),
        "Accept-Language": "en-IN,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
)

# ============================================================
# BASIC HELPERS
# ============================================================

def now_ist():
    return datetime.now(IST)


def format_rupees(value):
    if value is None:
        return "N/A"
    return f"₹{int(value):,}"


def valid_gold_rate(value):
    if value is None:
        return False
    try:
        value = int(value)
    except Exception:
        return False
    return 5000 <= value <= 50000


def clean_number(text):
    if text is None:
        return None

    text = str(text)

    text = (
        text.replace(",", "")
        .replace("₹", "")
        .replace("Rs.", "")
        .replace("Rs", "")
        .replace("INR", "")
    )

    # Filter out purity/weight terms to prevent false token captures
    cleaned = re.sub(r"\b(?:24|22|18|20)\s*(?:k|carat|karat)\b", " ", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(?:1|4|8|10|100)\s*(?:g|gm|gram|grams)\b", " ", cleaned, flags=re.IGNORECASE)

    matches = re.findall(r"\d+(?:\.\d+)?", cleaned)
    if not matches:
        matches = re.findall(r"\d+(?:\.\d+)?", text)

    if not matches:
        return None

    # Prioritize any match in the gold price bracket
    for m in matches:
        try:
            val = int(float(m))
            if valid_gold_rate(val):
                return val
        except Exception:
            continue

    try:
        return int(float(matches[0]))
    except Exception:
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

# ============================================================
# SCRAPERS
# ============================================================

def extract_livechennai_22k(soup):
    tables = soup.find_all("table")

    for table in tables:
        rows = table.find_all("tr")
        if not rows:
            continue

        header_text = " ".join(row.get_text(" ", strip=True) for row in rows[:5])
        normalized = re.sub(r"\s+", " ", header_text).lower()

        if "standard gold" in normalized and "22 k" in normalized:
            for row in rows:
                cells = row.find_all(["td", "th"])
                values = []
                for cell in cells:
                    val = clean_number(cell.get_text(" ", strip=True))
                    if val is not None:
                        values.append(val)

                if len(values) >= 4:
                    candidate = values[-4:][2]
                    if valid_gold_rate(candidate):
                        return candidate

            table_text = table.get_text(" ", strip=True)
            matches = re.findall(
                r"\d{1,2}/[A-Za-z]+/\d{4}.{0,100}?([\d,]+).{0,30}?([\d,]+).{0,30}?([\d,]+).{0,30}?([\d,]+)",
                table_text,
                flags=re.IGNORECASE,
            )

            for match in matches:
                values = [clean_number(x) for x in match]
                if len(values) == 4:
                    candidate = values[2]
                    if valid_gold_rate(candidate):
                        return candidate

    page_text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    patterns = [
        r"Today's\s+22K\s+Rate\s*₹?\s*([\d,]+)",
        r"Today's\s+22K\s+gold\s+rate.{0,100}?₹\s*([\d,]+)",
        r"22K\s+gold\s+rate.{0,100}?₹\s*([\d,]+)",
        r"22\s*carat\s+gold\s+rate.{0,100}?₹\s*([\d,]+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, page_text, flags=re.IGNORECASE)
        if match:
            value = clean_number(match.group(1))
            if valid_gold_rate(value):
                return value

    return None


def fetch_livechennai():
    try:
        response = SESSION.get(LIVECHENNAI_URL, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        rate = extract_livechennai_22k(soup)
        if rate:
            return {
                "source": "LiveChennai",
                "rate_22k": int(rate),
                "url": LIVECHENNAI_URL,
                "fetched_at": now_ist().isoformat(),
            }
    except Exception as exc:
        print(f"LiveChennai failed: {exc}")
    return None


def extract_goodreturns_22k(soup):
    for table in soup.find_all("table"):
        text = table.get_text(" ", strip=True)
        normalized = re.sub(r"\s+", " ", text).lower()

        if "22k" in normalized or "22 k" in normalized or "22 karat" in normalized:
            for row in table.find_all("tr"):
                row_text = row.get_text(" ", strip=True)
                if re.search(r"22\s*k|22\s*karat", row_text, re.IGNORECASE):
                    for cell in row.find_all(["td", "th"]):
                        val = clean_number(cell.get_text(" ", strip=True))
                        if valid_gold_rate(val):
                            return val

    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    patterns = [
        r"22K\s+Gold\s*/g\s*₹?\s*([\d,]+)",
        r"22K\s+Gold\s+/?g\s*₹?\s*([\d,]+)",
        r"22K\s+Gold.{0,80}?₹\s*([\d,]+)",
        r"22\s*karat\s+gold.{0,100}?₹\s*([\d,]+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = clean_number(match.group(1))
            if valid_gold_rate(value):
                return value

    return None


def fetch_goodreturns():
    try:
        response = SESSION.get(GOODRETURNS_URL, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        rate = extract_goodreturns_22k(soup)
        if rate:
            return {
                "source": "GoodReturns",
                "rate_22k": int(rate),
                "url": GOODRETURNS_URL,
                "fetched_at": now_ist().isoformat(),
            }
    except Exception as exc:
        print(f"GoodReturns failed: {exc}")
    return None


def fetch_all_sources():
    with ThreadPoolExecutor(max_workers=2) as executor:
        live_future = executor.submit(fetch_livechennai)
        good_future = executor.submit(fetch_goodreturns)
        live = live_future.result()
        good = good_future.result()
    return live, good

# ============================================================
# SELECTION & CONSENSUS
# ============================================================

def _rate_is_plausible(rate, previous_rate):
    if not isinstance(previous_rate, (int, float)) or previous_rate <= 0:
        return True
    change_pct = abs(rate - previous_rate) / previous_rate * 100
    return change_pct <= MAX_DAILY_CHANGE_PCT


def select_rate(live, good, previous_rate=None):
    live_rate = live["rate_22k"] if live else None
    good_rate = good["rate_22k"] if good else None

    # Both sources responded
    if live_rate is not None and good_rate is not None:
        if abs(live_rate - good_rate) <= SOURCE_AGREEMENT_TOLERANCE:
            agreed_rate = round((live_rate + good_rate) / 2)
            if not _rate_is_plausible(agreed_rate, previous_rate) and previous_rate is not None:
                return {
                    "rate_22k": previous_rate,
                    "agreement": False,
                    "source": "Previous rate - agreed value implausible",
                    "livechennai": live,
                    "goodreturns": good,
                }
            return {
                "rate_22k": agreed_rate,
                "agreement": True,
                "source": "LiveChennai + GoodReturns" if live_rate == good_rate else "LiveChennai + GoodReturns (tolerance)",
                "livechennai": live,
                "goodreturns": good,
            }

        # Substantial disagreement between available sources
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

    # Only LiveChennai available
    if live_rate is not None and good_rate is None:
        if not _rate_is_plausible(live_rate, previous_rate) and previous_rate is not None:
            return {
                "rate_22k": previous_rate,
                "agreement": None,
                "source": "Previous rate - LiveChennai value implausible",
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

    # Only GoodReturns available
    if live_rate is None and good_rate is not None:
        if not _rate_is_plausible(good_rate, previous_rate) and previous_rate is not None:
            return {
                "rate_22k": previous_rate,
                "agreement": None,
                "source": "Previous rate - GoodReturns value implausible",
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
        for key in ("rate_22k", "gold_22k", "rate", "price_22k"):
            val = data.get(key)
            if isinstance(val, (int, float)) and valid_gold_rate(val):
                return int(val)
    return None

# ============================================================
# DATA PERSISTENCE
# ============================================================

def extract_history_records(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("records", "history", "data", "prices"):
            val = data.get(key)
            if isinstance(val, list):
                return val
    return []


def session_for_time(dt, previous_session=None):
    hour = dt.hour + dt.minute / 60.0
    if 7.5 <= hour <= 13.5:
        return "AM"
    elif 14.5 <= hour <= 21.0:
        return "PM"
    return previous_session


def save_history(rate, selected, changed):
    existing = load_json(HISTORY_FILE, [])
    records = extract_history_records(existing)
    current = now_ist()
    today = current.strftime("%Y-%m-%d")

    record = {
        "date": today,
        "time": current.strftime("%H:%M:%S"),
        "timestamp": current.isoformat(),
        "session": session_for_time(current, None),
        "rate_22k": int(rate),
        "rate_8g": int(rate * 8),
        "changed": bool(changed),
        "source": selected.get("source", "Unknown"),
        "agreement": selected.get("agreement"),
        "livechennai_rate": selected["livechennai"]["rate_22k"] if selected.get("livechennai") else None,
        "goodreturns_rate": selected["goodreturns"]["rate_22k"] if selected.get("goodreturns") else None,
    }

    duplicate = False
    if records:
        last = records[-1]
        if isinstance(last, dict) and last.get("rate_22k") == int(rate) and last.get("date") == today:
            duplicate = True

    if not duplicate:
        records.append(record)

    if isinstance(existing, list) or not isinstance(existing, dict):
        save_json(HISTORY_FILE, records)
    else:
        output = dict(existing)
        output["records"] = records
        save_json(HISTORY_FILE, output)


def save_live(rate, selected, changed):
    current = now_ist()
    previous = load_json(LIVE_FILE, {})
    if not isinstance(previous, dict):
        previous = {}
    output = dict(previous)

    if changed:
        previous_rate = previous.get("rate_22k")
        output.update(
            {
                "rate_22k": int(rate),
                "rate_8g": int(rate * 8),
                "date": current.strftime("%Y-%m-%d"),
                "time": current.strftime("%H:%M:%S"),
                "timestamp": current.isoformat(),
                "session": session_for_time(current, previous.get("session")),
                "previous_rate_22k": previous_rate,
                "change": (
                    int(rate) - int(previous_rate)
                    if isinstance(previous_rate, (int, float))
                    else None
                ),
            }
        )
    else:
        output.setdefault("rate_22k", int(rate))
        output.setdefault("rate_8g", int(rate * 8))

    output.update(
        {
            "changed": bool(changed),
            "source": selected.get("source", "Unknown"),
            "agreement": selected.get("agreement"),
            "sources_agree": selected.get("agreement") is True,
            "sources": {
                "livechennai": selected.get("livechennai"),
                "goodreturns": selected.get("goodreturns"),
            },
            "last_checked": current.isoformat(),
            "last_checked_at": current.isoformat(),
        }
    )

    save_json(LIVE_FILE, output)

# ============================================================
# ALERTING & HEALTH
# ============================================================

def send_alert(title, message):
    webhook = os.environ.get("ALERT_WEBHOOK_URL")
    if not webhook:
        print(f"ALERT (no webhook configured): {title} — {message}")
        return

    body = f"{title}\n{message}"
    try:
        requests.post(webhook, json={"text": body, "content": body}, timeout=10)
        print(f"Alert sent: {title}")
    except Exception as exc:
        print(f"Failed to send alert: {exc}")


def _hours_since(iso_string, now):
    if not iso_string:
        return None
    try:
        then = datetime.fromisoformat(iso_string)
        return (now - then).total_seconds() / 3600
    except Exception:
        return None


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

    # 1. Stale feed check
    if hours_since_checked is not None and hours_since_checked >= ALERT_STALE_HOURS:
        last_alert_hours = _hours_since(state.get("last_stale_alert_at"), now)
        if last_alert_hours is None or last_alert_hours >= ALERT_COOLDOWN_HOURS:
            send_alert(
                "Gold Rate Feed Stale",
                f"No rate update in {hours_since_checked:.1f} hours.",
            )
            state["last_stale_alert_at"] = now.isoformat()
            changed_state = True
    elif state.get("last_stale_alert_at") is not None:
        state["last_stale_alert_at"] = None
        changed_state = True

    # 2. Confirmed disagreement check
    agreement = live.get("agreement")
    if agreement is False:
        if not state.get("disagree_since"):
            state["disagree_since"] = now.isoformat()
            changed_state = True

        disagree_hours = _hours_since(state.get("disagree_since"), now) or 0
        if disagree_hours >= ALERT_DISAGREE_HOURS:
            last_alert_hours = _hours_since(state.get("last_disagree_alert_at"), now)
            if last_alert_hours is None or last_alert_hours >= ALERT_COOLDOWN_HOURS:
                send_alert(
                    "Gold Rate Sources Disagreeing",
                    f"LiveChennai and GoodReturns have disagreed for {disagree_hours:.1f} hours.",
                )
                state["last_disagree_alert_at"] = now.isoformat()
                changed_state = True
    else:
        if state.get("disagree_since") is not None:
            state["disagree_since"] = None
            changed_state = True

    if changed_state:
        save_json(ALERT_FILE, state)

    # Persist health status
    disagree_hours_now = _hours_since(state.get("disagree_since"), now)
    if hours_since_checked is not None and hours_since_checked >= ALERT_STALE_HOURS:
        status = "stale"
    elif disagree_hours_now is not None and disagree_hours_now >= ALERT_DISAGREE_HOURS:
        status = "disagreeing"
    else:
        status = "ok"

    save_json(
        HEALTH_FILE,
        {
            "checked_at": now.isoformat(),
            "status": status,
            "hours_since_last_checked": round(hours_since_checked, 2) if hours_since_checked is not None else None,
            "sources_agree": live.get("agreement") is True,
            "disagree_since": state.get("disagree_since"),
            "webhook_configured": bool(os.environ.get("ALERT_WEBHOOK_URL")),
            "current_rate_22k": live.get("rate_22k"),
            "current_rate_date": live.get("date"),
        },
    )


def compute_and_save_summary():
    existing = load_json(HISTORY_FILE, [])
    records = extract_history_records(existing)

    valid = []
    for r in records:
        if not isinstance(r, dict):
            continue
        rate = r.get("rate_22k")
        date_str = r.get("date")
        if isinstance(rate, (int, float)) and date_str:
            valid.append((date_str, int(rate)))

    if not valid:
        return

    now = now_ist()
    current_month = now.strftime("%Y-%m")
    current_year = now.strftime("%Y")

    all_time_high = max(valid, key=lambda item: item[1])
    all_time_low = min(valid, key=lambda item: item[1])
    month_vals = [v for d, v in valid if d.startswith(current_month)]
    year_vals = [v for d, v in valid if d.startswith(current_year)]
    last_30_vals = [v for _, v in valid[-30:]]

    def bucket(vals):
        if not vals:
            return {"average_22k": None, "high": None, "low": None}
        return {
            "average_22k": round(sum(vals) / len(vals)),
            "high": max(vals),
            "low": min(vals),
        }

    summary = {
        "generated_at": now.isoformat(),
        "all_time_high": {"rate_22k": all_time_high[1], "date": all_time_high[0]},
        "all_time_low": {"rate_22k": all_time_low[1], "date": all_time_low[0]},
        "current_month": {"month": current_month, **bucket(month_vals)},
        "current_year": {"year": current_year, **bucket(year_vals)},
        "last_30_records": bucket(last_30_vals),
        "total_records": len(valid),
    }

    save_json(SUMMARY_FILE, summary)

# ============================================================
# PREDICTIVE MONITORING WINDOWS
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
    lo_minutes = lo[0] * 60 + lo[1]
    hi_minutes = hi[0] * 60 + hi[1]
    clamped = max(lo_minutes, min(hi_minutes, minutes))
    return (clamped // 60, clamped % 60)


def predict_session_times(now=None):
    now = now or now_ist()
    cutoff_date = (now - timedelta(days=HISTORY_LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    records = extract_history_records(load_json(HISTORY_FILE, []))
    am_minutes, pm_minutes = [], []

    for r in records:
        if not isinstance(r, dict):
            continue
        if (r.get("date") or "") < cutoff_date:
            continue
        mins = _parse_time_to_minutes(r.get("time"))
        if mins is None:
            continue
        if r.get("session") == "AM":
            am_minutes.append(mins)
        elif r.get("session") == "PM":
            pm_minutes.append(mins)

    # Bootstrap with seed file when history samples are sparse
    if len(am_minutes) < MIN_SAMPLES_FOR_PREDICTION or len(pm_minutes) < MIN_SAMPLES_FOR_PREDICTION:
        seed_records = load_json(SEED_FILE, [])
        for r in seed_records:
            if not isinstance(r, dict):
                continue
            mins = _parse_time_to_minutes(r.get("time"))
            if mins is None:
                continue
            if r.get("session") == "AM" and len(am_minutes) < MIN_SAMPLES_FOR_PREDICTION:
                am_minutes.append(mins)
            elif r.get("session") == "PM" and len(pm_minutes) < MIN_SAMPLES_FOR_PREDICTION:
                pm_minutes.append(mins)

    result = {}
    if len(am_minutes) >= MIN_SAMPLES_FOR_PREDICTION:
        med = _median(am_minutes)
        raw = (int(med // 60), int(med % 60))
        result["AM"] = _clamp_hm(raw, AM_PREDICTION_MIN, AM_PREDICTION_MAX)
    else:
        result["AM"] = FALLBACK_AM_TIME

    if len(pm_minutes) >= MIN_SAMPLES_FOR_PREDICTION:
        med = _median(pm_minutes)
        raw = (int(med // 60), int(med % 60))
        result["PM"] = _clamp_hm(raw, PM_PREDICTION_MIN, PM_PREDICTION_MAX)
    else:
        result["PM"] = FALLBACK_PM_TIME

    return result


def make_datetime(day, hour, minute):
    return datetime(day.year, day.month, day.day, hour, minute, 0, tzinfo=IST)


def _session_bounds(day, predicted_hm):
    predicted_dt = make_datetime(day, predicted_hm[0], predicted_hm[1])
    start = predicted_dt - timedelta(minutes=PRE_WINDOW_MINUTES)
    end = start + timedelta(minutes=WINDOW_DURATION_MINUTES)
    return start, end


def current_window(now=None):
    if now is None:
        now = now_ist()
    today = now.date()
    predicted = predict_session_times(now)

    am_start, am_end = _session_bounds(today, predicted["AM"])
    pm_start, pm_end = _session_bounds(today, predicted["PM"])

    if am_start <= now < am_end:
        return {"name": "AM", "start": am_start, "end": am_end}
    if pm_start <= now < pm_end:
        return {"name": "PM", "start": pm_start, "end": pm_end}
    return None


def next_window(now=None):
    if now is None:
        now = now_ist()
    today = now.date()
    predicted = predict_session_times(now)

    am_start, am_end = _session_bounds(today, predicted["AM"])
    pm_start, pm_end = _session_bounds(today, predicted["PM"])

    if now < am_start:
        return {"name": "AM", "start": am_start, "end": am_end}
    if now < pm_start:
        return {"name": "PM", "start": pm_start, "end": pm_end}

    tomorrow = today + timedelta(days=1)
    predicted_tomorrow = predict_session_times(make_datetime(tomorrow, 0, 0))
    am_start_tomorrow, am_end_tomorrow = _session_bounds(tomorrow, predicted_tomorrow["AM"])
    return {"name": "AM", "start": am_start_tomorrow, "end": am_end_tomorrow}


def save_window_info(window):
    predicted = predict_session_times(now_ist())
    data = {
        "timezone": "Asia/Kolkata",
        "updated_at": now_ist().isoformat(),
        "prediction_basis": f"median of last {HISTORY_LOOKBACK_DAYS} days",
        "windows": {
            "AM": {
                "predicted_fix_time": f"{predicted['AM'][0]:02d}:{predicted['AM'][1]:02d}",
                "polling_starts": f"{PRE_WINDOW_MINUTES} min before predicted time",
                "polling_duration_minutes": WINDOW_DURATION_MINUTES,
            },
            "PM": {
                "predicted_fix_time": f"{predicted['PM'][0]:02d}:{predicted['PM'][1]:02d}",
                "polling_starts": f"{PRE_WINDOW_MINUTES} min before predicted time",
                "polling_duration_minutes": WINDOW_DURATION_MINUTES,
            },
        },
        "active_window": window["name"] if window else None,
        "poll_seconds": POLL_SECONDS,
    }
    save_json(WINDOW_FILE, data)

# ============================================================
# EXECUTION MODES
# ============================================================

def normal_fetch():
    previous_rate = get_previous_rate()
    live, good = fetch_all_sources()
    selected = select_rate(live, good, previous_rate)

    if selected is None:
        return False

    rate = selected["rate_22k"]
    changed = previous_rate is not None and rate != previous_rate

    save_live(rate, selected, changed)
    save_history(rate, selected, changed)
    return True


def monitor_window(window):
    previous_rate = get_previous_rate()

    while True:
        now = now_ist()
        if now >= window["end"]:
            save_window_info(None)
            return False

        live, good = fetch_all_sources()
        selected = select_rate(live, good, previous_rate)

        if selected is None:
            time.sleep(POLL_SECONDS)
            continue

        current_rate = selected["rate_22k"]

        if previous_rate is not None and current_rate != previous_rate:
            save_live(current_rate, selected, True)
            save_history(current_rate, selected, True)
            save_window_info(None)
            return True

        save_live(current_rate, selected, False)

        remaining = (window["end"] - now_ist()).total_seconds()
        if remaining <= 0:
            save_window_info(None)
            return False

        time.sleep(min(POLL_SECONDS, max(1, int(remaining))))


def main():
    now = now_ist()
    github_actions = os.environ.get("GITHUB_ACTIONS", "").lower() == "true"
    github_event = os.environ.get("GITHUB_EVENT_NAME", "")
    force_fetch = os.environ.get("FORCE_FETCH", "").lower() == "true"

    if force_fetch:
        save_window_info(None)
        success = normal_fetch()
        if not success:
            sys.exit(1)
        return

    window = current_window(now)
    if window:
        save_window_info(window)
        monitor_window(window)
        return
    else:
        save_window_info(None)

    if github_actions and github_event == "schedule":
        upcoming = next_window(now)
        wait_seconds = (upcoming["start"] - now).total_seconds()
        MAX_SCHEDULE_WAIT_MINUTES = 45

        if wait_seconds > MAX_SCHEDULE_WAIT_MINUTES * 60:
            save_window_info(None)
            success = normal_fetch()
            if not success:
                sys.exit(1)
            return

        while True:
            now = now_ist()
            window = current_window(now)
            if window:
                save_window_info(window)
                monitor_window(window)
                return
            time.sleep(30)

    save_window_info(None)
    success = normal_fetch()
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
    except Exception as exc:
        print(f"FATAL ERROR: {exc}")
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
