import json
import re
import time
from collections import Counter
from datetime import datetime, timedelta, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

# ============================================================
# CHENNAI 22K GOLD RATE - ADAPTIVE MONITOR
#
# Strategy:
# 1. Keep a persistent timestamped change history.
# 2. Use up to 3 months of observations to establish AM/PM
#    monitoring windows.
# 3. After the baseline exists, automatically recalibrate from
#    the most recent 30 days.
# 4. During a monitoring window, poll every 10 seconds, up to
#    400 attempts (~66 minutes 40 seconds).
# 5. Stop immediately when the source rate changes.
#
# IMPORTANT:
# Daily historical prices do NOT contain reliable change times.
# Time-of-day learning therefore uses persistent change_history
# captured by this script on successful runs.
# ============================================================

CURRENT_URL = "https://www.livechennai.com/gold_silverrate.asp"
HISTORY_URL = "https://www.livechennai.com/get_goldrate_history.asp"

DATA_DIR = Path("data")
LIVE_FILE = DATA_DIR / "live.json"
HISTORY_FILE = DATA_DIR / "history.json"

IST = ZoneInfo("Asia/Kolkata")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    )
}

# There is intentionally NO arbitrary 5,000 / 30,000 rate filter.
MIN_VALID_RATE = 1000
MAX_VALID_RATE = 100000

POLL_SECONDS = 10
MAX_ATTEMPTS = 400

# Broad safety windows used only until enough observations exist.
DEFAULT_AM_START = 7 * 60 + 30   # 07:30 IST
DEFAULT_AM_END = 12 * 60 + 30    # 12:30 IST
DEFAULT_PM_START = 15 * 60 + 30  # 15:30 IST
DEFAULT_PM_END = 21 * 60 + 30    # 21:30 IST

# Minimum/maximum learned window width.
MIN_WINDOW_MINUTES = 60
MAX_WINDOW_MINUTES = 180

# ============================================================
# HTTP
# ============================================================

def get_html(url, params=None):
    response = requests.get(
        url,
        params=params,
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()
    return response.text


# ============================================================
# NUMBER / DATE HELPERS
# ============================================================

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

    if MIN_VALID_RATE <= number <= MAX_VALID_RATE:
        return int(round(number))

    return None


def parse_date(text):
    if not text:
        return None

    text = " ".join(str(text).split())

    formats = [
        "%d/%B/%Y",
        "%d/%b/%Y",
        "%d/%m/%Y",
        "%d/%m/%y",
        "%d-%m-%Y",
        "%d-%m-%y",
        "%Y-%m-%d",
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
                return datetime(
                    int(year), int(month), int(day)
                ).date()
            except ValueError:
                return None

        for fmt in ("%d/%B/%Y", "%d/%b/%Y"):
            try:
                return datetime.strptime(
                    f"{day}/{month}/{year}",
                    fmt,
                ).date()
            except ValueError:
                pass

    return None


# ============================================================
# CURRENT RATE PARSER
# ============================================================

def parse_current_rate(html):
    soup = BeautifulSoup(html, "html.parser")

    rate = None
    last_update_time = None

    # Prefer an explicitly labelled 22K / 1 gram field.
    explicit_patterns = [
        r"1\s*Gm\s*\(22\s*K\)\s*[:|]?\s*₹?\s*([\d,]+(?:\.\d+)?)",
        r"1\s*Gram\s*\(22\s*K\)\s*[:|]?\s*₹?\s*([\d,]+(?:\.\d+)?)",
        r"22\s*K\s*(?:Gold)?\s*(?:1\s*Gram|per\s*gram)\s*[:|]?\s*₹?\s*([\d,]+(?:\.\d+)?)",
        r"22\s*K\s*/\s*gram\s*[:|]?\s*₹?\s*([\d,]+(?:\.\d+)?)",
    ]

    page_text = soup.get_text(" ", strip=True)

    for pattern in explicit_patterns:
        match = re.search(pattern, page_text, re.IGNORECASE)
        if match:
            candidate = plausible_rate(match.group(1))
            if candidate is not None:
                rate = candidate
                break

    # Search tables by header labels and column position.
    if rate is None:
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if not rows:
                continue

            headers = []
            for row in rows[:5]:
                cells = row.find_all(["th", "td"])
                values = [
                    " ".join(c.stripped_strings)
                    for c in cells
                ]
                joined = " ".join(values).lower()

                if "22" in joined and (
                    "gold" in joined
                    or "gm" in joined
                    or "gram" in joined
                ):
                    headers = values
                    break

            # If a row itself contains an explicit 22K label,
            # use the numeric value in that row.
            for row in rows:
                values = [
                    " ".join(c.stripped_strings)
                    for c in row.find_all(["th", "td"])
                ]
                joined = " ".join(values).lower()

                if "22" not in joined:
                    continue
                if "gold" not in joined and "gm" not in joined and "gram" not in joined:
                    continue

                for value in values:
                    candidate = plausible_rate(value)
                    if candidate is not None:
                        rate = candidate
                        break

                if rate is not None:
                    break

            if rate is not None:
                break

    # Last fallback: date + nearby rate.
    if rate is None:
        match = re.search(
            r"\d{1,2}/[A-Za-z]{3,9}/\d{4}"
            r".{0,160}?([\d,]{4,6})",
            page_text,
            re.IGNORECASE,
        )
        if match:
            rate = plausible_rate(match.group(1))

    time_match = re.search(
        r"Last\s*Update\s*Time\s*:\s*"
        r"(\d{1,2}/\d{1,2}/\d{4})"
        r"\s*"
        r"(\d{1,2}:\d{2}(?::\d{2})?)"
        r"\s*(AM|PM)?",
        page_text,
        re.IGNORECASE,
    )

    if time_match:
        last_update_time = (
            f"{time_match.group(1)} {time_match.group(2)}"
        )
        if time_match.group(3):
            last_update_time += (
                f" {time_match.group(3).upper()}"
            )

    if rate is None:
        raise RuntimeError(
            "Could not find a valid Chennai 22K rate on the source page."
        )

    return rate, last_update_time


# ============================================================
# JSON
# ============================================================

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
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2,
        )

    temporary.replace(path)


# ============================================================
# HISTORICAL DAILY DATA
# ============================================================

def fetch_history_month(year, month):
    print(f"Fetching historical data: {year}-{month:02d}")

    html = get_html(
        HISTORY_URL,
        params={
            "monthno": month,
            "yearno": year,
        },
    )

    soup = BeautifulSoup(html, "html.parser")
    records = []

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue

        header_index = None

        for i, row in enumerate(rows[:6]):
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
            values = [
                " ".join(cell.stripped_strings)
                for cell in cells
            ]

            if len(values) < 3:
                continue

            d = parse_date(values[0])
            if d is None:
                continue

            # The existing source format has 24K and 22K in
            # adjacent columns. Prefer the third field as before.
            rate_22k = plausible_rate(values[2])
            if rate_22k is None:
                continue

            records.append(
                {
                    "date": d.isoformat(),
                    "rate_22k": rate_22k,
                    "rate_24k": plausible_rate(values[1]),
                    "weight_1g": rate_22k,
                    "weight_8g": rate_22k * 8,
                    "source": "LiveChennai",
                    "source_url": (
                        f"{HISTORY_URL}"
                        f"?monthno={month}"
                        f"&yearno={year}"
                    ),
                    "type": "daily_history",
                }
            )

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

        item_date = item.get("date")
        item_rate = item.get("rate_22k")

        if item_date and item_rate:
            by_date[item_date] = item

    today = datetime.now(IST).date()

    # Build missing daily history from approximately 3 years.
    if not by_date:
        print("No historical database found.")
        print("Building approximately 3 years of daily history...")

        start_year = today.year - 3
        start_month = today.month

        months = []
        year = start_year
        month = start_month

        while (
            year < today.year
            or (year == today.year and month <= today.month)
        ):
            months.append((year, month))
            month += 1

            if month == 13:
                month = 1
                year += 1

        for year, month in months:
            try:
                records = fetch_history_month(year, month)
                for item in records:
                    by_date[item["date"]] = item
            except Exception as exc:
                print(
                    f"History error {year}-{month:02d}: {exc}"
                )

            time.sleep(0.2)

    else:
        print("Existing historical database found.")
        print("Updating current month...")

        try:
            records = fetch_history_month(
                today.year,
                today.month,
            )
            for item in records:
                by_date[item["date"]] = item
        except Exception as exc:
            print(f"Current month history update failed: {exc}")

    records = list(by_date.values())
    records.sort(key=lambda x: x["date"])

    save_json(HISTORY_FILE, records)

    print(
        f"Historical database contains "
        f"{len(records)} daily records."
    )

    return records


# ============================================================
# PERSISTENT CHANGE HISTORY
# ============================================================

def normalize_change_history(live):
    history = live.get("change_history", [])

    if not isinstance(history, list):
        history = []

    cleaned = []

    for item in history:
        if not isinstance(item, dict):
            continue

        timestamp = item.get("timestamp")
        rate = item.get("rate_22k")

        if not timestamp or rate is None:
            continue

        try:
            dt = datetime.fromisoformat(timestamp)
            rate = int(rate)
        except Exception:
            continue

        cleaned.append(
            {
                "timestamp": dt.astimezone(IST).isoformat(),
                "rate_22k": rate,
            }
        )

    cleaned.sort(key=lambda x: x["timestamp"])

    # Keep enough observations for 3-month learning.
    cutoff = datetime.now(IST) - timedelta(days=120)

    cleaned = [
        x for x in cleaned
        if datetime.fromisoformat(x["timestamp"]) >= cutoff
    ]

    return cleaned


def add_change_observation(live, current_rate, source_last_update):
    history = normalize_change_history(live)

    previous_rate = live.get("rate_22k")
    previous_source_time = live.get("source_last_update")

    changed = (
        previous_rate is not None
        and int(previous_rate) != int(current_rate)
    )

    source_changed = (
        source_last_update
        and previous_source_time
        and source_last_update != previous_source_time
    )

    # A source update-time change is useful as evidence of a
    # new publication, even if the displayed numeric rate did
    # not move.
    if changed or source_changed:
        now = datetime.now(IST)

        observation = {
            "timestamp": now.isoformat(),
            "rate_22k": int(current_rate),
        }

        # Avoid duplicate observations from repeated polling.
        if not history:
            history.append(observation)
        else:
            last = history[-1]
            last_time = datetime.fromisoformat(last["timestamp"])
            if (
                int(last["rate_22k"]) != int(current_rate)
                or (now - last_time).total_seconds() > 60
            ):
                history.append(observation)

    return history, changed, source_changed


# ============================================================
# ADAPTIVE WINDOW LEARNING
# ============================================================

def minutes_since_midnight(dt):
    return dt.hour * 60 + dt.minute


def circular_distance(a, b):
    diff = abs(a - b)
    return min(diff, 1440 - diff)


def cluster_center(values):
    if not values:
        return None

    # Simple circular mean for clock minutes.
    import math

    angles = [
        (v / 1440.0) * 2.0 * math.pi
        for v in values
    ]

    x = sum(math.cos(a) for a in angles)
    y = sum(math.sin(a) for a in angles)

    if x == 0 and y == 0:
        return int(round(sum(values) / len(values))) % 1440

    angle = math.atan2(y, x)
    if angle < 0:
        angle += 2.0 * math.pi

    return int(round(angle / (2.0 * math.pi) * 1440)) % 1440


def calculate_window(center, half_width):
    start = (center - half_width) % 1440
    end = (center + half_width) % 1440
    return start, end


def format_clock_minutes(value):
    value %= 1440
    hour = value // 60
    minute = value % 60
    suffix = "AM" if hour < 12 else "PM"
    display_hour = hour % 12
    if display_hour == 0:
        display_hour = 12
    return f"{display_hour}:{minute:02d} {suffix}"


def in_window(now_minutes, start, end):
    if start <= end:
        return start <= now_minutes <= end
    return now_minutes >= start or now_minutes <= end


def learned_windows(live):
    changes = normalize_change_history(live)
    now = datetime.now(IST)

    three_month_cutoff = now - timedelta(days=90)
    thirty_day_cutoff = now - timedelta(days=30)

    last_3m = [
        x for x in changes
        if datetime.fromisoformat(x["timestamp"]) >= three_month_cutoff
    ]

    last_30d = [
        x for x in changes
        if datetime.fromisoformat(x["timestamp"]) >= thirty_day_cutoff
    ]

    # Prefer 30-day observations when there are enough of them.
    source = last_30d if len(last_30d) >= 4 else last_3m
    source_name = "30-day" if source is last_30d else "3-month"

    am_values = []
    pm_values = []

    for item in source:
        dt = datetime.fromisoformat(item["timestamp"]).astimezone(IST)
        m = minutes_since_midnight(dt)

        # Split around noon. A change at exactly noon is treated as AM.
        if m < 12 * 60:
            am_values.append(m)
        else:
            pm_values.append(m)

    # Defaults are deliberately broad for the bootstrap phase.
    am_center = cluster_center(am_values)
    pm_center = cluster_center(pm_values)

    if am_center is None:
        am_center = (DEFAULT_AM_START + DEFAULT_AM_END) // 2

    if pm_center is None:
        pm_center = (DEFAULT_PM_START + DEFAULT_PM_END) // 2

    # A learned window is at least 60 minutes wide. With fewer
    # observations, use a broader window; as evidence grows,
    # tighten it around the observed cluster.
    def half_width(count):
        if count < 4:
            return 150
        if count < 8:
            return 120
        if count < 15:
            return 90
        return 60

    am_half = min(MAX_WINDOW_MINUTES // 2, half_width(len(am_values)))
    pm_half = min(MAX_WINDOW_MINUTES // 2, half_width(len(pm_values)))

    am_start, am_end = calculate_window(am_center, am_half)
    pm_start, pm_end = calculate_window(pm_center, pm_half)

    # If enough 30-day data exists, use it directly. Otherwise
    # the 3-month baseline remains in force.
    return {
        "source": source_name,
        "observations_3m": len(last_3m),
        "observations_30d": len(last_30d),
        "am": {
            "start": am_start,
            "end": am_end,
            "center": am_center,
            "observations": len(am_values),
        },
        "pm": {
            "start": pm_start,
            "end": pm_end,
            "center": pm_center,
            "observations": len(pm_values),
        },
    }


# ============================================================
# LIVE SNAPSHOT
# ============================================================

def write_live(
    current_rate,
    source_last_update,
    live,
    change_history,
    changed,
    source_changed,
):
    now = datetime.now(IST)
    today = now.date().isoformat()

    previous_rate = live.get("rate_22k")

    snapshots = live.get("intraday", [])
    if not isinstance(snapshots, list):
        snapshots = []

    snapshots.append(
        {
            "date": today,
            "time": now.strftime("%H:%M:%S"),
            "rate_22k": int(current_rate),
            "rate_8g": int(current_rate) * 8,
            "session": "AM" if now.hour < 12 else "PM",
            "type": "poll",
        }
    )

    # Keep a useful rolling polling history without allowing the
    # JSON file to grow indefinitely.
    snapshots = snapshots[-2000:]

    last_change = live.get("last_change")

    if changed:
        last_change = {
            "date": today,
            "time": now.strftime("%H:%M:%S"),
            "rate_22k": int(current_rate),
            "rate_8g": int(current_rate) * 8,
            "previous_rate_22k": (
                int(previous_rate)
                if previous_rate is not None
                else None
            ),
            "change": (
                int(current_rate) - int(previous_rate)
                if previous_rate is not None
                else 0
            ),
            "session": "AM" if now.hour < 12 else "PM",
            "source_update": source_last_update,
        }

    learned = learned_windows(
        {
            **live,
            "change_history": change_history,
        }
    )

    new_live = {
        "rate_22k": int(current_rate),
        "rate_8g": int(current_rate) * 8,
        "rate_24k": None,
        "rate_18k": None,
        "updated_at": now.isoformat(),
        "date": today,
        "time": now.strftime("%H:%M:%S"),
        "session": "AM" if now.hour < 12 else "PM",
        "source": "LiveChennai",
        "source_url": CURRENT_URL,
        "source_last_update": source_last_update,
        "changed": changed,
        "source_update_changed": source_changed,
        "previous_rate_22k": (
            int(previous_rate)
            if previous_rate is not None
            else None
        ),
        "change": (
            int(current_rate) - int(previous_rate)
            if previous_rate is not None
            else 0
        ),
        "last_change": last_change,
        "intraday": snapshots,
        "change_history": change_history,
        "adaptive_monitor": learned,
    }

    save_json(LIVE_FILE, new_live)
    return new_live


# ============================================================
# INTENSIVE MONITOR
# ============================================================

def intensive_monitor(initial_rate, initial_source_time, live):
    windows = learned_windows(live)

    now = datetime.now(IST)
    now_minutes = minutes_since_midnight(now)

    am = windows["am"]
    pm = windows["pm"]

    am_active = in_window(
        now_minutes,
        am["start"],
        am["end"],
    )
    pm_active = in_window(
        now_minutes,
        pm["start"],
        pm["end"],
    )

    print()
    print("ADAPTIVE MONITOR")
    print(
        f"Learning source: {windows['source']} observations"
    )
    print(
        f"3-month observations: "
        f"{windows['observations_3m']}"
    )
    print(
        f"30-day observations: "
        f"{windows['observations_30d']}"
    )
    print(
        f"AM window: "
        f"{format_clock_minutes(am['start'])} - "
        f"{format_clock_minutes(am['end'])}"
    )
    print(
        f"PM window: "
        f"{format_clock_minutes(pm['start'])} - "
        f"{format_clock_minutes(pm['end'])}"
    )

    if not (am_active or pm_active):
        print(
            "Outside adaptive monitoring window; "
            "performing one normal fetch."
        )
        return initial_rate, initial_source_time, False

    session = "AM" if am_active else "PM"

    print(
        f"Inside {session} monitoring window."
    )
    print(
        f"Polling every {POLL_SECONDS} seconds, "
        f"maximum {MAX_ATTEMPTS} attempts."
    )

    rate = initial_rate
    source_time = initial_source_time

    for attempt in range(1, MAX_ATTEMPTS + 1):
        if attempt > 1:
            time.sleep(POLL_SECONDS)

        try:
            html = get_html(CURRENT_URL)
            new_rate, new_source_time = parse_current_rate(html)
        except Exception as exc:
            print(
                f"[{datetime.now(IST).strftime('%H:%M:%S')}] "
                f"Attempt {attempt}/{MAX_ATTEMPTS} "
                f"fetch error: {exc}"
            )
            continue

        print(
            f"[{datetime.now(IST).strftime('%H:%M:%S')}] "
            f"Attempt {attempt}/{MAX_ATTEMPTS} "
            f"Rate=₹{new_rate:,} "
            f"Source={new_source_time or 'n/a'}"
        )

        rate_changed = int(new_rate) != int(rate)
        source_changed = (
            new_source_time
            and source_time
            and new_source_time != source_time
        )

        if rate_changed or source_changed:
            print()
            print(
                "RATE/SOURCE UPDATE DETECTED - "
                "stopping intensive monitoring."
            )
            return new_rate, new_source_time, True

    print()
    print(
        f"Reached maximum of {MAX_ATTEMPTS} attempts "
        f"without a detected update."
    )

    return rate, source_time, False


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 70)
    print("CHENNAI 22K GOLD RATE - ADAPTIVE MONITOR")
    print("=" * 70)

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Update daily history. This remains independent of the
    # time-of-day learning system.
    history = update_historical_data()

    print()
    print("Fetching current Chennai 22K rate...")

    html = get_html(CURRENT_URL)
    current_rate, source_time = parse_current_rate(html)

    print(f"Initial 22K rate: ₹{current_rate:,}/gram")
    print(f"Initial 22K / 8g: ₹{current_rate * 8:,}")

    if source_time:
        print(f"LiveChennai update time: {source_time}")

    live = load_json(LIVE_FILE, {})
    if not isinstance(live, dict):
        live = {}

    # First, decide whether this run is inside the learned
    # monitoring window.
    monitored_rate, monitored_source_time, monitor_detected = (
        intensive_monitor(
            current_rate,
            source_time,
            live,
        )
    )

    # Record the final observed state and any detected change.
    final_rate = monitored_rate
    final_source_time = monitored_source_time

    change_history, changed, source_changed = add_change_observation(
        live,
        final_rate,
        final_source_time,
    )

    # If the current run began with an old rate but the monitor
    # found a new rate, ensure that observation is retained.
    if (
        live.get("rate_22k") is not None
        and int(live.get("rate_22k")) != int(final_rate)
    ):
        changed = True

    final_live = write_live(
        final_rate,
        final_source_time,
        live,
        change_history,
        changed,
        source_changed,
    )

    print()
    print("=" * 70)
    print("UPDATE COMPLETE")
    print("=" * 70)
    print(f"22K / gram : ₹{final_live['rate_22k']:,}")
    print(f"22K / 8g   : ₹{final_live['rate_8g']:,}")
    print(f"Date       : {final_live['date']}")
    print(f"Time       : {final_live['time']}")
    print(f"Changed    : {final_live['changed']}")
    print(f"History    : {len(history)} daily records")
    print(
        f"Timed observations: "
        f"{len(final_live.get('change_history', []))}"
    )

    learned = final_live["adaptive_monitor"]

    print()
    print("CURRENT ADAPTIVE WINDOWS")
    print(
        f"AM: {format_clock_minutes(learned['am']['start'])} "
        f"- {format_clock_minutes(learned['am']['end'])}"
    )
    print(
        f"PM: {format_clock_minutes(learned['pm']['start'])} "
        f"- {format_clock_minutes(learned['pm']['end'])}"
    )

    if final_live.get("last_change"):
        change = final_live["last_change"]
        print()
        print("LAST RATE CHANGE")
        print(f"Date     : {change['date']}")
        print(f"Time     : {change['time']}")
        print(
            f"Previous : ₹{change.get('previous_rate_22k', 'n/a')}"
        )
        print(f"Current  : ₹{change['rate_22k']:,}")
        print(f"Change   : ₹{change.get('change', 0):+,}")

    print("=" * 70)


if __name__ == "__main__":
    main()
