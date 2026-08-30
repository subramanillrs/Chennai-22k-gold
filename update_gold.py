#!/usr/bin/env python3

import json
import os
import re
import sys
import time
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

AM_START = (8, 30)
AM_END = (11, 30)

PM_START = (17, 0)
PM_END = (20, 0)


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

    match = re.search(r"\d+(?:\.\d+)?", text)

    if not match:
        return None

    try:
        return int(float(match.group(0)))
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
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

    temp.replace(path)


# ============================================================
# VALID RATE
# ============================================================

def valid_gold_rate(value):
    if value is None:
        return False

    try:
        value = int(value)
    except Exception:
        return False

    return 5000 <= value <= 50000


# ============================================================
# LIVECHENNAI
#
# CURRENT PAGE STRUCTURE:
#
# Date | Pure Gold (24 k) | Standard Gold (22 K)
#      | 1 Gm | 8 Gm | 1 Gm | 8 Gm
#
# Example:
# 30/August/2026 | 15824 | 126592 | 14505 | 116040
#
# We specifically locate the Standard Gold (22 K) column.
# ============================================================

def extract_livechennai_22k(soup):
    tables = soup.find_all("table")

    for table in tables:

        rows = table.find_all("tr")

        if not rows:
            continue

        header_text = " ".join(
            row.get_text(" ", strip=True)
            for row in rows[:5]
        )

        normalized = re.sub(
            r"\s+",
            " ",
            header_text
        ).lower()

        # This is the important identification.
        if (
            "standard gold" in normalized
            and "22 k" in normalized
        ):

            print(
                "LiveChennai: Found Standard Gold (22 K) table"
            )

            # ------------------------------------------------
            # First try to read the first data row.
            # ------------------------------------------------

            for row in rows:

                cells = row.find_all(
                    ["td", "th"]
                )

                values = []

                for cell in cells:
                    value = clean_number(
                        cell.get_text(
                            " ",
                            strip=True
                        )
                    )

                    if value is not None:
                        values.append(value)

                # A normal data row has:
                #
                # date
                # 24K 1g
                # 24K 8g
                # 22K 1g
                # 22K 8g
                #
                # The 22K 1g value is normally
                # the third numeric value.

                if len(values) >= 4:

                    candidates = values[-4:]

                    # Last four numeric values should be:
                    # 24K 1g
                    # 24K 8g
                    # 22K 1g
                    # 22K 8g

                    candidate = candidates[2]

                    if valid_gold_rate(candidate):

                        print(
                            "LiveChennai parser result:",
                            format_rupees(candidate),
                            "/gram"
                        )

                        return candidate

            # ------------------------------------------------
            # Fallback: inspect table text.
            # ------------------------------------------------

            table_text = table.get_text(
                " ",
                strip=True
            )

            # Look for a date followed by four prices.
            matches = re.findall(
                r"\d{1,2}/[A-Za-z]+/\d{4}"
                r".{0,100}?"
                r"([\d,]+)"
                r".{0,30}?"
                r"([\d,]+)"
                r".{0,30}?"
                r"([\d,]+)"
                r".{0,30}?"
                r"([\d,]+)",
                table_text,
                flags=re.IGNORECASE
            )

            for match in matches:

                values = [
                    clean_number(x)
                    for x in match
                ]

                if len(values) == 4:

                    candidate = values[2]

                    if valid_gold_rate(candidate):

                        print(
                            "LiveChennai fallback parser result:",
                            format_rupees(candidate),
                            "/gram"
                        )

                        return candidate

    # ========================================================
    # SECOND FALLBACK
    #
    # Current LiveChennai page also contains:
    #
    # Today's 22K Rate
    # ₹14,505
    # ========================================================

    page_text = soup.get_text(
        " ",
        strip=True
    )

    page_text = re.sub(
        r"\s+",
        " ",
        page_text
    )

    patterns = [

        r"Today's\s+22K\s+Rate\s*₹?\s*([\d,]+)",

        r"Today's\s+22K\s+gold\s+rate"
        r".{0,100}?"
        r"₹\s*([\d,]+)",

        r"22K\s+gold\s+rate"
        r".{0,100}?"
        r"₹\s*([\d,]+)",

        r"22\s*carat\s+gold\s+rate"
        r".{0,100}?"
        r"₹\s*([\d,]+)",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            page_text,
            flags=re.IGNORECASE
        )

        if match:

            value = clean_number(
                match.group(1)
            )

            if valid_gold_rate(value):

                print(
                    "LiveChennai text parser result:",
                    format_rupees(value),
                    "/gram"
                )

                return value

    return None


def fetch_livechennai():

    print("Checking LiveChennai...")

    try:

        response = SESSION.get(
            LIVECHENNAI_URL,
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()

        print(
            f"LiveChennai HTTP: {response.status_code}"
        )

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        rate = extract_livechennai_22k(
            soup
        )

        if rate:

            print(
                "LiveChennai:",
                format_rupees(rate),
                "/gram"
            )

            return {
                "source": "LiveChennai",
                "rate_22k": int(rate),
                "url": LIVECHENNAI_URL,
                "fetched_at": now_ist().isoformat()
            }

        print(
            "LiveChennai: Could not locate valid 22K rate"
        )

    except Exception as exc:

        print(
            f"LiveChennai failed: {exc}"
        )

    return None


# ============================================================
# GOODRETURNS
# ============================================================

def extract_goodreturns_22k(soup):

    # --------------------------------------------------------
    # First inspect tables.
    # --------------------------------------------------------

    for table in soup.find_all("table"):

        text = table.get_text(
            " ",
            strip=True
        )

        normalized = re.sub(
            r"\s+",
            " ",
            text
        ).lower()

        if (
            "22k" in normalized
            or "22 k" in normalized
            or "22 karat" in normalized
        ):

            rows = table.find_all("tr")

            for row in rows:

                cells = row.find_all(
                    ["td", "th"]
                )

                row_text = row.get_text(
                    " ",
                    strip=True
                )

                if re.search(
                    r"22\s*k|22\s*karat",
                    row_text,
                    re.IGNORECASE
                ):

                    numbers = []

                    for cell in cells:

                        value = clean_number(
                            cell.get_text(
                                " ",
                                strip=True
                            )
                        )

                        if valid_gold_rate(value):
                            numbers.append(value)

                    if numbers:

                        # Prefer the first valid 22K value.
                        for value in numbers:

                            if valid_gold_rate(value):

                                return value

    # --------------------------------------------------------
    # Text fallback.
    # --------------------------------------------------------

    text = soup.get_text(
        " ",
        strip=True
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    patterns = [

        r"22K\s+Gold\s*/g\s*₹?\s*([\d,]+)",

        r"22K\s+Gold\s+/?g\s*₹?\s*([\d,]+)",

        r"22K\s+Gold"
        r".{0,80}?"
        r"₹\s*([\d,]+)",

        r"22\s*karat\s+gold"
        r".{0,100}?"
        r"₹\s*([\d,]+)",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE
        )

        if match:

            value = clean_number(
                match.group(1)
            )

            if valid_gold_rate(value):
                return value

    return None


def fetch_goodreturns():

    print("Checking GoodReturns...")

    try:

        response = SESSION.get(
            GOODRETURNS_URL,
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()

        print(
            f"GoodReturns HTTP: {response.status_code}"
        )

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        rate = extract_goodreturns_22k(
            soup
        )

        if rate:

            print(
                "GoodReturns:",
                format_rupees(rate),
                "/gram"
            )

            return {
                "source": "GoodReturns",
                "rate_22k": int(rate),
                "url": GOODRETURNS_URL,
                "fetched_at": now_ist().isoformat()
            }

        print(
            "GoodReturns: Could not locate valid 22K rate"
        )

    except Exception as exc:

        print(
            f"GoodReturns failed: {exc}"
        )

    return None


# ============================================================
# FETCH BOTH SOURCES
# ============================================================

def fetch_all_sources():

    live = fetch_livechennai()

    good = fetch_goodreturns()

    return live, good


# ============================================================
# SELECT BEST RATE
# ============================================================

def select_rate(
    live,
    good,
    previous_rate=None
):

    live_rate = (
        live["rate_22k"]
        if live
        else None
    )

    good_rate = (
        good["rate_22k"]
        if good
        else None
    )

    print("")

    print(
        "SOURCE RESULTS"
    )

    print(
        "LiveChennai:",
        format_rupees(live_rate)
    )

    print(
        "GoodReturns:",
        format_rupees(good_rate)
    )

    # --------------------------------------------------------
    # Both sources agree.
    # --------------------------------------------------------

    if (
        live_rate is not None
        and good_rate is not None
        and live_rate == good_rate
    ):

        print(
            "Sources agree."
        )

        return {
            "rate_22k": live_rate,
            "agreement": True,
            "source": "LiveChennai + GoodReturns",
            "livechennai": live,
            "goodreturns": good
        }

    # --------------------------------------------------------
    # LiveChennai only.
    # --------------------------------------------------------

    if (
        live_rate is not None
        and good_rate is None
    ):

        print(
            "Only LiveChennai returned a valid rate."
        )

        return {
            "rate_22k": live_rate,
            "agreement": False,
            "source": "LiveChennai",
            "livechennai": live,
            "goodreturns": good
        }

    # --------------------------------------------------------
    # GoodReturns only.
    # --------------------------------------------------------

    if (
        live_rate is None
        and good_rate is not None
    ):

        print(
            "Only GoodReturns returned a valid rate."
        )

        return {
            "rate_22k": good_rate,
            "agreement": False,
            "source": "GoodReturns",
            "livechennai": live,
            "goodreturns": good
        }

    # --------------------------------------------------------
    # Both available but different.
    # --------------------------------------------------------

    if (
        live_rate is not None
        and good_rate is not None
        and live_rate != good_rate
    ):

        print("")
        print(
            "WARNING: SOURCES DISAGREE"
        )

        print(
            "LiveChennai:",
            format_rupees(live_rate)
        )

        print(
            "GoodReturns:",
            format_rupees(good_rate)
        )

        # Do not allow a suspicious difference
        # to overwrite a known good rate.

        if previous_rate is not None:

            print(
                "Keeping previous saved rate:",
                format_rupees(previous_rate)
            )

            return {
                "rate_22k": previous_rate,
                "agreement": False,
                "source": "Previous rate - sources disagree",
                "livechennai": live,
                "goodreturns": good
            }

        # No previous value.
        # Prefer LiveChennai.

        return {
            "rate_22k": live_rate,
            "agreement": False,
            "source": "LiveChennai - sources disagree",
            "livechennai": live,
            "goodreturns": good
        }

    return None


# ============================================================
# PREVIOUS RATE
# ============================================================

def get_previous_rate():

    data = load_json(
        LIVE_FILE,
        {}
    )

    if isinstance(data, dict):

        for key in (
            "rate_22k",
            "gold_22k",
            "rate",
            "price_22k"
        ):

            value = data.get(key)

            if isinstance(
                value,
                (int, float)
            ):

                value = int(value)

                if valid_gold_rate(value):
                    return value

    return None


# ============================================================
# HISTORY
# ============================================================

def extract_history_records(data):

    if isinstance(data, list):
        return data

    if isinstance(data, dict):

        for key in (
            "records",
            "history",
            "data",
            "prices"
        ):

            value = data.get(key)

            if isinstance(value, list):
                return value

    return []


def save_history(
    rate,
    selected,
    changed
):

    existing = load_json(
        HISTORY_FILE,
        []
    )

    records = extract_history_records(
        existing
    )

    current = now_ist()

    today = current.strftime(
        "%Y-%m-%d"
    )

    current_time = current.strftime(
        "%H:%M:%S"
    )

    record = {

        "date": today,

        "time": current_time,

        "timestamp": current.isoformat(),

        "rate_22k": int(rate),

        "rate_8g": int(rate * 8),

        "changed": bool(changed),

        "source": selected.get(
            "source",
            "Unknown"
        ),

        "agreement": bool(
            selected.get(
                "agreement",
                False
            )
        ),

        "livechennai_rate": (
            selected["livechennai"]["rate_22k"]
            if selected.get("livechennai")
            else None
        ),

        "goodreturns_rate": (
            selected["goodreturns"]["rate_22k"]
            if selected.get("goodreturns")
            else None
        )
    }

    # --------------------------------------------------------
    # Avoid duplicate observations.
    # --------------------------------------------------------

    duplicate = False

    if records:

        last = records[-1]

        if isinstance(last, dict):

            if (
                last.get("rate_22k")
                == int(rate)
                and last.get("date")
                == today
            ):

                duplicate = True

    if not duplicate:

        records.append(record)

    # --------------------------------------------------------
    # Preserve existing history structure.
    # --------------------------------------------------------

    if (
        isinstance(existing, list)
        or not isinstance(existing, dict)
    ):

        save_json(
            HISTORY_FILE,
            records
        )

    else:

        output = dict(existing)

        if "records" in existing:

            output["records"] = records

        elif "history" in existing:

            output["history"] = records

        elif "data" in existing:

            output["data"] = records

        elif "prices" in existing:

            output["prices"] = records

        else:

            output["records"] = records

        save_json(
            HISTORY_FILE,
            output
        )


# ============================================================
# LIVE DATA
# ============================================================

def save_live(
    rate,
    selected,
    changed
):

    current = now_ist()

    previous = load_json(
        LIVE_FILE,
        {}
    )

    if not isinstance(
        previous,
        dict
    ):

        previous = {}

    output = dict(previous)

    output.update(
        {

            "rate_22k": int(rate),

            "rate_8g": int(rate * 8),

            "date": current.strftime(
                "%Y-%m-%d"
            ),

            "time": current.strftime(
                "%H:%M:%S"
            ),

            "timestamp": current.isoformat(),

            "changed": bool(changed),

            "source": selected.get(
                "source",
                "Unknown"
            ),

            "agreement": bool(
                selected.get(
                    "agreement",
                    False
                )
            ),

            "sources": {

                "livechennai": (
                    selected["livechennai"]
                    if selected.get(
                        "livechennai"
                    )
                    else None
                ),

                "goodreturns": (
                    selected["goodreturns"]
                    if selected.get(
                        "goodreturns"
                    )
                    else None
                )
            },

            "last_checked": current.isoformat()
        }
    )

    save_json(
        LIVE_FILE,
        output
    )


# ============================================================
# MONITORING WINDOWS
# ============================================================

def make_datetime(
    day,
    hour,
    minute
):

    return datetime(
        day.year,
        day.month,
        day.day,
        hour,
        minute,
        0,
        tzinfo=IST
    )


def current_window(now=None):

    if now is None:
        now = now_ist()

    today = now.date()

    am_start = make_datetime(
        today,
        AM_START[0],
        AM_START[1]
    )

    am_end = make_datetime(
        today,
        AM_END[0],
        AM_END[1]
    )

    pm_start = make_datetime(
        today,
        PM_START[0],
        PM_START[1]
    )

    pm_end = make_datetime(
        today,
        PM_END[0],
        PM_END[1]
    )

    if (
        am_start
        <= now
        < am_end
    ):

        return {
            "name": "AM",
            "start": am_start,
            "end": am_end
        }

    if (
        pm_start
        <= now
        < pm_end
    ):

        return {
            "name": "PM",
            "start": pm_start,
            "end": pm_end
        }

    return None


def next_window(now=None):

    if now is None:
        now = now_ist()

    today = now.date()

    am_start = make_datetime(
        today,
        AM_START[0],
        AM_START[1]
    )

    pm_start = make_datetime(
        today,
        PM_START[0],
        PM_START[1]
    )

    if now < am_start:

        return {
            "name": "AM",
            "start": am_start,
            "end": make_datetime(
                today,
                AM_END[0],
                AM_END[1]
            )
        }

    if now < pm_start:

        return {
            "name": "PM",
            "start": pm_start,
            "end": make_datetime(
                today,
                PM_END[0],
                PM_END[1]
            )
        }

    tomorrow = today + timedelta(
        days=1
    )

    return {
        "name": "AM",
        "start": make_datetime(
            tomorrow,
            AM_START[0],
            AM_START[1]
        ),
        "end": make_datetime(
            tomorrow,
            AM_END[0],
            AM_END[1]
        )
    }


def save_window_info(window):

    data = {

        "timezone": "Asia/Kolkata",

        "updated_at": now_ist().isoformat(),

        "windows": {

            "AM": {
                "start": "08:30",
                "end": "11:30"
            },

            "PM": {
                "start": "17:00",
                "end": "20:00"
            }
        },

        "active_window": (
            window["name"]
            if window
            else None
        ),

        "poll_seconds": POLL_SECONDS
    }

    save_json(
        WINDOW_FILE,
        data
    )


# ============================================================
# NORMAL FETCH
# ============================================================

def normal_fetch():

    print("")
    print("=" * 70)
    print("NORMAL FETCH")
    print("=" * 70)

    previous_rate = get_previous_rate()

    print(
        "Previous 22K rate:",
        format_rupees(previous_rate)
    )

    live, good = fetch_all_sources()

    selected = select_rate(
        live,
        good,
        previous_rate
    )

    if selected is None:

        print(
            "ERROR: No valid 22K rate found."
        )

        return False

    rate = selected["rate_22k"]

    changed = (
        previous_rate is not None
        and rate != previous_rate
    )

    print("")

    print(
        "Current 22K rate:",
        format_rupees(rate)
    )

    print(
        "Previous 22K rate:",
        format_rupees(previous_rate)
    )

    print(
        "Changed:",
        changed
    )

    # --------------------------------------------------------
    # Always update live.json.
    # --------------------------------------------------------

    save_live(
        rate,
        selected,
        changed
    )

    # --------------------------------------------------------
    # Save history.
    # --------------------------------------------------------

    save_history(
        rate,
        selected,
        changed
    )

    if changed:

        print("")
        print(
            "NEW PRICE DISCOVERED."
        )

    else:

        print("")
        print(
            "PRICE UNCHANGED."
        )

    return True


# ============================================================
# FULL 10-SECOND MONITOR
# ============================================================

def monitor_window(window):

    print("")
    print("=" * 70)
    print("FULL-WINDOW 10-SECOND MONITOR")
    print("=" * 70)

    print(
        "Window:",
        window["name"]
    )

    print(
        "Start:",
        window["start"].strftime(
            "%d-%m-%Y %H:%M:%S"
        )
    )

    print(
        "End:",
        window["end"].strftime(
            "%d-%m-%Y %H:%M:%S"
        )
    )

    print(
        f"Polling every {POLL_SECONDS} seconds."
    )

    print(
        "Monitoring will stop after a new price "
        "is confirmed or when the window ends."
    )

    print("=" * 70)

    previous_rate = get_previous_rate()

    print(
        "Previous saved 22K rate:",
        format_rupees(previous_rate)
    )

    attempt = 0

    while True:

        now = now_ist()

        # ----------------------------------------------------
        # WINDOW END
        # ----------------------------------------------------

        if now >= window["end"]:

            print("")
            print("=" * 70)
            print("MONITORING WINDOW ENDED")
            print("=" * 70)

            print(
                "No new price was discovered."
            )

            return False

        attempt += 1

        print("")
        print("-" * 70)

        print(
            f"FETCH #{attempt}"
        )

        print(
            "IST:",
            now.strftime(
                "%d-%m-%Y %H:%M:%S"
            )
        )

        print("-" * 70)

        # ----------------------------------------------------
        # FETCH
        # ----------------------------------------------------

        live, good = fetch_all_sources()

        selected = select_rate(
            live,
            good,
            previous_rate
        )

        if selected is None:

            print(
                "No valid rate returned."
            )

            print(
                f"Retrying in {POLL_SECONDS} seconds..."
            )

            time.sleep(
                POLL_SECONDS
            )

            continue

        current_rate = selected[
            "rate_22k"
        ]

        print("")

        print(
            "Selected 22K rate:",
            format_rupees(current_rate)
        )

        print(
            "Previous 22K rate:",
            format_rupees(previous_rate)
        )

        # ----------------------------------------------------
        # NEW PRICE
        # ----------------------------------------------------

        if (
            previous_rate is not None
            and current_rate != previous_rate
        ):

            print("")
            print("=" * 70)
            print("NEW GOLD PRICE DISCOVERED")
            print("=" * 70)

            print(
                "OLD:",
                format_rupees(previous_rate)
            )

            print(
                "NEW:",
                format_rupees(current_rate)
            )

            print(
                "CHANGE:",
                format_rupees(
                    current_rate
                    - previous_rate
                )
            )

            print(
                "Source:",
                selected["source"]
            )

            print("=" * 70)

            save_live(
                current_rate,
                selected,
                True
            )

            save_history(
                current_rate,
                selected,
                True
            )

            print(
                "NEW PRICE SAVED."
            )

            print(
                "MONITORING STOPPED."
            )

            return True

        # ----------------------------------------------------
        # SAME PRICE
        # ----------------------------------------------------

        print(
            "No price change."
        )

        save_live(
            current_rate,
            selected,
            False
        )

        # ----------------------------------------------------
        # WAIT
        # ----------------------------------------------------

        remaining = (
            window["end"]
            - now_ist()
        ).total_seconds()

        if remaining <= 0:
            continue

        sleep_for = min(
            POLL_SECONDS,
            max(1, int(remaining))
        )

        print(
            f"Next fetch in {sleep_for} seconds..."
        )

        time.sleep(
            sleep_for
        )


# ============================================================
# MAIN
# ============================================================

def main():

    print("")
    print("=" * 70)
    print("CHENNAI 22K GOLD RATE")
    print("FULL-WINDOW ADAPTIVE MONITOR")
    print("=" * 70)

    now = now_ist()

    print(
        "IST:",
        now.strftime(
            "%d-%m-%Y %H:%M:%S"
        )
    )

    print(
        "LiveChennai:",
        LIVECHENNAI_URL
    )

    print(
        "GoodReturns:",
        GOODRETURNS_URL
    )

    print(
        f"Polling interval: {POLL_SECONDS} seconds"
    )

    print("=" * 70)

    # --------------------------------------------------------
    # ENVIRONMENT
    # --------------------------------------------------------

    github_actions = (
        os.environ.get(
            "GITHUB_ACTIONS",
            ""
        ).lower()
        == "true"
    )

    github_event = os.environ.get(
        "GITHUB_EVENT_NAME",
        ""
    )

    force_fetch = (
        os.environ.get(
            "FORCE_FETCH",
            ""
        ).lower()
        == "true"
    )

    print(
        "GITHUB_ACTIONS:",
        github_actions
    )

    print(
        "GITHUB_EVENT_NAME:",
        github_event or "local"
    )

    print(
        "FORCE_FETCH:",
        force_fetch
    )

    # ========================================================
    # FORCE FETCH
    #
    # Manual GitHub Fetch should work immediately.
    # It must NOT wait for 08:30 or 17:00.
    # ========================================================

    if force_fetch:

        print("")
        print("=" * 70)
        print("FORCED FETCH REQUEST")
        print("=" * 70)

        print(
            "Monitoring-window restriction bypassed."
        )

        print(
            "Fetching LiveChennai + GoodReturns immediately."
        )

        print("=" * 70)

        success = normal_fetch()

        print("")
        print("=" * 70)
        print(
            "FORCED FETCH COMPLETE"
        )
        print("=" * 70)

        if not success:
            sys.exit(1)

        return

    # ========================================================
    # CURRENT WINDOW
    # ========================================================

    window = current_window(now)

    if window:

        save_window_info(
            window
        )

        monitor_window(
            window
        )

        return

    # ========================================================
    # SCHEDULED GITHUB RUN
    # ========================================================

    if (
        github_actions
        and github_event == "schedule"
    ):

        upcoming = next_window(now)

        print("")
        print(
            "Scheduled GitHub run detected."
        )

        print(
            "Waiting for monitoring window."
        )

        print(
            f"Next window: {upcoming['name']}"
        )

        print(
            "Starts:",
            upcoming["start"].strftime(
                "%d-%m-%Y %H:%M:%S"
            )
        )

        while True:

            now = now_ist()

            window = current_window(
                now
            )

            if window:

                save_window_info(
                    window
                )

                monitor_window(
                    window
                )

                return

            time.sleep(30)

    # ========================================================
    # LOCAL / OTHER MANUAL RUN
    # ========================================================

    print("")
    print(
        "Outside monitoring window."
    )

    print(
        "Performing one normal fetch."
    )

    success = normal_fetch()

    if not success:
        sys.exit(1)

    print("")
    print("=" * 70)
    print("UPDATE COMPLETE")
    print("=" * 70)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print("")
        print(
            "Monitoring interrupted."
        )

        sys.exit(1)

    except Exception as exc:

        print("")
        print("=" * 70)
        print("FATAL ERROR")
        print("=" * 70)

        print(
            repr(exc)
        )

        sys.exit(1)
