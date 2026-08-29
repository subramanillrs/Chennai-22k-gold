import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import median
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup


# ============================================================
# CHENNAI 22K GOLD PRICE - ADAPTIVE FULL-WINDOW MONITOR
# ============================================================

IST = ZoneInfo("Asia/Kolkata")

LIVE_FILE = "data/live.json"
HISTORY_FILE = "data/history.json"
WINDOW_FILE = "data/monitoring_windows.json"

LIVECHENNAI_URL = "https://www.livechennai.com/gold_silverrate.asp"
GOODRETURNS_URL = "https://www.goodreturns.in/gold-rates/chennai.html"

# Poll every 10 seconds while inside a monitoring window.
POLL_SECONDS = 10

# Individual website timeout.
REQUEST_TIMEOUT = 8

# Safety validation only.
# These are NOT expected price ranges.
MIN_VALID_RATE = 5000
MAX_VALID_RATE = 30000

# Never allow a single monitoring session to exceed this.
MAX_MONITOR_MINUTES = 190

# Learning periods.
THREE_MONTH_DAYS = 92
THIRTY_DAY_DAYS = 30

# Default windows are used only when there is not enough
# historical information to calculate a learned window.
DEFAULT_AM_START = "08:30"
DEFAULT_AM_END = "11:30"
DEFAULT_PM_START = "17:00"
DEFAULT_PM_END = "20:00"

# Maximum/minimum reasonable learned window widths.
MIN_WINDOW_MINUTES = 60
MAX_WINDOW_MINUTES = 210

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/18.0 Safari/605.1.15"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


# ============================================================
# DIRECTORY
# ============================================================

os.makedirs("data", exist_ok=True)


# ============================================================
# TIME HELPERS
# ============================================================

def now_ist():
    return datetime.now(IST)


def today_string():
    return now_ist().strftime("%Y-%m-%d")


def current_time_string():
    return now_ist().strftime("%H:%M:%S")


def iso_now():
    return now_ist().isoformat()


# ============================================================
# JSON
# ============================================================

def load_json(path, default):
    try:
        if not os.path.exists(path):
            return default

        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception as exc:
        print(f"WARNING: Cannot read {path}: {exc}")
        return default


def save_json(path, value):
    temp = path + ".tmp"

    with open(temp, "w", encoding="utf-8") as f:
        json.dump(
            value,
            f,
            indent=2,
            ensure_ascii=False
        )

    os.replace(temp, path)


# ============================================================
# RATE VALIDATION
# ============================================================

def clean_rate(value):
    if value is None:
        return None

    text = str(value)

    digits = re.sub(r"[^\d]", "", text)

    if not digits:
        return None

    try:
        rate = int(digits)
    except Exception:
        return None

    if rate < MIN_VALID_RATE:
        return None

    if rate > MAX_VALID_RATE:
        return None

    return rate


# ============================================================
# DATETIME PARSING
# ============================================================

def parse_history_datetime(item):
    """
    Supports several possible formats already used by the app.
    """

    if not isinstance(item, dict):
        return None

    # First preference: timestamp.
    for key in (
        "timestamp",
        "datetime",
        "fetched_at",
        "updated_at",
        "last_fetch",
    ):
        value = item.get(key)

        if value:
            try:
                text = str(value)

                # Handle Z.
                if text.endswith("Z"):
                    text = text[:-1] + "+00:00"

                dt = datetime.fromisoformat(text)

                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=IST)

                return dt.astimezone(IST)

            except Exception:
                pass

    date_value = item.get("date")

    if not date_value:
        return None

    time_value = (
        item.get("time")
        or item.get("update_time")
        or item.get("updated_time")
        or "12:00:00"
    )

    date_text = str(date_value).strip()
    time_text = str(time_value).strip()

    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %I:%M:%S %p",
        "%Y-%m-%d %I:%M %p",
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
    ]

    combined = f"{date_text} {time_text}"

    for fmt in formats:
        try:
            return datetime.strptime(
                combined,
                fmt
            ).replace(tzinfo=IST)

        except Exception:
            pass

    return None


# ============================================================
# EXTRACT RATE FROM HISTORY ITEM
# ============================================================

def history_rate(item):
    if not isinstance(item, dict):
        return None

    for key in (
        "rate_22k",
        "rate22k",
        "gold_22k",
        "rate",
        "price",
    ):
        rate = clean_rate(item.get(key))

        if rate:
            return rate

    return None


# ============================================================
# LOAD HISTORY IN MULTIPLE POSSIBLE FORMATS
# ============================================================

def extract_history_records(data):
    """
    Handles:
      - list of records
      - {"history": [...]}
      - {"data": [...]}
      - {"records": [...]}
    """

    if isinstance(data, list):
        return data

    if isinstance(data, dict):

        for key in (
            "history",
            "data",
            "records",
            "prices",
            "observations",
        ):
            value = data.get(key)

            if isinstance(value, list):
                return value

    return []


# ============================================================
# LEARN MONITORING WINDOWS
# ============================================================

def round_to_5_minutes(minutes):
    return int(round(minutes / 5.0) * 5)


def minutes_to_hhmm(minutes):
    minutes = int(minutes) % (24 * 60)

    hour = minutes // 60
    minute = minutes % 60

    return f"{hour:02d}:{minute:02d}"


def hhmm_to_minutes(value):
    try:
        hour, minute = str(value).split(":")
        return int(hour) * 60 + int(minute)

    except Exception:
        return None


def make_window(center, width):
    width = max(
        MIN_WINDOW_MINUTES,
        min(MAX_WINDOW_MINUTES, width)
    )

    half = width / 2

    start = int(round(center - half))
    end = int(round(center + half))

    # Keep windows within a normal day.
    start = max(0, start)
    end = min(1439, end)

    return {
        "start": minutes_to_hhmm(
            round_to_5_minutes(start)
        ),
        "end": minutes_to_hhmm(
            round_to_5_minutes(end)
        ),
    }


def learn_windows():
    """
    Learn change periods from the previous 92 days.

    The algorithm:
      1. Read historical observations.
      2. Detect records where the 22K rate changed.
      3. Separate morning and evening observations.
      4. Give the last 30 days extra weight.
      5. Calculate robust median change times.
      6. Create monitoring windows around those times.
      7. Save the learned windows.
    """

    print()
    print("=" * 70)
    print("LEARNING MONITORING WINDOWS")
    print("=" * 70)

    raw = load_json(HISTORY_FILE, [])
    records = extract_history_records(raw)

    observations = []

    for item in records:

        dt = parse_history_datetime(item)
        rate = history_rate(item)

        if not dt or not rate:
            continue

        observations.append({
            "dt": dt,
            "rate": rate,
        })

    observations.sort(
        key=lambda x: x["dt"]
    )

    cutoff_92 = now_ist() - timedelta(
        days=THREE_MONTH_DAYS
    )

    cutoff_30 = now_ist() - timedelta(
        days=THIRTY_DAY_DAYS
    )

    observations_92 = [
        x for x in observations
        if x["dt"] >= cutoff_92
    ]

    observations_30 = [
        x for x in observations
        if x["dt"] >= cutoff_30
    ]

    print(
        f"Historical observations: {len(observations)}"
    )

    print(
        f"3-month observations: {len(observations_92)}"
    )

    print(
        f"30-day observations: {len(observations_30)}"
    )

    # --------------------------------------------------------
    # Detect actual price-change observations.
    # --------------------------------------------------------

    changes = []

    previous = None

    for item in observations_92:

        rate = item["rate"]

        if previous is not None and rate != previous:
            changes.append(item)

        previous = rate

    print(
        f"Detected price-change observations: {len(changes)}"
    )

    # If there is no usable change history, retain existing
    # saved windows if available.
    if not changes:
        existing = load_json(
            WINDOW_FILE,
            {}
        )

        if (
            isinstance(existing, dict)
            and existing.get("am")
            and existing.get("pm")
        ):
            print("No new learning data.")
            print("Keeping existing learned windows.")

            return existing

        defaults = {
            "am": {
                "start": DEFAULT_AM_START,
                "end": DEFAULT_AM_END,
            },
            "pm": {
                "start": DEFAULT_PM_START,
                "end": DEFAULT_PM_END,
            },
        }

        save_json(WINDOW_FILE, defaults)

        print("Insufficient history.")
        print("Using safe default windows.")

        return defaults

    # --------------------------------------------------------
    # Classify change times.
    #
    # AM changes:
    # roughly 05:00-14:00
    #
    # PM changes:
    # roughly 14:00-23:00
    # --------------------------------------------------------

    am_three_month = []
    pm_three_month = []

    am_recent = []
    pm_recent = []

    for item in changes:

        dt = item["dt"]

        minute = (
            dt.hour * 60
            + dt.minute
        )

        if 300 <= minute < 840:
            am_three_month.append(minute)

            if dt >= cutoff_30:
                am_recent.append(minute)

        elif 840 <= minute <= 1380:
            pm_three_month.append(minute)

            if dt >= cutoff_30:
                pm_recent.append(minute)

    print(
        f"AM change observations: "
        f"{len(am_three_month)}"
    )

    print(
        f"PM change observations: "
        f"{len(pm_three_month)}"
    )

    print(
        f"AM last-30-day observations: "
        f"{len(am_recent)}"
    )

    print(
        f"PM last-30-day observations: "
        f"{len(pm_recent)}"
    )

    # --------------------------------------------------------
    # Weighted robust median.
    #
    # Last 30 days receive 3x weight.
    # --------------------------------------------------------

    def weighted_time(recent, all_values):
        values = []

        for value in all_values:
            values.append(value)

        # Add recent observations twice more.
        for value in recent:
            values.append(value)
            values.append(value)

        if not values:
            return None

        return int(round(median(values)))

    am_center = weighted_time(
        am_recent,
        am_three_month
    )

    pm_center = weighted_time(
        pm_recent,
        pm_three_month
    )

    # --------------------------------------------------------
    # Window width.
    #
    # We deliberately keep a reasonably wide window so that
    # GitHub Actions does not miss a price update.
    # --------------------------------------------------------

    def learned_width(values):
        if len(values) < 3:
            return 180

        spread = max(values) - min(values)

        # Convert spread into a useful monitoring width.
        width = spread + 60

        return max(
            MIN_WINDOW_MINUTES,
            min(MAX_WINDOW_MINUTES, width)
        )

    am_width = learned_width(
        am_three_month
    )

    pm_width = learned_width(
        pm_three_month
    )

    # --------------------------------------------------------
    # If only one side has enough history, use the default
    # for the other side.
    # --------------------------------------------------------

    if am_center is None:
        am_window = {
            "start": DEFAULT_AM_START,
            "end": DEFAULT_AM_END,
        }
    else:
        am_window = make_window(
            am_center,
            am_width
        )

    if pm_center is None:
        pm_window = {
            "start": DEFAULT_PM_START,
            "end": DEFAULT_PM_END,
        }
    else:
        pm_window = make_window(
            pm_center,
            pm_width
        )

    learned = {
        "am": am_window,
        "pm": pm_window,
        "learned_at": iso_now(),
        "learning_source": "last_92_days",
        "recent_weight": "3x_for_last_30_days",
        "three_month_observations": len(
            observations_92
        ),
        "thirty_day_observations": len(
            observations_30
        ),
        "price_change_observations": len(
            changes
        ),
        "am_observations": len(
            am_three_month
        ),
        "pm_observations": len(
            pm_three_month
        ),
    }

    save_json(
        WINDOW_FILE,
        learned
    )

    print()
    print("LEARNED WINDOWS")
    print(
        f"AM: {am_window['start']} - "
        f"{am_window['end']}"
    )
    print(
        f"PM: {pm_window['start']} - "
        f"{pm_window['end']}"
    )

    print()
    print(
        f"Saved to {WINDOW_FILE}"
    )

    return learned


# ============================================================
# GET CURRENT WINDOWS
# ============================================================

def get_windows():
    data = load_json(
        WINDOW_FILE,
        {}
    )

    if (
        not isinstance(data, dict)
        or not data.get("am")
        or not data.get("pm")
    ):
        return learn_windows()

    return data


# ============================================================
# CURRENT ACTIVE WINDOW
# ============================================================

def active_window(windows):
    now = now_ist()

    current = (
        now.hour * 60
        + now.minute
    )

    for name in ("am", "pm"):

        item = windows.get(name, {})

        start = hhmm_to_minutes(
            item.get("start", "")
        )

        end = hhmm_to_minutes(
            item.get("end", "")
        )

        if start is None or end is None:
            continue

        if start <= current <= end:

            start_dt = now.replace(
                hour=start // 60,
                minute=start % 60,
                second=0,
                microsecond=0,
            )

            end_dt = now.replace(
                hour=end // 60,
                minute=end % 60,
                second=0,
                microsecond=0,
            )

            return {
                "name": name,
                "start": start_dt,
                "end": end_dt,
            }

    return None


# ============================================================
# LIVECHENNAI FETCH
# ============================================================

def fetch_livechennai():

    print("  Checking LiveChennai...")

    try:

        response = requests.get(
            LIVECHENNAI_URL,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        text = soup.get_text(
            " ",
            strip=True
        )

        rate = None

        patterns = [

            r"1\s*Gm\s*\(22\s*K\).*?₹?\s*([\d,]+)",

            r"22K\s*Gold.*?₹\s*([\d,]+)",

            r"22K\s*Gold.*?Rs\.?\s*([\d,]+)",

            r"22\s*carat\s*gold.*?₹\s*([\d,]+)",

        ]

        for pattern in patterns:

            match = re.search(
                pattern,
                text,
                re.I | re.S
            )

            if match:

                rate = clean_rate(
                    match.group(1)
                )

                if rate:
                    break

        # Table fallback.
        if not rate:

            for row in soup.find_all("tr"):

                row_text = row.get_text(
                    " ",
                    strip=True
                )

                if (
                    "22" in row_text
                    and "Gold" in row_text
                ):

                    numbers = re.findall(
                        r"\b\d{2},?\d{3}\b",
                        row_text
                    )

                    for number in numbers:

                        candidate = clean_rate(
                            number
                        )

                        if candidate:
                            rate = candidate
                            break

                if rate:
                    break

        if not rate:
            raise ValueError(
                "Could not locate valid Chennai 22K rate"
            )

        update_time = None

        time_patterns = [

            r"Last Update Time:\s*([^|]+)",

            r"Last Update.*?"
            r"(\d{1,2}:\d{2}:\d{2}\s*[AP]M)",

            r"Updated:\s*([^|]+)",

        ]

        for pattern in time_patterns:

            match = re.search(
                pattern,
                text,
                re.I
            )

            if match:
                update_time = (
                    match.group(1).strip()
                )
                break

        return {
            "source": "LiveChennai",
            "rate_22k": rate,
            "update_time": update_time,
            "url": LIVECHENNAI_URL,
            "fetched_at": iso_now(),
        }

    except Exception as exc:

        print(
            f"  LiveChennai failed: {exc}"
        )

        return None


# ============================================================
# GOODRETURNS FETCH
# ============================================================

def fetch_goodreturns():

    print("  Checking GoodReturns...")

    try:

        response = requests.get(
            GOODRETURNS_URL,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        text = soup.get_text(
            " ",
            strip=True
        )

        rate = None

        patterns = [

            r"22K\s*Gold\s*/g\s*₹?\s*([\d,]+)",

            r"22K\s*Gold.*?₹\s*([\d,]+)",

            r"22K\s*Gold.*?Rs\.?\s*([\d,]+)",

            r"22\s*K\s*Gold.*?₹\s*([\d,]+)",

        ]

        for pattern in patterns:

            match = re.search(
                pattern,
                text,
                re.I | re.S
            )

            if match:

                rate = clean_rate(
                    match.group(1)
                )

                if rate:
                    break

        # Chennai table fallback.
        if not rate:

            for row in soup.find_all("tr"):

                row_text = row.get_text(
                    " ",
                    strip=True
                )

                if "Chennai" in row_text:

                    numbers = re.findall(
                        r"\b\d{2},?\d{3}\b",
                        row_text
                    )

                    if len(numbers) >= 2:

                        candidate = clean_rate(
                            numbers[1]
                        )

                        if candidate:
                            rate = candidate
                            break

        if not rate:
            raise ValueError(
                "Could not locate valid GoodReturns Chennai 22K rate"
            )

        return {
            "source": "GoodReturns",
            "rate_22k": rate,
            "update_time": None,
            "url": GOODRETURNS_URL,
            "fetched_at": iso_now(),
        }

    except Exception as exc:

        print(
            f"  GoodReturns failed: {exc}"
        )

        return None


# ============================================================
# FETCH BOTH
# ============================================================

def fetch_all_sources():

    results = []

    live = fetch_livechennai()

    if live:
        results.append(live)

    good = fetch_goodreturns()

    if good:
        results.append(good)

    return results


# ============================================================
# PREVIOUS RATE
# ============================================================

def get_previous_live():

    return load_json(
        LIVE_FILE,
        {}
    )


def get_previous_rate():

    live = get_previous_live()

    if not isinstance(live, dict):
        return None

    for key in (
        "rate_22k",
        "rate22k",
        "gold_22k",
    ):

        rate = clean_rate(
            live.get(key)
        )

        if rate:
            return rate

    return None


# ============================================================
# SAVE LIVE
# ============================================================

def save_live(
    rate,
    sources,
    changed,
    previous_rate
):

    old = get_previous_live()

    live = {

        "rate_22k": rate,

        "rate_8g": rate * 8,

        "date": today_string(),

        "time": current_time_string(),

        "timezone": "Asia/Kolkata",

        "timestamp": iso_now(),

        "changed": bool(changed),

        "previous_rate_22k": previous_rate,

        "sources": [
            item["source"]
            for item in sources
        ],

        "source_details": sources,

        "last_fetch": iso_now(),

        "status": "live",

    }

    # Preserve existing useful information.
    if isinstance(old, dict):

        for key in (
            "last_change",
            "market_status",
        ):

            if key in old:
                live[key] = old[key]

    if changed:

        live["last_change"] = {
            "from": previous_rate,
            "to": rate,
            "date": today_string(),
            "time": current_time_string(),
            "timestamp": iso_now(),
        }

    save_json(
        LIVE_FILE,
        live
    )


# ============================================================
# SAVE HISTORY
# ============================================================

def save_history(
    rate,
    sources,
    changed
):

    raw = load_json(
        HISTORY_FILE,
        []
    )

    history = extract_history_records(
        raw
    )

    if not isinstance(history, list):
        history = []

    entry = {

        "date": today_string(),

        "time": current_time_string(),

        "timestamp": iso_now(),

        "rate_22k": rate,

        "rate_8g": rate * 8,

        "changed": bool(changed),

        "sources": [
            item["source"]
            for item in sources
        ],

    }

    # Do not create a duplicate entry if the last
    # record has the same date/time/rate.
    if history:

        last = history[-1]

        if (
            last.get("date")
            == entry["date"]
            and last.get("rate_22k")
            == entry["rate_22k"]
            and last.get("time")
            == entry["time"]
        ):
            return

    history.append(entry)

    # Keep plenty of historical data.
    history = history[-5000:]

    save_json(
        HISTORY_FILE,
        history
    )


# ============================================================
# ONE NORMAL FETCH
# ============================================================

def normal_fetch(previous_rate):

    print()
    print("NORMAL FETCH")

    results = fetch_all_sources()

    if not results:

        print(
            "Both sources failed."
        )

        print(
            "Keeping previous valid rate."
        )

        return

    # Prefer LiveChennai when available.
    primary = next(
        (
            item for item in results
            if item["source"] == "LiveChennai"
        ),
        None
    )

    if primary is None:
        primary = results[0]

    rate = primary["rate_22k"]

    changed = (
        previous_rate is not None
        and rate != previous_rate
    )

    print()
    print(
        f"Current 22K rate: ₹{rate:,}"
    )

    print(
        f"Previous 22K rate: "
        f"₹{previous_rate:,}"
        if previous_rate
        else
        "Previous 22K rate: NONE"
    )

    print(
        f"Changed: {changed}"
    )

    save_live(
        rate,
        results,
        changed,
        previous_rate
    )

    save_history(
        rate,
        results,
        changed
    )


# ============================================================
# FULL MONITOR
# ============================================================

def full_monitor(
    window,
    previous_rate
):

    start = window["start"]
    end = window["end"]

    print()
    print("=" * 70)
    print("FULL MONITORING WINDOW ACTIVE")
    print("=" * 70)

    print(
        f"Window: {window['name'].upper()}"
    )

    print(
        f"Start: {start.strftime('%I:%M:%S %p')}"
    )

    print(
        f"End:   {end.strftime('%I:%M:%S %p')}"
    )

    print(
        f"Polling every {POLL_SECONDS} seconds"
    )

    print(
        "Monitoring continues until a NEW price "
        "is discovered or the window ends."
    )

    print()

    # Safety limit.
    hard_end = min(
        end,
        now_ist()
        + timedelta(
            minutes=MAX_MONITOR_MINUTES
        )
    )

    attempt = 0

    while True:

        now = now_ist()

        if now >= hard_end:

            print()
            print("=" * 70)
            print("FULL MONITORING WINDOW FINISHED")
            print("=" * 70)

            print(
                "No new price discovered."
            )

            if previous_rate:
                print(
                    f"Retained rate: "
                    f"₹{previous_rate:,}"
                )

            return

        attempt += 1

        remaining = int(
            (
                hard_end - now
            ).total_seconds()
        )

        print(
            f"[{current_time_string()}] "
            f"Attempt #{attempt} "
            f"| remaining "
            f"{remaining // 60}m "
            f"{remaining % 60}s"
        )

        results = fetch_all_sources()

        if not results:

            print(
                "  No valid source result."
            )

        else:

            for item in results:

                print(
                    f"  {item['source']}: "
                    f"₹{item['rate_22k']:,}"
                )

            # ------------------------------------------------
            # PRIMARY RATE
            # ------------------------------------------------

            live = next(
                (
                    item for item in results
                    if item["source"]
                    == "LiveChennai"
                ),
                None
            )

            good = next(
                (
                    item for item in results
                    if item["source"]
                    == "GoodReturns"
                ),
                None
            )

            if live:

                candidate = live["rate_22k"]

            elif good:

                candidate = good["rate_22k"]

            else:

                candidate = None

            if candidate:

                # ------------------------------------------------
                # NEW PRICE DETECTED
                # ------------------------------------------------

                if (
                    previous_rate is not None
                    and candidate != previous_rate
                ):

                    print()
                    print("*" * 70)
                    print("NEW 22K GOLD PRICE DISCOVERED")
                    print("*" * 70)

                    print(
                        f"Previous: ₹{previous_rate:,}"
                    )

                    print(
                        f"New:      ₹{candidate:,}"
                    )

                    if live and good:

                        if (
                            live["rate_22k"]
                            == good["rate_22k"]
                        ):

                            print(
                                "Confirmation: "
                                "LiveChennai + GoodReturns AGREE"
                            )

                        else:

                            print(
                                "Sources differ; "
                                "LiveChennai used as primary."
                            )

                    save_live(
                        candidate,
                        results,
                        True,
                        previous_rate
                    )

                    save_history(
                        candidate,
                        results,
                        True
                    )

                    print()
                    print(
                        "NEW PRICE SAVED."
                    )

                    print(
                        "MONITORING STOPPED "
                        "BECAUSE NEW PRICE WAS FOUND."
                    )

                    return

                # ------------------------------------------------
                # FIRST EVER RATE
                # ------------------------------------------------

                if previous_rate is None:

                    print(
                        "No previous rate exists."
                    )

                    print(
                        "Saving initial valid rate."
                    )

                    save_live(
                        candidate,
                        results,
                        True,
                        None
                    )

                    save_history(
                        candidate,
                        results,
                        True
                    )

                    return

                print(
                    f"  No new price. "
                    f"Still ₹{candidate:,}"
                )

        # ----------------------------------------------------
        # WAIT 10 SECONDS
        # ----------------------------------------------------

        now = now_ist()

        seconds_left = int(
            (
                hard_end - now
            ).total_seconds()
        )

        if seconds_left <= 0:
            continue

        sleep_time = min(
            POLL_SECONDS,
            seconds_left
        )

        time.sleep(
            sleep_time
        )


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 70)
    print("CHENNAI 22K GOLD RATE")
    print("ADAPTIVE FULL-WINDOW MONITOR")
    print("=" * 70)

    print(
        f"IST: "
        f"{now_ist().strftime('%d-%m-%Y %I:%M:%S %p')}"
    )

    # --------------------------------------------------------
    # FIRST: LEARN / UPDATE WINDOWS
    # --------------------------------------------------------

    windows = learn_windows()

    print()
    print("CURRENT LEARNED WINDOWS")

    print(
        f"AM: "
        f"{windows['am']['start']} - "
        f"{windows['am']['end']}"
    )

    print(
        f"PM: "
        f"{windows['pm']['start']} - "
        f"{windows['pm']['end']}"
    )

    previous_rate = get_previous_rate()

    print()

    if previous_rate:
        print(
            f"Previous saved rate: "
            f"₹{previous_rate:,}"
        )
    else:
        print(
            "Previous saved rate: NONE"
        )

    # --------------------------------------------------------
    # DETERMINE ACTIVE WINDOW
    # --------------------------------------------------------

    window = active_window(
        windows
    )

    if window:

        print()
        print(
            "CURRENTLY INSIDE "
            "MONITORING WINDOW."
        )

        full_monitor(
            window,
            previous_rate
        )

    else:

        print()
        print(
            "CURRENTLY OUTSIDE "
            "MONITORING WINDOW."
        )

        print(
            "Performing ONE normal fetch "
            "and exiting."
        )

        normal_fetch(
            previous_rate
        )

    print()
    print("=" * 70)
    print("UPDATE COMPLETE")
    print("=" * 70)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    try:
        main()

    except KeyboardInterrupt:

        print()
        print(
            "Monitor manually stopped."
        )

        sys.exit(0)

    except Exception as exc:

        print()
        print("=" * 70)
        print("FATAL ERROR")
        print("=" * 70)

        print(str(exc))

        sys.exit(1)
