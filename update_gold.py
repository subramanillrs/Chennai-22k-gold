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

LIVECHENNAI_URL = "https://www.livechennai.com/gold_silverrate.asp"
GOODRETURNS_URL = "https://www.goodreturns.in/gold-rates/chennai.html"

POLL_SECONDS = 10

# Actual monitoring windows
AM_START = (8, 30)
AM_END = (11, 30)

PM_START = (17, 0)
PM_END = (20, 0)

# GitHub scheduled jobs start shortly before these windows.
# The script waits until the actual monitoring window begins.
WAIT_FOR_WINDOW = True

REQUEST_TIMEOUT = 15


# ============================================================
# HTTP SESSION
# ============================================================

SESSION = requests.Session()

SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/18.0 Safari/605.1.15"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,*/*;q=0.8"
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

    # Remove currency symbols and commas.
    text = text.replace(",", "")
    text = text.replace("₹", "")
    text = text.replace("Rs.", "")
    text = text.replace("Rs", "")

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
# EXTRACT 22K RATE
# ============================================================

def extract_22k_rate_from_text(text):
    """
    Extract a Chennai 22K gold rate from page text.

    We deliberately look for 22K/22 carat context instead of
    taking the first number on the page.
    """

    if not text:
        return None

    text = re.sub(r"\s+", " ", text)

    patterns = [

        # Example:
        # 22K Gold /g ₹14,505
        r"22K\s*(?:Gold|gold)?\s*(?:/g|per\s*gram)?\s*"
        r"[:\-]?\s*₹?\s*([\d,]+)",

        # Example:
        # 22K Gold 1 Gram: ₹14,505
        r"22K\s+Gold\s+(?:1\s*Gram|/g)\s*[:\-]?\s*"
        r"₹?\s*([\d,]+)",

        # Example:
        # 22K gold rate is ₹14,505 per gram
        r"22K.*?(?:rate|price).*?"
        r"₹\s*([\d,]+).*?(?:gram|g)",

        # Example:
        # 22 Carat Gold ... ₹14,505
        r"22[\s-]*carat.*?"
        r"₹\s*([\d,]+).*?(?:gram|g)",

        # Example:
        # Standard Gold (22 K) ... 14,505
        r"Standard\s+Gold\s*\(22\s*K\).*?"
        r"₹?\s*([\d,]+)",

    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE | re.DOTALL
        )

        if match:
            value = clean_number(match.group(1))

            # Chennai 22K gram prices should be in a sensible range.
            if value and 5000 <= value <= 50000:
                return value

    return None


# ============================================================
# LIVECHENNAI FETCH
# ============================================================

def fetch_livechennai():
    print("Checking LiveChennai...")

    try:

        response = SESSION.get(
            LIVECHENNAI_URL,
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        text = soup.get_text(" ", strip=True)

        rate = extract_22k_rate_from_text(text)

        if rate:

            print(
                f"LiveChennai: "
                f"{format_rupees(rate)}/gram"
            )

            return {
                "source": "LiveChennai",
                "rate_22k": rate,
                "url": LIVECHENNAI_URL,
                "fetched_at": now_ist().isoformat()
            }

        print(
            "LiveChennai: Could not locate valid Chennai 22K rate"
        )

    except Exception as exc:

        print(
            f"LiveChennai failed: {exc}"
        )

    return None


# ============================================================
# GOODRETURNS FETCH
# ============================================================

def fetch_goodreturns():
    print("Checking GoodReturns...")

    try:

        response = SESSION.get(
            GOODRETURNS_URL,
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        text = soup.get_text(" ", strip=True)

        rate = extract_22k_rate_from_text(text)

        if rate:

            print(
                f"GoodReturns: "
                f"{format_rupees(rate)}/gram"
            )

            return {
                "source": "GoodReturns",
                "rate_22k": rate,
                "url": GOODRETURNS_URL,
                "fetched_at": now_ist().isoformat()
            }

        print(
            "GoodReturns: Could not locate valid Chennai 22K rate"
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

def select_rate(live, good, previous_rate=None):
    """
    Prefer agreement between both sources.

    If both sources agree:
        accept the rate.

    If only one source works:
        accept the available source.

    If both work but disagree:
        keep the previous rate when possible.
        This prevents one website parsing error from
        changing the app's price incorrectly.
    """

    live_rate = live["rate_22k"] if live else None
    good_rate = good["rate_22k"] if good else None

    # Both sources agree.
    if (
        live_rate is not None
        and good_rate is not None
        and live_rate == good_rate
    ):

        return {
            "rate_22k": live_rate,
            "agreement": True,
            "source": "LiveChennai + GoodReturns",
            "livechennai": live,
            "goodreturns": good
        }

    # Only LiveChennai available.
    if live_rate is not None and good_rate is None:

        return {
            "rate_22k": live_rate,
            "agreement": False,
            "source": "LiveChennai",
            "livechennai": live,
            "goodreturns": good
        }

    # Only GoodReturns available.
    if good_rate is not None and live_rate is None:

        return {
            "rate_22k": good_rate,
            "agreement": False,
            "source": "GoodReturns",
            "livechennai": live,
            "goodreturns": good
        }

    # Both available but disagree.
    if (
        live_rate is not None
        and good_rate is not None
        and live_rate != good_rate
    ):

        print(
            "WARNING: Sources disagree:"
        )

        print(
            f"  LiveChennai : {format_rupees(live_rate)}"
        )

        print(
            f"  GoodReturns : {format_rupees(good_rate)}"
        )

        if previous_rate is not None:

            print(
                f"Keeping previous rate: "
                f"{format_rupees(previous_rate)}"
            )

            return {
                "rate_22k": previous_rate,
                "agreement": False,
                "source": "Previous rate - sources disagree",
                "livechennai": live,
                "goodreturns": good
            }

        # If no previous value exists, prefer LiveChennai.
        return {
            "rate_22k": live_rate,
            "agreement": False,
            "source": "LiveChennai - sources disagree",
            "livechennai": live,
            "goodreturns": good
        }

    return None


# ============================================================
# READ PREVIOUS LIVE RATE
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

            if isinstance(value, (int, float)):
                return int(value)

    return None


# ============================================================
# HISTORY NORMALIZATION
# ============================================================

def extract_history_records(data):
    """
    Supports several possible existing history.json formats.
    """

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


# ============================================================
# SAVE HISTORY
# ============================================================

def save_history(rate, selected, changed):
    existing = load_json(
        HISTORY_FILE,
        []
    )

    records = extract_history_records(existing)

    current = now_ist()

    record = {
        "date": current.strftime("%Y-%m-%d"),
        "time": current.strftime("%H:%M:%S"),
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

    # Do not add an identical observation repeatedly.
    duplicate = False

    if records:

        last = records[-1]

        if isinstance(last, dict):

            last_rate = last.get(
                "rate_22k"
            )

            last_date = last.get(
                "date"
            )

            if (
                last_rate == int(rate)
                and last_date == current.strftime(
                    "%Y-%m-%d"
                )
            ):

                duplicate = True

    if not duplicate:
        records.append(record)

    # Preserve list-style history where possible.
    if isinstance(existing, list) or not isinstance(existing, dict):

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
# SAVE LIVE DATA
# ============================================================

def save_live(rate, selected, changed):
    current = now_ist()

    previous = load_json(
        LIVE_FILE,
        {}
    )

    if not isinstance(previous, dict):
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

            "sources": {
                "livechennai": (
                    selected["livechennai"]
                    if selected.get("livechennai")
                    else None
                ),

                "goodreturns": (
                    selected["goodreturns"]
                    if selected.get("goodreturns")
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
# MONITORING WINDOW
# ============================================================

def make_datetime(day, hour, minute):
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

    if am_start <= now < am_end:

        return {
            "name": "AM",
            "start": am_start,
            "end": am_end
        }

    if pm_start <= now < pm_end:

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

    tomorrow = today + timedelta(days=1)

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


# ============================================================
# SAVE MONITORING WINDOW
# ============================================================

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
# WAIT FOR MONITORING WINDOW
# ============================================================

def wait_until_window():
    """
    Used for scheduled GitHub Actions runs.

    Example:
        GitHub starts at 08:15
        script waits until 08:30
        monitoring starts
    """

    while True:

        now = now_ist()

        window = current_window(now)

        if window:

            save_window_info(window)

            return window

        upcoming = next_window(now)

        wait_seconds = (
            upcoming["start"] - now
        ).total_seconds()

        print("")
        print(
            "OUTSIDE MONITORING WINDOW"
        )

        print(
            f"Current IST time: "
            f"{now.strftime('%d-%m-%Y %H:%M:%S')}"
        )

        print(
            f"Next {upcoming['name']} "
            f"window starts: "
            f"{upcoming['start'].strftime('%d-%m-%Y %H:%M:%S')}"
        )

        print(
            f"Waiting approximately "
            f"{int(max(0, wait_seconds))} seconds..."
        )

        # Do not sleep for more than 60 seconds.
        # This allows the program to react promptly.
        sleep_for = min(
            60,
            max(1, int(wait_seconds))
        )

        time.sleep(sleep_for)


# ============================================================
# NORMAL ONE-TIME FETCH
# ============================================================

def normal_fetch():
    print("")
    print("=" * 70)
    print("NORMAL FETCH")
    print("=" * 70)

    previous_rate = get_previous_rate()

    print(
        f"Previous 22K rate: "
        f"{format_rupees(previous_rate)}"
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
        f"Current 22K rate: "
        f"{format_rupees(rate)}"
    )

    print(
        f"Previous 22K rate: "
        f"{format_rupees(previous_rate)}"
    )

    print(
        f"Changed: {changed}"
    )

    save_live(
        rate,
        selected,
        changed
    )

    if changed:

        save_history(
            rate,
            selected,
            changed
        )

        print(
            "NEW PRICE DISCOVERED."
        )

    else:

        # Still save today's observation if needed.
        save_history(
            rate,
            selected,
            False
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
        f"Window: {window['name']}"
    )

    print(
        f"Start: "
        f"{window['start'].strftime('%d-%m-%Y %H:%M:%S')}"
    )

    print(
        f"End: "
        f"{window['end'].strftime('%d-%m-%Y %H:%M:%S')}"
    )

    print(
        f"Polling every {POLL_SECONDS} seconds."
    )

    print(
        "Monitoring will stop when a NEW price is discovered "
        "or when the window ends."
    )

    print("=" * 70)

    previous_rate = get_previous_rate()

    print(
        f"Previous saved 22K rate: "
        f"{format_rupees(previous_rate)}"
    )

    attempt = 0

    while True:

        now = now_ist()

        # ----------------------------------------------------
        # END OF WINDOW
        # ----------------------------------------------------

        if now >= window["end"]:

            print("")
            print("=" * 70)
            print("MONITORING WINDOW ENDED")
            print("=" * 70)

            print(
                f"End time: "
                f"{now.strftime('%d-%m-%Y %H:%M:%S')}"
            )

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
            f"IST: "
            f"{now.strftime('%d-%m-%Y %H:%M:%S')}"
        )

        print("-" * 70)

        # ----------------------------------------------------
        # FETCH BOTH SOURCES
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

            time.sleep(POLL_SECONDS)

            continue

        current_rate = selected["rate_22k"]

        print("")
        print(
            f"Selected 22K rate: "
            f"{format_rupees(current_rate)}"
        )

        print(
            f"Previous 22K rate: "
            f"{format_rupees(previous_rate)}"
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
                f"OLD: "
                f"{format_rupees(previous_rate)}"
            )

            print(
                f"NEW: "
                f"{format_rupees(current_rate)}"
            )

            print(
                f"CHANGE: "
                f"{format_rupees(current_rate - previous_rate)}"
            )

            print(
                f"Source: "
                f"{selected['source']}"
            )

            print("=" * 70)

            # Save immediately.
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

            print("")
            print(
                "NEW PRICE SAVED TO LIVE.JSON"
            )

            print(
                "HISTORY UPDATED."
            )

            print(
                "MONITORING STOPPED AFTER NEW PRICE."
            )

            return True

        # ----------------------------------------------------
        # SAME PRICE
        # ----------------------------------------------------

        print(
            "No price change."
        )

        # Keep live.json current with latest source checks.
        save_live(
            current_rate,
            selected,
            False
        )

        # ----------------------------------------------------
        # WAIT 10 SECONDS
        # ----------------------------------------------------

        now_after_fetch = now_ist()

        remaining = (
            window["end"] - now_after_fetch
        ).total_seconds()

        if remaining <= 0:
            continue

        sleep_for = min(
            POLL_SECONDS,
            int(remaining)
        )

        print(
            f"Next fetch in {sleep_for} seconds..."
        )

        time.sleep(
            max(1, sleep_for)
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
        f"Polling interval: "
        f"{POLL_SECONDS} seconds"
    )

    print("=" * 70)

    # --------------------------------------------------------
    # CHECK CURRENT WINDOW
    # --------------------------------------------------------

    window = current_window(now)

    # --------------------------------------------------------
    # GITHUB ACTIONS
    # --------------------------------------------------------

    github_actions = (
        os.environ.get(
            "GITHUB_ACTIONS",
            ""
        ).lower() == "true"
    )

    github_event = os.environ.get(
        "GITHUB_EVENT_NAME",
        ""
    )

    print(
        f"GITHUB_ACTIONS: "
        f"{github_actions}"
    )

    print(
        f"GITHUB_EVENT_NAME: "
        f"{github_event or 'local'}"
    )

    # --------------------------------------------------------
    # ALREADY INSIDE MONITORING WINDOW
    # --------------------------------------------------------

    if window:

        save_window_info(
            window
        )

        monitor_window(
            window
        )

        return

    # --------------------------------------------------------
    # SCHEDULED GITHUB RUN
    #
    # If GitHub starts at 08:15 or 16:45, wait until
    # the actual monitoring window.
    # --------------------------------------------------------

    if (
        github_actions
        and github_event == "schedule"
        and WAIT_FOR_WINDOW
    ):

        print("")
        print(
            "Scheduled GitHub run detected."
        )

        window = wait_until_window()

        monitor_window(
            window
        )

        return

    # --------------------------------------------------------
    # MANUAL GITHUB RUN / LOCAL RUN OUTSIDE WINDOW
    #
    # Do ONE fetch and exit.
    # --------------------------------------------------------

    print("")
    print(
        "Outside monitoring window."
    )

    print(
        "Performing one normal fetch."
    )

    normal_fetch()

    print("")
    print("=" * 70)
    print("UPDATE COMPLETE")
    print("=" * 70)


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
