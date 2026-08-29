name: Update Chennai 22K Gold Rate

on:
  schedule:
    # Bootstrap/learn morning window: every 30 minutes.
    - cron: "0 4 * * *"
    - cron: "30 4 * * *"
    - cron: "0 5 * * *"
    - cron: "30 5 * * *"

    # Bootstrap/learn evening window: every 30 minutes.
    - cron: "0 10 * * *"
    - cron: "30 10 * * *"
    - cron: "0 11 * * *"
    - cron: "30 11 * * *"

  workflow_dispatch:

permissions:
  contents: write

concurrency:
  group: gold-rate-update
  cancel-in-progress: false

jobs:
  update:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install requests beautifulsoup4

      - name: Monitor and update Chennai 22K rate
        run: python update_gold.py

      - name: Save updated data
        run: |
          git config user.name "Chennai 22K Gold Bot"
          git config user.email "actions@users.noreply.github.com"

          git add data/live.json data/history.json data/change_log.json

          if git diff --cached --quiet; then
            echo "No data changes to commit."
          else
            git commit -m "Update Chennai 22K gold rate"
            git push
          fi
