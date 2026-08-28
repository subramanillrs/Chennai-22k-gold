# Chennai 22K Gold — rebuilt data layer

This version deliberately separates **rate date**, **session**, **source**, and **fetch time** so yesterday's cached value cannot silently become today's rate.

## Upload
Upload all files/folders in this ZIP to the root of the GitHub repository. Keep the existing `icon.svg`.

## Important
The included snapshot is a verified starting point for the rebuild. The GitHub Action is designed to append new source snapshots; it should not overwrite historical records.

## Historical backfill
The current public pages expose different windows and sometimes disagree. A 3-year daily history should therefore be backfilled from a consistent source before it is labelled as verified. The UI is ready for that data in `data/history.json`.
