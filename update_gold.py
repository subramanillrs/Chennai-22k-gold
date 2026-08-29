#!/usr/bin/env python3

from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

IST = ZoneInfo("Asia/Kolkata")

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

LIVE_FILE = DATA / "live.json"
HISTORY_FILE = DATA / "history.json"
WINDOW_FILE = DATA / "monitoring_windows.json"

LIVECHENNAI_URL = "https://www.livechennai.com/gold_silverrate.asp"
GOODRETURNS_URL = "https://www.goodreturns.in/gold-rates/chennai.html"

POLL_SECONDS = 10
REQUEST_TIMEOUT = 15

FALLBACK_WINDOWS = {
    "am": {
        "start": "08:30",
        "end": "11:30"
    },
    "pm": {
        "start": "17:00",
        "end": "20:00"
    }
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) "
        "Version/18.0 Safari/605.1.15"
    ),
    "Accept-Language": "en-IN,en;q=0.9"
}


# ============================================================
# BASIC JSON FUNCTIONS
# ============================================================

def now_ist() -> datetime:
    return datetime.now(IST)


def load_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as exc:
        print(f"WARNING: Could not read {path}: {exc}")

    return default


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    temp = path.with_suffix(path.suffix + ".tmp")

    with temp.open("w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )
        f.write("\n")

    temp.replace(path)


# ============================================================
# NUMBER PARSING
# ============================================================

def clean_number(value: str) -> Optional[int]:

    if not value:
        return None

    value = str(value)

    match = re.search(
        r"(?:₹|Rs\.?|INR)?\s*([0-9][0-9,]*)",
        value,
        re.IGNORECASE
    )

    if not match:
        return None

    try:
        return int(
            match.group(1)
            .replace(",", "")
        )
    except ValueError:
        return None


# ============================================================
# DATE/TIME PARSING
# ============================================================

def parse_time(text: str) -> Optional[datetime]:

    if not text:
        return None

    patterns = [

        # 29/Aug/2026 9:44:41 AM
        (
            r"(\d{1,2})/"
            r"([A-Za-z]{3})/"
            r"(\d{4})\s+"
            r"(\d{1,2}):"
            r"(\d{2})"
            r"(?::(\d{2}))?"
            r"\s*([AP]M)"
        ),

        # 29/08/2026 9:44:41 AM
        (
            r"(\d{1,2})/"
            r"(\d{1,2})/"
            r"(\d{4})\s+"
            r"(\d{1,2}):"
            r"(\d{2})"
            r"(?::(\d{2}))?"
            r"\s*([AP]M)"
        )
    ]

    months = {
        "Jan": 1,
        "Feb": 2,
        "Mar": 3,
        "Apr": 4,
        "May": 5,
        "Jun": 6,
        "Jul": 7,
        "Aug": 8,
        "Sep": 9,
        "Oct": 10,
        "Nov": 11,
        "Dec": 12
    }

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if not match:
            continue

        a, b, c, hh, mm, ss, ap = match.groups()

        try:

            if b.title() in months:

                day = int(a)
                month = months[b.title()]
                year = int(c)

            else:

                day = int(a)
                month = int(b)
                year = int(c)

            hour = int(hh) % 12

            if ap.upper() == "PM":
                hour += 12

            return datetime(
                year,
                month,
                day,
                hour,
                int(mm),
                int(ss or 0),
                tzinfo=IST
            )

        except ValueError:
            pass

    return None


def parse_iso_datetime(value: Any) -> Optional[datetime]:

    if not isinstance(value, str):
        return None

    try:

        dt = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)

        return dt.astimezone(IST)

    except Exception:
        return None


# ============================================================
# HTTP
# ============================================================

def fetch_html(url: str) -> str:

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    return response.text


# ============================================================
# LIVECHENNAI
# ============================================================

def fetch_livechennai() -> dict[str, Any]:

    print("Checking LiveChennai...")

    html = fetch_html(
        LIVECHENNAI_URL
    )

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    text = soup.get_text(
        " ",
        strip=True
    )

    rate = None

    patterns = [

        r"Standard\s*Gold\s*\(22\s*K\).*?"
        r"1\s*Gm.*?"
        r"([0-9,]{4,})",

        r"22\s*K.*?"
        r"1\s*Gm.*?"
        r"([0-9,]{4,})",

        r"22K\s*Gold.*?"
        r"₹\s*([0-9,]{4,})",

        r"22\s*carat.*?"
        r"₹\s*([0-9,]{4,})"
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE | re.DOTALL
        )

        if match:

            number = clean_number(
                match.group(1)
            )

            if number and 8000 <= number <= 30000:

                rate = number
                break

    # Additional fallback.
    if rate is None:

        candidates = re.findall(
            r"22\s*K.{0,150}?"
            r"₹?\s*([0-9][0-9,]{3,})",
            text,
            re.IGNORECASE | re.DOTALL
        )

        for candidate in candidates:

            number = clean_number(
                candidate
            )

            if number and 8000 <= number <= 30000:

                rate = number
                break

    if rate is None:

        raise RuntimeError(
            "Could not locate valid Chennai 22K rate on LiveChennai"
        )

    update_time = None

    labels = [
        "Last Update Time",
        "Updated:",
        "Last Updated"
    ]

    for label in labels:

        position = text.lower().find(
            label.lower()
        )

        if position >= 0:

            update_time = parse_time(
                text[
                    position:
                    position + 150
                ]
            )

            if update_time:
                break

    return {
        "source": "LiveChennai",
        "rate_22k": rate,
        "updated_at": (
            update_time.isoformat()
            if update_time
            else None
        ),
        "url": LIVECHENNAI_URL,
        "fetched_at": now_ist().isoformat()
    }


# ============================================================
# GOODRETURNS
# ============================================================

def fetch_goodreturns() -> dict[str, Any]:

    print("Checking GoodReturns...")

    html = fetch_html(
        GOODRETURNS_URL
    )

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    text = soup.get_text(
        " ",
        strip=True
    )

    rate = None

    patterns = [

        r"22K\s*Gold\s*/\s*g\s*₹?\s*([0-9,]{4,})",

        r"22K\s*Gold[^₹]{0,100}"
        r"₹\s*([0-9,]{4,})",

        r"22K\s*Gold.{0,150}?"
        r"([0-9,]{4,})"
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE | re.DOTALL
        )

        if match:

            number = clean_number(
                match.group(1)
            )

            if number and 8000 <= number <= 30000:

                rate = number
                break

    # Table fallback.
    if rate is None:

        for row in soup.find_all(
            ["tr", "div", "p"]
        ):

            row_text = row.get_text(
                " ",
                strip=True
            )

            if (
                "22K Gold" in row_text
                and "Chennai" in row_text
            ):

                number = clean_number(
                    row_text
                )

                if number and 8000 <= number <= 30000:

                    rate = number
                    break

    if rate is None:

        raise RuntimeError(
            "Could not locate valid Chennai 22K rate on GoodReturns"
        )

    return {
        "source": "GoodReturns",
        "rate_22k": rate,
        "updated_at": None,
        "url": GOODRETURNS_URL,
        "fetched_at": now_ist().isoformat()
    }


# ============================================================
# FETCH BOTH SOURCES
# ============================================================

def fetch_sources() -> list[dict[str, Any]]:

    results = []

    try:

        result = fetch_livechennai()

        print(
            f"LiveChennai: "
            f"₹{result['rate_22k']:,}/gram"
        )

        results.append(result)

    except Exception as exc:

        print(
            f"LiveChennai FAILED: {exc}"
        )

    try:

        result = fetch_goodreturns()

        print(
            f"GoodReturns: "
            f"₹{result['rate_22k']:,}/gram"
        )

        results.append(result)

    except Exception as exc:

        print(
            f"GoodReturns FAILED: {exc}"
        )

    return results


# ============================================================
# SOURCE CONSENSUS
# ============================================================

def determine_rate(
    results: list[dict[str, Any]]
) -> Optional[int]:

    if not results:
        return None

    valid = []

    for result in results:

        rate = result.get(
            "rate_22k"
        )

        if isinstance(rate, int):

            if 8000 <= rate <= 30000:
                valid.append(rate)

    if not valid:
        return None

    # Both sources agree.
    if len(valid) >= 2:

        if valid[0] == valid[1]:

            return valid[0]

        print(
            "WARNING: Sources disagree."
        )

        print(
            "Keeping previous rate until "
            "a later poll produces agreement."
        )

        return None

    # Only one source available.
    return valid[0]


# ============================================================
# HISTORY
# ============================================================

def extract_timestamped_history(
    history: Any
) -> list[tuple[datetime, int]]:

    observations = []

    if not isinstance(history, list):
        return observations

    for item in history:

        if not isinstance(item, dict):
            continue

        rate = None

        for key in [
            "rate_22k",
            "rate22k",
            "22k",
            "gold_22k",
            "price_22k"
        ]:

            if key in item:

                try:

                    rate = int(
                        str(item[key])
                        .replace(",", "")
                        .replace("₹", "")
                        .strip()
                    )

                    break

                except Exception:
                    pass

        if not rate:
            continue

        dt = None

        for key in [
            "timestamp",
            "updated_at",
            "datetime",
            "date_time"
        ]:

            if key in item:

                dt = parse_iso_datetime(
                    item[key]
                )

                if dt:
                    break

        if not dt:

            if (
                item.get("date")
                and item.get("time")
            ):

                dt = parse_time(
                    f"{item['date']} "
                    f"{item['time']}"
                )

        if dt and 5000 <= rate <= 50000:

            observations.append(
                (dt, rate)
            )

    observations.sort()

    return observations


# ============================================================
# LEARN MONITORING WINDOWS
# ============================================================

def learn_monitoring_windows(
    history: Any
) -> dict[str, Any]:

    current = now_ist()

    observations = (
        extract_timestamped_history(
            history
        )
    )

    cutoff_90 = (
        current -
        timedelta(days=90)
    )

    cutoff_30 = (
        current -
        timedelta(days=30)
    )

    observations_90 = [
        item
        for item in observations
        if item[0] >= cutoff_90
    ]

    observations_30 = [
        item
        for item in observations
        if item[0] >= cutoff_30
    ]

    # Detect actual changes.
    changes_90 = []

    previous_rate = None

    for timestamp, rate in observations_90:

        if (
            previous_rate is not None
            and rate != previous_rate
        ):

            changes_90.append(
                timestamp
            )

        previous_rate = rate

    changes_30 = [
        timestamp
        for timestamp in changes_90
        if timestamp >= cutoff_30
    ]

    # Separate AM/PM.
    am_90 = [
        timestamp
        for timestamp in changes_90
        if timestamp.hour < 14
    ]

    pm_90 = [
        timestamp
        for timestamp in changes_90
        if timestamp.hour >= 14
    ]

    am_30 = [
        timestamp
        for timestamp in changes_30
        if timestamp.hour < 14
    ]

    pm_30 = [
        timestamp
        for timestamp in changes_30
        if timestamp.hour >= 14
    ]

    def make_window(
        timestamps: list[datetime],
        fallback: dict[str, str]
    ) -> dict[str, str]:

        if not timestamps:
            return fallback.copy()

        minutes = [
            t.hour * 60 + t.minute
            for t in timestamps
        ]

        minimum = min(minutes)
        maximum = max(minutes)

        # 45-minute safety margin.
        start = max(
            0,
            minimum - 45
        )

        end = min(
            1439,
            maximum + 45
        )

        # Never create an excessively broad window
        # from sparse/bad observations.
        if end - start > 240:

            sorted_minutes = sorted(
                minutes
            )

            center = sorted_minutes[
                len(sorted_minutes) // 2
            ]

            start = max(
                0,
                center - 90
            )

            end = min(
                1439,
                center + 90
            )

        return {
            "start": (
                f"{start // 60:02d}:"
                f"{start % 60:02d}"
            ),
            "end": (
                f"{end // 60:02d}:"
                f"{end % 60:02d}"
            )
        }

    # 30-day data gets priority.
    if am_30:
        am_window = make_window(
            am_30,
            FALLBACK_WINDOWS["am"]
        )
        am_basis = "30-day"
    elif am_90:
        am_window = make_window(
            am_90,
            FALLBACK_WINDOWS["am"]
        )
        am_basis = "90-day"
    else:
        am_window = FALLBACK_WINDOWS["am"].copy()
        am_basis = "fallback"

    if pm_30:
        pm_window = make_window(
            pm_30,
            FALLBACK_WINDOWS["pm"]
        )
        pm_basis = "30-day"
    elif pm_90:
        pm_window = make_window(
            pm_90,
            FALLBACK_WINDOWS["pm"]
        )
        pm_basis = "90-day"
    else:
        pm_window = FALLBACK_WINDOWS["pm"].copy()
        pm_basis = "fallback"

    return {

        "generated_at":
            current.isoformat(),

        "timezone":
            "Asia/Kolkata",

        "learning_method":
            "30-day priority, 90-day fallback",

        "historical_observations":
            len(observations),

        "three_month_observations":
            len(observations_90),

        "thirty_day_observations":
            len(observations_30),

        "price_change_observations_90d":
            len(changes_90),

        "price_change_observations_30d":
            len(changes_30),

        "timestamp_learning_available":
            bool(changes_90),

        "windows": {

            "am": am_window,

            "pm": pm_window

        },

        "basis": {

            "am": am_basis,

            "pm": pm_basis

        },

        "poll_interval_seconds":
            POLL_SECONDS
    }


# ============================================================
# WINDOW CHECKING
# ============================================================

def time_to_minutes(
    value: str
) -> int:

    hour, minute = map(
        int,
        value.split(":")
    )

    return (
        hour * 60 +
        minute
    )


def inside_window(
    current: datetime,
    window: dict[str, str]
) -> bool:

    current_minutes = (
        current.hour * 60 +
        current.minute
    )

    start = time_to_minutes(
        window["start"]
    )

    end = time_to_minutes(
        window["end"]
    )

    return (
        start <=
        current_minutes <=
        end
    )


# ============================================================
# FULL 10 SECOND MONITOR
# ============================================================

def monitor_window(
    previous_rate: Optional[int],
    window: dict[str, str]
) -> tuple[
    Optional[int],
    list[dict[str, Any]]
]:

    print()
    print("=" * 72)
    print(
        "FULL MONITORING WINDOW"
    )
    print("=" * 72)

    print(
        f"Window: "
        f"{window['start']} - "
        f"{window['end']} IST"
    )

    print(
        f"Polling every "
        f"{POLL_SECONDS} seconds"
    )

    print(
        "Monitoring will continue "
        "until a NEW price is discovered "
        "or the window ends."
    )

    print("=" * 72)

    all_results = []

    while inside_window(
        now_ist(),
        window
    ):

        print()
        print(
            f"[{now_ist():%H:%M:%S}] "
            "FETCH"
        )

        results = fetch_sources()

        all_results.extend(
            results
        )

        candidate = determine_rate(
            results
        )

        print(
            f"Candidate rate: "
            f"{candidate}"
        )

        if (
            candidate is not None
            and previous_rate is not None
            and candidate != previous_rate
        ):

            print()
            print(
                "****************************************"
            )

            print(
                f"NEW PRICE DISCOVERED!"
            )

            print(
                f"Previous: "
                f"₹{previous_rate:,}"
            )

            print(
                f"New: "
                f"₹{candidate:,}"
            )

            print(
                "****************************************"
            )

            return candidate, all_results

        if (
            candidate is not None
            and previous_rate is None
        ):

            return candidate, all_results

        # IMPORTANT:
        # Do not sleep after the window has already ended.
        remaining = (
            time_to_minutes(
                window["end"]
            )
            -
            (
                now_ist().hour * 60
                +
                now_ist().minute
            )
        )

        if remaining <= 0:
            break

        time.sleep(
            POLL_SECONDS
        )

    print()
    print(
        "Monitoring window ended."
    )

    return previous_rate, all_results


# ============================================================
# LIVE.JSON
# ============================================================

def build_live_data(
    previous: dict[str, Any],
    rate: int,
    results: list[dict[str, Any]],
    changed: bool
) -> dict[str, Any]:

    current = now_ist()

    old_rate = None

    try:

        old_rate = int(
            previous.get(
                "rate_22k"
            )
        )

    except Exception:
        pass

    source_names = [
        item["source"]
        for item in results
        if item.get("source")
    ]

    source_times = [
        item["updated_at"]
        for item in results
        if item.get("updated_at")
    ]

    rates = [
        item["rate_22k"]
        for item in results
        if isinstance(
            item.get("rate_22k"),
            int
        )
    ]

    return {

        "rate_22k":
            rate,

        "rate_8g":
            rate * 8,

        "currency":
            "INR",

        "city":
            "Chennai",

        "purity":
            "22K",

        "date":
            current.strftime(
                "%Y-%m-%d"
            ),

        "time":
            current.strftime(
                "%H:%M:%S"
            ),

        "timestamp":
            current.isoformat(),

        "changed":
            changed,

        "previous_rate_22k":
            old_rate,

        "sources":
            source_names,

        "source_update_times":
            source_times,

        "source_rates":
            rates,

        "sources_agree":
            (
                len(set(rates)) <= 1
                if rates
                else False
            ),

        "last_checked_at":
            current.isoformat()
    }


# ============================================================
# HISTORY UPDATE
# ============================================================

def append_history(
    history: Any,
    live: dict[str, Any]
) -> list:

    if not isinstance(
        history,
        list
    ):

        history = []

    entry = {

        "timestamp":
            live["timestamp"],

        "date":
            live["date"],

        "time":
            live["time"],

        "rate_22k":
            live["rate_22k"],

        "rate_8g":
            live["rate_8g"],

        "changed":
            live["changed"],

        "sources":
            live.get(
                "sources",
                []
            )
    }

    # Keep history useful without storing every
    # identical 10-second poll.
    if history:

        last = history[-1]

        if (
            isinstance(last, dict)
            and
            last.get("rate_22k")
            ==
            entry["rate_22k"]
            and
            last.get("date")
            ==
            entry["date"]
            and
            last.get("time")
            ==
            entry["time"]
        ):

            return history

    history.append(
        entry
    )

    # Keep existing history.
    return history


# ============================================================
# MAIN
# ============================================================

def main() -> int:

    print()
    print("=" * 72)
    print(
        "CHENNAI 22K GOLD RATE"
    )
    print(
        "ADAPTIVE FULL-WINDOW MONITOR"
    )
    print("=" * 72)

    DATA.mkdir(
        exist_ok=True
    )

    previous = load_json(
        LIVE_FILE,
        {}
    )

    history = load_json(
        HISTORY_FILE,
        []
    )

    windows = learn_monitoring_windows(
        history
    )

    save_json(
        WINDOW_FILE,
        windows
    )

    current = now_ist()

    print(
        f"IST: "
        f"{current:%d-%m-%Y %I:%M:%S %p}"
    )

    print()
    print(
        "LEARNING INFORMATION"
    )

    print(
        f"Historical observations: "
        f"{windows['historical_observations']}"
    )

    print(
        f"3-month observations: "
        f"{windows['three_month_observations']}"
    )

    print(
        f"30-day observations: "
        f"{windows['thirty_day_observations']}"
    )

    print(
        f"Price changes 90d: "
        f"{windows['price_change_observations_90d']}"
    )

    print(
        f"Price changes 30d: "
        f"{windows['price_change_observations_30d']}"
    )

    print(
        f"Timestamp learning: "
        f"{windows['timestamp_learning_available']}"
    )

    print()
    print(
        "CURRENT MONITORING WINDOWS"
    )

    print(
        f"AM: "
        f"{windows['windows']['am']['start']} - "
        f"{windows['windows']['am']['end']} "
        f"({windows['basis']['am']})"
    )

    print(
        f"PM: "
        f"{windows['windows']['pm']['start']} - "
        f"{windows['windows']['pm']['end']} "
        f"({windows['basis']['pm']})"
    )

    try:

        previous_rate = int(
            previous.get(
                "rate_22k"
            )
        )

    except Exception:

        previous_rate = None

    # Determine active monitoring window.
    active_window = None

    for key in (
        "am",
        "pm"
    ):

        window = windows[
            "windows"
        ][key]

        if inside_window(
            current,
            window
        ):

            active_window = window
            break

    if active_window:

        print()
        print(
            "CURRENTLY INSIDE "
            "MONITORING WINDOW"
        )

        rate, results = monitor_window(
            previous_rate,
            active_window
        )

    else:

        print()
        print(
            "OUTSIDE MONITORING WINDOW"
        )

        print(
            "Performing one normal fetch."
        )

        results = fetch_sources()

        candidate = determine_rate(
            results
        )

        if candidate is not None:

            rate = candidate

        else:

            rate = previous_rate

    if rate is None:

        print()
        print(
            "ERROR: No valid rate available."
        )

        return 1

    changed = (
        previous_rate is not None
        and
        rate != previous_rate
    )

    live = build_live_data(
        previous,
        rate,
        results,
        changed
    )

    save_json(
        LIVE_FILE,
        live
    )

    history = append_history(
        history,
        live
    )

    save_json(
        HISTORY_FILE,
        history
    )

    # Relearn after every successful run.
    windows = learn_monitoring_windows(
        history
    )

    save_json(
        WINDOW_FILE,
        windows
    )

    print()
    print("=" * 72)
    print(
        "UPDATE COMPLETE"
    )
    print("=" * 72)

    print(
        f"22K / gram : "
        f"₹{rate:,}"
    )

    print(
        f"22K / 8g   : "
        f"₹{rate * 8:,}"
    )

    print(
        f"Date       : "
        f"{live['date']}"
    )

    print(
        f"Time       : "
        f"{live['time']}"
    )

    print(
        f"Changed    : "
        f"{changed}"
    )

    print(
        f"History    : "
        f"{len(history)} records"
    )

    print(
        f"Live file  : "
        f"{LIVE_FILE}"
    )

    print(
        f"Window file: "
        f"{WINDOW_FILE}"
    )

    print("=" * 72)

    return 0


if __name__ == "__main__":
    sys.exit(
        main()
    )
