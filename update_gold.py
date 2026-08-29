import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from statistics import median
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup


# ============================================================
# CHENNAI 22K GOLD RATE
# ADAPTIVE FULL-WINDOW MONITOR
# ============================================================

IST = ZoneInfo("Asia/Kolkata")

LIVE_FILE = "data/live.json"
HISTORY_FILE = "data/history.json"
WINDOW_FILE = "data/monitoring_windows.json"

LIVECHENNAI_URL = "https://www.livechennai.com/gold_silverrate.asp"
GOODRETURNS_URL = "https://www.goodreturns.in/gold-rates/chennai.html"

POLL_SECONDS = 10
REQUEST_TIMEOUT = 8

# Validation only - NOT a prediction range.
MIN_VALID_RATE = 5000
MAX_VALID_RATE = 30000

# Absolute safety limit for one monitoring session.
MAX_MONITOR_MINUTES = 190

THREE_MONTH_DAYS = 92
THIRTY_DAY_DAYS = 30

# Safe windows if genuine intraday historical timing
# is insufficient.
DEFAULT_AM_START = "08:30"
DEFAULT_AM_END = "11:30"

DEFAULT_PM_START = "15:30"
DEFAULT_PM_END = "18:30"

MIN_WINDOW_MINUTES = 90
MAX_WINDOW_MINUTES = 210

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/18.0 Safari/605.1.15"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,*/*;q=0.8"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

os.makedirs("data", exist_ok=True)


# ============================================================
# BASIC HELPERS
# ============================================================

def now_ist():
    return datetime.now(IST)


def iso_now():
    return now_ist().isoformat()


def today_string():
    return now_ist().strftime("%Y-%m-%d")


def current_time_string():
    return now_ist().strftime("%H:%M:%S")


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


def clean_rate(value):
    if value is None:
        return None

    digits = re.sub(r"[^\d]", "", str(value))

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
# TIME PARSING
# ============================================================

def parse_hhmm(value):
    try:
        hour, minute = str(value).split(":")
        return int(hour), int(minute)
    except Exception:
        return None


def hhmm_to_minutes(value):
    parsed = parse_hhmm(value)

    if not parsed:
        return None

    return parsed[0] * 60 + parsed[1]


def minutes_to_hhmm(value):
    value = max(0, min(1439, int(value)))

    hour = value // 60
    minute = value % 60

    return f"{hour:02d}:{minute:02d}"


def round_to_5(value):
    return int(round(value / 5.0) * 5)


# ============================================================
# HISTORY EXTRACTION
# ============================================================

def extract_history_records(data):

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


def get_history_rate(item):

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
# IMPORTANT:
# ONLY USE A REAL TIMESTAMP FOR LEARNING.
#
# We deliberately DO NOT assume that the history record's
# date/time represents the actual gold price change time.
# ============================================================

def parse_genuine_timestamp(item):

    if not isinstance(item, dict):
        return None

    # These are potentially genuine timestamps.
    timestamp_keys = (
        "source_update_time",
        "livechennai_update_time",
        "actual_update_time",
        "price_update_time",
        "source_timestamp",
    )

    for key in timestamp_keys:

        value = item.get(key)

        if not value:
            continue

        parsed = parse_timestamp_value(value)

        if parsed:
            return parsed

    # source_details may contain the actual source update time.
    details = item.get("source_details")

    if isinstance(details, list):

        for source in details:

            if not isinstance(source, dict):
                continue

            source_name = str(
                source.get("source", "")
            ).lower()

            if "livechennai" not in source_name:
                continue

            value = source.get("update_time")

            if value:

                parsed = parse_timestamp_value(
                    value,
                    fallback_date=item.get("date")
                )

                if parsed:
                    return parsed

    return None


def parse_timestamp_value(
    value,
    fallback_date=None
):

    text = str(value).strip()

    # ISO timestamp.
    try:

        iso_text = text

        if iso_text.endswith("Z"):
            iso_text = iso_text[:-1] + "+00:00"

        dt = datetime.fromisoformat(
            iso_text
        )

        if dt.tzinfo is None:
            dt = dt.replace(
                tzinfo=IST
            )

        return dt.astimezone(IST)

    except Exception:
        pass

    # LiveChennai:
    # 29/08/2026 9:44:41 AM
    formats = [
        "%d/%m/%Y %I:%M:%S %p",
        "%d/%m/%Y %I:%M %p",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d-%m-%Y %I:%M:%S %p",
        "%d-%m-%Y %I:%M %p",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    ]

    for fmt in formats:

        try:

            dt = datetime.strptime(
                text,
                fmt
            )

            return dt.replace(
                tzinfo=IST
            )

        except Exception:
            pass

    # If only a time was supplied, use the record date.
    if fallback_date:

        combined = (
            f"{fallback_date} {text}"
        )

        date_formats = [
            "%Y-%m-%d %I:%M:%S %p",
            "%Y-%m-%d %I:%M %p",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%d/%m/%Y %I:%M:%S %p",
            "%d/%m/%Y %I:%M %p",
        ]

        for fmt in date_formats:

            try:

                dt = datetime.strptime(
                    combined,
                    fmt
                )

                return dt.replace(
                    tzinfo=IST
                )

            except Exception:
                pass

    return None


# ============================================================
# LEARN WINDOWS
# ============================================================

def learn_windows():

    print()
    print("=" * 70)
    print("LEARNING MONITORING WINDOWS")
    print("=" * 70)

    raw = load_json(
        HISTORY_FILE,
        []
    )

    records = extract_history_records(
        raw
    )

    cutoff_92 = (
        now_ist()
        - timedelta(days=THREE_MONTH_DAYS)
    )

    cutoff_30 = (
        now_ist()
        - timedelta(days=THIRTY_DAY_DAYS)
    )

    genuine = []

    for item in records:

        rate = get_history_rate(item)

        if not rate:
            continue

        dt = parse_genuine_timestamp(item)

        # CRITICAL:
        # Do NOT use the generic record date/time here.
        if not dt:
            continue

        if dt < cutoff_92:
            continue

        genuine.append({
            "dt": dt,
            "rate": rate,
        })

    genuine.sort(
        key=lambda x: x["dt"]
    )

    print(
        f"Historical records: {len(records)}"
    )

    print(
        f"Genuine timestamped observations: "
        f"{len(genuine)}"
    )

    # --------------------------------------------------------
    # Find actual changes ONLY between genuine timestamps.
    # --------------------------------------------------------

    changes = []

    previous_rate = None

    for item in genuine:

        if (
            previous_rate is not None
            and item["rate"] != previous_rate
        ):

            changes.append(item)

        previous_rate = item["rate"]

    print(
        f"Genuine timed price changes: "
        f"{len(changes)}"
    )

    # --------------------------------------------------------
    # Separate AM and PM.
    # --------------------------------------------------------

    am_all = []
    pm_all = []

    am_recent = []
    pm_recent = []

    for item in changes:

        dt = item["dt"]

        minute = (
            dt.hour * 60
            + dt.minute
        )

        if 6 * 60 <= minute < 14 * 60:

            am_all.append(minute)

            if dt >= cutoff_30:
                am_recent.append(minute)

        elif 14 * 60 <= minute <= 22 * 60:

            pm_all.append(minute)

            if dt >= cutoff_30:
                pm_recent.append(minute)

    print(
        f"AM genuine changes: {len(am_all)}"
    )

    print(
        f"PM genuine changes: {len(pm_all)}"
    )

    print(
        f"AM last 30 days: {len(am_recent)}"
    )

    print(
        f"PM last 30 days: {len(pm_recent)}"
    )

    # --------------------------------------------------------
    # If there isn't enough genuine timestamp data,
    # DO NOT INVENT a window.
    # --------------------------------------------------------

    MIN_GENUINE_OBSERVATIONS = 5

    if len(am_all) < MIN_GENUINE_OBSERVATIONS:

        print()
        print(
            "Not enough genuine AM timestamps."
        )

        print(
            "AM will use safe established window:"
        )

        print(
            f"{DEFAULT_AM_START} - "
            f"{DEFAULT_AM_END}"
        )

        am_window = {
            "start": DEFAULT_AM_START,
            "end": DEFAULT_AM_END,
        }

        am_mode = "safe_default"

    else:

        am_window = calculate_window(
            am_all,
            am_recent
        )

        am_mode = "learned"

    if len(pm_all) < MIN_GENUINE_OBSERVATIONS:

        print()
        print(
            "Not enough genuine PM timestamps."
        )

        print(
            "PM will use safe established window:"
        )

        print(
            f"{DEFAULT_PM_START} - "
            f"{DEFAULT_PM_END}"
        )

        pm_window = {
            "start": DEFAULT_PM_START,
            "end": DEFAULT_PM_END,
        }

        pm_mode = "safe_default"

    else:

        pm_window = calculate_window(
            pm_all,
            pm_recent
        )

        pm_mode = "learned"

    learned = {

        "am": am_window,

        "pm": pm_window,

        "learned_at": iso_now(),

        "learning_period_days": THREE_MONTH_DAYS,

        "recent_weight_days": THIRTY_DAY_DAYS,

        "recent_weight_multiplier": 3,

        "total_history_records": len(records),

        "genuine_timestamped_observations": len(
            genuine
        ),

        "genuine_timed_changes": len(
            changes
        ),

        "am_observations": len(am_all),

        "pm_observations": len(pm_all),

        "am_recent_observations": len(
            am_recent
        ),

        "pm_recent_observations": len(
            pm_recent
        ),

        "am_mode": am_mode,

        "pm_mode": pm_mode,

        "important_note": (
            "Only genuine source update timestamps "
            "are used for learning. Generic history "
            "record timestamps are ignored."
        ),
    }

    save_json(
        WINDOW_FILE,
        learned
    )

    print()
    print("=" * 70)
    print("LEARNED / VERIFIED WINDOWS")
    print("=" * 70)

    print(
        f"AM: {am_window['start']} - "
        f"{am_window['end']} "
        f"({am_mode})"
    )

    print(
        f"PM: {pm_window['start']} - "
        f"{pm_window['end']} "
        f"({pm_mode})"
    )

    print(
        f"Saved: {WINDOW_FILE}"
    )

    return learned


def calculate_window(
    all_values,
    recent_values
):

    # 3x weighting for last 30 days.
    weighted = list(all_values)

    for value in recent_values:
        weighted.append(value)
        weighted.append(value)

    center = int(
        median(weighted)
    )

    # Use spread to determine a reasonable width.
    spread = 0

    if len(all_values) >= 3:

        spread = (
            max(all_values)
            - min(all_values)
        )

    width = spread + 60

    width = max(
        MIN_WINDOW_MINUTES,
        min(
            MAX_WINDOW_MINUTES,
            width
        )
    )

    half = width / 2

    start = round_to_5(
        center - half
    )

    end = round_to_5(
        center + half
    )

    start = max(0, start)
    end = min(1439, end)

    return {
        "start": minutes_to_hhmm(start),
        "end": minutes_to_hhmm(end),
    }


# ============================================================
# LIVECHENNAI
# ============================================================

def fetch_livechennai():

    print(
        "  Checking LiveChennai..."
    )

    try:

        response = requests.get(
            LIVECHENNAI_URL,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT
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

        # ----------------------------------------------------
        # LiveChennai current page has:
        #
        # Date | 1 Gm (22 K) | Silver 1 Gm
        #
        # and:
        #
        # Last Update Time:
        # 29/08/2026 9:44:41 AM
        # ----------------------------------------------------

        patterns = [

            r"1\s*Gm\s*\(\s*22\s*K\s*\)"
            r".{0,200}?([\d,]+)\s*\(",

            r"1\s*Gm\s*\(\s*22\s*K\s*\)"
            r".{0,200}?([\d,]+)",

            r"Standard\s+Gold\s*\(\s*22\s*K\s*\)"
            r".{0,300}?([\d,]+)",

            r"Today's\s+22K\s+Rate"
            r".{0,200}?₹?\s*([\d,]+)",

        ]

        for pattern in patterns:

            match = re.search(
                pattern,
                text,
                re.I | re.S
            )

            if match:

                candidate = clean_rate(
                    match.group(1)
                )

                if candidate:

                    rate = candidate
                    break

        # ----------------------------------------------------
        # More robust table extraction.
        # ----------------------------------------------------

        if not rate:

            for table in soup.find_all("table"):

                table_text = table.get_text(
                    " ",
                    strip=True
                )

                if (
                    "22 K" in table_text
                    or "22K" in table_text
                ):

                    # Look around 1 Gm (22 K).
                    match = re.search(
                        r"1\s*Gm\s*\(\s*22\s*K\s*\)"
                        r".{0,250}?([\d,]+)",
                        table_text,
                        re.I | re.S
                    )

                    if match:

                        candidate = clean_rate(
                            match.group(1)
                        )

                        if candidate:

                            rate = candidate
                            break

        if not rate:

            raise ValueError(
                "Could not locate valid Chennai 22K rate"
            )

        # ----------------------------------------------------
        # REAL LiveChennai update timestamp.
        # ----------------------------------------------------

        update_time = None

        time_patterns = [

            r"Last\s+Update\s+Time\s*:\s*"
            r"(\d{1,2}/\d{1,2}/\d{4}\s+"
            r"\d{1,2}:\d{2}:\d{2}\s*[AP]M)",

            r"Last\s+Update\s+Time\s*:\s*"
            r"(\d{1,2}/\d{1,2}/\d{4}\s+"
            r"\d{1,2}:\d{2}\s*[AP]M)",

        ]

        for pattern in time_patterns:

            match = re.search(
                pattern,
                text,
                re.I
            )

            if match:

                update_time = (
                    match.group(1)
                    .strip()
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
# GOODRETURNS
# ============================================================

def fetch_goodreturns():

    print(
        "  Checking GoodReturns..."
    )

    try:

        response = requests.get(
            GOODRETURNS_URL,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT
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

            r"22K\s*Gold\s*/g"
            r".{0,100}?₹?\s*([\d,]+)",

            r"22K\s*Gold"
            r".{0,150}?₹\s*([\d,]+)",

        ]

        for pattern in patterns:

            match = re.search(
                pattern,
                text,
                re.I | re.S
            )

            if match:

                candidate = clean_rate(
                    match.group(1)
                )

                if candidate:

                    rate = candidate
                    break

        # Table fallback.
        if not rate:

            for row in soup.find_all("tr"):

                row_text = row.get_text(
                    " ",
                    strip=True
                )

                if (
                    "22K" in row_text
                    and "₹" in row_text
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
                "Could not locate GoodReturns Chennai 22K rate"
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
# FETCH BOTH SOURCES
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
# CURRENT SAVED RATE
# ============================================================

def get_previous_rate():

    live = load_json(
        LIVE_FILE,
        {}
    )

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

    old = load_json(
        LIVE_FILE,
        {}
    )

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

    if isinstance(old, dict):

        if "last_change" in old:
            live["last_change"] = old[
                "last_change"
            ]

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

    # Store source update timestamp separately.
    source_update_time = None

    for source in sources:

        if (
            source.get("source")
            == "LiveChennai"
        ):

            source_update_time = (
                source.get("update_time")
            )

            break

    entry = {

        "date": today_string(),

        "time": current_time_string(),

        "timestamp": iso_now(),

        "rate_22k": rate,

        "rate_8g": rate * 8,

        "changed": bool(changed),

        "sources": [
            source["source"]
            for source in sources
        ],

        # IMPORTANT:
        # This is the genuine source timestamp.
        "source_update_time":
            source_update_time,

        "source_details": sources,

    }

    # Avoid exact duplicates.
    if history:

        last = history[-1]

        if (
            last.get("rate_22k")
            == entry["rate_22k"]
            and last.get("source_update_time")
            == entry["source_update_time"]
            and last.get("date")
            == entry["date"]
        ):

            return

    history.append(entry)

    history = history[-5000:]

    save_json(
        HISTORY_FILE,
        history
    )


# ============================================================
# NORMAL FETCH
# ============================================================

def normal_fetch(
    previous_rate
):

    print()
    print("NORMAL FETCH")

    results = fetch_all_sources()

    if not results:

        print(
            "Both sources failed."
        )

        print(
            "Previous verified rate retained."
        )

        return

    live = next(
        (
            item for item in results
            if item["source"]
            == "LiveChennai"
        ),
        None
    )

    primary = (
        live
        if live
        else results[0]
    )

    rate = primary["rate_22k"]

    changed = (
        previous_rate is not None
        and rate != previous_rate
    )

    print()
    print(
        f"Current 22K: ₹{rate:,}"
    )

    if previous_rate:

        print(
            f"Previous 22K: "
            f"₹{previous_rate:,}"
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
# FULL 10-SECOND MONITOR
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
        f"Start: "
        f"{start.strftime('%I:%M %p')}"
    )

    print(
        f"End:   "
        f"{end.strftime('%I:%M %p')}"
    )

    print(
        f"Polling interval: "
        f"{POLL_SECONDS} seconds"
    )

    print(
        "Will continue until a NEW price "
        "is found or the window ends."
    )

    # Absolute safety.
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
            print("MONITORING WINDOW FINISHED")
            print("=" * 70)

            if previous_rate:

                print(
                    f"Retained rate: "
                    f"₹{previous_rate:,}"
                )

            print(
                "No new price discovered."
            )

            return

        attempt += 1

        remaining = int(
            (
                hard_end - now
            ).total_seconds()
        )

        print()
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
                "No valid source result."
            )

        else:

            for item in results:

                print(
                    f"  {item['source']}: "
                    f"₹{item['rate_22k']:,}"
                )

                if item.get(
                    "update_time"
                ):

                    print(
                        f"    Source update: "
                        f"{item['update_time']}"
                    )

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

                candidate = (
                    live["rate_22k"]
                )

            elif good:

                candidate = (
                    good["rate_22k"]
                )

            else:

                candidate = None

            if candidate:

                # ------------------------------------------------
                # NEW PRICE
                # ------------------------------------------------

                if (
                    previous_rate is not None
                    and candidate != previous_rate
                ):

                    print()
                    print("*" * 70)
                    print(
                        "NEW 22K GOLD PRICE DISCOVERED"
                    )
                    print("*" * 70)

                    print(
                        f"Previous: "
                        f"₹{previous_rate:,}"
                    )

                    print(
                        f"New:      "
                        f"₹{candidate:,}"
                    )

                    if live and good:

                        if (
                            live["rate_22k"]
                            == good["rate_22k"]
                        ):

                            print(
                                "Confirmation: "
                                "LiveChennai + "
                                "GoodReturns AGREE"
                            )

                        else:

                            print(
                                "Sources differ. "
                                "LiveChennai is "
                                "primary."
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

                    print(
                        "NEW PRICE SAVED."
                    )

                    print(
                        "MONITORING STOPPED "
                        "AFTER NEW PRICE."
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

        remaining = int(
            (
                hard_end - now
            ).total_seconds()
        )

        if remaining <= 0:
            continue

        time.sleep(
            min(
                POLL_SECONDS,
                remaining
            )
        )


# ============================================================
# ACTIVE WINDOW
# ============================================================

def get_active_window(
    windows
):

    now = now_ist()

    current_minutes = (
        now.hour * 60
        + now.minute
    )

    for name in (
        "am",
        "pm"
    ):

        item = windows.get(
            name,
            {}
        )

        start = hhmm_to_minutes(
            item.get("start")
        )

        end = hhmm_to_minutes(
            item.get("end")
        )

        if (
            start is None
            or end is None
        ):
            continue

        if (
            start
            <= current_minutes
            <= end
        ):

            start_dt = now.replace(
                hour=start // 60,
                minute=start % 60,
                second=0,
                microsecond=0
            )

            end_dt = now.replace(
                hour=end // 60,
                minute=end % 60,
                second=0,
                microsecond=0
            )

            return {
                "name": name,
                "start": start_dt,
                "end": end_dt,
            }

    return None


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
        "IST:",
        now_ist().strftime(
            "%d-%m-%Y %I:%M:%S %p"
        )
    )

    # --------------------------------------------------------
    # LEARN WINDOWS
    # --------------------------------------------------------

    windows = learn_windows()

    print()
    print(
        "CURRENT WINDOWS"
    )

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
    # ACTIVE WINDOW
    # --------------------------------------------------------

    window = get_active_window(
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
            "Performing ONE normal fetch."
        )

        normal_fetch(
            previous_rate
        )

    print()
    print("=" * 70)
    print("UPDATE COMPLETE")
    print("=" * 70)


# ============================================================
# START
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

        print(
            str(exc)
        )

        sys.exit(1)
