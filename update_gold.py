import json
import re
import time
from datetime import datetime, date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

CURRENT_URL = "https://www.livechennai.com/gold_silverrate.asp"
HISTORY_URL = "https://www.livechennai.com/get_goldrate_history.asp"

DATA_DIR = Path("data")
LIVE_FILE = DATA_DIR / "live.json"
HISTORY_FILE = DATA_DIR / "history.json"
CHANGE_LOG_FILE = DATA_DIR / "change_log.json"

IST = ZoneInfo("Asia/Kolkata")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    )
}

MIN_RATE = 5000
MAX_RATE = 30000

# The workflow starts this script during a monitoring window.
# The script polls every 10 seconds for up to this many minutes.
POLL_SECONDS = 10
POLL_MAX_MINUTES = 70

# Once enough observations exist, the script learns the most common
# source-update hour/minute separately for AM and PM.
LEARNING_OBSERVATIONS = 100
LEARN_TOP_MINUTES = 15


def get_html(url, params=None):
    response = requests.get(
        url,
        params=params,
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()
    return response.text


def clean_number(value):
    if value is None:
        return None
    text = str(value)
    text = (
        text.replace(",", "")
        .replace("₹", "")
        .replace("Rs.", "")
        .replace("Rs", "")
        .strip()
    )
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def plausible_rate(value):
    number = clean_number(value)
    if number is None:
        return None
    if MIN_RATE <= number <= MAX_RATE:
        return int(round(number))
    return None


def parse_date(text):
    if not text:
        return None
    text = " ".join(str(text).split())

    formats = [
        "%d/%B/%Y", "%d/%b/%Y", "%d/%m/%Y", "%d/%m/%y",
        "%d-%m-%Y", "%d-%m-%y", "%Y-%m-%d",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass

    match = re.search(
        r"(\d{1,2})[/-]([A-Za-z]+|\d{1,2})[/-](\d{4})",
        text,
        re.IGNORECASE,
    )
    if match:
        day, month, year = match.groups()
        if month.isdigit():
            try:
                return date(int(year), int(month), int(day))
            except ValueError:
                return None

        for fmt in ("%d/%B/%Y", "%d/%b/%Y"):
            try:
                return datetime.strptime(
                    f"{day}/{month}/{year}", fmt
                ).date()
            except ValueError:
                pass

    return None


def parse_current_rate(html):
    soup = BeautifulSoup(html, "html.parser")
    rate = None
    source_last_update = None

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all(["th", "td"])
            values = [" ".join(c.stripped_strings) for c in cells]
            if not values:
                continue

            joined = " ".join(values).lower()
            if "22" in joined and ("gm" in joined or "gram" in joined):
                for value in values:
                    candidate = plausible_rate(value)
                    if candidate is not None:
                        rate = candidate
                        break
            if rate is not None:
                break
        if rate is not None:
            break

    text = soup.get_text(" ", strip=True)

    if rate is None:
        patterns = [
            r"1\s*Gm\s*\(22\s*K\)\s*[:|]?\s*₹?\s*([\d,]+)",
            r"22\s*K\s*(?:Gold)?\s*(?:1\s*Gram|per\s*gram)\s*[:|]?\s*₹?\s*([\d,]+)",
            r"22\s*K\s*/\s*gram\s*[:|]?\s*₹?\s*([\d,]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                candidate = plausible_rate(match.group(1))
                if candidate is not None:
                    rate = candidate
                    break

    # LiveChennai's own source timestamp.
    time_patterns = [
        r"Last\s*Update\s*Time\s*:\s*"
        r"(\d{1,2}/\d{1,2}/\d{4})\s*"
        r"(\d{1,2}:\d{2}(?::\d{2})?)\s*(AM|PM)?",
        r"Update\s*Time\s*:\s*"
        r"(\d{1,2}/\d{1,2}/\d{4})\s*"
        r"(\d{1,2}:\d{2}(?::\d{2})?)\s*(AM|PM)?",
    ]

    for pattern in time_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            source_last_update = (
                f"{match.group(1)} {match.group(2)}"
                + (f" {match.group(3).upper()}" if match.group(3) else "")
            )
            break

    if rate is None:
        match = re.search(
            r"\d{1,2}/[A-Za-z]{3,9}/\d{4}.{0,100}?([\d,]{4,6})",
            text,
            re.IGNORECASE,
        )
        if match:
            rate = plausible_rate(match.group(1))

    if rate is None:
        raise RuntimeError("Could not find current Chennai 22K rate")

    return rate, source_last_update


def source_time_parts(source_time):
    if not source_time:
        return None

    match = re.search(
        r"(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM)?",
        source_time,
        re.IGNORECASE,
    )
    if not match:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2))
    second = int(match.group(3) or 0)
    ampm = (match.group(4) or "").upper()

    if ampm:
        if ampm == "AM" and hour == 12:
            hour = 0
        elif ampm == "PM" and hour != 12:
            hour += 12

    return hour, minute, second


def session_for_source_time(source_time, now=None):
    parts = source_time_parts(source_time)
    if parts:
        return "AM" if parts[0] < 13 else "PM"

    now = now or datetime.now(IST)
    return "AM" if now.hour < 13 else "PM"


def load_json(path, default):
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    temporary.replace(path)


def fetch_history_month(year, month):
    print(f"Fetching historical data: {year}-{month:02d}")
    html = get_html(
        HISTORY_URL,
        params={"monthno": month, "yearno": year},
    )
    soup = BeautifulSoup(html, "html.parser")
    records = []

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue

        header_index = None
        for i, row in enumerate(rows[:5]):
            values = [
                " ".join(cell.stripped_strings)
                for cell in row.find_all(["th", "td"])
            ]
            joined = " ".join(values).lower()
            if "date" in joined and "22" in joined:
                header_index = i
                break

        if header_index is None:
            continue

        for row in rows[header_index + 1:]:
            cells = row.find_all(["td", "th"])
            values = [" ".join(c.stripped_strings) for c in cells]
            if len(values) < 3:
                continue

            d = parse_date(values[0])
            if d is None:
                continue

            rate_22k = plausible_rate(values[2])
            if rate_22k is None:
                continue

            records.append({
                "date": d.isoformat(),
                "rate_22k": rate_22k,
                "rate_24k": plausible_rate(values[1]),
                "weight_1g": rate_22k,
                "weight_8g": rate_22k * 8,
                "source": "LiveChennai",
                "source_url": (
                    f"{HISTORY_URL}?monthno={month}&yearno={year}"
                ),
                "type": "daily_history",
            })

        if records:
            break

    print(f"  Found {len(records)} records")
    return records


def update_historical_data():
    existing = load_json(HISTORY_FILE, [])
    if not isinstance(existing, list):
        existing = []

    by_date = {}
    for item in existing:
        if not isinstance(item, dict):
            continue
        if item.get("date") and item.get("rate_22k"):
            by_date[item["date"]] = item

    today = datetime.now(IST).date()

    if not by_date:
        print("No historical database found. Building approximately 3 years...")
        start = today.replace(year=today.year - 3)
        year, month = start.year, start.month

        while (year, month) <= (today.year, today.month):
            try:
                for item in fetch_history_month(year, month):
                    by_date[item["date"]] = item
            except Exception as exc:
                print(f"History error {year}-{month:02d}: {exc}")

            month += 1
            if month == 13:
                month = 1
                year += 1
            time.sleep(0.2)
    else:
        try:
            for item in fetch_history_month(today.year, today.month):
                by_date[item["date"]] = item
        except Exception as exc:
            print(f"Current month history update failed: {exc}")

    records = sorted(by_date.values(), key=lambda x: x["date"])
    save_json(HISTORY_FILE, records)
    print(f"Historical database contains {len(records)} daily records.")
    return records


def append_change_log(
    old_rate,
    new_rate,
    detected_at,
    source_last_update,
    session,
):
    log = load_json(CHANGE_LOG_FILE, [])
    if not isinstance(log, list):
        log = []

    source_parts = source_time_parts(source_last_update)
    source_hour = source_parts[0] if source_parts else None
    source_minute = source_parts[1] if source_parts else None

    entry = {
        "detected_at": detected_at.isoformat(),
        "detected_time": detected_at.strftime("%H:%M:%S"),
        "source_last_update": source_last_update,
        "source_hour": source_hour,
        "source_minute": source_minute,
        "session": session,
        "previous_rate_22k": old_rate,
        "rate_22k": new_rate,
        "change": new_rate - old_rate,
    }

    # Prevent the same change from being logged twice.
    signature = (
        entry["detected_at"][:10],
        entry["source_last_update"],
        entry["rate_22k"],
        entry["previous_rate_22k"],
    )
    for old in log:
        old_signature = (
            str(old.get("detected_at", ""))[:10],
            old.get("source_last_update"),
            old.get("rate_22k"),
            old.get("previous_rate_22k"),
        )
        if old_signature == signature:
            return log

    log.append(entry)
    log = log[-1000:]
    save_json(CHANGE_LOG_FILE, log)
    return log


def learned_windows():
    log = load_json(CHANGE_LOG_FILE, [])
    if not isinstance(log, list):
        log = []

    result = {}
    for session in ("AM", "PM"):
        minutes = []
        for item in log:
            if item.get("session") != session:
                continue
            h, m = item.get("source_hour"), item.get("source_minute")
            if isinstance(h, int) and isinstance(m, int):
                minutes.append(h * 60 + m)

        if len(minutes) < 5:
            result[session] = None
            continue

        # Robust mode: select the densest 15-minute neighborhood.
        best_center = None
        best_count = -1
        for center in minutes:
            count = sum(abs(x - center) <= 15 for x in minutes)
            if count > best_count:
                best_count = count
                best_center = center

        result[session] = {
            "observations": len(minutes),
            "center_minute": best_center,
            "center": f"{best_center // 60:02d}:{best_center % 60:02d}",
            "window_start": max(0, best_center - 30),
            "window_end": min(1439, best_center + 30),
        }

    return result


def print_learning_status():
    windows = learned_windows()
    print()
    print("LEARNED CHANGE WINDOWS")
    for session in ("AM", "PM"):
        item = windows.get(session)
        if not item:
            print(f"  {session}: not enough observations yet")
        else:
            print(
                f"  {session}: center {item['center']} "
                f"(±30 min), observations={item['observations']}"
            )
    return windows


def in_window(now, session, windows):
    item = windows.get(session)
    if not item:
        return False

    minute = now.hour * 60 + now.minute
    return item["window_start"] <= minute <= item["window_end"]


def default_monitor_session(now):
    # Until the data has learned a real window, use broad morning/evening
    # periods. These are only bootstrap windows; they are replaced by learned
    # windows after observations accumulate.
    if 6 <= now.hour < 13:
        return "AM"
    if 13 <= now.hour <= 20:
        return "PM"
    return None


def read_current():
    html = get_html(CURRENT_URL)
    return parse_current_rate(html)


def update_live_data(
    current_rate,
    source_last_update,
    previous_rate,
    detected_at,
):
    live = load_json(LIVE_FILE, {})
    if not isinstance(live, dict):
        live = {}

    changed = (
        previous_rate is not None
        and int(previous_rate) != int(current_rate)
    )

    session = session_for_source_time(source_last_update, detected_at)
    snapshots = live.get("intraday", [])
    if not isinstance(snapshots, list):
        snapshots = []

    if changed:
        snapshots.append({
            "date": detected_at.date().isoformat(),
            "time": detected_at.strftime("%H:%M:%S"),
            "rate_22k": int(current_rate),
            "rate_8g": int(current_rate) * 8,
            "session": session,
            "type": "live_change",
            "source_last_update": source_last_update,
        })

    snapshots = snapshots[-100:]

    last_change = live.get("last_change")
    if changed:
        last_change = {
            "date": detected_at.date().isoformat(),
            "time": detected_at.strftime("%H:%M:%S"),
            "rate_22k": int(current_rate),
            "rate_8g": int(current_rate) * 8,
            "previous_rate_22k": int(previous_rate),
            "change": int(current_rate) - int(previous_rate),
            "session": session,
            "source_last_update": source_last_update,
            "detected_at": detected_at.isoformat(),
        }

    result = {
        "rate_22k": int(current_rate),
        "rate_8g": int(current_rate) * 8,
        "rate_24k": live.get("rate_24k"),
        "rate_18k": live.get("rate_18k"),
        "updated_at": detected_at.isoformat(),
        "date": detected_at.date().isoformat(),
        "time": detected_at.strftime("%H:%M:%S"),
        "session": session,
        "source": "LiveChennai",
        "source_url": CURRENT_URL,
        "source_last_update": source_last_update,
        "changed": changed,
        "previous_rate_22k": previous_rate,
        "change": (
            int(current_rate) - int(previous_rate)
            if previous_rate is not None else 0
        ),
        "last_change": last_change,
        "intraday": snapshots,
    }

    save_json(LIVE_FILE, result)
    return result


def poll_until_change():
    live = load_json(LIVE_FILE, {})
    previous_rate = live.get("rate_22k") if isinstance(live, dict) else None

    now = datetime.now(IST)
    windows = learned_windows()

    # Prefer learned windows. Before enough data exists, use broad bootstrap
    # windows so the system can begin learning.
    session = None
    for candidate in ("AM", "PM"):
        if in_window(now, candidate, windows):
            session = candidate
            break

    if session is None:
        session = default_monitor_session(now)

    if session is None:
        print("Outside monitoring window; performing one normal fetch.")
        rate, source_time = read_current()
        detected_at = datetime.now(IST)
        update_live_data(rate, source_time, previous_rate, detected_at)
        return

    print(
        f"Monitoring {session} window every {POLL_SECONDS} seconds "
        f"for up to {POLL_MAX_MINUTES} minutes."
    )
    print(f"Starting rate: ₹{previous_rate:,}" if previous_rate else "Starting rate: unknown")

    deadline = time.monotonic() + POLL_MAX_MINUTES * 60

    while time.monotonic() < deadline:
        try:
            rate, source_time = read_current()
            detected_at = datetime.now(IST)

            print(
                f"[{detected_at.strftime('%H:%M:%S')}] "
                f"Source={source_time or 'unknown'} "
                f"Rate=₹{rate:,}"
            )

            if previous_rate is not None and int(rate) != int(previous_rate):
                print(
                    f"RATE CHANGED: ₹{previous_rate:,} → ₹{rate:,}"
                )

                update_live_data(
                    rate,
                    source_time,
                    int(previous_rate),
                    detected_at,
                )

                append_change_log(
                    int(previous_rate),
                    int(rate),
                    detected_at,
                    source_time,
                    session_for_source_time(source_time, detected_at),
                )

                print_learning_status()
                return

            # If the first run has no prior rate, establish a baseline but do
            # not call it a change.
            if previous_rate is None:
                previous_rate = int(rate)
                update_live_data(
                    rate, source_time, None, detected_at
                )

        except Exception as exc:
            print(f"Poll error: {exc}")

        time.sleep(POLL_SECONDS)

    print("Monitoring window ended without detecting a rate change.")
    print_learning_status()


def main():
    print("=" * 70)
    print("CHENNAI 22K GOLD RATE LEARNING UPDATER")
    print("=" * 70)

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Keep the existing 3-year history-building behavior.
    if not HISTORY_FILE.exists():
        update_historical_data()
    else:
        # Refresh the current month without rebuilding the whole database.
        update_historical_data()

    print_learning_status()
    poll_until_change()

    print("=" * 70)
    print("UPDATE COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
