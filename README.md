## Fix for GitHub Pages

The previous version was trying to call GoldPrice.dev directly from browser JavaScript. GoldPrice.dev explicitly says its API is not a browser CORS surface, so the browser can show Loading forever.

This version fixes that architecture:
PHONE/PWA -> same-origin data/live.json -> GitHub Pages
GitHub Actions -> free GoldPrice.dev API -> updates data/live.json twice daily

### Install
Copy the contents of this folder into the GitHub Pages repository.

Enable:
Settings -> Actions -> General -> Workflow permissions -> Read and write permissions.

Then Actions -> Update 22K Gold Rate -> Run workflow once.

The scheduled workflow runs at 11:00 AM and 5:00 PM IST (05:30 and 11:30 UTC). Opening the PWA always fetches the latest same-origin `data/live.json`, so it no longer depends on browser CORS.

The free GoldPrice.dev /v1/carat endpoint is documented as no-auth and free.
