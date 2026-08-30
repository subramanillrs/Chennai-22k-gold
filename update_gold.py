def main():

    print("")
    print("=" * 70)
    print("CHENNAI 22K GOLD RATE")
    print("FULL-WINDOW ADAPTIVE MONITOR")
    print("=" * 70)

    now = now_ist()

    print(
        "IST:",
        now.strftime("%d-%m-%Y %H:%M:%S")
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
        ).lower() == "true"
    )

    github_event = os.environ.get(
        "GITHUB_EVENT_NAME",
        ""
    )

    force_fetch = (
        os.environ.get(
            "FORCE_FETCH",
            ""
        ).lower() == "true"
    )

    print(
        f"GITHUB_ACTIONS: {github_actions}"
    )

    print(
        f"GITHUB_EVENT_NAME: "
        f"{github_event or 'local'}"
    )

    print(
        f"FORCE_FETCH: {force_fetch}"
    )

    # --------------------------------------------------------
    # FORCE FETCH
    #
    # Used by the app Fetch / Refresh button.
    #
    # This MUST bypass the monitoring window.
    # --------------------------------------------------------

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

        if success:

            print("")
            print("=" * 70)
            print("FORCED FETCH COMPLETE")
            print("=" * 70)

            return

        print("")
        print("=" * 70)
        print("FORCED FETCH FAILED")
        print("=" * 70)

        sys.exit(1)

    # --------------------------------------------------------
    # CHECK CURRENT MONITORING WINDOW
    # --------------------------------------------------------

    window = current_window(now)

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
    # If GitHub starts slightly before the configured window,
    # wait until the window begins.
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
    # MANUAL GITHUB RUN WITHOUT FORCE_FETCH
    # / LOCAL RUN OUTSIDE WINDOW
    #
    # Do one fetch and exit.
    # --------------------------------------------------------

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
