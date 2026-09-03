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
# PATHS & CONSTANTS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

LIVE_FILE = DATA_DIR / "live.json"
HISTORY_FILE = DATA_DIR / "history.json"
WINDOW_FILE = DATA_DIR / "monitoring_windows.json"
ALERT_FILE = DATA_DIR / "alert_state.json"
SUMMARY_FILE = DATA_DIR / "summary.json"
HEALTH_FILE = DATA_DIR / "health_status.json"

SEED_FILE = BASE_DIR / "historical_monitor_seed.json"
if not SEED_FILE.exists():
    SEED_FILE = DATA_DIR / "historical_monitor_seed.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)
IST = ZoneInfo("Asia/Kolkata")

LIVECHENNAI_URL = "https://www.livechennai.com/gold_silverrate.asp"
GOODRETURNS_URL = "https://www.goodreturns.in/gold-rates/chennai.html"

POLL_SECONDS = 10
REQUEST_TIMEOUT = 20

AM_START = (9, 30)
AM_END = (12, 30)
PM_START = (16, 30)
PM_END = (19, 30)

FALLBACK_AM_TIME = AM_START
FALLBACK_PM_TIME = PM_START

HISTORY_LOOKBACK_DAYS = 30
PRE_WINDOW_MINUTES = 15
WINDOW_DURATION_MINUTES = 85
MIN_SAMPLES_FOR_PREDICTION = 3

# Scheduled GitHub Actions runs may need to wait for the
# predicted monitoring window. 300 minutes gives enough room
# for the PM window without requiring another overlapping cron.
MAX_SCHEDULE_WAIT_MINUTES = 300

AM_PREDICTION_MIN = (7, 0)
AM_PREDICTION_MAX = (13, 0)
PM_PREDICTION_MIN = (14, 0)
PM_PREDICTION_MAX = (21, 0)

MAX_DAILY_CHANGE_PCT = 8
SOURCE_AGREEMENT_TOLERANCE = 50

ALERT_STALE_HOURS = 20
ALERT_DISAGREE_HOURS = 3
ALERT_COOLDOWN_HOURS = 12

# Optional: set the WEBHOOK_URL environment variable (e.g. a Slack
# incoming webhook or generic POST endpoint) to receive alerts when
# the feed goes stale or sources disagree for too long. Left unset,
# alert_state.json is still tracked/updated, but no network call is
# made and health_status.json reports webhook_configured: false.
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", os.environ.get("ALERT_WEBHOOK_URL", "")).strip()

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
# UTILITIES
# ============================================================

def now_ist():
    return datetime.now(IST)


def valid_gold_rate(value):
    if value is None:
        return False

    try:
        val = int(value)
        return 5000 <= val <= 50000
    except (ValueError, TypeError):
        return False


def clean_number(text):
    if text is None:
        return None

    cleaned = (
        str(text)
        .replace(",", "")
        .replace("₹", "")
        .replace("Rs.", "")
        .replace("Rs", "")
        .replace("INR", "")
    )

    cleaned = re.sub(
        r"\b(?:24|22|18|20)\s*(?:k|carat|karat)\b",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )

    cleaned = re.sub(
        r"\b(?:1|4|8|10|100)\s*(?:g|gm|gram|grams)\b",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )

    matches = re.findall(r"\d+(?:\.\d+)?", cleaned)

    for m in matches:
        try:
            val = int(float(m))
            if valid_gold_rate(val):
                return val
        except (ValueError, TypeError):
            continue

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
            indent=2,
        )

    temp.replace(path)


def _hours_since(iso_string, now):
    if not iso_string:
        return None

    try:
        then = datetime.fromisoformat(iso_string)

        if then.tzinfo is None:
            then = then.replace(tzinfo=IST)
        else:
            then = then.astimezone(IST)

        return (now - then).total_seconds() / 3600

    except Exception:
        return None


# Broad AM/PM day-half split used to label *any* timestamp (live
# rate updates, legacy history records, etc.) as morning or evening.
# This is intentionally wider than the learned/predicted monitoring
# windows (AM_PREDICTION_MIN/MAX, PM_PREDICTION_MIN/MAX) which decide
# *when to poll*. Keep this as the single source of truth for the
# AM/PM cut -- predict_session_times() reuses it instead of
# re-encoding the same hours separately, so the two can't drift.
DAY_HALF_SPLIT_HOUR = 14
DAY_HALF_AM_START_HOUR = 6


def session_for_time(dt):
    hour = dt.hour

    if DAY_HALF_AM_START_HOUR <= hour < DAY_HALF_SPLIT_HOUR:
        return "AM"

    if DAY_HALF_SPLIT_HOUR <= hour <= 23:
        return "PM"

    return None


def session_for_minutes(mins):
    """Same AM/PM split as session_for_time, but from a minutes-since-
    midnight integer (used by the history-based prediction learner,
    which works in minutes rather than datetimes)."""
    if mins is None:
        return ""

    am_start = DAY_HALF_AM_START_HOUR * 60
    split = DAY_HALF_SPLIT_HOUR * 60

    if am_start <= mins < split:
        return "AM"

    if split <= mins <= 23 * 60 + 59:
        return "PM"

    return ""


# ============================================================
# HISTORY HELPERS
# ============================================================

def extract_history_records(data):
    if isinstance(data, list):
        return [
            item
            for item in data
            if isinstance(item, dict)
        ]

    if isinstance(data, dict):
        for key in ("records", "history", "data"):
            value = data.get(key)

            if isinstance(value, list):
                return [
                    item
                    for item in value
                    if isinstance(item, dict)
                ]

    return []


def get_previous_rate():
    records = extract_history_records(load_json(HISTORY_FILE, []))

    def record_key(record):
        timestamp = record.get("timestamp")
        if timestamp:
            try:
                return datetime.fromisoformat(str(timestamp)).timestamp()
            except Exception:
                pass
        date = str(record.get("date") or "")
        time_value = str(record.get("time") or "23:59:59")
        try:
            return datetime.fromisoformat(f"{date}T{time_value}+05:30").timestamp()
        except Exception:
            return 0

    valid_records = [r for r in records if valid_gold_rate(r.get("rate_22k"))]
    if valid_records:
        latest = max(valid_records, key=record_key)
        return int(latest["rate_22k"])

    live = load_json(LIVE_FILE, {})
    if isinstance(live, dict) and valid_gold_rate(live.get("rate_22k")):
        return int(live["rate_22k"])
    return None


# ============================================================
# SCRAPERS
# ============================================================

def extract_livechennai_22k(soup):
    for table in soup.find_all("table"):
        rows = table.find_all("tr")

        if len(rows) < 3:
            continue

        # LiveChennai's rate table has a two-row header using
        # colspan: row 0 = "Date" | "Pure Gold (24 k)" (colspan=2)
        # | "Standard Gold (22 K)" (colspan=2); row 1 = "" | "1 Gm"
        # | "8 Gm" | "1 Gm" | "8 Gm". Expand colspans on row 0 so
        # its column positions line up with the real data columns,
        # then use row 1 to pick the "22K, 1 Gm" column precisely.
        def expanded_header(row):
            cells = row.find_all(["th", "td"])
            out = []
            for c in cells:
                span = int(c.get("colspan", 1) or 1)
                text = c.get_text(" ", strip=True).lower()
                out.extend([text] * span)
            return out

        top = expanded_header(rows[0])
        sub = expanded_header(rows[1])

        col_22k_idx = -1
        for idx in range(min(len(top), len(sub))):
            if (
                ("22" in top[idx] or "standard" in top[idx])
                and "24" not in top[idx]
                and ("1" in sub[idx] and "8" not in sub[idx])
            ):
                col_22k_idx = idx
                break

        if col_22k_idx != -1:
            for r in rows[2:]:
                cells = r.find_all(["td", "th"])

                if col_22k_idx < len(cells):
                    val = clean_number(
                        cells[col_22k_idx].get_text(
                            " ",
                            strip=True,
                        )
                    )

                    if valid_gold_rate(val):
                        return val

        for row in rows:
            row_text = row.get_text(
                " ",
                strip=True,
            ).lower()

            if (
                (
                    "22 k" in row_text
                    or "22k" in row_text
                    or "22 carat" in row_text
                )
                and "24" not in row_text
            ):
                for cell in row.find_all(
                    ["td", "th"]
                ):
                    val = clean_number(
                        cell.get_text(
                            " ",
                            strip=True,
                        )
                    )

                    if valid_gold_rate(val):
                        return val

    page_text = re.sub(
        r"\s+",
        " ",
        soup.get_text(
            " ",
            strip=True,
        ),
    )

    patterns = [
        r"Today(?:'s)?\s+22\s*K\s*(?:Rate|Gold)?"
        r"[^0-9\r\n]{0,30}"
        r"(?:₹|Rs\.?|INR)?\s*([\d,]+)",

        r"22\s*K(?:arat|orat)?\s*"
        r"(?:\(1\s*g\)|1\s*gm?|1\s*gram|Gold|Rate)?"
        r"[^0-9\r\n]{0,30}"
        r"(?:₹|Rs\.?|INR)?\s*([\d,]+)",

        r"22\s*Carat\s+gold\s+rate"
        r"[^0-9\r\n]{0,30}"
        r"(?:₹|Rs\.?|INR)?\s*([\d,]+)",

        r"1\s*Gram\s*(?:\(22\s*K\)|22\s*K)"
        r"[^0-9\r\n]{0,30}"
        r"(?:₹|Rs\.?|INR)?\s*([\d,]+)",
    ]

    for pattern in patterns:
        for match in re.finditer(
            pattern,
            page_text,
            flags=re.IGNORECASE,
        ):
            val = clean_number(match.group(1))

            if valid_gold_rate(val):
                return val

    return None


def fetch_livechennai():
    try:
        res = SESSION.get(
            LIVECHENNAI_URL,
            timeout=REQUEST_TIMEOUT,
        )

        res.raise_for_status()

        soup = BeautifulSoup(
            res.text,
            "html.parser",
        )

        rate = extract_livechennai_22k(soup)

        if rate:
            return {
                "source": "LiveChennai",
                "rate_22k": int(rate),
                "url": LIVECHENNAI_URL,
                "fetched_at": now_ist().isoformat(),
            }

    except Exception as exc:
        print(
            f"LiveChennai scrape error: {exc}"
        )

    return None


def extract_goodreturns_22k(soup):
    for table in soup.find_all("table"):
        rows = table.find_all("tr")

        if len(rows) < 2:
            continue

        # GoodReturns' "Today Gold Price Per Gram" table is
        # transposed from LiveChennai's: rows are gram weights
        # (1, 8, 10, 100...) and columns are karats (24K, 22K, 18K).
        # Find the 22K column from the header row, then the "1 gram"
        # data row, and read that cell.
        header_cells = rows[0].find_all(["th", "td"])
        header_text = [
            c.get_text(" ", strip=True).lower()
            for c in header_cells
        ]

        col_22k_idx = -1
        for idx, h in enumerate(header_text):
            if "22" in h and "24" not in h and "18" not in h:
                col_22k_idx = idx
                break

        if col_22k_idx != -1:
            for r in rows[1:]:
                cells = r.find_all(["td", "th"])
                if not cells:
                    continue

                row_label = cells[0].get_text(" ", strip=True).lower()
                is_one_gram_row = row_label in ("1", "1g", "1 g", "1gm", "1 gm", "1 gram")

                if is_one_gram_row and col_22k_idx < len(cells):
                    val = clean_number(
                        cells[col_22k_idx].get_text(" ", strip=True)
                    )
                    if valid_gold_rate(val):
                        return val

        table_context = ""

        prev = table.find_previous(
            [
                "h1",
                "h2",
                "h3",
                "h4",
                "caption",
                "div",
            ]
        )

        if prev:
            table_context = prev.get_text(
                " ",
                strip=True,
            ).lower()

        table_text = table.get_text(
            " ",
            strip=True,
        ).lower()

        is_22k_table = (
            ("22" in table_context or "22" in table_text)
            and "24" not in table_context
        )

        for row in table.find_all("tr"):
            row_text = row.get_text(
                " ",
                strip=True,
            ).lower()

            condition_1 = (
                is_22k_table
                and (
                    "1 gram" in row_text
                    or "1g" in row_text
                    or "1 gm" in row_text
                )
            )

            condition_2 = (
                (
                    "22 k" in row_text
                    or "22k" in row_text
                    or "22 carat" in row_text
                )
                and "8" not in row_text
            )

            if condition_1 or condition_2:
                for cell in row.find_all(
                    ["td", "th"]
                ):
                    val = clean_number(
                        cell.get_text(
                            " ",
                            strip=True,
                        )
                    )

                    if valid_gold_rate(val):
                        return val

    page_text = re.sub(
        r"\s+",
        " ",
        soup.get_text(
            " ",
            strip=True,
        ),
    )

    patterns = [
        r"22\s*K\s+Gold\s*/\s*g"
        r"[^0-9\r\n]{0,30}"
        r"(?:₹|Rs\.?|INR)?\s*([\d,]+)",

        r"22\s*(?:K|Carat|Karat)\s*Gold"
        r"[^0-9\r\n]{0,50}"
        r"(?:₹|Rs\.?|INR)?\s*([\d,]+)",

        r"1\s*Gram"
        r"[^0-9\r\n]{0,30}"
        r"(?:₹|Rs\.?|INR)?\s*([\d,]+)",
    ]

    for pattern in patterns:
        for match in re.finditer(
            pattern,
            page_text,
            flags=re.IGNORECASE,
        ):
            val = clean_number(match.group(1))

            if valid_gold_rate(val):
                return val

    return None


def fetch_goodreturns():
    try:
        res = SESSION.get(
            GOODRETURNS_URL,
            timeout=REQUEST_TIMEOUT,
        )

        res.raise_for_status()

        soup = BeautifulSoup(
            res.text,
            "html.parser",
        )

        rate = extract_goodreturns_22k(soup)

        if rate:
            return {
                "source": "GoodReturns",
                "rate_22k": int(rate),
                "url": GOODRETURNS_URL,
                "fetched_at": now_ist().isoformat(),
            }

    except Exception as exc:
        print(
            f"GoodReturns scrape error: {exc}"
        )

    return None


def fetch_all_sources():
    with ThreadPoolExecutor(
        max_workers=2
    ) as executor:

        f_live = executor.submit(
            fetch_livechennai
        )

        f_good = executor.submit(
            fetch_goodreturns
        )

        return (
            f_live.result(),
            f_good.result(),
        )


# ============================================================
# CONSENSUS & VALIDATION
# ============================================================

def _rate_is_plausible(
    rate,
    previous_rate,
):
    if (
        not isinstance(
            previous_rate,
            (int, float),
        )
        or previous_rate <= 0
    ):
        return True

    return (
        abs(rate - previous_rate)
        / previous_rate
        * 100
    ) <= MAX_DAILY_CHANGE_PCT


def select_rate(
    live,
    good,
    previous_rate=None,
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

    if (
        live_rate is not None
        and good_rate is not None
    ):
        diff = abs(
            live_rate - good_rate
        )

        if diff <= SOURCE_AGREEMENT_TOLERANCE:
            consensus_rate = round(
                (live_rate + good_rate)
                / 2
            )

            if (
                not _rate_is_plausible(
                    consensus_rate,
                    previous_rate,
                )
                and previous_rate is not None
            ):
                return {
                    "rate_22k": int(previous_rate),
                    "source": "Previous verified rate",
                    "agreement": False,
                    "livechennai": live,
                    "goodreturns": good,
                    "warning": (
                        "Source consensus rejected "
                        "because change exceeded "
                        "plausibility threshold."
                    ),
                }

            return {
                "rate_22k": int(consensus_rate),
                "source": "LiveChennai + GoodReturns",
                "agreement": True,
                "livechennai": live,
                "goodreturns": good,
            }

        # Both sources are available but disagree.
        # Do not call this healthy.
        if previous_rate is not None:
            return {
                "rate_22k": int(previous_rate),
                "source": "Previous verified rate",
                "agreement": False,
                "livechennai": live,
                "goodreturns": good,
                "warning": (
                    f"Sources disagree by {diff}."
                ),
            }

        # No previous verified rate exists.
        # Use the midpoint, but explicitly mark
        # the result as unverified.
        midpoint = round(
            (live_rate + good_rate) / 2
        )

        return {
            "rate_22k": int(midpoint),
            "source": "LiveChennai + GoodReturns",
            "agreement": False,
            "livechennai": live,
            "goodreturns": good,
            "warning": (
                f"Sources disagree by {diff}."
            ),
        }

    # --------------------------------------------------------
    # SINGLE SOURCE
    # --------------------------------------------------------

    if live_rate is not None:
        if (
            previous_rate is None
            or _rate_is_plausible(
                live_rate,
                previous_rate,
            )
        ):
            return {
                "rate_22k": int(live_rate),
                "source": "LiveChennai",
                "agreement": None,
                "livechennai": live,
                "goodreturns": good,
                "warning": (
                    "Only LiveChennai is reporting."
                ),
            }

    if good_rate is not None:
        if (
            previous_rate is None
            or _rate_is_plausible(
                good_rate,
                previous_rate,
            )
        ):
            return {
                "rate_22k": int(good_rate),
                "source": "GoodReturns",
                "agreement": None,
                "livechennai": live,
                "goodreturns": good,
                "warning": (
                    "Only GoodReturns is reporting."
                ),
            }

    return None


# ============================================================
# LIVE DATA
# ============================================================

def save_live(
    rate,
    selected,
    changed,
):
    now = now_ist()

    live_source = (
        selected.get("livechennai")
        or {}
    )

    good_source = (
        selected.get("goodreturns")
        or {}
    )

    data = load_json(
        LIVE_FILE,
        {},
    )

    if not isinstance(data, dict):
        data = {}

    previous_rate = data.get(
        "rate_22k"
    )

    # BUGFIX: "updated_at"/"last_checked_at" get refreshed to `now` on
    # *every* run, including runs where select_rate() fell back to the
    # "Previous verified rate" (sources disagreed, or the reading was
    # implausible) -- i.e. runs where nothing was actually confirmed.
    # health_status.json's age_hours was computed from "updated_at",
    # so a feed that's actually stuck (both sources broken, silently
    # repeating the last good rate every run) always looked perfectly
    # fresh and never tripped the stale alert. Track "verified_at"
    # separately: it only advances when this run's reading is
    # trustworthy (two sources agreeing, or a single source whose
    # value passed the plausibility check) -- not on a bare fallback
    # to the previous rate. run_health_check() uses this field.
    is_verified_reading = selected.get("source") != "Previous verified rate"

    data.update(
        {
            "date": now.strftime(
                "%Y-%m-%d"
            ),
            "time": now.strftime(
                "%H:%M:%S"
            ),
            "timestamp": now.isoformat(),
            "rate_22k": int(rate),
            "rate_24k": round(
                int(rate) * 24 / 22
            ),
            "rate_8g": int(rate) * 8,
            "weight_1g": int(rate),
            "weight_8g": int(rate) * 8,
            "session": session_for_time(now),
            "source": selected.get(
                "source",
                "Unknown",
            ),
            "agreement": selected.get(
                "agreement"
            ),
            "changed": bool(changed),
            "previous_rate_22k": (
                previous_rate
                if valid_gold_rate(
                    previous_rate
                )
                else data.get(
                    "previous_rate_22k"
                )
            ),
            "livechennai_rate": live_source.get(
                "rate_22k"
            ),
            "goodreturns_rate": good_source.get(
                "rate_22k"
            ),
            "livechennai_fetched_at": live_source.get(
                "fetched_at"
            ),
            "goodreturns_fetched_at": good_source.get(
                "fetched_at"
            ),
            "livechennai_url": live_source.get(
                "url"
            ),
            "goodreturns_url": good_source.get(
                "url"
            ),
            "updated_at": now.isoformat(),
            "last_checked_at": now.isoformat(),
            "last_checked": now.isoformat(),
            "verified_at": (
                now.isoformat()
                if is_verified_reading
                else data.get("verified_at")
            ),
            "change": (int(rate) - int(previous_rate)) if valid_gold_rate(previous_rate) else 0,
            "sources": {
                "livechennai": live_source or None,
                "goodreturns": good_source or None,
            },
            "source_rates": [
                int(v) for v in (live_source.get("rate_22k"), good_source.get("rate_22k"))
                if valid_gold_rate(v)
            ],
            "source_update_times": [
                v for v in (live_source.get("fetched_at"), good_source.get("fetched_at"))
                if v
            ],
            "sources_agree": selected.get("agreement"),
        }
    )

    save_json(
        LIVE_FILE,
        data,
    )


# ============================================================
# HISTORY
# ============================================================

def save_history(
    rate,
    selected,
    changed,
):
    existing = load_json(
        HISTORY_FILE,
        [],
    )

    records = extract_history_records(
        existing
    )

    current = now_ist()
    today = current.strftime(
        "%Y-%m-%d"
    )

    current_session = session_for_time(
        current
    )

    rate = int(rate)

    live_source = (
        selected.get("livechennai")
        or {}
    )

    good_source = (
        selected.get("goodreturns")
        or {}
    )

    source_urls = [
        source.get("url")
        for source in (
            live_source,
            good_source,
        )
        if source.get("url")
    ]

    rec = {
        "date": today,
        "time": current.strftime(
            "%H:%M:%S"
        ),
        "timestamp": current.isoformat(),
        "session": current_session,
        "rate_22k": rate,

        # Legacy-compatible fields
        "rate_24k": round(
            rate * 24 / 22
        ),
        "weight_1g": rate,
        "weight_8g": rate * 8,

        # Current fields
        "rate_8g": rate * 8,
        "changed": bool(changed),
        "source": selected.get(
            "source",
            "Unknown",
        ),
        "source_url": (
            source_urls[0]
            if source_urls
            else None
        ),
        "type": "intraday",
        "agreement": selected.get(
            "agreement"
        ),
        "livechennai_rate": live_source.get(
            "rate_22k"
        ),
        "goodreturns_rate": good_source.get(
            "rate_22k"
        ),
    }

    should_append = False

    if not records:
        should_append = True

    else:
        last = (
            records[-1]
            if isinstance(
                records[-1],
                dict,
            )
            else {}
        )

        last_date = last.get(
            "date"
        )

        last_session = last.get(
            "session"
        )

        # Legacy records may not contain
        # an explicit session.
        if (
            not last_session
            and last.get("time")
        ):
            try:
                hour = int(
                    str(
                        last["time"]
                    ).split(":")[0]
                )

                last_session = (
                    "AM"
                    if 6 <= hour < 14
                    else "PM"
                )

            except Exception:
                last_session = None

        should_append = (
            last_date != today
            or last_session
            != current_session
            or last.get("rate_22k")
            != rate
        )

    if should_append:
        records.append(rec)
    else:
        # Refresh the current observation's timing fields, but never
        # let a less-verified reading (e.g. a single source, or
        # sources disagreeing) downgrade a record that was already
        # confirmed by both sources agreeing. The rate is identical
        # either way (that's why should_append is False) -- only the
        # verification metadata could regress.
        existing_rec = (
            records[-1]
            if isinstance(records[-1], dict)
            else {}
        )

        was_agreed = existing_rec.get("agreement") is True
        now_agreed = rec.get("agreement") is True

        if was_agreed and not now_agreed:
            # Keep the stronger verification info, just bump the
            # timestamp/time so the record reflects it was re-checked.
            existing_rec["time"] = rec["time"]
            existing_rec["timestamp"] = rec["timestamp"]
            records[-1] = existing_rec
        else:
            existing_rec.update(rec)
            records[-1] = existing_rec

    if isinstance(existing, dict):
        existing["records"] = records
        save_json(
            HISTORY_FILE,
            existing,
        )
    else:
        save_json(
            HISTORY_FILE,
            records,
        )


# ============================================================
# HEALTH CHECK
# ============================================================

def run_health_check():
    now = now_ist()

    live = load_json(
        LIVE_FILE,
        {},
    )

    if not isinstance(live, dict):
        live = {}

    live_rate = live.get(
        "livechennai_rate"
    )

    good_rate = live.get(
        "goodreturns_rate"
    )

    source_count = sum(
        1
        for value in (
            live_rate,
            good_rate,
        )
        if valid_gold_rate(value)
    )

    agreement = live.get(
        "agreement"
    )

    updated_at = live.get(
        "updated_at"
    )

    # BUGFIX: use "verified_at" (last genuinely-confirmed reading),
    # not "updated_at" (last time the script *ran*), so a feed stuck
    # on repeated "Previous verified rate" fallbacks is correctly
    # reported as aging/stale instead of looking fresh every run.
    # Older live.json files won't have "verified_at" yet -- fall back
    # to "updated_at" for those rather than treating them as infinitely
    # stale.
    verified_at = live.get(
        "verified_at"
    ) or updated_at

    age_hours = _hours_since(
        verified_at,
        now,
    )

    status = "offline"

    # No usable sources.
    if source_count == 0:
        status = "offline"

    # Data exists but is too old.
    elif (
        age_hours is not None
        and age_hours > ALERT_STALE_HOURS
    ):
        status = "stale"

    # Two sources agreeing = healthy.
    elif (
        source_count >= 2
        and agreement is True
    ):
        status = "ok"

    # Two sources disagreeing.
    elif (
        source_count >= 2
        and agreement is False
    ):
        status = "degraded"

    # Only one source.
    # This MUST NOT be reported as healthy.
    elif source_count == 1:
        status = "degraded"

    else:
        status = "degraded"

    health = {
        "status": status,
        "checked_at": now.isoformat(),
        "updated_at": updated_at,
        "verified_at": verified_at,
        "age_hours": (
            round(age_hours, 2)
            if age_hours is not None
            else None
        ),
        "source_count": source_count,
        "single_source": source_count == 1,
        "agreement": agreement,
        "livechennai_rate": (
            int(live_rate)
            if valid_gold_rate(live_rate)
            else None
        ),
        "goodreturns_rate": (
            int(good_rate)
            if valid_gold_rate(good_rate)
            else None
        ),
        "rate_22k": (
            live.get("rate_22k")
            if valid_gold_rate(
                live.get("rate_22k")
            )
            else None
        ),
    }

    health["webhook_configured"] = bool(WEBHOOK_URL)

    save_json(
        HEALTH_FILE,
        health,
    )

    return health


# ============================================================
# ALERTING
# ============================================================

def send_webhook_alert(message, health):
    """POST a short alert payload to WEBHOOK_URL, if configured.

    Failures here are logged and swallowed -- alerting must never
    take down the main fetch pipeline.
    """
    if not WEBHOOK_URL:
        return False

    payload = {
        "text": message,
        "status": health.get("status"),
        "age_hours": health.get("age_hours"),
        "source_count": health.get("source_count"),
        "agreement": health.get("agreement"),
        "rate_22k": health.get("rate_22k"),
        "checked_at": health.get("checked_at"),
    }

    try:
        resp = SESSION.post(
            WEBHOOK_URL,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return True

    except Exception as exc:
        print(f"Webhook alert failed: {exc}")
        return False


def run_alert_check(health):
    """Track staleness/disagreement over time and fire cooldown-gated
    webhook alerts. Always updates alert_state.json so the frontend
    (or a future dashboard) can show alert history even without a
    webhook configured.
    """
    now = now_ist()

    state = load_json(
        ALERT_FILE,
        {
            "disagree_since": None,
            "last_disagree_alert_at": None,
            "last_stale_alert_at": None,
        },
    )

    if not isinstance(state, dict):
        state = {
            "disagree_since": None,
            "last_disagree_alert_at": None,
            "last_stale_alert_at": None,
        }

    status = health.get("status")
    agreement = health.get("agreement")
    source_count = health.get("source_count", 0)

    # --------------------------------------------------------
    # Disagreement tracking: only "degraded due to disagreement"
    # (both sources up, values differ) counts -- a single-source
    # or offline state is a different failure mode and shouldn't
    # extend a disagreement streak.
    # --------------------------------------------------------
    is_disagreeing = (
        status == "degraded"
        and source_count >= 2
        and agreement is False
    )

    if is_disagreeing:
        if not state.get("disagree_since"):
            state["disagree_since"] = now.isoformat()
    else:
        state["disagree_since"] = None

    disagree_hours = _hours_since(
        state.get("disagree_since"),
        now,
    )

    cooldown_ok_disagree = True
    last_disagree_alert = state.get("last_disagree_alert_at")
    if last_disagree_alert:
        since_last = _hours_since(last_disagree_alert, now)
        cooldown_ok_disagree = (
            since_last is None
            or since_last >= ALERT_COOLDOWN_HOURS
        )

    if (
        is_disagreeing
        and disagree_hours is not None
        and disagree_hours >= ALERT_DISAGREE_HOURS
        and cooldown_ok_disagree
    ):
        sent = send_webhook_alert(
            f"Gold rate sources have disagreed for "
            f"{disagree_hours:.1f}h (LiveChennai vs GoodReturns).",
            health,
        )
        state["last_disagree_alert_at"] = now.isoformat()
        if not WEBHOOK_URL:
            print(
                "ALERT (no webhook configured): sources disagree "
                f"for {disagree_hours:.1f}h"
            )
        elif not sent:
            print("ALERT: disagree webhook attempt failed")

    # --------------------------------------------------------
    # Staleness alerting, independent of disagreement.
    # --------------------------------------------------------
    cooldown_ok_stale = True
    last_stale_alert = state.get("last_stale_alert_at")
    if last_stale_alert:
        since_last = _hours_since(last_stale_alert, now)
        cooldown_ok_stale = (
            since_last is None
            or since_last >= ALERT_COOLDOWN_HOURS
        )

    if status == "stale" and cooldown_ok_stale:
        age = health.get("age_hours")
        sent = send_webhook_alert(
            f"Gold rate feed is stale "
            f"({age if age is not None else '?'}h since last update).",
            health,
        )
        state["last_stale_alert_at"] = now.isoformat()
        if not WEBHOOK_URL:
            print(
                "ALERT (no webhook configured): feed stale "
                f"({age}h)"
            )
        elif not sent:
            print("ALERT: stale webhook attempt failed")

    save_json(ALERT_FILE, state)
    return state


# ============================================================
# SUMMARY
# ============================================================

def compute_and_save_summary():
    existing = load_json(
        HISTORY_FILE,
        [],
    )

    records = extract_history_records(
        existing
    )

    valid = [
        (
            r["date"],
            int(r["rate_22k"]),
        )
        for r in records
        if (
            isinstance(r, dict)
            and valid_gold_rate(
                r.get("rate_22k")
            )
            and r.get("date")
        )
    ]

    if not valid:
        return

    now = now_ist()

    current_month = now.strftime(
        "%Y-%m"
    )

    current_year = now.strftime(
        "%Y"
    )

    hi = max(
        valid,
        key=lambda x: x[1],
    )

    lo = min(
        valid,
        key=lambda x: x[1],
    )

    month_vals = [
        v
        for d, v in valid
        if d.startswith(current_month)
    ]

    year_vals = [
        v
        for d, v in valid
        if d.startswith(current_year)
    ]

    daily = {}
    for d, v in valid:
        daily[d] = v
    recent_30 = [v for d, v in sorted(daily.items())[-30:]]

    def bucket(vals):
        if not vals:
            return {
                "average_22k": None,
                "high": None,
                "low": None,
            }

        return {
            "average_22k": round(
                sum(vals) / len(vals)
            ),
            "high": max(vals),
            "low": min(vals),
        }

    save_json(
        SUMMARY_FILE,
        {
            "generated_at": now.isoformat(),

            "all_time_high": {
                "rate_22k": hi[1],
                "date": hi[0],
            },

            "all_time_low": {
                "rate_22k": lo[1],
                "date": lo[0],
            },

            "current_month": {
                "month": current_month,
                **bucket(month_vals),
            },

            "current_year": {
                "year": current_year,
                **bucket(year_vals),
            },

            "last_30_records": bucket(
                recent_30
            ),

            "total_records": len(valid),
        },
    )


# ============================================================
# MONITORING WINDOW PREDICTION
# ============================================================

def _parse_time_to_minutes(time_str):
    try:
        parts = str(
            time_str
        ).split(":")

        return (
            int(parts[0]) * 60
            + int(parts[1])
        )

    except Exception:
        return None


def _median(values):
    if not values:
        return None

    s = sorted(values)
    n = len(s)
    mid = n // 2

    if n % 2 == 0:
        return (
            s[mid - 1]
            + s[mid]
        ) / 2

    return s[mid]


def _clamp_hm(
    hm,
    lo,
    hi,
):
    minutes = (
        hm[0] * 60
        + hm[1]
    )

    clamped = max(
        lo[0] * 60 + lo[1],
        min(
            hi[0] * 60 + hi[1],
            minutes,
        ),
    )

    return (
        clamped // 60,
        clamped % 60,
    )


def predict_session_times(
    now=None
):
    now = now or now_ist()

    cutoff = (
        now
        - timedelta(
            days=HISTORY_LOOKBACK_DAYS
        )
    ).date()

    records = extract_history_records(
        load_json(
            HISTORY_FILE,
            [],
        )
    )

    am_m = []
    pm_m = []

    for r in records:
        if not isinstance(r, dict):
            continue

        try:
            record_date = (
                datetime.fromisoformat(
                    str(
                        r.get("date")
                    )
                ).date()
            )
        except Exception:
            record_date = None

        if (
            record_date is not None
            and record_date < cutoff
        ):
            continue

        session = str(
            r.get("session")
            or ""
        ).upper()

        mins = _parse_time_to_minutes(
            r.get("time")
        )

        # Older records may not have a
        # "time" field, but can have timestamp.
        if (
            mins is None
            and r.get("timestamp")
        ):
            try:
                dt = datetime.fromisoformat(
                    str(
                        r["timestamp"]
                    )
                )

                mins = (
                    dt.hour * 60
                    + dt.minute
                )

                if not session:
                    session = session_for_time(
                        dt
                    )

            except Exception:
                pass

        if mins is None:
            continue

        # Historical records before the session
        # field was introduced are still useful.
        if session not in {
            "AM",
            "PM",
        }:
            session = session_for_minutes(mins)

        # BUGFIX: session_for_time()/session_for_minutes() intentionally
        # use a wide AM/PM day-half split (any hour 14-23 counts as
        # "PM") for *labeling* purposes -- but that's much wider than a
        # plausible fix-time window. A late-night run (health-check
        # re-save, delayed GitHub Actions retry, manual dispatch after
        # the real PM fix) was getting tagged session="PM" and its
        # clock time fed straight into the PM median below. That
        # dragged the *learned* PM window later and later each time it
        # happened (e.g. a 23:56 reading pulled the predicted PM fix
        # from ~16:30 to ~19:34), which in turn made it *more* likely
        # for the next run to again land late and reinforce the drift.
        # Only genuine fix-time observations should influence the
        # learned median, so drop anything outside the plausible
        # prediction bounds here -- clamping just the final median
        # (via _clamp_hm below) is not enough, since a bad sample can
        # still skew *which* value the median lands on.
        if session == "AM" and not (
            AM_PREDICTION_MIN[0] * 60 + AM_PREDICTION_MIN[1]
            <= mins
            <= AM_PREDICTION_MAX[0] * 60 + AM_PREDICTION_MAX[1]
        ):
            continue

        if session == "PM" and not (
            PM_PREDICTION_MIN[0] * 60 + PM_PREDICTION_MIN[1]
            <= mins
            <= PM_PREDICTION_MAX[0] * 60 + PM_PREDICTION_MAX[1]
        ):
            continue

        if session == "AM":
            am_m.append(mins)

        elif session == "PM":
            pm_m.append(mins)

    # --------------------------------------------------------
    # Seed data is only used when real historical samples
    # are insufficient.
    # --------------------------------------------------------

    seed = load_json(
        SEED_FILE,
        [],
    )

    if not isinstance(seed, list):
        seed = []

    if len(am_m) < MIN_SAMPLES_FOR_PREDICTION:
        for r in seed:
            if (
                isinstance(r, dict)
                and str(
                    r.get(
                        "session",
                        "",
                    )
                ).upper()
                == "AM"
            ):
                m = _parse_time_to_minutes(
                    r.get("time")
                )

                if m is not None:
                    am_m.append(m)

    if len(pm_m) < MIN_SAMPLES_FOR_PREDICTION:
        for r in seed:
            if (
                isinstance(r, dict)
                and str(
                    r.get(
                        "session",
                        "",
                    )
                ).upper()
                == "PM"
            ):
                m = _parse_time_to_minutes(
                    r.get("time")
                )

                if m is not None:
                    pm_m.append(m)

    res = {}

    if len(am_m) >= MIN_SAMPLES_FOR_PREDICTION:
        med = _median(am_m)

        res["AM"] = _clamp_hm(
            (
                int(med // 60),
                int(med % 60),
            ),
            AM_PREDICTION_MIN,
            AM_PREDICTION_MAX,
        )

    else:
        res["AM"] = FALLBACK_AM_TIME

    if len(pm_m) >= MIN_SAMPLES_FOR_PREDICTION:
        med = _median(pm_m)

        res["PM"] = _clamp_hm(
            (
                int(med // 60),
                int(med % 60),
            ),
            PM_PREDICTION_MIN,
            PM_PREDICTION_MAX,
        )

    else:
        res["PM"] = FALLBACK_PM_TIME

    print(
        "Predicted session times: "
        f"AM {res['AM'][0]:02d}:{res['AM'][1]:02d} "
        f"from {len(am_m)} samples; "
        f"PM {res['PM'][0]:02d}:{res['PM'][1]:02d} "
        f"from {len(pm_m)} samples"
    )

    return res


def _session_bounds(
    day,
    hm,
):
    dt = datetime(
        day.year,
        day.month,
        day.day,
        hm[0],
        hm[1],
        0,
        tzinfo=IST,
    )

    start = (
        dt
        - timedelta(
            minutes=PRE_WINDOW_MINUTES
        )
    )

    end = (
        start
        + timedelta(
            minutes=WINDOW_DURATION_MINUTES
        )
    )

    return start, end


def current_window(
    now=None
):
    now = now or now_ist()

    day = now.date()

    p = predict_session_times(
        now
    )

    am_s, am_e = _session_bounds(
        day,
        p["AM"],
    )

    pm_s, pm_e = _session_bounds(
        day,
        p["PM"],
    )

    if am_s <= now < am_e:
        return {
            "name": "AM",
            "start": am_s,
            "end": am_e,
        }

    if pm_s <= now < pm_e:
        return {
            "name": "PM",
            "start": pm_s,
            "end": pm_e,
        }

    return None


def next_window(
    now=None
):
    now = now or now_ist()

    day = now.date()

    p = predict_session_times(
        now
    )

    am_s, am_e = _session_bounds(
        day,
        p["AM"],
    )

    pm_s, pm_e = _session_bounds(
        day,
        p["PM"],
    )

    if now < am_s:
        return {
            "name": "AM",
            "start": am_s,
            "end": am_e,
        }

    if now < pm_s:
        return {
            "name": "PM",
            "start": pm_s,
            "end": pm_e,
        }

    tomorrow = (
        day
        + timedelta(days=1)
    )

    p_tom = predict_session_times(
        datetime(
            tomorrow.year,
            tomorrow.month,
            tomorrow.day,
            0,
            0,
            tzinfo=IST,
        )
    )

    am_s_tom, am_e_tom = _session_bounds(
        tomorrow,
        p_tom["AM"],
    )

    return {
        "name": "AM",
        "start": am_s_tom,
        "end": am_e_tom,
    }


def save_window_info(
    window
):
    p = predict_session_times(
        now_ist()
    )

    save_json(
        WINDOW_FILE,
        {
            "timezone": "Asia/Kolkata",

            "updated_at": (
                now_ist().isoformat()
            ),

            "windows": {
                "AM": {
                    "predicted_fix_time": (
                        f"{p['AM'][0]:02d}:"
                        f"{p['AM'][1]:02d}"
                    ),
                    "polling_starts": (
                        f"{PRE_WINDOW_MINUTES} "
                        "min before"
                    ),
                    "duration_minutes": (
                        WINDOW_DURATION_MINUTES
                    ),
                },

                "PM": {
                    "predicted_fix_time": (
                        f"{p['PM'][0]:02d}:"
                        f"{p['PM'][1]:02d}"
                    ),
                    "polling_starts": (
                        f"{PRE_WINDOW_MINUTES} "
                        "min before"
                    ),
                    "duration_minutes": (
                        WINDOW_DURATION_MINUTES
                    ),
                },
            },

            "active_window": (
                window["name"]
                if window
                else None
            ),

            "poll_seconds": POLL_SECONDS,
        },
    )


# ============================================================
# MAIN PIPELINE
# ============================================================

def normal_fetch():
    prev_rate = get_previous_rate()

    live, good = fetch_all_sources()

    selected = select_rate(
        live,
        good,
        prev_rate,
    )

    if not selected:
        return False

    rate = selected["rate_22k"]

    changed = (
        prev_rate is not None
        and rate != prev_rate
    )

    save_live(
        rate,
        selected,
        changed,
    )

    save_history(
        rate,
        selected,
        changed,
    )

    return True


def monitor_window(
    window
):
    prev_rate = get_previous_rate()

    last_selected = None

    while True:
        now = now_ist()

        if now >= window["end"]:
            if last_selected:
                rate = last_selected[
                    "rate_22k"
                ]

                save_live(
                    rate,
                    last_selected,
                    False,
                )

                save_history(
                    rate,
                    last_selected,
                    False,
                )

            save_window_info(None)

            return False

        live, good = fetch_all_sources()

        selected = select_rate(
            live,
            good,
            prev_rate,
        )

        if selected:
            last_selected = selected

            rate = selected[
                "rate_22k"
            ]

            if (
                prev_rate is not None
                and rate != prev_rate
            ):
                save_live(
                    rate,
                    selected,
                    True,
                )

                save_history(
                    rate,
                    selected,
                    True,
                )

                save_window_info(
                    None
                )

                return True

            save_live(
                rate,
                selected,
                False,
            )

        remaining = (
            window["end"]
            - now_ist()
        ).total_seconds()

        if remaining <= 0:
            if last_selected:
                rate = last_selected[
                    "rate_22k"
                ]

                save_live(
                    rate,
                    last_selected,
                    False,
                )

                save_history(
                    rate,
                    last_selected,
                    False,
                )

            save_window_info(None)

            return False

        time.sleep(
            min(
                POLL_SECONDS,
                max(
                    1,
                    int(remaining),
                ),
            )
        )


def main():
    now = now_ist()

    is_gha = (
        os.environ.get(
            "GITHUB_ACTIONS",
            "",
        ).lower()
        == "true"
    )

    gha_event = os.environ.get(
        "GITHUB_EVENT_NAME",
        "",
    )

    force = (
        os.environ.get(
            "FORCE_FETCH",
            "",
        ).lower()
        == "true"
    )

    # --------------------------------------------------------
    # Manual/forced fetch
    # --------------------------------------------------------

    if force:
        save_window_info(None)

        if not normal_fetch():
            sys.exit(1)

        return

    # --------------------------------------------------------
    # If currently inside a monitoring window,
    # monitor immediately.
    # --------------------------------------------------------

    active = current_window(
        now
    )

    if active:
        save_window_info(
            active
        )

        monitor_window(
            active
        )

        return

    # --------------------------------------------------------
    # Scheduled GitHub Actions execution.
    #
    # The workflow starts before the predicted session.
    # Wait until the monitoring window opens, provided the
    # wait is within MAX_SCHEDULE_WAIT_MINUTES.
    # --------------------------------------------------------

    if (
        is_gha
        and gha_event == "schedule"
    ):
        upcoming = next_window(
            now
        )

        wait_seconds = (
            upcoming["start"]
            - now
        ).total_seconds()

        if (
            wait_seconds
            <= MAX_SCHEDULE_WAIT_MINUTES * 60
        ):
            time.sleep(
                max(
                    0,
                    int(wait_seconds),
                )
            )

            active = current_window(
                now_ist()
            )

            if active:
                save_window_info(
                    active
                )

                monitor_window(
                    active
                )

                return

    # --------------------------------------------------------
    # Outside monitoring window.
    # Perform normal fetch.
    # --------------------------------------------------------

    save_window_info(None)

    if not normal_fetch():
        sys.exit(1)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    try:
        main()

    except KeyboardInterrupt:
        sys.exit(1)

    except Exception as exc:
        print(
            f"FATAL: {exc}"
        )
        sys.exit(1)

    finally:
        try:
            health = run_health_check()

        except Exception as exc:
            print(
                f"Health check failed: {exc}"
            )
            health = None

        try:
            if health:
                run_alert_check(health)

        except Exception as exc:
            print(
                f"Alert check failed: {exc}"
            )

        try:
            compute_and_save_summary()

        except Exception as exc:
            print(
                f"Summary computation failed: {exc}"
            )
