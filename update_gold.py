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

# Fixed windows used ONLY as a fallback until 30 days of history with
# session-tagged records exist. Once enough history is available,
# the actual monitoring window is computed from real observed fix
# times instead (see predict_session_times() below).
AM_START = (9, 30)
AM_END = (12, 30)

PM_START = (16, 30)
PM_END = (19, 30)

FALLBACK_AM_TIME = AM_START
FALLBACK_PM_TIME = PM_START

# How many past days of history.json to look at when predicting
# today's likely AM/PM fix time.
HISTORY_LOOKBACK_DAYS = 30

# Start polling this many minutes BEFORE the predicted fix time...
PRE_WINDOW_MINUTES = 15

# ...and keep polling for this long in total (so the window runs from
# predicted-15min to predicted+45min = 60 minutes, if nothing changes
# sooner — monitor_window() already exits the moment a change IS
# detected, well before the window closes).
WINDOW_DURATION_MINUTES = 60

# Need at least this many past AM/PM samples before trusting the
# prediction over the fixed fallback time.
MIN_SAMPLES_FOR_PREDICTION = 3

# Sanity bounds for predicted fix times. Even if history data is noisy,
# or a burst of odd-hour force-fetches somehow gets session-tagged
# wrong, the predicted median is clamped back into a plausible range
# instead of the monitoring window drifting somewhere absurd (e.g. a
# bad sample pulling the "predicted AM fix" to 2 AM).
AM_PREDICTION_MIN = (7, 0)
AM_PREDICTION_MAX = (13, 0)
PM_PREDICTION_MIN = (14, 0)
PM_PREDICTION_MAX = (21, 0)

# A single day's genuine gold price move is essentially never this
# large. If a newly scraped rate deviates from the last known good
# rate by more than this, it's far more likely a parser grabbed the
# wrong number (e.g. a different purity's column) than a real move —
# reject it rather than saving it as if it were legitimate.
MAX_DAILY_CHANGE_PCT = 8


# ============================================================
# ALERTING / HEALTH CHECK
# ============================================================

ALERT_FILE = DATA_DIR / "alert_state.json"
SUMMARY_FILE = DATA_DIR / "summary.json"
HEALTH_FILE = DATA_DIR / "health_status.json"

# If live.json hasn't been successfully written in this many hours,
# something is wrong with both scrapers (site down, blocked, HTML
# structure changed, etc.) — worth a human looking at it.
ALERT_STALE_HOURS = 20

# If LiveChennai and GoodReturns have disagreed continuously for this
# long, one of the parsers is likely broken or reading a stale page.
ALERT_DISAGREE_HOURS = 3

# Don't repeat the same alert more often than this, even if the
# condition is still true on every subsequent run.
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

    # --------------------------------------------------------
    # Fetch both sources concurrently instead of one after
    # another. Same two function calls, same return values -
    # just started in parallel so total wait time is roughly
    # max(livechennai, goodreturns) instead of the sum.
    # --------------------------------------------------------

    with ThreadPoolExecutor(max_workers=2) as executor:

        live_future = executor.submit(
            fetch_livechennai
        )

        good_future = executor.submit(
            fetch_goodreturns
        )

        live = live_future.result()
        good = good_future.result()

    return live, good


# ============================================================
# SELECT BEST RATE
# ============================================================

def _rate_is_plausible(rate, previous_rate):
    """
    True if `rate` is within MAX_DAILY_CHANGE_PCT of `previous_rate`.
    If there's no previous rate to compare against yet (first ever
    run), nothing to reject — always plausible.
    """

    if not isinstance(previous_rate, (int, float)) or previous_rate <= 0:
        return True

    change_pct = abs(rate - previous_rate) / previous_rate * 100
    return change_pct <= MAX_DAILY_CHANGE_PCT


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

        if not _rate_is_plausible(live_rate, previous_rate):

            print(
                f"WARNING: Both sources agree on {format_rupees(live_rate)}, "
                f"but that's a >{MAX_DAILY_CHANGE_PCT}% jump from the last "
                f"saved rate {format_rupees(previous_rate)}. Both parsers "
                "may be reading the wrong field. Keeping previous rate."
            )

            if previous_rate is not None:
                return {
                    "rate_22k": previous_rate,
                    "agreement": False,
                    "source": "Previous rate - agreed value implausible",
                    "livechennai": live,
                    "goodreturns": good
                }

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

        if not _rate_is_plausible(live_rate, previous_rate) and previous_rate is not None:

            print(
                f"WARNING: LiveChennai's only rate {format_rupees(live_rate)} "
                f"is a >{MAX_DAILY_CHANGE_PCT}% jump from the last saved "
                f"rate {format_rupees(previous_rate)}, and GoodReturns "
                "isn't available to cross-check it. Keeping previous rate."
            )

            return {
                "rate_22k": previous_rate,
                "agreement": False,
                "source": "Previous rate - LiveChennai value implausible",
                "livechennai": live,
                "goodreturns": good
            }

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

        if not _rate_is_plausible(good_rate, previous_rate) and previous_rate is not None:

            print(
                f"WARNING: GoodReturns' only rate {format_rupees(good_rate)} "
                f"is a >{MAX_DAILY_CHANGE_PCT}% jump from the last saved "
                f"rate {format_rupees(previous_rate)}, and LiveChennai "
                "isn't available to cross-check it. Keeping previous rate."
            )

            return {
                "rate_22k": previous_rate,
                "agreement": False,
                "source": "Previous rate - GoodReturns value implausible",
                "livechennai": live,
                "goodreturns": good
            }

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

        "session": session_for_time(current, None),

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

def session_for_time(dt, previous_session=None):
    """
    Map an IST datetime to the AM/PM fix window it falls inside, using
    the SAME adaptive prediction (last 30 days' median fix time,
    +/- the same start/duration) that current_window()/next_window()
    use for actual polling — so a record's "session" label always
    matches whichever window it was really detected in.
    Outside both real windows, we do NOT guess a session — we keep
    whatever session was last recorded, so a force-fetch at 1 AM
    never gets labeled as a fresh "AM" fix.
    """

    predicted = predict_session_times(dt)
    day = dt.date()

    am_start, am_end = _session_bounds(day, predicted["AM"])
    pm_start, pm_end = _session_bounds(day, predicted["PM"])

    if am_start <= dt <= am_end:
        return "AM"

    if pm_start <= dt <= pm_end:
        return "PM"

    return previous_session


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

    # --------------------------------------------------------
    # "date" / "time" / "timestamp" / "session" describe WHEN
    # THE RATE ITSELF WAS FIXED — not when this script happened
    # to run. They must only move forward when a genuinely NEW
    # price has been confirmed (changed == True). A "no change"
    # poll, or a manual force-fetch in the middle of the night,
    # must never bump these forward — otherwise the front end
    # (and anyone reading this file) can't tell a real new AM/PM
    # fix apart from "the script happened to execute".
    #
    # "last_checked" / "last_checked_at" are a SEPARATE concept
    # ("when did we last look") and are always safe to update.
    # --------------------------------------------------------

    if changed:

        previous_rate = previous.get("rate_22k")

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

                "session": session_for_time(
                    current,
                    previous.get("session")
                ),

                "previous_rate_22k": previous_rate,

                "change": (
                    int(rate) - int(previous_rate)
                    if isinstance(
                        previous_rate,
                        (int, float)
                    )
                    else None
                ),
            }
        )

    else:

        # No real change discovered. Keep the last confirmed
        # fix's rate/date/time/session exactly as they were.
        # Only fill in a rate if we truly have nothing saved yet.

        output.setdefault(
            "rate_22k",
            int(rate)
        )

        output.setdefault(
            "rate_8g",
            int(rate * 8)
        )

    output.update(
        {

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

            "last_checked": current.isoformat(),

            "last_checked_at": current.isoformat()
        }
    )

    save_json(
        LIVE_FILE,
        output
    )


# ============================================================
# ALERTING (webhook notifications for stuck feed / disagreement)
# ============================================================

def send_alert(title, message):
    """
    POSTs a notification to ALERT_WEBHOOK_URL if that secret/env var is
    set. Sends both "text" and "content" keys so this works out of the
    box with Slack incoming webhooks (text) and Discord webhooks
    (content) without extra config; unused keys are ignored by both.
    If no webhook is configured, just logs to the Actions log instead
    of failing.
    """

    webhook = os.environ.get("ALERT_WEBHOOK_URL")

    if not webhook:
        print(f"ALERT (no ALERT_WEBHOOK_URL configured): {title} — {message}")
        return

    body = f"{title}\n{message}"

    payload = {
        "text": body,
        "content": body,
    }

    try:
        requests.post(webhook, json=payload, timeout=10)
        print(f"Alert sent: {title}")

    except Exception as exc:
        print(f"Failed to send alert webhook: {exc}")


def _hours_since(iso_string, now):
    if not iso_string:
        return None

    try:
        then = datetime.fromisoformat(iso_string)
        return (now - then).total_seconds() / 3600
    except Exception:
        return None


def run_health_check():
    """
    Looks at the CURRENT data/live.json + data/alert_state.json and
    decides whether to fire an alert. Safe to call on every run,
    success or failure — it never raises past its own boundary
    (callers still wrap it defensively too).
    """

    now = now_ist()

    state = load_json(ALERT_FILE, {})
    if not isinstance(state, dict):
        state = {}

    live = load_json(LIVE_FILE, {})
    if not isinstance(live, dict):
        live = {}

    changed_state = False

    # --------------------------------------------------------
    # 1. Stale feed: live.json hasn't been successfully written
    #    (by save_live, which always sets last_checked) in too long.
    # --------------------------------------------------------

    hours_since_checked = _hours_since(live.get("last_checked"), now)

    if hours_since_checked is not None and hours_since_checked >= ALERT_STALE_HOURS:

        cooldown_ok = True
        last_alert_hours = _hours_since(state.get("last_stale_alert_at"), now)
        if last_alert_hours is not None and last_alert_hours < ALERT_COOLDOWN_HOURS:
            cooldown_ok = False

        if cooldown_ok:
            send_alert(
                "Gold Rate Feed Stale",
                f"No successful rate update in {hours_since_checked:.1f} hours. "
                "LiveChennai and/or GoodReturns may be unreachable, blocking "
                "the scraper, or their page structure may have changed."
            )
            state["last_stale_alert_at"] = now.isoformat()
            changed_state = True

    elif state.get("last_stale_alert_at") is not None:
        # Feed recovered — clear so the next stale spell can alert again.
        state["last_stale_alert_at"] = None
        changed_state = True

    # --------------------------------------------------------
    # 2. Sustained source disagreement.
    # --------------------------------------------------------

    agreement = live.get("agreement")

    if agreement is False:

        if not state.get("disagree_since"):
            state["disagree_since"] = now.isoformat()
            changed_state = True

        disagree_hours = _hours_since(state.get("disagree_since"), now) or 0

        if disagree_hours >= ALERT_DISAGREE_HOURS:

            cooldown_ok = True
            last_alert_hours = _hours_since(state.get("last_disagree_alert_at"), now)
            if last_alert_hours is not None and last_alert_hours < ALERT_COOLDOWN_HOURS:
                cooldown_ok = False

            if cooldown_ok:
                send_alert(
                    "Gold Rate Sources Disagreeing",
                    f"LiveChennai and GoodReturns have disagreed for over "
                    f"{disagree_hours:.1f} hours. Current live rate: "
                    f"{format_rupees(live.get('rate_22k'))}. One parser may "
                    "need attention."
                )
                state["last_disagree_alert_at"] = now.isoformat()
                changed_state = True

    elif state.get("disagree_since") is not None:
        state["disagree_since"] = None
        changed_state = True

    if changed_state:
        save_json(ALERT_FILE, state)

    # --------------------------------------------------------
    # 3. Persist a plain status snapshot regardless of whether a
    #    webhook is configured — so feed health is inspectable just
    #    by looking at a committed file, even if ALERT_WEBHOOK_URL
    #    was never set up (or the webhook itself silently breaks).
    # --------------------------------------------------------

    disagree_hours_now = _hours_since(state.get("disagree_since"), now)

    if hours_since_checked is not None and hours_since_checked >= ALERT_STALE_HOURS:
        status = "stale"
    elif disagree_hours_now is not None and disagree_hours_now >= ALERT_DISAGREE_HOURS:
        status = "disagreeing"
    else:
        status = "ok"

    save_json(HEALTH_FILE, {
        "checked_at": now.isoformat(),
        "status": status,
        "hours_since_last_checked": round(hours_since_checked, 2) if hours_since_checked is not None else None,
        "sources_agree": live.get("agreement"),
        "disagree_since": state.get("disagree_since"),
        "webhook_configured": bool(os.environ.get("ALERT_WEBHOOK_URL")),
        "current_rate_22k": live.get("rate_22k"),
        "current_rate_date": live.get("date"),
    })


# ============================================================
# SERVER-SIDE SUMMARY STATS (monthly/yearly avg, all-time high/low)
# ============================================================

def compute_and_save_summary():
    """
    Reads data/history.json and writes data/summary.json with
    pre-computed stats, so the front end doesn't need to crunch the
    whole history array on every page load just to show a high/low
    or a monthly average.
    """

    existing = load_json(HISTORY_FILE, [])
    records = extract_history_records(existing)

    valid = []

    for r in records:

        if not isinstance(r, dict):
            continue

        rate = r.get("rate_22k")
        date_str = r.get("date")

        if not isinstance(rate, (int, float)) or not date_str:
            continue

        valid.append((date_str, int(rate)))

    if not valid:
        print("No history records available yet — skipping summary.")
        return

    now = now_ist()
    current_month = now.strftime("%Y-%m")
    current_year = now.strftime("%Y")

    all_time_high = max(valid, key=lambda item: item[1])
    all_time_low = min(valid, key=lambda item: item[1])

    month_vals = [v for d, v in valid if d.startswith(current_month)]
    year_vals = [v for d, v in valid if d.startswith(current_year)]

    last_30 = valid[-30:] if len(valid) > 30 else valid
    last_30_vals = [v for _, v in last_30]

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

        "all_time_high": {
            "rate_22k": all_time_high[1],
            "date": all_time_high[0],
        },

        "all_time_low": {
            "rate_22k": all_time_low[1],
            "date": all_time_low[0],
        },

        "current_month": {"month": current_month, **bucket(month_vals)},
        "current_year": {"year": current_year, **bucket(year_vals)},
        "last_30_records": bucket(last_30_vals),

        "total_records": len(valid),
    }

    save_json(SUMMARY_FILE, summary)

    print("Summary stats saved:")
    print(json.dumps(summary, indent=2))


# ============================================================
# MONITORING WINDOWS
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

    if n % 2 == 0:
        return (s[mid - 1] + s[mid]) / 2

    return s[mid]


def _clamp_hm(hm, lo, hi):
    minutes = hm[0] * 60 + hm[1]
    lo_minutes = lo[0] * 60 + lo[1]
    hi_minutes = hi[0] * 60 + hi[1]
    clamped = max(lo_minutes, min(hi_minutes, minutes))
    return (clamped // 60, clamped % 60)


def predict_session_times(now=None):
    """
    Looks at the last HISTORY_LOOKBACK_DAYS days of data/history.json
    and returns the MEDIAN observed AM and PM fix time, as (hour,
    minute) tuples — e.g. today's gold rate has actually been
    changing around 08:47 and 17:12, this returns those, not the
    generic 08:30/17:00 assumption.

    Falls back to FALLBACK_AM_TIME / FALLBACK_PM_TIME per session
    when there isn't yet enough session-tagged history to trust
    (fewer than MIN_SAMPLES_FOR_PREDICTION samples).
    """

    now = now or now_ist()
    cutoff_date = (now - timedelta(days=HISTORY_LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    existing = load_json(HISTORY_FILE, [])
    records = extract_history_records(existing)

    am_minutes = []
    pm_minutes = []

    for r in records:

        if not isinstance(r, dict):
            continue

        date_str = r.get("date")
        time_str = r.get("time")
        session = r.get("session")

        if not date_str or not time_str or not session:
            continue

        if date_str < cutoff_date:
            continue

        mins = _parse_time_to_minutes(time_str)

        if mins is None:
            continue

        if session == "AM":
            am_minutes.append(mins)
        elif session == "PM":
            pm_minutes.append(mins)

    result = {}

    if len(am_minutes) >= MIN_SAMPLES_FOR_PREDICTION:
        med = _median(am_minutes)
        raw = (int(med // 60), int(med % 60))
        result["AM"] = _clamp_hm(raw, AM_PREDICTION_MIN, AM_PREDICTION_MAX)
        if result["AM"] != raw:
            print(f"Predicted AM time {raw} out of sane range — clamped to {result['AM']}")
    else:
        result["AM"] = FALLBACK_AM_TIME

    if len(pm_minutes) >= MIN_SAMPLES_FOR_PREDICTION:
        med = _median(pm_minutes)
        raw = (int(med // 60), int(med % 60))
        result["PM"] = _clamp_hm(raw, PM_PREDICTION_MIN, PM_PREDICTION_MAX)
        if result["PM"] != raw:
            print(f"Predicted PM time {raw} out of sane range — clamped to {result['PM']}")
    else:
        result["PM"] = FALLBACK_PM_TIME

    return result


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


def _session_bounds(day, predicted_hm):
    """
    Given a predicted (hour, minute) fix time on a given day, returns
    the (start, end) datetimes for the polling window: starts
    PRE_WINDOW_MINUTES before the predicted time, runs for
    WINDOW_DURATION_MINUTES total.
    """

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
    predicted = predict_session_times(now)

    am_start, am_end = _session_bounds(today, predicted["AM"])
    pm_start, pm_end = _session_bounds(today, predicted["PM"])

    if now < am_start:

        return {
            "name": "AM",
            "start": am_start,
            "end": am_end
        }

    if now < pm_start:

        return {
            "name": "PM",
            "start": pm_start,
            "end": pm_end
        }

    tomorrow = today + timedelta(days=1)
    predicted_tomorrow = predict_session_times(
        make_datetime(tomorrow, 0, 0)
    )
    am_start_tomorrow, am_end_tomorrow = _session_bounds(
        tomorrow, predicted_tomorrow["AM"]
    )

    return {
        "name": "AM",
        "start": am_start_tomorrow,
        "end": am_end_tomorrow
    }


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
                "polling_duration_minutes": WINDOW_DURATION_MINUTES
            },

            "PM": {
                "predicted_fix_time": f"{predicted['PM'][0]:02d}:{predicted['PM'][1]:02d}",
                "polling_starts": f"{PRE_WINDOW_MINUTES} min before predicted time",
                "polling_duration_minutes": WINDOW_DURATION_MINUTES
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
        wait_seconds = (upcoming["start"] - now).total_seconds()

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

        print(
            f"Wait required: {wait_seconds / 60:.1f} minutes"
        )

        # GitHub's `schedule:` trigger is best-effort and can fire
        # significantly late on low-traffic repos (an 08:30 cron
        # starting at 13:29 has been observed here). If that happens,
        # the AM window is already over, and blindly sleeping until
        # the NEXT window (PM) can burn the entire job timeout before
        # ever reaching monitor_window() — leaving that run having
        # done nothing at all. Instead, once the wait grows past a
        # sane bound, do one immediate fetch now so at least today's
        # rate gets checked, and let the next scheduled trigger handle
        # its own window normally.
        MAX_SCHEDULE_WAIT_MINUTES = 45

        if wait_seconds > MAX_SCHEDULE_WAIT_MINUTES * 60:

            print("")
            print(
                f"Wait exceeds {MAX_SCHEDULE_WAIT_MINUTES} minutes — "
                "GitHub's scheduler likely delayed this run past its "
                "intended window. Doing one immediate fetch instead of "
                "waiting, so this run isn't wasted."
            )

            success = normal_fetch()

            if not success:
                sys.exit(1)

            return

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

    finally:

        # Runs after every attempt — success, failure, or interrupt —
        # so a stuck feed or persistent source disagreement always gets
        # evaluated, and the summary file stays in sync with whatever
        # history.json currently holds. Wrapped so a problem here can
        # never mask the real exit code from the block above.

        try:
            run_health_check()
        except Exception as exc:
            print(f"Health check failed (non-fatal): {exc}")

        try:
            compute_and_save_summary()
        except Exception as exc:
            print(f"Summary computation failed (non-fatal): {exc}")
