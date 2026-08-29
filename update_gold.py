import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, time as dt_time
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup


# ============================================================
# CHENNAI 22K GOLD PRICE MONITOR
# Sources:
#   1. LiveChennai
#   2. GoodReturns
#
# Monitoring:
#   - Learns historical update times
#   - Last 30 days receive higher weight
#   - Polls every 10 seconds during monitoring window
#   - Stops immediately after a confirmed NEW price
#   - Outside window: one normal fetch only
# ============================================================

IST = ZoneInfo("Asia/Kolkata")

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

LIVE_FILE = DATA_DIR / "live.json"
HISTORY_FILE = DATA_DIR / "history.json"
WINDOW_FILE = DATA_DIR / "monitoring_windows.json"

LIVECHENNAI_URL = "https://www.livechennai.com/gold_silverrate.asp"
GOODRETURNS_URL = "https://www.goodreturns.in/gold-rates/chennai.html"

POLL_SECONDS = 10
REQUEST_TIMEOUT = 20

# Maximum number of polls in one monitoring window.
# This protects GitHub Actions from an accidental endless loop.
MAX_MONITOR_SECONDS = 5 * 60 * 60


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/18.0 Safari/605.1.15"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


# ============================================================
# BASIC HELPERS
# ============================================================

def now_ist():
    return datetime.now(IST)


def ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_json(path, default):
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"WARNING: Could not read {path}: {e}")

    return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)

    temp = path.with_suffix(path.suffix + ".tmp")

    with open(temp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    temp.replace(path)


def clean_number(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return int(value)

    text = str(value)
    text = text.replace(",", "")
    text = text.replace("₹", "")
    text = text.replace("Rs.", "")
    text = text.replace("Rs", "")
    text = text.replace("/gram", "")
    text = text.strip()

    match = re.search(r"\d+(?:\.\d+)?", text)

    if not match:
        return None

    try:
        return int(float(match.group(0)))
    except Exception:
        return None


def parse_time_string(value):
    """
    Convert strings such as:
      9:44:41 AM
      09:44 AM
      10:04:58
    into an IST datetime time object.
    """

    if not value:
        return None

    value = value.strip().upper()

    patterns = [
        "%I:%M:%S %p",
        "%I:%M %p",
        "%H:%M:%S",
        "%H:%M",
    ]

    for pattern in patterns:
        try:
            return datetime.strptime(value, pattern).time()
        except ValueError:
            pass

    return None


def time_to_minutes(t):
    return t.hour * 60 + t.minute


def minutes_to_string(minutes):
    minutes = int(minutes) % (24 * 60)

    h = minutes // 60
    m = minutes % 60

    suffix = "AM" if h < 12 else "PM"

    display_h = h % 12
    if display_h == 0:
        display_h = 12

    return f"{display_h}:{m:02d} {suffix}"


# ============================================================
# FETCH LIVECHENNAI
# ============================================================

def fetch_livechennai():
    print("Checking LiveChennai...")

    try:
        # Cache-busting query parameter.
        url = f"{LIVECHENNAI_URL}?_={int(time.time())}"

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        text = soup.get_text(" ", strip=True)

        # ----------------------------------------------------
        # 22K price
        # ----------------------------------------------------

        rate = None

        patterns = [
            r"Standard Gold\s*\(22\s*K\).*?1\s*Gm.*?8\s*Gm.*?1\s*Gm.*?8\s*Gm",
            r"1\s*Gm\s+8\s*Gm\s+1\s*Gm\s+8\s*Gm",
        ]

        # First search for the common explicit format:
        # "22K Gold ... ₹14,505"
        price_patterns = [
            r"22K[^₹\d]{0,100}₹\s*([\d,]+)",
            r"22\s*carat[^₹\d]{0,100}₹\s*([\d,]+)",
            r"22\s*K[^0-9]{0,100}([\d,]{4,6})",
            r"Standard Gold\s*\(22\s*K\)[^0-9]{0,100}([\d,]{4,6})",
        ]

        for pattern in price_patterns:
            match = re.search(pattern, text, re.I)

            if match:
                candidate = clean_number(match.group(1))

                if candidate and 8000 <= candidate <= 30000:
                    rate = candidate
                    break

        # ----------------------------------------------------
        # Last Update Time
        # ----------------------------------------------------

        update_time = None

        time_patterns = [
            r"Last Update Time\s*:\s*([0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?\s*[AP]M)",
            r"Last Updated?\s*:?\s*([0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?\s*[AP]M)",
            r"Updated\s*:?\s*([0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?\s*[AP]M)",
        ]

        for pattern in time_patterns:
            match = re.search(pattern, text, re.I)

            if match:
                update_time = parse_time_string(match.group(1))
                if update_time:
                    break

        # ----------------------------------------------------
        # Date
        # ----------------------------------------------------

        today = now_ist().date()

        result = {
            "source": "LiveChennai",
            "url": LIVECHENNAI_URL,
            "rate_22k": rate,
            "update_time": update_time.strftime("%H:%M:%S")
            if update_time
            else None,
            "date": today.isoformat(),
            "fetched_at": now_ist().isoformat(),
        }

        if rate is None:
            print("LiveChennai: 22K price not found")
            return result

        print(
            f"LiveChennai: ₹{rate:,}/gram"
            + (
                f" | source update {update_time.strftime('%I:%M:%S %p')}"
                if update_time
                else ""
            )
        )

        return result

    except Exception as e:
        print(f"LiveChennai failed: {e}")

        return {
            "source": "LiveChennai",
            "url": LIVECHENNAI_URL,
            "rate_22k": None,
            "update_time": None,
            "date": now_ist().date().isoformat(),
            "fetched_at": now_ist().isoformat(),
            "error": str(e),
        }


# ============================================================
# FETCH GOODRETURNS
# ============================================================

def fetch_goodreturns():
    print("Checking GoodReturns...")

    try:
        url = f"{GOODRETURNS_URL}?_={int(time.time())}"

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        text = soup.get_text(" ", strip=True)

        rate = None

        patterns = [
            r"22K\s*Gold\s*/\s*g\s*₹?\s*([\d,]+)",
            r"22K\s*Gold[^₹\d]{0,80}₹\s*([\d,]+)",
            r"22K[^₹\d]{0,100}₹\s*([\d,]+)",
            r"22K[^0-9]{0,100}([\d,]{4,6})",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.I)

            if match:
                candidate = clean_number(match.group(1))

                if candidate and 8000 <= candidate <= 30000:
                    rate = candidate
                    break

        result = {
            "source": "GoodReturns",
            "url": GOODRETURNS_URL,
            "rate_22k": rate,
            "update_time": None,
            "date": now_ist().date().isoformat(),
            "fetched_at": now_ist().isoformat(),
        }

        if rate is None:
            print("GoodReturns: 22K price not found")
        else:
            print(f"GoodReturns: ₹{rate:,}/gram")

        return result

    except Exception as e:
        print(f"GoodReturns failed: {e}")

        return {
            "source": "GoodReturns",
            "url": GOODRETURNS_URL,
            "rate_22k": None,
            "update_time": None,
            "date": now_ist().date().isoformat(),
            "fetched_at": now_ist().isoformat(),
            "error": str(e),
        }


# ============================================================
# SOURCE CONSENSUS
# ============================================================

def fetch_sources():
    live = fetch_livechennai()
    good = fetch_goodreturns()

    live_rate = live.get("rate_22k")
    good_rate = good.get("rate_22k")

    # Prefer agreement between sources.
    if live_rate and good_rate:
        if live_rate == good_rate:
            return {
                "rate": live_rate,
                "confirmed": True,
                "source": "LiveChennai + GoodReturns",
                "livechennai": live,
                "goodreturns": good,
            }

        # If they disagree, prefer LiveChennai because it provides
        # an explicit source update timestamp.
        return {
            "rate": live_rate,
            "confirmed": False,
            "source": "LiveChennai",
            "source_disagreement": True,
            "livechennai": live,
            "goodreturns": good,
        }

    if live_rate:
        return {
            "rate": live_rate,
            "confirmed": False,
            "source": "LiveChennai",
            "livechennai": live,
            "goodreturns": good,
        }

    if good_rate:
        return {
            "rate": good_rate,
            "confirmed": False,
            "source": "GoodReturns",
            "livechennai": live,
            "goodreturns": good,
        }

    return {
        "rate": None,
        "confirmed": False,
        "source": None,
        "livechennai": live,
        "goodreturns": good,
    }


# ============================================================
# HISTORY
# ============================================================

def load_history():
    data = load_json(HISTORY_FILE, [])

    if isinstance(data, dict):
        if isinstance(data.get("history"), list):
            return data["history"]

        if isinstance(data.get("records"), list):
            return data["records"]

    if isinstance(data, list):
        return data

    return []


def extract_rate(record):
    if not isinstance(record, dict):
        return None

    keys = [
        "rate_22k",
        "rate22k",
        "22k",
        "gold_22k",
        "price_22k",
        "rate",
    ]

    for key in keys:
        if key in record:
            value = clean_number(record[key])

            if value and 8000 <= value <= 30000:
                return value

    return None


def extract_datetime(record):
    if not isinstance(record, dict):
        return None

    candidates = [
        record.get("source_update_time"),
        record.get("update_time"),
        record.get("updated_at"),
        record.get("timestamp"),
        record.get("datetime"),
        record.get("date"),
    ]

    for value in candidates:
        if not value:
            continue

        text = str(value)

        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))

            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=IST)

            return dt.astimezone(IST)
        except Exception:
            pass

    return None


# ============================================================
# LEARN MONITORING WINDOW
# ============================================================

def learn_windows():
    """
    Learn actual historical update times.

    IMPORTANT:
    We only use records that have an actual time.
    Daily records without a timestamp are NOT treated as
    intraday update observations.
    """

    history = load_history()

    now = now_ist()

    three_month_cutoff = now - timedelta(days=92)
    thirty_day_cutoff = now - timedelta(days=30)

    observations = []

    for record in history:
        dt = extract_datetime(record)

        if not dt:
            continue

        if dt < three_month_cutoff:
            continue

        rate = extract_rate(record)

        if not rate:
            continue

        observations.append(
            {
                "dt": dt,
                "rate": rate,
                "recent": dt >= thirty_day_cutoff,
            }
        )

    # --------------------------------------------------------
    # Detect only genuine rate-change observations.
    # --------------------------------------------------------

    observations.sort(key=lambda x: x["dt"])

    change_times = []

    previous_rate = None

    for item in observations:
        rate = item["rate"]

        if previous_rate is None:
            previous_rate = rate
            continue

        if rate != previous_rate:
            change_times.append(item)

        previous_rate = rate

    # --------------------------------------------------------
    # Last 30 days are weighted heavily.
    # --------------------------------------------------------

    recent_am = []
    recent_pm = []

    all_am = []
    all_pm = []

    for item in change_times:
        dt = item["dt"]

        mins = time_to_minutes(dt.time())

        # Morning market window.
        if 5 * 60 <= mins < 14 * 60:
            all_am.append(mins)

            if item["recent"]:
                recent_am.append(mins)

        # Evening market window.
        elif 14 * 60 <= mins <= 23 * 60:
            all_pm.append(mins)

            if item["recent"]:
                recent_pm.append(mins)

    # If enough recent observations exist, use them.
    # Otherwise use the full 3-month observations.
    am_points = recent_am if len(recent_am) >= 3 else all_am
    pm_points = recent_pm if len(recent_pm) >= 3 else all_pm

    def build_window(points, default_start, default_end):
        if not points:
            return {
                "start": default_start,
                "end": default_end,
                "observations": 0,
            }

        # Use a robust central cluster rather than the extreme earliest
        # and latest observations.
        points = sorted(points)

        if len(points) >= 5:
            trim = max(1, int(len(points) * 0.10))
            trimmed = points[trim:-trim]

            if trimmed:
                points = trimmed

        center = sum(points) / len(points)

        # Monitoring window deliberately covers ±45 minutes
        # around the learned centre.
        start = int(center - 45)
        end = int(center + 45)

        # Clamp.
        start = max(5 * 60, min(start, 23 * 60))
        end = max(start + 30, min(end, 23 * 60 + 30))

        return {
            "start": start,
            "end": end,
            "observations": len(points),
        }

    am = build_window(
        am_points,
        8 * 60 + 30,
        11 * 60 + 30,
    )

    pm = build_window(
        pm_points,
        17 * 60,
        20 * 60,
    )

    windows = {
        "generated_at": now.isoformat(),
        "timezone": "Asia/Kolkata",
        "learning_period_days": 92,
        "priority_period_days": 30,
        "change_observations": len(change_times),
        "am_observations": len(am_points),
        "pm_observations": len(pm_points),
        "am": {
            "start_minutes": am["start"],
            "end_minutes": am["end"],
            "start": minutes_to_string(am["start"]),
            "end": minutes_to_string(am["end"]),
            "observations": am["observations"],
        },
        "pm": {
            "start_minutes": pm["start"],
            "end_minutes": pm["end"],
            "start": minutes_to_string(pm["start"]),
            "end": minutes_to_string(pm["end"]),
            "observations": pm["observations"],
        },
    }

    save_json(WINDOW_FILE, windows)

    print()
    print("LEARNED MONITORING WINDOWS")
    print("--------------------------------")
    print(
        f"AM: {windows['am']['start']} - {windows['am']['end']} "
        f"({windows['am']['observations']} observations)"
    )
    print(
        f"PM: {windows['pm']['start']} - {windows['pm']['end']} "
        f"({windows['pm']['observations']} observations)"
    )
    print(f"Price-change observations: {len(change_times)}")
    print(f"Saved: {WINDOW_FILE}")

    return windows


# ============================================================
# WINDOW CHECK
# ============================================================

def get_active_window(windows, current):
    minutes = current.hour * 60 + current.minute

    for name in ("am", "pm"):
        window = windows.get(name, {})

        start = window.get("start_minutes")
        end = window.get("end_minutes")

        if start is None or end is None:
            continue

        if start <= minutes <= end:
            return name, start, end

    return None


# ============================================================
# LIVE.JSON
# ============================================================

def load_live():
    return load_json(LIVE_FILE, {})


def save_live(result, previous_rate, changed):
    rate = result.get("rate")

    if not rate:
        return

    live = load_live()

    now = now_ist()

    live.update(
        {
            "rate_22k": rate,
            "rate_8g": rate * 8,
            "date": now.date().isoformat(),
            "time": now.strftime("%H:%M:%S"),
            "updated_at": now.isoformat(),
            "timezone": "Asia/Kolkata",
            "changed": changed,
            "previous_rate_22k": previous_rate,
            "source": result.get("source"),
            "livechennai": result.get("livechennai"),
            "goodreturns": result.get("goodreturns"),
            "monitoring": True,
        }
    )

    save_json(LIVE_FILE, live)


# ============================================================
# MAIN NORMAL FETCH
# ============================================================

def normal_fetch(previous_rate):
    print()
    print("NORMAL FETCH")
    print("--------------------------------")

    result = fetch_sources()

    rate = result.get("rate")

    if not rate:
        print("No valid 22K rate found.")
        return previous_rate, False

    changed = (
        previous_rate is not None
        and rate != previous_rate
    )

    print(f"Current 22K rate: ₹{rate:,}")
    print(f"Previous 22K rate: ₹{previous_rate:,}" if previous_rate else "No previous rate")
    print(f"Changed: {changed}")

    save_live(
        result,
        previous_rate,
        changed,
    )

    return rate, changed


# ============================================================
# FULL 10-SECOND MONITOR
# ============================================================

def monitor_window(window_name, start_minutes, end_minutes, previous_rate):
    """
    Poll every 10 seconds for the ENTIRE monitoring window.

    This is intentionally a blocking loop.
    """

    print()
    print("=" * 70)
    print("FULL MONITORING STARTED")
    print("=" * 70)

    print(f"Window: {minutes_to_string(start_minutes)} - {minutes_to_string(end_minutes)}")
    print(f"Polling interval: {POLL_SECONDS} seconds")
    print("Sources: LiveChennai + GoodReturns")
    print("Will stop only when:")
    print("  1. A genuinely new 22K rate is confirmed")
    print("  2. Monitoring window ends")
    print()

    window_end = end_minutes

    # Maximum safety limit.
    monitor_started = time.monotonic()

    last_seen_rate = previous_rate

    poll_number = 0

    while True:
        now = now_ist()

        current_minutes = (
            now.hour * 60
            + now.minute
            + now.second / 60
        )

        # ----------------------------------------------------
        # End of monitoring window.
        # ----------------------------------------------------

        if current_minutes > window_end:
            print()
            print("MONITORING WINDOW ENDED")
            print(f"Final time: {now.strftime('%I:%M:%S %p')}")
            break

        # ----------------------------------------------------
        # Safety timeout.
        # ----------------------------------------------------

        if time.monotonic() - monitor_started > MAX_MONITOR_SECONDS:
            print()
            print("SAFETY TIMEOUT REACHED")
            break

        poll_number += 1

        print()
        print("-" * 70)
        print(
            f"POLL #{poll_number} | "
            f"{now.strftime('%d-%m-%Y %I:%M:%S %p')}"
        )
        print("-" * 70)

        result = fetch_sources()

        rate = result.get("rate")

        if not rate:
            print("No valid rate found.")
            print(f"Retrying in {POLL_SECONDS} seconds...")
            time.sleep(POLL_SECONDS)
            continue

        print(f"Observed 22K rate: ₹{rate:,}")
        print(f"Previous saved rate: ₹{previous_rate:,}" if previous_rate else "Previous saved rate: NONE")

        # ----------------------------------------------------
        # New price discovered.
        # ----------------------------------------------------

        if previous_rate is not None and rate != previous_rate:
            print()
            print("=" * 70)
            print("NEW 22K GOLD PRICE DISCOVERED")
            print("=" * 70)
            print(f"Old: ₹{previous_rate:,}/gram")
            print(f"New: ₹{rate:,}/gram")
            print(f"Source: {result.get('source')}")

            save_live(
                result,
                previous_rate,
                True,
            )

            print("live.json updated.")
            print("Monitoring stopped.")

            return rate, True

        # ----------------------------------------------------
        # First valid price if no previous price exists.
        # ----------------------------------------------------

        if previous_rate is None:
            print("No previous saved price.")
            print("Saving first valid price.")

            save_live(
                result,
                None,
                False,
            )

            previous_rate = rate
            last_seen_rate = rate

        else:
            print("No new price yet.")

        # ----------------------------------------------------
        # IMPORTANT:
        # Always wait exactly 10 seconds before next poll.
        # ----------------------------------------------------

        remaining = max(
            0,
            int((window_end - current_minutes) * 60)
        )

        if remaining <= 0:
            break

        sleep_for = min(POLL_SECONDS, remaining)

        print(f"Next fetch in {sleep_for} seconds...")
        time.sleep(sleep_for)

    return previous_rate, False


# ============================================================
# MAIN
# ============================================================

def main():
    ensure_data_dir()

    print("=" * 70)
    print("CHENNAI 22K GOLD RATE")
    print("FULL-WINDOW 10-SECOND MONITOR")
    print("=" * 70)

    now = now_ist()

    print(
        f"IST time: {now.strftime('%d-%m-%Y %I:%M:%S %p')}"
    )

    # --------------------------------------------------------
    # Load existing live price.
    # --------------------------------------------------------

    live = load_live()

    previous_rate = clean_number(
        live.get("rate_22k")
    )

    if previous_rate:
        print(f"Previous saved 22K rate: ₹{previous_rate:,}")
    else:
        print("Previous saved 22K rate: NONE")

    # --------------------------------------------------------
    # Learn monitoring windows every run.
    # --------------------------------------------------------

    windows = learn_windows()

    # --------------------------------------------------------
    # Determine whether currently inside a window.
    # --------------------------------------------------------

    active = get_active_window(
        windows,
        now,
    )

    if active:
        window_name, start_minutes, end_minutes = active

        print()
        print("=" * 70)
        print("CURRENTLY INSIDE MONITORING WINDOW")
        print("=" * 70)
        print(
            f"{window_name.upper()}: "
            f"{minutes_to_string(start_minutes)} - "
            f"{minutes_to_string(end_minutes)}"
        )

        # ----------------------------------------------------
        # FULL 10-second monitoring.
        # ----------------------------------------------------

        new_rate, changed = monitor_window(
            window_name,
            start_minutes,
            end_minutes,
            previous_rate,
        )

        previous_rate = new_rate

    else:
        print()
        print("=" * 70)
        print("OUTSIDE MONITORING WINDOW")
        print("=" * 70)
        print("Performing ONE normal fetch and exiting.")

        previous_rate, changed = normal_fetch(
            previous_rate
        )

    # --------------------------------------------------------
    # Final output.
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print("UPDATE COMPLETE")
    print("=" * 70)

    if previous_rate:
        print(f"22K / gram : ₹{previous_rate:,}")
        print(f"22K / 8g   : ₹{previous_rate * 8:,}")

    print(f"Date       : {now_ist().date().isoformat()}")
    print(f"Time       : {now_ist().strftime('%H:%M:%S')}")
    print(f"Changed    : {changed}")
    print(f"Live file  : {LIVE_FILE}")
    print(f"Window file: {WINDOW_FILE}")
    print("=" * 70)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        print("Monitoring manually stopped.")
        sys.exit(130)
    except Exception as e:
        print()
        print("=" * 70)
        print("FATAL ERROR")
        print("=" * 70)
        print(str(e))
        sys.exit(1)
