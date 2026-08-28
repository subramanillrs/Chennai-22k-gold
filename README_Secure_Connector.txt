# Chennai Gold Rate Tracker — Secure Connector

## What this package does
The HTML app stores historical observations locally, validates incoming records, and calls a
backend endpoint for updates. The backend example is a Cloudflare Worker that keeps the
Metals-API key in a server-side secret.

Metals-API currently documents:
- `CHEN-22k` — Chennai Gold 22K
- `CHEN-24k` — Chennai Gold 24K
- historical coverage from 2023-12-14
- latest endpoint
- daily time-series endpoint

## Setup
1. Create a Metals-API account and obtain an API key.
2. Deploy `worker.js` to Cloudflare Workers (or adapt it to another server).
3. Add the Worker secret:
   `METALS_API_KEY=YOUR_REAL_KEY`
4. Put your deployed URL into the app's "Your secure backend endpoint" field.
5. Press **Fetch & validate** for current rates.
6. Press **Sync history** for the historical feed.

## Important
Do NOT put the Metals-API key into the HTML file or browser JavaScript.
The backend is the security boundary.

The app retains cached data if the backend fails. It also keeps source/timestamp
metadata and does not silently overwrite conflicting observations.

## API response expected by the HTML
The backend can return:
{
  "success": true,
  "observations": [
    {
      "date": "2026-08-28",
      "time": "09:39:48",
      "city": "Chennai",
      "purity": "22K",
      "rate": 14650,
      "source": "Metals-API",
      "granularity": "daily"
    }
  ]
}

For production, restrict CORS to your app's origin instead of `*`.
