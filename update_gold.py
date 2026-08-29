#!/usr/bin/env python3
"""
Chennai 22K Gold updater
- LiveChennai source
- Adaptive monitoring based on intraday change observations
- Last 30 days are weighted most heavily
- Last 90 days are inspected first; daily history is never treated as an
  intraday observation unless it contains a real clock time
- 10-second polling, maximum 400 attempts during an active window
- Every request has a hard timeout
- Writes data/live.json, data/history.json and data/change_log.json
"""

from __future__ import annotations

import json
import re
import statistics
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

IST = ZoneInfo("Asia/Kolkata")
ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

LIVE_FILE = DATA / "live.json"
HISTORY_FILE = DATA / "history.json"
CHANGE_LOG_FILE = DATA / "change_log.json"
SEED_FILE = DATA / "historical_monitor_seed.json"

SOURCE_URL = "https://www.livechennai.com/gold_silverrate.asp"
GOODRETURNS_URL = "https://www.goodreturns.in/gold-rates/chennai.html"
REQUEST_TIMEOUT = 15
POLL_SECONDS = 10
MAX_ATTEMPTS = 400  # safety cap; monitoring also stops at the learned window end

# Adaptive monitor parameters.
LEARNING_DAYS = 90
PRIORITY_DAYS = 30
MIN_OBSERVATIONS = 3
WINDOW_HALF_WIDTH_MIN = 45
MIN_WINDOW_WIDTH_MIN = 30
MAX_WINDOW_WIDTH_MIN = 180

# Safe bootstrap windows. They are only used until enough real observations
# have been collected; they are NOT claimed to be learned times.
FALLBACK_WINDOWS = {
    "AM": (8 * 60 + 30, 11 * 60 + 30),
    "PM": (17 * 60, 20 * 60),
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; Chennai22KGoldBot/2.0)",
    "Accept-Language": "en-IN,en;q=0.9",
}


def now_ist() -> datetime:
    return datetime.now(IST)


def session_for_minutes(minutes: int) -> str:
    return "AM" if minutes < 12 * 60 else "PM"


def minutes_from_time(value: str | None) -> int | None:
    if not value:
        return None
    m = re.match(r"^\s*(\d{1,2}):(\d{2})(?::\d{2})?\s*$", str(value))
    if not m:
        return None
    h, minute = int(m.group(1)), int(m.group(2))
    if h > 23 or minute > 59:
        return None
    return h * 60 + minute


def fmt_minutes(minutes: int) -> str:
    minutes %= 24 * 60
    h, m = divmod(minutes, 60)
    suffix = "AM" if h < 12 else "PM"
    hh = h % 12 or 12
    return f"{hh}:{m:02d} {suffix}"


def load_json(path: Path, default):
    try:
        if not path.exists():
            return default
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        print(f"WARNING: cannot read {path}: {exc}")
        return default


def save_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(path)


def fetch_page(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.text


def extract_22k_rate_livechennai(html: str) -> int:
    soup = BeautifulSoup(html, "html.parser")

    for row in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in row.find_all(["th", "td"])]
        joined = " ".join(cells)
        if re.search(r"\b22\s*K\b", joined, re.I):
            nums = re.findall(r"(?:₹|Rs\.?|INR)?\s*([0-9][0-9,]{3,})", joined, re.I)
            for raw in nums:
                value = int(raw.replace(",", ""))
                if 5000 <= value <= 30000:
                    return value

    page_text = soup.get_text(" ", strip=True)
    patterns = [
        r"22\s*K.{0,160}?(?:₹|Rs\.?|INR)?\s*([0-9][0-9,]{3,})",
        r"(?:₹|Rs\.?|INR)?\s*([0-9][0-9,]{3,}).{0,160}?22\s*K",
    ]
    for pattern in patterns:
        m = re.search(pattern, page_text, re.I)
        if m:
            value = int(m.group(1).replace(",", ""))
            if 5000 <= value <= 30000:
                return value

    raise RuntimeError("Could not locate a valid Chennai 22K rate on LiveChennai")


def extract_22k_rate_goodreturns(html: str) -> int:
    soup = BeautifulSoup(html, "html.parser")

    # GoodReturns currently publishes a Chennai table with 24K/22K/18K
    # and a separate summary such as "22K Gold /g ₹14,505".
    for row in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in row.find_all(["th", "td"])]
        joined = " ".join(cells)
        if re.search(r"22K\s*(?:Gold)?\s*/?\s*g|22\s*K\s*(?:Gold)?\s*/?\s*g", joined, re.I):
            nums = re.findall(r"(?:₹|Rs\.?|INR)?\s*([0-9][0-9,]{3,})", joined, re.I)
            for raw in nums:
                value = int(raw.replace(",", ""))
                if 5000 <= value <= 30000:
                    return value

    page_text = soup.get_text(" ", strip=True)

    # Strong patterns for the current GoodReturns Chennai page.
    patterns = [
        r"22K\s*(?:Gold)?\s*/\s*g\s*(?:₹|Rs\.?|INR)?\s*([0-9][0-9,]{3,})",
        r"22K\s*(?:Gold)?\s*per\s*gram\s*(?:₹|Rs\.?|INR)?\s*([0-9][0-9,]{3,})",
        r"22K\s+Gold.{0,80}?(?:₹|Rs\.?|INR)\s*([0-9][0-9,]{3,})",
        r"22K\s+gold.{0,120}?(?:₹|Rs\.?|INR)\s*([0-9][0-9,]{3,})",
    ]

    for pattern in patterns:
        m = re.search(pattern, page_text, re.I)
        if m:
            value = int(m.group(1).replace(",", ""))
            if 5000 <= value <= 30000:
                return value

    # Table text fallback: locate "22K Gold /g" then nearby number.
    for marker in re.finditer(r"22K\s*(?:Gold)?", page_text, re.I):
        snippet = page_text[marker.start():marker.start() + 250]
        nums = re.findall(r"(?:₹|Rs\.?|INR)?\s*([0-9][0-9,]{3,})", snippet, re.I)
        for raw in nums:
            value = int(raw.replace(",", ""))
            if 5000 <= value <= 30000:
                return value

    raise RuntimeError("Could not locate a valid Chennai 22K rate on GoodReturns")


def fetch_source(source_name: str):
    if source_name == "LiveChennai":
        html = fetch_page(SOURCE_URL)
        return extract_22k_rate_livechennai(html), SOURCE_URL
    if source_name == "GoodReturns":
        html = fetch_page(GOODRETURNS_URL)
        return extract_22k_rate_goodreturns(html), GOODRETURNS_URL
    raise ValueError(f"Unknown source: {source_name}")


def fetch_all_sources():
    results = {}
    errors = {}

    for source_name in ("LiveChennai", "GoodReturns"):
        try:
            rate, url = fetch_source(source_name)
            results[source_name] = {"rate": rate, "url": url}
            print(f"{source_name}: ₹{rate:,}/gram")
        except Exception as exc:
            errors[source_name] = str(exc)
            print(f"{source_name}: FETCH ERROR: {exc}")

    return results, errors


def choose_verified_rate(results, previous_rate=None):
    """
    Verification policy:
      - both sources available and equal: high-confidence confirmed
      - only one source available: usable, but marked single-source
      - both available and disagree: do not accept a new rate
      - if disagreement equals previous verified rate, keep previous
    """
    live = results.get("LiveChennai", {}).get("rate")
    good = results.get("GoodReturns", {}).get("rate")

    if live is not None and good is not None:
        if live == good:
            return {
                "rate": live,
                "verified": True,
                "verification": "both_sources_agree",
                "source": "LiveChennai + GoodReturns",
            }
        return {
            "rate": None,
            "verified": False,
            "verification": "source_disagreement",
            "source": "LiveChennai + GoodReturns",
            "livechennai_rate": live,
            "goodreturns_rate": good,
        }

    if live is not None:
        return {
            "rate": live,
            "verified": False,
            "verification": "livechennai_only",
            "source": "LiveChennai",
        }

    if good is not None:
        return {
            "rate": good,
            "verified": False,
            "verification": "goodreturns_only",
            "source": "GoodReturns",
        }

    return {
        "rate": previous_rate,
        "verified": False,
        "verification": "no_source_available",
        "source": "previous_verified_rate",
    }


def fetch_verified_rate(previous_rate=None, require_change=False):
    results, errors = fetch_all_sources()
    chosen = choose_verified_rate(results, previous_rate)

    if chosen["rate"] is None:
        raise RuntimeError("Neither LiveChennai nor GoodReturns returned a usable 22K rate")

    if chosen["verification"] == "source_disagreement":
        raise RuntimeError(
            f"Source disagreement: LiveChennai={chosen['livechennai_rate']}, "
            f"GoodReturns={chosen['goodreturns_rate']}"
        )

    chosen["errors"] = errors
    return chosen


def fetch_rate() -> int:
    """
    Compatibility helper used by older callers.
    Prefer fetch_verified_rate() in monitoring.
    """
    result = fetch_verified_rate()
    return int(result["rate"])

def normalise_events(raw):
    if isinstance(raw, dict):
        for key in ("events", "changes", "records", "observations", "data"):
            if isinstance(raw.get(key), list):
                raw = raw[key]
                break
        else:
            raw = []
    if not isinstance(raw, list):
        return []

    out = []
    seen = set()

    for x in raw:
        if not isinstance(x, dict):
            continue

        date = str(x.get("date") or "")[:10]
        tm = str(x.get("time") or "")
        rate = x.get("rate_22k", x.get("rate", x.get("new_rate")))
        try:
            rate = int(float(rate))
        except Exception:
            continue

        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            continue
        mins = minutes_from_time(tm)
        if mins is None:
            continue
        if not (5000 <= rate <= 30000):
            continue

        key = (date, tm, rate)
        if key in seen:
            continue
        seen.add(key)

        out.append({
            "date": date,
            "time": tm if len(tm) >= 5 else f"{tm}:00",
            "rate_22k": rate,
            "session": x.get("session") or session_for_minutes(mins),
            "type": x.get("type") or "live_change",
        })

    return out


def history_time_events(history):
    """
    Accept historical records only when they contain a real clock time.
    This prevents a daily record with an invented/default time from becoming
    a false intraday observation.
    """
    if not isinstance(history, list):
        return []

    out = []
    for x in history:
        if not isinstance(x, dict):
            continue
        tm = str(x.get("time") or "")
        mins = minutes_from_time(tm)
        if mins is None:
            continue
        if tm in {"00:00", "00:00:00", "12:00", "12:00:00"}:
            # Common placeholder times are not evidence of a change time.
            continue
        rate = x.get("rate_22k", x.get("rate"))
        try:
            rate = int(float(rate))
        except Exception:
            continue
        out.append({
            "date": str(x.get("date") or "")[:10],
            "time": tm,
            "rate_22k": rate,
            "session": session_for_minutes(mins),
            "type": "historical_timed_observation",
        })
    return out


def load_observations():
    cutoff = now_ist().date() - timedelta(days=LEARNING_DAYS)
    cutoff30 = now_ist().date() - timedelta(days=PRIORITY_DAYS)

    events = normalise_events(load_json(CHANGE_LOG_FILE, []))

    # Seed the learner with externally verified Chennai intraday update times.
    # These are source-published gold-rate update timestamps, not fabricated
    # observations. They bootstrap the monitor until GitHub collects its own
    # change events; GitHub-collected events are weighted more naturally as
    # they accumulate in change_log.json/live.json.
    seed = load_json(SEED_FILE, [])
    if isinstance(seed, list):
        events += normalise_events(seed)

    live = load_json(LIVE_FILE, {})
    events += normalise_events(live.get("intraday", []))
    events += history_time_events(load_json(HISTORY_FILE, []))

    # Only real observations in the last 90 days.
    cleaned = []
    seen = set()
    for e in events:
        try:
            d = datetime.strptime(e["date"], "%Y-%m-%d").date()
        except Exception:
            continue
        if d < cutoff:
            continue
        key = (e["date"], e["time"], e["rate_22k"])
        if key not in seen:
            seen.add(key)
            e["priority"] = "30d" if d >= cutoff30 else "90d"
            cleaned.append(e)

    cleaned.sort(key=lambda e: (e["date"], e["time"]))
    return cleaned


def adaptive_window(observations, session: str):
    """
    Derive a window from actual observed change times.
    The last 30 days receive 3x weight. Recent observations also get a
    modest recency multiplier. The weighted median is used instead of the
    mean so one unusual day cannot move the window excessively.
    """
    candidates = []
    today = now_ist().date()

    for e in observations:
        if e.get("session") != session:
            continue
        mins = minutes_from_time(e.get("time"))
        if mins is None:
            continue

        try:
            d = datetime.strptime(e["date"], "%Y-%m-%d").date()
        except Exception:
            continue

        age = max(0, (today - d).days)
        base = 3.0 if age <= PRIORITY_DAYS else 1.0
        recency = max(0.25, 1.0 - age / (LEARNING_DAYS * 1.4))
        weight = base * recency
        candidates.append((mins, weight))

    if len(candidates) < MIN_OBSERVATIONS:
        return {
            "start": FALLBACK_WINDOWS[session][0],
            "end": FALLBACK_WINDOWS[session][1],
            "learned": False,
            "observations": len(candidates),
            "reason": "insufficient observations",
        }

    candidates.sort()
    total = sum(w for _, w in candidates)
    acc = 0.0
    median = candidates[-1][0]
    for mins, weight in candidates:
        acc += weight
        if acc >= total / 2:
            median = mins
            break

    # Use weighted absolute deviations to estimate spread.
    deviations = sorted((abs(mins - median), weight) for mins, weight in candidates)
    total_w = sum(w for _, w in deviations)
    acc = 0.0
    mad = 30.0
    for deviation, weight in deviations:
        acc += weight
        if acc >= total_w / 2:
            mad = float(deviation)
            break

    half = max(WINDOW_HALF_WIDTH_MIN, int(mad * 2.5))
    half = min(half, MAX_WINDOW_WIDTH_MIN // 2)
    half = max(half, MIN_WINDOW_WIDTH_MIN // 2)

    start = max(0, median - half)
    end = min(24 * 60 - 1, median + half)

    # Keep AM and PM windows inside their natural halves of the day.
    if session == "AM":
        start = max(5 * 60, start)
        end = min(13 * 60, end)
    else:
        start = max(14 * 60, start)
        end = min(23 * 60, end)

    return {
        "start": int(start),
        "end": int(end),
        "learned": True,
        "observations": len(candidates),
        "median": int(median),
        "mad": round(mad, 1),
        "reason": "weighted 30d/90d observations",
    }


def build_windows(observations):
    return {
        "AM": adaptive_window(observations, "AM"),
        "PM": adaptive_window(observations, "PM"),
    }


def in_window(current: datetime, window) -> bool:
    mins = current.hour * 60 + current.minute
    return window["start"] <= mins <= window["end"]


def append_change_event(event):
    current = load_json(CHANGE_LOG_FILE, [])
    if isinstance(current, dict):
        events = current.get("events")
        if not isinstance(events, list):
            events = []
        events.append(event)
        current = {"events": events}
    elif isinstance(current, list):
        current.append(event)
    else:
        current = [event]

    # Keep a generous rolling archive. This is tiny compared with GitHub limits.
    events = current.get("events") if isinstance(current, dict) else current
    events = normalise_events(events)
    events = events[-1000:]
    save_json(CHANGE_LOG_FILE, events)


def session_name(dt: datetime) -> str:
    return "AM" if dt.hour < 12 else "PM"


def write_live(
    rate: int,
    previous: dict | None,
    changed: bool,
    source_update=None,
    verification: dict | None = None,
):
    dt = now_ist()
    prev_rate = previous.get("rate_22k") if isinstance(previous, dict) else None
    delta = rate - prev_rate if isinstance(prev_rate, (int, float)) else 0

    event = None
    if changed and prev_rate is not None:
        event = {
            "date": dt.date().isoformat(),
            "time": dt.strftime("%H:%M:%S"),
            "rate_22k": rate,
            "rate_8g": rate * 8,
            "previous_rate_22k": prev_rate,
            "change": delta,
            "session": session_name(dt),
            "type": "live_change",
            "source": (verification or {}).get("source", "unknown"),
            "verification": (verification or {}).get("verification", "unknown"),
        }

    verification = verification or {}

    live = {
        "rate_22k": rate,
        "rate_8g": rate * 8,
        "rate_24k": None,
        "rate_18k": None,
        "updated_at": dt.isoformat(),
        "date": dt.date().isoformat(),
        "time": dt.strftime("%H:%M:%S"),
        "session": session_name(dt),
        "source": verification.get("source", "previous_verified_rate"),
        "source_url": (
            GOODRETURNS_URL
            if verification.get("source") == "GoodReturns"
            else SOURCE_URL
        ),
        "source_last_update": source_update,
        "verified": bool(verification.get("verified", False)),
        "verification": verification.get("verification", "unknown"),
        "source_rates": {
            "LiveChennai": verification.get("livechennai_rate"),
            "GoodReturns": verification.get("goodreturns_rate"),
        },
        "changed": bool(changed),
        "previous_rate_22k": prev_rate,
        "change": delta,
        "last_change": event if event else (
            previous.get("last_change") if isinstance(previous, dict) else None
        ),
        "intraday": [event] if event else (
            previous.get("intraday", []) if isinstance(previous, dict) else []
        ),
    }
    save_json(LIVE_FILE, live)
    return live, event


def update_history(live):
    history = load_json(HISTORY_FILE, [])
    if not isinstance(history, list):
        history = []

    date = live["date"]
    # One daily row per date; update today's row with the newest known rate.
    row = {
        "date": date,
        "rate_22k": live["rate_22k"],
        "rate_8g": live["rate_8g"],
        "source": "LiveChennai",
        "updated_at": live["updated_at"],
    }

    replaced = False
    for i, item in enumerate(history):
        if isinstance(item, dict) and item.get("date") == date:
            history[i] = {**item, **row}
            replaced = True
            break

    if not replaced:
        history.append(row)

    history.sort(key=lambda x: str(x.get("date", "")))
    save_json(HISTORY_FILE, history)


def one_fetch(previous_rate: int | None):
    rate = fetch_rate()
    return rate


def monitor(window, initial_rate: int):
    """
    Poll every 10 seconds for the ENTIRE learned monitoring window.
    Stops only when:
      1) a new rate is detected and validated, or
      2) the window ends, or
      3) MAX_ATTEMPTS is reached as an emergency safety cap.
    """
    start_min = window["start"]
    end_min = window["end"]
    now = now_ist()
    current_min = now.hour * 60 + now.minute

    print(
        f"Monitoring window: {fmt_minutes(start_min)} - "
        f"{fmt_minutes(end_min)}"
    )
    print(
        f"Polling every {POLL_SECONDS}s for the entire window "
        f"(safety cap {MAX_ATTEMPTS} attempts)"
    )

    # If the job starts before the learned window, wait until it begins.
    if current_min < start_min:
        wait_seconds = (start_min - current_min) * 60 - now.second
        wait_seconds = max(0, wait_seconds)
        if wait_seconds:
            print(
                f"Before monitoring window. Waiting approximately "
                f"{wait_seconds}s until {fmt_minutes(start_min)}."
            )
            time.sleep(wait_seconds)

    last_seen = initial_rate
    attempt = 0

    while attempt < MAX_ATTEMPTS:
        current = now_ist()
        current_min = current.hour * 60 + current.minute

        # Handles normal same-day window. If window crosses midnight, support it.
        if current_min > end_min:
            print("Monitoring window ended.")
            break

        attempt += 1

        try:
            result = fetch_verified_rate(previous_rate=last_seen)
            rate = int(result["rate"])

            print(
                f"Attempt {attempt}/{MAX_ATTEMPTS}: "
                f"verified_rate=₹{rate:,} "
                f"verification={result['verification']}"
            )

            # A source disagreement is deliberately not treated as a new price.
            if result["verification"] == "source_disagreement":
                print("Sources disagree. Retrying in 10 seconds.")
            elif rate != initial_rate:
                # A changed value from one usable source is recorded, but the
                # second source disagreement is never blindly accepted.
                print(
                    f"RATE CHANGE DETECTED: "
                    f"₹{initial_rate:,} -> ₹{rate:,}"
                )
                return rate, attempt, result
            else:
                last_seen = rate

        except Exception as exc:
            print(
                f"Attempt {attempt}/{MAX_ATTEMPTS}: "
                f"fetch/verification error: {exc}"
            )

        # Sleep exactly 10 seconds, but never beyond the monitoring window.
        now = now_ist()
        current_min = now.hour * 60 + now.minute
        if current_min >= end_min:
            break

        time.sleep(POLL_SECONDS)

    print("Monitoring window ended without a detected new rate.")
    return initial_rate, attempt, {
        "rate": initial_rate,
        "verified": True,
        "verification": "previous_verified_rate",
        "source": "previous_verified_rate",
    }


def main():
    print("=" * 70)
    print("CHENNAI 22K GOLD RATE — ADAPTIVE DUAL-SOURCE MONITOR")
    print("=" * 70)

    DATA.mkdir(parents=True, exist_ok=True)

    previous = load_json(LIVE_FILE, {})
    history = load_json(HISTORY_FILE, [])

    print(
        f"Historical database contains "
        f"{len(history) if isinstance(history, list) else 0} daily records."
    )

    observations = load_observations()
    windows = build_windows(observations)

    print(f"3-month observations: {len(observations)}")
    print(
        f"30-day observations: "
        f"{sum(1 for x in observations if x.get('priority') == '30d')}"
    )

    for s in ("AM", "PM"):
        w = windows[s]
        print(
            f"{s} window: {fmt_minutes(w['start'])} - "
            f"{fmt_minutes(w['end'])} "
            f"({'LEARNED' if w['learned'] else 'FALLBACK'}; "
            f"{w['observations']} obs)"
        )

    previous_rate = previous.get("rate_22k")
    print()
    print("Fetching current Chennai 22K rate from both sources...")

    try:
        initial_result = fetch_verified_rate(previous_rate=previous_rate)
        initial_rate = int(initial_result["rate"])

        print(f"Selected initial rate: ₹{initial_rate:,}/gram")
        print(f"Selected initial 8g: ₹{initial_rate * 8:,}")
        print(
            f"Verification: {initial_result.get('verification')}; "
            f"source: {initial_result.get('source')}"
        )

    except Exception as exc:
        print(f"ERROR: live fetch failed: {exc}")
        if previous_rate:
            print(
                f"Keeping previous successful rate: "
                f"₹{int(previous_rate):,}/gram"
            )
            return
        raise

    current = now_ist()
    current_session = session_name(current)
    window = windows.get(current_session)

    # If the job starts before the window, wait until it begins.
    # If already inside, monitor immediately.
    current_min = current.hour * 60 + current.minute
    should_monitor = False

    if window:
        if current_min < window["start"]:
            should_monitor = True
        elif window["start"] <= current_min <= window["end"]:
            should_monitor = True

    if should_monitor:
        print("Monitoring is active for the full learned window.")
        final_rate, attempts, final_verification = monitor(
            window,
            initial_rate,
        )
    else:
        print("Outside adaptive monitoring window; no monitoring loop started.")
        final_rate = initial_rate
        attempts = 1
        final_verification = initial_result

    prev_rate = previous.get("rate_22k")
    changed = prev_rate is not None and int(final_rate) != int(prev_rate)

    live, event = write_live(
        int(final_rate),
        previous,
        changed,
        source_update=previous.get("source_last_update"),
        verification=final_verification,
    )

    if event:
        append_change_event(event)
        print(
            f"Recorded intraday change at "
            f"{event['date']} {event['time']} "
            f"({event['session']})."
        )

    update_history(live)

    print("=" * 70)
    print("UPDATE COMPLETE")
    print("=" * 70)
    print(f"22K / gram : ₹{final_rate:,}")
    print(f"22K / 8g   : ₹{final_rate * 8:,}")
    print(f"Date       : {live['date']}")
    print(f"Time       : {live['time']}")
    print(f"Changed    : {changed}")
    print(f"Source     : {live['source']}")
    print(f"Verification: {live['verification']}")
    print(f"Attempts   : {attempts}")
    print(f"Timed observations now: {len(load_observations())}")
    print(
        f"Current windows: AM "
        f"{fmt_minutes(windows['AM']['start'])} - "
        f"{fmt_minutes(windows['AM']['end'])}; PM "
        f"{fmt_minutes(windows['PM']['start'])} - "
        f"{fmt_minutes(windows['PM']['end'])}"
    )


if __name__ == "__main__":
    main()
