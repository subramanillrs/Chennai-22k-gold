# Chennai 22K Gold PWA

A mobile-first Progressive Web App for tracking 22K gold metal value in INR.

## Live data
Uses the Chennai 22K retail-market reference from Golden Chennai. The GitHub Actions updater fetches the Chennai page server-side and commits the latest 22K/g value into `data.json`.

The app tracks the Chennai 22K retail-market reference rate. It excludes making charges, GST and other jewellery-specific charges. Source: Golden Chennai.

## Run locally
Because service workers require a secure origin, serve this folder from localhost:

```bash
python -m http.server 8000
```

Open:
http://localhost:8000

For phone installation, deploy the folder to an HTTPS host (GitHub Pages, Netlify, Cloudflare Pages, etc.), open it in Chrome, then choose Add to Home screen / Install app.

## Important
The browser calls the public endpoint directly. The API documentation says the karat endpoint is free and requires no key. Anonymous limits still apply. For a production/commercial deployment, use a server-side cache/proxy and follow the provider's terms.

## Files
- index.html — app UI and logic
- manifest.webmanifest — PWA manifest
- sw.js — offline shell
- icon.svg — app icon


## Live update architecture
GitHub Pages is static and browsers cannot reliably call this API because the provider intentionally does not expose it as a browser CORS surface. The included GitHub Actions workflow fetches the public `/v1/carat?currency=INR` endpoint every 30 minutes and commits the 22K value into `data.json`. The PWA reads that same-origin JSON file, so it works from GitHub Pages.


## Troubleshooting v3
The PWA uses cache-busting requests and a Raw GitHub fallback for `data.json`. The service worker never caches `data.json` and uses network-first behavior for the HTML shell. This is intended to prevent stale PWA content on Android Chrome.

## Data source
The updater uses the Golden Chennai Chennai 22K rate page as the reference source. Rates are indicative retail-market rates and should not be treated as a final jeweller invoice.
