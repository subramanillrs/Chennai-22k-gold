# ============================================================
# MONITOR RATE
# ============================================================

MAX_ATTEMPTS = 400
CHECK_INTERVAL = 10


def monitor_rate():
    """
    Check LiveChennai every 10 seconds.

    Maximum:
        400 attempts
        10 seconds between attempts
        ~66 minutes 40 seconds maximum

    Stops immediately when either:
        - 22K rate changes, OR
        - LiveChennai's source update timestamp changes.
    """

    print()
    print("=" * 60)
    print("MONITORING CHENNAI 22K GOLD RATE")
    print("=" * 60)
    print(f"Maximum attempts : {MAX_ATTEMPTS}")
    print(f"Interval         : {CHECK_INTERVAL} seconds")
    print(f"Maximum runtime  : ~66 minutes 40 seconds")
    print("=" * 60)

    previous_rate = None
    previous_source_time = None

    # Read the rate currently stored in live.json.
    existing = load_json(LIVE_FILE, {})

    if isinstance(existing, dict):
        stored_rate = existing.get("rate_22k")
        stored_source_time = existing.get("source_last_update")

        if stored_rate is not None:
            try:
                previous_rate = int(stored_rate)
            except (TypeError, ValueError):
                previous_rate = None

        previous_source_time = stored_source_time

    for attempt in range(1, MAX_ATTEMPTS + 1):

        try:
            html = get_html(CURRENT_URL)

            current_rate, source_time = parse_current_rate(html)

            print(
                f"[{attempt:03d}/{MAX_ATTEMPTS}] "
                f"{datetime.now(IST).strftime('%H:%M:%S')} "
                f"Source={source_time} "
                f"Rate=₹{current_rate:,}"
            )

            rate_changed = (
                previous_rate is not None
                and current_rate != previous_rate
            )

            source_changed = (
                previous_source_time is not None
                and source_time is not None
                and source_time != previous_source_time
            )

            if rate_changed or source_changed:

                print()
                print("=" * 60)
                print("NEW GOLD RATE DETECTED")
                print("=" * 60)

                if rate_changed:
                    print(
                        f"Rate changed: "
                        f"₹{previous_rate:,} → "
                        f"₹{current_rate:,}"
                    )

                if source_changed:
                    print(
                        f"Source time changed: "
                        f"{previous_source_time} → "
                        f"{source_time}"
                    )

                print("=" * 60)

                return current_rate, source_time

        except Exception as exc:

            print(
                f"[{attempt:03d}/{MAX_ATTEMPTS}] "
                f"Fetch error: {exc}"
            )

        # NEVER sleep after the final attempt.
        if attempt < MAX_ATTEMPTS:
            time.sleep(CHECK_INTERVAL)

    print()
    print("=" * 60)
    print("400 ATTEMPTS COMPLETED")
    print("NO NEW RATE DETECTED")
    print("=" * 60)

    # Fetch one final value so the normal update process
    # can still save the latest available source data.
    html = get_html(CURRENT_URL)
    return parse_current_rate(html)
