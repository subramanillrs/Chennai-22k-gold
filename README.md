# Chennai 22K Gold PWA

A mobile-first Progressive Web App for tracking 22K gold metal value in INR.

## Live data
Uses the public goldprice.dev endpoint:
https://api.goldprice.dev/v1/carat?currency=INR

The endpoint returns a 22K purity-adjusted metal value. It is NOT a Chennai jewellery retail quote and excludes making charges, GST and dealer premiums.

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
