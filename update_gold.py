#!/usr/bin/env python3
"""
Chennai 22K Gold updater

Sources
-------
1. LiveChennai  - primary source
2. GoodReturns  - secondary/cross-check source
3. Previous verified rate - final safe fallback

Behaviour
---------
- Learns AM/PM monitoring windows from the last 90 days.
- Last 30 days are weighted more heavily.
- Only real clock-time observations are used for intraday learning.
- Inside an active monitoring window, polls every 10 seconds.
- If both sources agree, the rate is confirmed immediately.
- If only one source is available, the same value must repeat on the next
  successful poll before a new rate is accepted.
- If the two sources disagree, the system retries rather than blindly
  accepting either value.
- Outside the monitoring window, performs one bounded fetch and exits.
- Network requests have hard timeouts.
- Keeps the previous verified rate if both sources fail.
- Writes data/live.json, data/history.json and data/change_log.json.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup


# ============================================================
# BASIC CONFIGURATION
# ============================================================

IST = ZoneInfo("Asia/Kolkata")

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

LIVE_FILE = DATA / "live.json"
HISTORY_FILE = DATA / "history.json"
CHANGE_LOG_FILE = DATA / "change_log.json"
SEED_FILE = DATA / "historical_monitor_seed.json"


# ============================================================
# GOLD RATE SOURCES
# ============================================================

LIVECHENNAI_URL = (
    "https://www.livechennai.com/gold_silverrate.asp"
)

GOODRETURNS_URL = (
    "https://www.goodreturns.in/gold-rates/chennai.html"
)


# ============================================================
# NETWORK / MONITOR SETTINGS
# ============================================================

REQUEST_TIMEOUT = 8

# Poll every 10 seconds during an active monitoring window.
POLL_SECONDS = 10

# Emergency safety limit.
# 400 attempts = approximately 66 minutes of 10-second polling.
# This prevents a GitHub Actions job from running forever.
MAX_ATTEMPTS = 400


# ============================================================
# ADAPTIVE MONITOR SETTINGS
# ============================================================

LEARNING_DAYS = 90
PRIORITY_DAYS = 30

MIN_OBSERVATIONS = 3

WINDOW_HALF_WIDTH_MIN = 45
MIN_WINDOW_WIDTH_MIN = 30
MAX_WINDOW_WIDTH_MIN = 180


# Safe initial windows until enough observations are available.
FALLBACK_WINDOWS = {
    "AM": (
        8 * 60 + 30,
        11 * 60 + 30,
    ),
    "PM": (
        17 * 60,
        20 * 60,
    ),
}


# ============================================================
# HTTP HEADERS
# ============================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept": (
        "text/html,"
        "application/xhtml+xml,"
        "application/xml;q=0.9,"
        "*/*;q=0.8"
    ),
    "Cache-Control": "no-cache",
}


# ============================================================
# TIME HELPERS
# ============================================================

def now_ist() -> datetime:
    return datetime.now(IST)


def session_for_minutes(minutes: int) -> str:
    if minutes < 12 * 60:
        return "AM"
    return "PM"


def session_name(dt: datetime) -> str:
    if dt.hour < 12:
        return "AM"
    return "PM"


def minutes_from_time(value: str | None) -> int | None:
    if not value:
        return None

    match = re.match(
        r"^\s*(\d{1,2}):(\d{2})(?::\d{2})?\s*$",
        str(value),
    )

    if not match:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2))

    if hour > 23 or minute > 59:
        return None

    return hour * 60 + minute


def fmt_minutes(minutes: int) -> str:
    minutes %= 24 * 60

    hour, minute = divmod(minutes, 60)

    suffix = "AM" if hour < 12 else "PM"

    display_hour = hour % 12 or 12

    return f"{display_hour}:{minute:02d} {suffix}"


# ============================================================
# RATE VALIDATION
# ============================================================

def valid_rate(value) -> bool:
    try:
        value = int(float(value))
    except Exception:
        return False

    # Chennai 22K per gram sanity range.
    return 5000 <= value <= 30000


# ============================================================
# JSON HELPERS
# ============================================================

def load_json(path: Path, default):
    try:
        if not path.exists():
            return default

        with path.open(
            "r",
            encoding="utf-8",
        ) as file:
            return json.load(file)

    except Exception as exc:
        print(
            f"WARNING: cannot read {path}: {exc}"
        )
        return default


def save_json(path: Path, value) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    tmp = path.with_suffix(
        path.suffix + ".tmp"
    )

    with tmp.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            value,
            file,
            ensure_ascii=False,
            indent=2,
        )
        file.write("\n")

    tmp.replace(path)


# ============================================================
# HTTP
# ============================================================

def http_get(url: str) -> str:
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    return response.text


# ============================================================
# NUMBER EXTRACTION
# ============================================================

def extract_candidate_numbers(text: str) -> list[int]:

    values = []

    pattern = (
        r"(?:₹|Rs\.?|INR)?\s*"
        r"([0-9][0-9,]{3,})"
    )

    for raw in re.findall(
        pattern,
        text,
        re.I,
    ):
        try:
            value = int(
                raw.replace(",", "")
            )
        except ValueError:
            continue

        if valid_rate(value):
            values.append(value)

    return values


# ============================================================
# LIVECHENNAI PARSER
# ============================================================

def extract_livechennai_22k(
    html: str,
) -> int:

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    # --------------------------------------------------------
    # First: tables
    # --------------------------------------------------------

    for row in soup.find_all("tr"):

        cells = [
            cell.get_text(
                " ",
                strip=True,
            )
            for cell in row.find_all(
                ["th", "td"]
            )
        ]

        if not cells:
            continue

        joined = " | ".join(cells)

        if re.search(
            r"\b22\s*K\b|22\s*carat",
            joined,
            re.I,
        ):

            values = extract_candidate_numbers(
                joined
            )

            if values:
                return values[0]

    # --------------------------------------------------------
    # Second: visible text
    # --------------------------------------------------------

    text = soup.get_text(
        " ",
        strip=True,
    )

    patterns = [

        r"22\s*K.{0,220}?"
        r"(?:₹|Rs\.?|INR)?\s*"
        r"([0-9][0-9,]{3,})",

        r"22\s*carat.{0,220}?"
        r"(?:₹|Rs\.?|INR)?\s*"
        r"([0-9][0-9,]{3,})",

        r"(?:₹|Rs\.?|INR)?\s*"
        r"([0-9][0-9,]{3,})"
        r".{0,220}?22\s*K",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.I,
        )

        if not match:
            continue

        value = int(
            match.group(1).replace(
                ",",
                "",
            )
        )

        if valid_rate(value):
            return value

    raise RuntimeError(
        "Could not locate a valid Chennai "
        "22K rate on LiveChennai"
    )


# ============================================================
# GOODRETURNS PARSER
# ============================================================

def extract_goodreturns_22k(
    html: str,
) -> int:

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    # --------------------------------------------------------
    # First: inspect tables
    # --------------------------------------------------------

    for row in soup.find_all("tr"):

        cells = [
            cell.get_text(
                " ",
                strip=True,
            )
            for cell in row.find_all(
                ["th", "td"]
            )
        ]

        if not cells:
            continue

        joined = " | ".join(cells)

        if not re.search(
            r"22\s*carat|22\s*K",
            joined,
            re.I,
        ):
            continue

        # Prefer a value in a cell mentioning gram.
        for cell in cells:

            if re.search(
                r"(?:1\s*gram|per\s*gram|gram|gm)",
                cell,
                re.I,
            ):

                candidates = (
                    extract_candidate_numbers(
                        cell
                    )
                )

                if candidates:
                    return candidates[0]

        values = extract_candidate_numbers(
            joined
        )

        if values:
            return values[0]

    # --------------------------------------------------------
    # Second: visible text
    # --------------------------------------------------------

    text = soup.get_text(
        " ",
        strip=True,
    )

    patterns = [

        r"22\s*Carat.{0,180}?"
        r"(?:1\s*Gram|per\s*Gram|Gram).{0,100}?"
        r"(?:₹|Rs\.?|INR)?\s*"
        r"([0-9][0-9,]{3,})",

        r"22\s*K.{0,180}?"
        r"(?:1\s*Gram|per\s*Gram|Gram).{0,100}?"
        r"(?:₹|Rs\.?|INR)?\s*"
        r"([0-9][0-9,]{3,})",

        r"(?:₹|Rs\.?|INR)?\s*"
        r"([0-9][0-9,]{3,})"
        r".{0,100}?22\s*Carat",

        r"(?:₹|Rs\.?|INR)?\s*"
        r"([0-9][0-9,]{3,})"
        r".{0,100}?22\s*K",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.I,
        )

        if not match:
            continue

        value = int(
            match.group(1).replace(
                ",",
                "",
            )
        )

        if valid_rate(value):
            return value

    # --------------------------------------------------------
    # Third: inspect elements containing 22K
    # --------------------------------------------------------

    for element in soup.find_all(
        string=re.compile(
            r"22\s*(?:K|Carat)",
            re.I,
        )
    ):

        parent = element.parent

        if parent is None:
            continue

        if parent.parent is not None:
            context = parent.parent.get_text(
                " ",
                strip=True,
            )
        else:
            context = str(element)

        values = extract_candidate_numbers(
            context
        )

        if values:
            return values[0]

    raise RuntimeError(
        "Could not locate a valid Chennai "
        "22K rate on GoodReturns"
    )


# ============================================================
# INDIVIDUAL SOURCE FETCHERS
# ============================================================

def fetch_livechennai() -> dict:

    fetched_at = now_ist().isoformat()

    html = http_get(
        LIVECHENNAI_URL
    )

    rate = extract_livechennai_22k(
        html
    )

    return {
        "rate": rate,
        "source": "LiveChennai",
        "url": LIVECHENNAI_URL,
        "fetched_at": fetched_at,
    }


def fetch_goodreturns() -> dict:

    fetched_at = now_ist().isoformat()

    html = http_get(
        GOODRETURNS_URL
    )

    rate = extract_goodreturns_22k(
        html
    )

    return {
        "rate": rate,
        "source": "GoodReturns",
        "url": GOODRETURNS_URL,
        "fetched_at": fetched_at,
    }


# ============================================================
# FETCH BOTH SOURCES
# ============================================================

def fetch_sources():

    live = None
    good = None

    # --------------------------------------------------------
    # LiveChennai
    # --------------------------------------------------------

    try:

        live = fetch_livechennai()

        print(
            f"LiveChennai: "
            f"₹{live['rate']:,}/gram"
        )

    except Exception as exc:

        print(
            f"LiveChennai ERROR: {exc}"
        )

    # --------------------------------------------------------
    # GoodReturns
    # --------------------------------------------------------

    try:

        good = fetch_goodreturns()

        print(
            f"GoodReturns: "
            f"₹{good['rate']:,}/gram"
        )

    except Exception as exc:

        print(
            f"GoodReturns ERROR: {exc}"
        )

    return live, good


# ============================================================
# SOURCE DECISION
# ============================================================

def choose_observation(
    live: dict | None,
    good: dict | None,
) -> dict | None:

    # --------------------------------------------------------
    # Both sources available
    # --------------------------------------------------------

    if live and good:

        if live["rate"] == good["rate"]:

            return {
                "rate": live["rate"],
                "source": (
                    "LiveChennai + GoodReturns"
                ),
                "verification": (
                    "both_sources_agree"
                ),
                "verified": True,
                "source_url": (
                    LIVECHENNAI_URL
                ),
                "secondary_source_url": (
                    GOODRETURNS_URL
                ),
                "source_last_update": (
                    live.get("fetched_at")
                ),
            }

        print(
            "SOURCE DISAGREEMENT: "
            f"LiveChennai "
            f"₹{live['rate']:,} vs "
            f"GoodReturns "
            f"₹{good['rate']:,}"
        )

        return {
            "rate": None,
            "source": (
                "LiveChennai + GoodReturns"
            ),
            "verification": (
                "source_disagreement"
            ),
            "verified": False,
            "source_url": (
                LIVECHENNAI_URL
            ),
            "secondary_source_url": (
                GOODRETURNS_URL
            ),
            "source_last_update": (
                live.get("fetched_at")
            ),
        }

    # --------------------------------------------------------
    # Only LiveChennai available
    # --------------------------------------------------------

    if live:

        return {
            "rate": live["rate"],
            "source": "LiveChennai",
            "verification": "primary_only",
            "verified": False,
            "source_url": (
                LIVECHENNAI_URL
            ),
            "secondary_source_url": (
                GOODRETURNS_URL
            ),
            "source_last_update": (
                live.get("fetched_at")
            ),
        }

    # --------------------------------------------------------
    # Only GoodReturns available
    # --------------------------------------------------------

    if good:

        return {
            "rate": good["rate"],
            "source": "GoodReturns",
            "verification": "secondary_only",
            "verified": False,
            "source_url": (
                LIVECHENNAI_URL
            ),
            "secondary_source_url": (
                GOODRETURNS_URL
            ),
            "source_last_update": (
                good.get("fetched_at")
            ),
        }

    # --------------------------------------------------------
    # Neither available
    # --------------------------------------------------------

    return None


# ============================================================
# NORMALISE LEARNING EVENTS
# ============================================================

def normalise_events(raw):

    if isinstance(raw, dict):

        for key in (
            "events",
            "changes",
            "records",
            "observations",
            "data",
        ):

            if isinstance(
                raw.get(key),
                list,
            ):

                raw = raw[key]
                break

        else:
            raw = []

    if not isinstance(
        raw,
        list,
    ):
        return []

    out = []
    seen = set()

    for item in raw:

        if not isinstance(
            item,
            dict,
        ):
            continue

        date = str(
            item.get("date") or ""
        )[:10]

        tm = str(
            item.get("time") or ""
        )

        rate = item.get(
            "rate_22k",
            item.get(
                "rate",
                item.get(
                    "new_rate"
                ),
            ),
        )

        try:
            rate = int(
                float(rate)
            )
        except Exception:
            continue

        if not re.match(
            r"^\d{4}-\d{2}-\d{2}$",
            date,
        ):
            continue

        mins = minutes_from_time(
            tm
        )

        if mins is None:
            continue

        if not valid_rate(rate):
            continue

        key = (
            date,
            tm,
            rate,
        )

        if key in seen:
            continue

        seen.add(key)

        out.append(
            {
                "date": date,
                "time": (
                    tm
                    if len(tm) >= 5
                    else f"{tm}:00"
                ),
                "rate_22k": rate,
                "session": (
                    item.get("session")
                    or session_for_minutes(
                        mins
                    )
                ),
                "type": (
                    item.get("type")
                    or "live_change"
                ),
            }
        )

    return out


# ============================================================
# HISTORY TIME EVENTS
# ============================================================

def history_time_events(history):

    if not isinstance(
        history,
        list,
    ):
        return []

    out = []

    for item in history:

        if not isinstance(
            item,
            dict,
        ):
            continue

        tm = str(
            item.get("time") or ""
        )

        mins = minutes_from_time(
            tm
        )

        if mins is None:
            continue

        # Ignore common placeholder times.
        if tm in {
            "00:00",
            "00:00:00",
            "12:00",
            "12:00:00",
        }:
            continue

        rate = item.get(
            "rate_22k",
            item.get("rate"),
        )

        if not valid_rate(rate):
            continue

        out.append(
            {
                "date": str(
                    item.get("date") or ""
                )[:10],
                "time": tm,
                "rate_22k": int(
                    float(rate)
                ),
                "session": (
                    session_for_minutes(
                        mins
                    )
                ),
                "type": (
                    "historical_timed_observation"
                ),
            }
        )

    return out


# ============================================================
# LOAD 90-DAY OBSERVATIONS
# ============================================================

def load_observations():

    cutoff = (
        now_ist().date()
        - timedelta(
            days=LEARNING_DAYS
        )
    )

    cutoff30 = (
        now_ist().date()
        - timedelta(
            days=PRIORITY_DAYS
        )
    )

    events = normalise_events(
        load_json(
            CHANGE_LOG_FILE,
            [],
        )
    )

    # Bootstrap seed.
    seed = load_json(
        SEED_FILE,
        [],
    )

    if isinstance(
        seed,
        list,
    ):

        events += normalise_events(
            seed
        )

    # Current live intraday events.
    live = load_json(
        LIVE_FILE,
        {},
    )

    if isinstance(
        live,
        dict,
    ):

        events += normalise_events(
            live.get(
                "intraday",
                [],
            )
        )

    # Historical timed events.
    events += history_time_events(
        load_json(
            HISTORY_FILE,
            [],
        )
    )

    cleaned = []
    seen = set()

    for event in events:

        try:

            date = datetime.strptime(
                event["date"],
                "%Y-%m-%d",
            ).date()

        except Exception:
            continue

        if date < cutoff:
            continue

        key = (
            event["date"],
            event["time"],
            event["rate_22k"],
        )

        if key in seen:
            continue

        seen.add(key)

        event["priority"] = (
            "30d"
            if date >= cutoff30
            else "90d"
        )

        cleaned.append(
            event
        )

    cleaned.sort(
        key=lambda item: (
            item["date"],
            item["time"],
        )
    )

    return cleaned


# ============================================================
# ADAPTIVE WINDOW CALCULATION
# ============================================================

def adaptive_window(
    observations,
    session: str,
):

    candidates = []

    today = now_ist().date()

    for event in observations:

        if event.get(
            "session"
        ) != session:
            continue

        mins = minutes_from_time(
            event.get("time")
        )

        if mins is None:
            continue

        try:

            date = datetime.strptime(
                event["date"],
                "%Y-%m-%d",
            ).date()

        except Exception:
            continue

        age = max(
            0,
            (
                today - date
            ).days,
        )

        # Last 30 days have 3x weight.
        base = (
            3.0
            if age <= PRIORITY_DAYS
            else 1.0
        )

        recency = max(
            0.25,
            1.0
            - age
            / (
                LEARNING_DAYS
                * 1.4
            ),
        )

        weight = (
            base * recency
        )

        candidates.append(
            (
                mins,
                weight,
            )
        )

    # Not enough data.
    if len(candidates) < MIN_OBSERVATIONS:

        return {
            "start": (
                FALLBACK_WINDOWS[
                    session
                ][0]
            ),
            "end": (
                FALLBACK_WINDOWS[
                    session
                ][1]
            ),
            "learned": False,
            "observations": len(
                candidates
            ),
            "reason": (
                "insufficient observations"
            ),
        }

    candidates.sort()

    total = sum(
        weight
        for _, weight
        in candidates
    )

    accumulated = 0.0

    median = candidates[-1][0]

    for mins, weight in candidates:

        accumulated += weight

        if accumulated >= total / 2:

            median = mins
            break

    # Weighted MAD.
    deviations = sorted(
        (
            abs(
                mins - median
            ),
            weight,
        )
        for mins, weight
        in candidates
    )

    total_weight = sum(
        weight
        for _, weight
        in deviations
    )

    accumulated = 0.0

    mad = 30.0

    for deviation, weight in deviations:

        accumulated += weight

        if accumulated >= (
            total_weight / 2
        ):

            mad = float(
                deviation
            )

            break

    half = max(
        WINDOW_HALF_WIDTH_MIN,
        int(
            mad * 2.5
        ),
    )

    half = min(
        half,
        MAX_WINDOW_WIDTH_MIN
        // 2,
    )

    half = max(
        half,
        MIN_WINDOW_WIDTH_MIN
        // 2,
    )

    start = max(
        0,
        median - half,
    )

    end = min(
        24 * 60 - 1,
        median + half,
    )

    # Keep AM in the daytime AM area.
    if session == "AM":

        start = max(
            5 * 60,
            start,
        )

        end = min(
            13 * 60,
            end,
        )

    # Keep PM in the afternoon/evening area.
    else:

        start = max(
            14 * 60,
            start,
        )

        end = min(
            23 * 60,
            end,
        )

    return {
        "start": int(start),
        "end": int(end),
        "learned": True,
        "observations": len(
            candidates
        ),
        "median": int(
            median
        ),
        "mad": round(
            mad,
            1,
        ),
        "reason": (
            "weighted 30d/90d observations"
        ),
    }


def build_windows(
    observations,
):

    return {
        "AM": adaptive_window(
            observations,
            "AM",
        ),
        "PM": adaptive_window(
            observations,
            "PM",
        ),
    }


def in_window(
    current: datetime,
    window,
) -> bool:

    mins = (
        current.hour * 60
        + current.minute
    )

    return (
        window["start"]
        <= mins
        <= window["end"]
    )


# ============================================================
# CHANGE LOG
# ============================================================

def append_change_event(
    event,
):

    current = load_json(
        CHANGE_LOG_FILE,
        [],
    )

    if isinstance(
        current,
        dict,
    ):

        events = current.get(
            "events"
        )

        if not isinstance(
            events,
            list,
        ):
            events = []

        events.append(event)

        current = events

    elif not isinstance(
        current,
        list,
    ):

        current = []

    events = normalise_events(
        current
    )

    events = events[-1000:]

    save_json(
        CHANGE_LOG_FILE,
        events,
    )


# ============================================================
# WRITE LIVE.JSON
# ============================================================

def write_live(
    rate: int,
    previous: dict | None,
    changed: bool,
    observation: dict | None,
    event_time: datetime | None = None,
):

    dt = (
        event_time
        or now_ist()
    )

    if not isinstance(
        previous,
        dict,
    ):
        previous = {}

    previous_rate = previous.get(
        "rate_22k"
    )

    if valid_rate(
        previous_rate
    ):

        previous_rate = int(
            float(
                previous_rate
            )
        )

    else:

        previous_rate = None

    delta = (
        rate - previous_rate
        if previous_rate is not None
        else 0
    )

    event = None

    if (
        changed
        and previous_rate is not None
    ):

        event = {
            "date": (
                dt.date().isoformat()
            ),
            "time": (
                dt.strftime(
                    "%H:%M:%S"
                )
            ),
            "rate_22k": rate,
            "rate_8g": rate * 8,
            "previous_rate_22k": (
                previous_rate
            ),
            "change": delta,
            "session": session_name(
                dt
            ),
            "type": "live_change",
            "source": (
                observation.get(
                    "source"
                )
                if observation
                else previous.get(
                    "source"
                )
            ),
            "verification": (
                observation.get(
                    "verification"
                )
                if observation
                else previous.get(
                    "verification"
                )
            ),
        }

    old_intraday = previous.get(
        "intraday",
        [],
    )

    if not isinstance(
        old_intraday,
        list,
    ):
        old_intraday = []

    intraday = list(
        old_intraday
    )

    if event:

        intraday.append(
            event
        )

        intraday = intraday[-100:]

    source = (
        observation.get(
            "source"
        )
        if observation
        else previous.get(
            "source",
            "LiveChennai",
        )
    )

    verification = (
        observation.get(
            "verification"
        )
        if observation
        else previous.get(
            "verification",
            "previous_verified_rate",
        )
    )

    verified = (
        observation.get(
            "verified"
        )
        if observation
        else previous.get(
            "verified",
            False,
        )
    )

    live = {

        "rate_22k": rate,

        "rate_8g": (
            rate * 8
        ),

        "rate_24k": None,

        "rate_18k": None,

        "updated_at": (
            dt.isoformat()
        ),

        "date": (
            dt.date().isoformat()
        ),

        "time": (
            dt.strftime(
                "%H:%M:%S"
            )
        ),

        "session": (
            session_name(dt)
        ),

        "source": source,

        "source_url": (
            observation.get(
                "source_url"
            )
            if observation
            else previous.get(
                "source_url",
                LIVECHENNAI_URL,
            )
        ),

        "secondary_source_url": (
            observation.get(
                "secondary_source_url"
            )
            if observation
            else previous.get(
                "secondary_source_url",
                GOODRETURNS_URL,
            )
        ),

        "source_last_update": (
            observation.get(
                "source_last_update"
            )
            if observation
            else previous.get(
                "source_last_update"
            )
        ),

        "verification": verification,

        "verified": bool(
            verified
        ),

        "changed": bool(
            changed
        ),

        "previous_rate_22k": (
            previous_rate
        ),

        "change": delta,

        "last_change": (
            event
            if event
            else previous.get(
                "last_change"
            )
        ),

        "intraday": intraday,
    }

    save_json(
        LIVE_FILE,
        live,
    )

    return live, event


# ============================================================
# UPDATE DAILY HISTORY
# ============================================================

def update_history(
    live,
):

    history = load_json(
        HISTORY_FILE,
        [],
    )

    if not isinstance(
        history,
        list,
    ):
        history = []

    date = live["date"]

    row = {

        "date": date,

        "rate_22k": (
            live["rate_22k"]
        ),

        "rate_8g": (
            live["rate_8g"]
        ),

        "source": (
            live.get(
                "source",
                "LiveChennai",
            )
        ),

        "updated_at": (
            live["updated_at"]
        ),

        "verification": (
            live.get(
                "verification"
            )
        ),

        "verified": (
            live.get(
                "verified",
                False,
            )
        ),
    }

    replaced = False

    for index, item in enumerate(
        history
    ):

        if (
            isinstance(
                item,
                dict,
            )
            and item.get(
                "date"
            )
            == date
        ):

            history[index] = {
                **item,
                **row,
            }

            replaced = True
            break

    if not replaced:

        history.append(
            row
        )

    history.sort(
        key=lambda item:
        str(
            item.get(
                "date",
                "",
            )
        )
    )

    save_json(
        HISTORY_FILE,
        history,
    )


# ============================================================
# FETCH ONE VERIFIED OBSERVATION
# ============================================================

def fetch_verified_once():

    live, good = fetch_sources()

    observation = choose_observation(
        live,
        good,
    )

    if (
        observation
        and observation.get(
            "rate"
        ) is not None
    ):

        print(
            f"Selected rate: "
            f"₹{observation['rate']:,}/gram "
            f"[{observation['source']} / "
            f"{observation['verification']}]"
        )

        return observation

    return None


# ============================================================
# ACTIVE MONITOR
# ============================================================

def monitor(
    window,
    initial_observation,
    initial_rate,
):

    print(
        "Monitoring window: "
        f"{fmt_minutes(window['start'])} - "
        f"{fmt_minutes(window['end'])}"
    )

    print(
        f"Polling every {POLL_SECONDS}s, "
        f"maximum {MAX_ATTEMPTS} attempts"
    )

    baseline = initial_rate

    last_seen_candidate = None

    candidate_count = 0

    for attempt in range(
        1,
        MAX_ATTEMPTS + 1,
    ):

        # Stop as soon as the learned window ends.
        current = now_ist()

        if not in_window(
            current,
            window,
        ):

            print(
                "Monitoring window ended."
            )

            return (
                baseline,
                initial_observation,
                attempt - 1,
            )

        observation = (
            fetch_verified_once()
        )

        if observation is None:

            print(
                f"Attempt "
                f"{attempt}/{MAX_ATTEMPTS}: "
                "no verified observation."
            )

        else:

            rate = observation[
                "rate"
            ]

            print(
                f"Attempt "
                f"{attempt}/{MAX_ATTEMPTS}: "
                f"₹{rate:,}/gram; "
                f"verification="
                f"{observation['verification']}"
            )

            # ------------------------------------------------
            # Price unchanged
            # ------------------------------------------------

            if rate == baseline:

                last_seen_candidate = None
                candidate_count = 0

            # ------------------------------------------------
            # New price
            # ------------------------------------------------

            else:

                # Both sources agree.
                if observation[
                    "verified"
                ]:

                    print(
                        "CONFIRMED RATE CHANGE: "
                        f"₹{baseline:,} -> "
                        f"₹{rate:,}"
                    )

                    return (
                        rate,
                        observation,
                        attempt,
                    )

                # Single-source result.
                # Require same value twice.
                if (
                    last_seen_candidate
                    == rate
                ):

                    candidate_count += 1

                else:

                    last_seen_candidate = rate

                    candidate_count = 1

                if candidate_count >= 2:

                    observation = dict(
                        observation
                    )

                    observation[
                        "verified"
                    ] = True

                    observation[
                        "verification"
                    ] = (
                        "single_source_repeated"
                    )

                    print(
                        "CONFIRMED REPEATED "
                        "RATE CHANGE: "
                        f"₹{baseline:,} -> "
                        f"₹{rate:,}"
                    )

                    return (
                        rate,
                        observation,
                        attempt,
                    )

                print(
                    "New single-source value "
                    "seen once; waiting "
                    "for confirmation."
                )

        # ----------------------------------------------------
        # Wait 10 seconds before next fetch.
        # ----------------------------------------------------

        if attempt < MAX_ATTEMPTS:

            time.sleep(
                POLL_SECONDS
            )

    print(
        "Safety attempt limit reached "
        "without a confirmed rate change."
    )

    return (
        baseline,
        initial_observation,
        MAX_ATTEMPTS,
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "=" * 70
    )

    print(
        "CHENNAI 22K GOLD RATE — "
        "ADAPTIVE MONITOR"
    )

    print(
        "=" * 70
    )

    DATA.mkdir(
        parents=True,
        exist_ok=True,
    )

    previous = load_json(
        LIVE_FILE,
        {},
    )

    history = load_json(
        HISTORY_FILE,
        [],
    )

    history_count = (
        len(history)
        if isinstance(
            history,
            list,
        )
        else 0
    )

    print(
        "Historical database contains "
        f"{history_count} daily records."
    )

    observations = (
        load_observations()
    )

    windows = build_windows(
        observations
    )

    print(
        f"3-month observations: "
        f"{len(observations)}"
    )

    print(
        "30-day observations: "
        f"{sum(1 for x in observations if x.get('priority') == '30d')}"
    )

    for session in (
        "AM",
        "PM",
    ):

        window = windows[
            session
        ]

        print(
            f"{session} window: "
            f"{fmt_minutes(window['start'])} - "
            f"{fmt_minutes(window['end'])} "
            f"("
            f"{'LEARNED' if window['learned'] else 'FALLBACK'}; "
            f"{window['observations']} obs)"
        )

    # ========================================================
    # INITIAL DUAL-SOURCE FETCH
    # ========================================================

    print(
        "Fetching current Chennai 22K "
        "rate from both sources..."
    )

    initial_observation = (
        fetch_verified_once()
    )

    if initial_observation is None:

        print(
            "ERROR: neither source returned "
            "a usable observation."
        )

        if valid_rate(
            previous.get(
                "rate_22k"
            )
        ):

            print(
                "Keeping previous successful "
                "live rate."
            )

            return

        raise RuntimeError(
            "No usable gold rate available "
            "from either source"
        )

    initial_rate = int(
        initial_observation[
            "rate"
        ]
    )

    print(
        f"Initial 22K rate: "
        f"₹{initial_rate:,}/gram"
    )

    print(
        f"Initial 22K / 8g: "
        f"₹{initial_rate * 8:,}"
    )

    # ========================================================
    # DETERMINE CURRENT WINDOW
    # ========================================================

    current = now_ist()

    current_session = (
        session_name(
            current
        )
    )

    window = windows[
        current_session
    ]

    # ========================================================
    # INSIDE WINDOW
    # ========================================================

    if in_window(
        current,
        window,
    ):

        print(
            "INSIDE adaptive "
            "monitoring window."
        )

        (
            final_rate,
            final_observation,
            attempts,
        ) = monitor(
            window,
            initial_observation,
            initial_rate,
        )

    # ========================================================
    # OUTSIDE WINDOW
    # ========================================================

    else:

        print(
            "Outside adaptive "
            "monitoring window; "
            "performing one normal fetch."
        )

        final_rate = initial_rate

        final_observation = (
            initial_observation
        )

        attempts = 1

    # ========================================================
    # DETERMINE WHETHER DAILY PRICE CHANGED
    # ========================================================

    previous_rate = previous.get(
        "rate_22k"
    )

    if valid_rate(
        previous_rate
    ):

        previous_rate_int = int(
            float(
                previous_rate
            )
        )

    else:

        previous_rate_int = None

    changed = (
        previous_rate_int is not None
        and final_rate
        != previous_rate_int
    )

    # ========================================================
    # WRITE LIVE DATA
    # ========================================================

    live, event = write_live(
        final_rate,
        previous,
        changed,
        final_observation,
    )

    # ========================================================
    # SAVE CHANGE EVENT
    # ========================================================

    if event:

        append_change_event(
            event
        )

        print(
            "Recorded intraday change at "
            f"{event['date']} "
            f"{event['time']} "
            f"({event['session']})."
        )

    # ========================================================
    # UPDATE HISTORY
    # ========================================================

    update_history(
        live
    )

    # ========================================================
    # FINAL OUTPUT
    # ========================================================

    print(
        "=" * 70
    )

    print(
        "UPDATE COMPLETE"
    )

    print(
        "=" * 70
    )

    print(
        f"22K / gram : "
        f"₹{final_rate:,}"
    )

    print(
        f"22K / 8g   : "
        f"₹{final_rate * 8:,}"
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
        f"Source     : "
        f"{live['source']}"
    )

    print(
        f"Verification: "
        f"{live['verification']}"
    )

    print(
        f"Verified   : "
        f"{live['verified']}"
    )

    print(
        f"Attempts   : "
        f"{attempts}"
    )

    print(
        "Timed observations now: "
        f"{len(load_observations())}"
    )

    print(
        "Current windows: "
        f"AM {fmt_minutes(windows['AM']['start'])} - "
        f"{fmt_minutes(windows['AM']['end'])}; "
        f"PM {fmt_minutes(windows['PM']['start'])} - "
        f"{fmt_minutes(windows['PM']['end'])}"
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
