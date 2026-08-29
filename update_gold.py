import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup


# ============================================================
# CHENNAI 22K GOLD RATE MONITOR
# ============================================================

IST = ZoneInfo("Asia/Kolkata")

LIVE_FILE = "data/live.json"
HISTORY_FILE = "data/history.json"
WINDOW_FILE = "data/monitoring_windows.json"

LIVECHENNAI_URL = "https://www.livechennai.com/gold_silverrate.asp"
GOODRETURNS_URL = "https://www.goodreturns.in/gold-rates/chennai.html"

POLL_SECONDS = 10

# Maximum individual website request time.
REQUEST_TIMEOUT = 8

# Safety validation only.
MIN_VALID_RATE = 5000
MAX_VALID_RATE = 30000

# Never allow a monitoring session to run beyond this.
MAX_MONITOR_MINUTES = 190

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/18.0 Safari/605.1.15"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
    "Cache-Control": "no-cache",
}


# ============================================================
# DIRECTORY
# ============================================================

os.makedirs("data", exist_ok=True)


# ============================================================
# TIME
# ============================================================

def now_ist():
    return datetime.now(IST)


def today_string():
    return now_ist().strftime("%Y-%m-%d")


def time_string(dt=None):
    dt = dt or now_ist()
    return dt.strftime("%H:%M:%S")


# ============================================================
# JSON HELPERS
# ============================================================

def load_json(path, default):
    try:
        if not os.path.exists(path):
            return default

        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    except Exception as e:
        print(f"WARNING: Could not read {path}: {e}")
        return default


def save_json(path, value):
    tmp = path + ".tmp"

    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, indent=2, ensure_ascii=False)

    os.replace(tmp, path)


# ============================================================
# RATE VALIDATION
# ============================================================

def valid_rate(rate):
    if rate is None:
        return False

    try:
        rate = int(rate)
    except Exception:
        return False

    return MIN_VALID_RATE <= rate <= MAX_VALID_RATE


def clean_rate(value):
    if value is None:
        return None

    value = str(value)

    # Remove commas, currency symbols, spaces etc.
    digits = re.sub(r"[^\d]", "", value)

    if not digits:
        return None

    try:
        rate = int(digits)
    except Exception:
        return None

    if not valid_rate(rate):
        return None

    return rate


# ============================================================
# LIVECHENNAI
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

        soup = BeautifulSoup(response.text, "html.parser")
        text = soup.get_text(" ", strip=True)

        # Preferred pattern:
        # 1 Gm (22 K) ... 14,505
        patterns = [
            r"1\s*Gm\s*\(22\s*K\).*?₹?\s*([\d,]+)",
            r"22K\s*Gold.*?₹\s*([\d,]+)",
            r"22K\s*Gold.*?Rs\.?\s*([\d,]+)",
            r"22\s*carat\s*gold.*?₹\s*([\d,]+)",
        ]

        rate = None

        for pattern in patterns:
            match = re.search(pattern, text, re.I | re.S)

            if match:
                rate = clean_rate(match.group(1))

                if rate:
                    break

        # Last fallback: inspect table cells.
        if not rate:
            for row in soup.find_all("tr"):
                row_text = row.get_text(" ", strip=True)

                if "22" in row_text and "Gold" in row_text:
                    numbers = re.findall(r"\b\d{2},?\d{3}\b", row_text)

                    for number in numbers:
                        candidate = clean_rate(number)

                        if candidate:
                            rate = candidate
                            break

                if rate:
                    break

        if not rate:
            raise ValueError("Could not locate a valid Chennai 22K rate")

        # Try to locate update time.
        update_time = None

        time_patterns = [
            r"Last Update Time:\s*([^|]+)",
            r"Last Update.*?(\d{1,2}:\d{2}:\d{2}\s*[AP]M)",
            r"Updated:\s*([^|]+)",
        ]

        for pattern in time_patterns:
            match = re.search(pattern, text, re.I)

            if match:
                update_time = match.group(1).strip()
                break

        return {
            "source": "LiveChennai",
            "rate_22k": rate,
            "update_time": update_time,
            "url": LIVECHENNAI_URL,
            "fetched_at": now_ist().isoformat(),
        }

    except Exception as e:
        print(f"  LiveChennai failed: {e}")
        return None


# ============================================================
# GOODRETURNS
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

        soup = BeautifulSoup(response.text, "html.parser")
        text = soup.get_text(" ", strip=True)

        rate = None

        # GoodReturns currently publishes:
        # 22K Gold /g ₹14,505
        patterns = [
            r"22K\s*Gold\s*/g\s*₹?\s*([\d,]+)",
            r"22K\s*Gold.*?₹\s*([\d,]+)",
            r"22K\s*Gold.*?Rs\.?\s*([\d,]+)",
            r"22\s*K\s*Gold.*?₹\s*([\d,]+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.I | re.S)

            if match:
                rate = clean_rate(match.group(1))

                if rate:
                    break

        # Fallback: find a Chennai table row.
        if not rate:
            for row in soup.find_all("tr"):
                row_text = row.get_text(" ", strip=True)

                if "Chennai" in row_text:
                    numbers = re.findall(r"\b\d{2},?\d{3}\b", row_text)

                    # Typical row is 24K, 22K, 18K.
                    if len(numbers) >= 2:
                        candidate = clean_rate(numbers[1])

                        if candidate:
                            rate = candidate
                            break

        if not rate:
            raise ValueError("Could not locate a valid GoodReturns Chennai 22K rate")

        return {
            "source": "GoodReturns",
            "rate_22k": rate,
            "update_time": None,
            "url": GOODRETURNS_URL,
            "fetched_at": now_ist().isoformat(),
        }

    except Exception as e:
        print(f"  GoodReturns failed: {e}")
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
# CURRENT DATA
# ============================================================

def get_previous_rate():
    live = load_json(LIVE_FILE, {})

    if isinstance(live, dict):
        value = live.get("rate_22k")

        if value is None:
            value = live.get("rate22k")

        if value is None:
            value = live.get("gold_22k")

        return clean_rate(value)

    return None


def get_previous_live():
    return load_json(LIVE_FILE, {})


# ============================================================
# MONITORING WINDOWS
# ============================================================

DEFAULT_WINDOWS = {
    "am": {
        "start": "08:30",
        "end": "11:30",
    },
    "pm": {
        "start": "17:00",
        "end": "20:00",
    },
}


def parse_hhmm(value):
    try:
        hour, minute = value.split(":")
        return int(hour), int(minute)
    except Exception:
        return None


def minutes_of_day(dt):
    return dt.hour * 60 + dt.minute


def load_windows():
    data = load_json(WINDOW_FILE, DEFAULT_WINDOWS)

    if not isinstance(data, dict):
        return DEFAULT_WINDOWS

    result = {}

    for key in ("am", "pm"):
        item = data.get(key, {})

        start = item.get("start", DEFAULT_WINDOWS[key]["start"])
        end = item.get("end", DEFAULT_WINDOWS[key]["end"])

        if parse_hhmm(start) and parse_hhmm(end):
            result[key] = {
                "start": start,
                "end": end,
            }
        else:
            result[key] = DEFAULT_WINDOWS[key]

    return result


def window_datetime_today(hhmm):
    hour, minute = parse_hhmm(hhmm)

    now = now_ist()

    return now.replace(
        hour=hour,
        minute=minute,
        second=0,
        microsecond=0,
    )


def active_window():
    now = now_ist()
    current_minutes = minutes_of_day(now)

    windows = load_windows()

    for name in ("am", "pm"):
        start = windows[name]["start"]
        end = windows[name]["end"]

        sh, sm = parse_hhmm(start)
        eh, em = parse_hhmm(end)

        start_minutes = sh * 60 + sm
        end_minutes = eh * 60 + em

        if start_minutes <= current_minutes <= end_minutes:
            return {
                "name": name,
                "start": window_datetime_today(start),
                "end": window_datetime_today(end),
                "start_text": start,
                "end_text": end,
            }

    return None


# ============================================================
# SAVE LIVE DATA
# ============================================================

def save_live(rate, sources, changed, previous_rate):
    current = get_previous_live()

    source_names = [x["source"] for x in sources]

    live = {
        "rate_22k": rate,
        "rate_8g": rate * 8,
        "date": today_string(),
        "time": time_string(),
        "timezone": "Asia/Kolkata",
        "changed": bool(changed),
        "previous_rate_22k": previous_rate,
        "sources": source_names,
        "source_details": sources,
        "last_fetch": now_ist().isoformat(),
        "status": "live",
    }

    # Preserve useful existing fields.
    if isinstance(current, dict):
        for key in ("history", "last_change", "market_status"):
            if key in current and key not in live:
                live[key] = current[key]

    save_json(LIVE_FILE, live)


# ============================================================
# HISTORY
# ============================================================

def save_history(rate, sources, changed):
    history = load_json(HISTORY_FILE, [])

    if not isinstance(history, list):
        history = []

    entry = {
        "date": today_string(),
        "time": time_string(),
        "timestamp": now_ist().isoformat(),
        "rate_22k": rate,
        "rate_8g": rate * 8,
        "changed": bool(changed),
        "sources": [x["source"] for x in sources],
    }

    # Do not create thousands of identical history records.
    if history:
        last = history[-1]

        if (
            last.get("date") == entry["date"]
            and last.get("rate_22k") == entry["rate_22k"]
        ):
            return

    history.append(entry)

    # Keep a generous history.
    history = history[-5000:]

    save_json(HISTORY_FILE, history)


# ============================================================
# MONITOR
# ============================================================

def monitor():
    print("=" * 70)
    print("CHENNAI 22K GOLD RATE — FULL WINDOW MONITOR")
    print("=" * 70)

    now = now_ist()

    print(f"IST time: {now.strftime('%d-%m-%Y %I:%M:%S %p')}")

    previous_rate = get_previous_rate()

    print(f"Previous saved 22K rate: ₹{previous_rate:,}" if previous_rate else
          "Previous saved 22K rate: NONE")

    windows = load_windows()

    print(
        f"AM window: {windows['am']['start']} - {windows['am']['end']}"
    )

    print(
        f"PM window: {windows['pm']['start']} - {windows['pm']['end']}"
    )

    window = active_window()

    # --------------------------------------------------------
    # OUTSIDE WINDOW
    # --------------------------------------------------------

    if not window:
        print()
        print("Currently outside monitoring window.")
        print("Performing ONE normal fetch and exiting.")

        results = fetch_all_sources()

        if results:
            rates = [x["rate_22k"] for x in results]

            # Prefer LiveChennai when available.
            rate = rates[0]

            if previous_rate is None:
                changed = True
            else:
                changed = rate != previous_rate

            save_live(rate, results, changed, previous_rate)
            save_history(rate, results, changed)

            print()
            print(f"Current 22K rate: ₹{rate:,}")
            print(f"Changed: {changed}")
        else:
            print("Both sources failed.")
            print("Previous valid rate retained.")

        print("NORMAL FETCH COMPLETE")
        return

    # --------------------------------------------------------
    # INSIDE WINDOW
    # --------------------------------------------------------

    start = window["start"]
    end = window["end"]

    print()
    print(f"ACTIVE WINDOW: {window['name'].upper()}")
    print(
        f"Monitoring from "
        f"{start.strftime('%I:%M %p')} "
        f"until "
        f"{end.strftime('%I:%M %p')}"
    )
    print()
    print("Polling interval: 10 seconds")
    print("The monitor WILL remain active for the complete window")
    print("unless a NEW price is discovered.")
    print()

    # If workflow started just before the window, wait until start.
    now = now_ist()

    if now < start:
        wait_seconds = int((start - now).total_seconds())

        print(
            f"Waiting {wait_seconds} seconds until "
            f"monitoring window starts..."
        )

        time.sleep(wait_seconds)

    # Hard safety limit.
    hard_end = min(
        end,
        now_ist() + timedelta(minutes=MAX_MONITOR_MINUTES)
    )

    attempt = 0
    last_seen_rates = {}

    while True:
        now = now_ist()

        if now >= hard_end:
            print()
            print("MONITORING WINDOW FINISHED.")
            print("No new price was discovered.")
            break

        attempt += 1

        remaining = int((hard_end - now).total_seconds())

        print()
        print(
            f"[{time_string()}] "
            f"Attempt #{attempt} "
            f"| approximately {remaining // 60}m "
            f"{remaining % 60}s remaining"
        )

        results = fetch_all_sources()

        if not results:
            print("  No source returned a valid rate.")
        else:
            for item in results:
                print(
                    f"  {item['source']}: "
                    f"₹{item['rate_22k']:,}"
                )

            # ------------------------------------------------
            # SOURCE ANALYSIS
            # ------------------------------------------------

            # Prefer LiveChennai.
            live_result = next(
                (
                    x for x in results
                    if x["source"] == "LiveChennai"
                ),
                None,
            )

            good_result = next(
                (
                    x for x in results
                    if x["source"] == "GoodReturns"
                ),
                None,
            )

            candidate = None

            if live_result:
                candidate = live_result["rate_22k"]
            elif good_result:
                candidate = good_result["rate_22k"]

            # Store what each source last saw.
            for item in results:
                last_seen_rates[item["source"]] = item["rate_22k"]

            # ------------------------------------------------
            # NEW PRICE
            # ------------------------------------------------

            if previous_rate is not None and candidate != previous_rate:

                print()
                print("************************************************")
                print("NEW 22K GOLD PRICE DISCOVERED")
                print("************************************************")
                print(
                    f"Previous: ₹{previous_rate:,}"
                )
                print(
                    f"New:      ₹{candidate:,}"
                )

                # If both sources are available, report agreement.
                if live_result and good_result:
                    if (
                        live_result["rate_22k"]
                        == good_result["rate_22k"]
                    ):
                        print("Source confirmation: BOTH SOURCES AGREE")
                    else:
                        print(
                            "Source status: sources differ; "
                            "using LiveChennai as primary."
                        )

                save_live(
                    candidate,
                    results,
                    True,
                    previous_rate,
                )

                save_history(
                    candidate,
                    results,
                    True,
                )

                print("NEW PRICE SAVED.")
                print("MONITORING STOPPED EARLY.")
                return

            # First-ever rate.
            if previous_rate is None and candidate:
                print("No previous rate exists.")
                print("Saving initial valid rate.")

                save_live(
                    candidate,
                    results,
                    True,
                    None,
                )

                save_history(
                    candidate,
                    results,
                    True,
                )

                print("INITIAL RATE SAVED.")
                return

            print(
                f"  No new price. Current remains ₹{candidate:,}"
                if candidate
                else
                "  No usable candidate rate."
            )

        # ----------------------------------------------------
        # WAIT EXACTLY 10 SECONDS
        # ----------------------------------------------------

        now = now_ist()

        if now + timedelta(seconds=POLL_SECONDS) >= hard_end:
            # One last opportunity at the end of the window.
            remaining = max(
                0,
                int((hard_end - now).total_seconds())
            )

            if remaining > 0:
                time.sleep(remaining)

            continue

        time.sleep(POLL_SECONDS)

    # --------------------------------------------------------
    # END OF WINDOW
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print("FULL MONITORING WINDOW COMPLETE")
    print("=" * 70)

    # Keep previous data if no new rate.
    if previous_rate:
        print(
            f"Retained verified rate: ₹{previous_rate:,}"
        )

    print("Workflow can now finish normally.")


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    try:
        monitor()

    except KeyboardInterrupt:
        print()
        print("Monitor manually stopped.")

    except Exception as e:
        print()
        print("FATAL ERROR:")
        print(str(e))
        sys.exit(1)
