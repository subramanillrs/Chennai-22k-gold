import json
import re
import time
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIGURATION
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

MIN_RATE = 5000
MAX_RATE = 30000


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
# NUMBER HELPERS
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

    if MIN_RATE <= number <= MAX_RATE:
        return int(round(number))

    return None


# ============================================================
# DATE PARSING
# ============================================================

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

    # Fallback for strings containing a date
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
                    f"{day}/{month}/{year}",
                    fmt
                ).date()
            except ValueError:
                pass

    return None


# ============================================================
# CURRENT RATE
# ============================================================

def parse_current_rate(html):
    soup = BeautifulSoup(html, "html.parser")

    rate = None
    last_update_time = None

    # --------------------------------------------------------
    # Search tables first
    # --------------------------------------------------------

    for table in soup.find_all("table"):

        rows = table.find_all("tr")

        for row in rows:

            cells = row.find_all(["th", "td"])

            values = [
                " ".join(cell.stripped_strings)
                for cell in cells
            ]

            if not values:
                continue

            joined = " ".join(values).lower()

            # A row containing 22K / 22 K
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

    # --------------------------------------------------------
    # Search entire page text as fallback
    # --------------------------------------------------------

    text = soup.get_text(" ", strip=True)

    if rate is None:

        patterns = [
            r"1\s*Gm\s*\(22\s*K\)\s*[:|]?\s*₹?\s*([\d,]+)",
            r"22\s*K\s*(?:Gold)?\s*(?:1\s*Gram|per\s*gram)\s*[:|]?\s*₹?\s*([\d,]+)",
            r"22\s*K\s*/\s*gram\s*[:|]?\s*₹?\s*([\d,]+)",
        ]

        for pattern in patterns:

            match = re.search(
                pattern,
                text,
                re.IGNORECASE,
            )

            if match:

                candidate = plausible_rate(
                    match.group(1)
                )

                if candidate is not None:
                    rate = candidate
                    break

    # --------------------------------------------------------
    # Last update time
    # --------------------------------------------------------

    time_match = re.search(
        r"Last\s*Update\s*Time\s*:\s*"
        r"(\d{1,2}/\d{1,2}/\d{4})"
        r"\s*"
        r"(\d{1,2}:\d{2}(?::\d{2})?)"
        r"\s*(AM|PM)?",
        text,
        re.IGNORECASE,
    )

    if time_match:
        last_update_time = (
            f"{time_match.group(1)} "
            f"{time_match.group(2)}"
        )

        if time_match.group(3):
            last_update_time += (
                f" {time_match.group(3).upper()}"
            )

    # --------------------------------------------------------
    # Another fallback: search for date + 22K rate
    # --------------------------------------------------------

    if rate is None:

        match = re.search(
            r"\d{1,2}/[A-Za-z]{3,9}/\d{4}"
            r".{0,100}?"
            r"([\d,]{4,6})",
            text,
            re.IGNORECASE,
        )

        if match:

            candidate = plausible_rate(
                match.group(1)
            )

            if candidate is not None:
                rate = candidate

    if rate is None:
        raise RuntimeError(
            "Could not find current Chennai 22K rate"
        )

    return rate, last_update_time


# ============================================================
# HISTORY FOR ONE MONTH
# ============================================================

def fetch_history_month(year, month):
    print(
        f"Fetching historical data: "
        f"{year}-{month:02d}"
    )

    html = get_html(
        HISTORY_URL,
        params={
            "monthno": month,
            "yearno": year,
        },
    )

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    records = []

    for table in soup.find_all("table"):

        rows = table.find_all("tr")

        if not rows:
            continue

        header_index = None

        for i, row in enumerate(rows[:5]):

            values = [
                " ".join(cell.stripped_strings)
                for cell in row.find_all(
                    ["th", "td"]
                )
            ]

            joined = " ".join(values).lower()

            if (
                "date" in joined
                and "22" in joined
            ):
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

            rate_22k = plausible_rate(values[2])

            if rate_22k is None:
                continue

            records.append(
                {
                    "date": d.isoformat(),
                    "rate_22k": rate_22k,
                    "rate_24k": (
                        plausible_rate(values[1])
                    ),
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

    print(
        f"  Found {len(records)} records"
    )

    return records


# ============================================================
# LOAD JSON
# ============================================================

def load_json(path, default):
    if not path.exists():
        return default

    try:
        with path.open(
            "r",
            encoding="utf-8",
        ) as f:
            return json.load(f)

    except Exception:
        return default


# ============================================================
# SAVE JSON
# ============================================================

def save_json(path, data):
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = path.with_suffix(
        path.suffix + ".tmp"
    )

    with temporary.open(
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2,
        )

    temporary.replace(path)


# ============================================================
# BUILD DAILY HISTORY
# ============================================================

def update_historical_data():
    existing = load_json(
        HISTORY_FILE,
        [],
    )

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

    # --------------------------------------------------------
    # If history is empty, build approximately 3 years.
    # Otherwise update the current month only.
    # --------------------------------------------------------

    if not by_date:

        print(
            "No historical database found."
        )

        print(
            "Building approximately 3 years "
            "of daily history..."
        )

        start_year = today.year - 3
        start_month = today.month

        months = []

        year = start_year
        month = start_month

        while (
            year < today.year
            or (
                year == today.year
                and month <= today.month
            )
        ):

            months.append(
                (year, month)
            )

            month += 1

            if month == 13:
                month = 1
                year += 1

        for year, month in months:

            try:
                records = fetch_history_month(
                    year,
                    month,
                )

                for item in records:
                    by_date[item["date"]] = item

            except Exception as exc:

                print(
                    f"History error "
                    f"{year}-{month:02d}: "
                    f"{exc}"
                )

            time.sleep(0.2)

    else:

        print(
            "Existing historical database found."
        )

        print(
            "Updating current month..."
        )

        try:

            records = fetch_history_month(
                today.year,
                today.month,
            )

            for item in records:
                by_date[item["date"]] = item

        except Exception as exc:

            print(
                "Current month history update "
                f"failed: {exc}"
            )

    records = list(by_date.values())

    records.sort(
        key=lambda x: x["date"]
    )

    save_json(
        HISTORY_FILE,
        records,
    )

    print(
        f"Historical database contains "
        f"{len(records)} daily records."
    )

    return records


# ============================================================
# LIVE SNAPSHOT
# ============================================================

def update_live_data(
    current_rate,
    source_last_update_time,
):
    now = datetime.now(IST)

    live = load_json(
        LIVE_FILE,
        {},
    )

    if not isinstance(live, dict):
        live = {}

    previous_rate = live.get("rate_22k")

    changed = (
        previous_rate is not None
        and int(previous_rate) != int(current_rate)
    )

    # --------------------------------------------------------
    # Keep a compact two-times-per-day change history.
    # --------------------------------------------------------

    snapshots = live.get(
        "intraday",
        [],
    )

    if not isinstance(snapshots, list):
        snapshots = []

    today = now.date().isoformat()

    session = (
        "AM"
        if now.hour < 13
        else "PM"
    )

    # If rate changed, save the change.
    if changed:

        snapshots.append(
            {
                "date": today,
                "time": now.strftime(
                    "%H:%M:%S"
                ),
                "rate_22k": int(current_rate),
                "rate_8g": int(current_rate) * 8,
                "session": session,
                "type": "live_change",
            }
        )

    # Keep only the last 100 snapshots.
    snapshots = snapshots[-100:]

    # --------------------------------------------------------
    # Find latest actual rate change.
    # --------------------------------------------------------

    last_change = live.get(
        "last_change",
        None,
    )

    if changed:

        last_change = {
            "date": today,
            "time": now.strftime(
                "%H:%M:%S"
            ),
            "rate_22k": int(current_rate),
            "rate_8g": int(current_rate) * 8,
            "previous_rate_22k": (
                int(previous_rate)
            ),
            "change": (
                int(current_rate)
                - int(previous_rate)
            ),
            "session": session,
        }

    # --------------------------------------------------------
    # Current live data
    # --------------------------------------------------------

    live_data = {
        "rate_22k": int(current_rate),
        "rate_8g": int(current_rate) * 8,

        "rate_24k": None,
        "rate_18k": None,

        "updated_at": now.isoformat(),

        "date": today,

        "time": now.strftime(
            "%H:%M:%S"
        ),

        "session": session,

        "source": "LiveChennai",

        "source_url": CURRENT_URL,

        "source_last_update": (
            source_last_update_time
        ),

        "changed": changed,

        "previous_rate_22k": (
            int(previous_rate)
            if previous_rate is not None
            else None
        ),

        "change": (
            int(current_rate)
            - int(previous_rate)
            if previous_rate is not None
            else 0
        ),

        "last_change": last_change,

        "intraday": snapshots,
    }

    save_json(
        LIVE_FILE,
        live_data,
    )

    return live_data


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("CHENNAI 22K GOLD RATE UPDATE")
    print("=" * 60)

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # Current rate
    # --------------------------------------------------------

    print()
    print("Fetching current Chennai rate...")

    html = get_html(
        CURRENT_URL
    )

    current_rate, source_time = (
        parse_current_rate(html)
    )

    print(
        f"Current 22K rate: "
        f"₹{current_rate:,}/gram"
    )

    print(
        f"Current 22K / 8g: "
        f"₹{current_rate * 8:,}"
    )

    if source_time:
        print(
            f"LiveChennai update time: "
            f"{source_time}"
        )

    # --------------------------------------------------------
    # Historical data
    # --------------------------------------------------------

    history = update_historical_data()

    # --------------------------------------------------------
    # Live data
    # --------------------------------------------------------

    live = update_live_data(
        current_rate,
        source_time,
    )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    print()
    print("=" * 60)
    print("UPDATE COMPLETE")
    print("=" * 60)

    print(
        f"22K / gram : "
        f"₹{live['rate_22k']:,}"
    )

    print(
        f"22K / 8 g  : "
        f"₹{live['rate_8g']:,}"
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
        f"Session    : "
        f"{live['session']}"
    )

    print(
        f"Changed    : "
        f"{live['changed']}"
    )

    print(
        f"History    : "
        f"{len(history)} records"
    )

    if live.get("last_change"):

        change = live["last_change"]

        print()
        print("LAST RATE CHANGE")
        print(
            f"Date       : "
            f"{change['date']}"
        )
        print(
            f"Time       : "
            f"{change['time']}"
        )
        print(
            f"Previous   : "
            f"₹{change['previous_rate_22k']:,}"
        )
        print(
            f"Current    : "
            f"₹{change['rate_22k']:,}"
        )
        print(
            f"Change     : "
            f"₹{change['change']:+,}"
        )

    print("=" * 60)


if __name__ == "__main__":
    main()
