# 22K Gold Tracker — Final Free PWA

Live source: GoldPrice.dev /v1/carat?currency=INR. The provider documents this endpoint as free, no API key, and returns 22K purity-adjusted metal value. Historical data is bundled locally as a 3-year monthly benchmark series.

The app refreshes on opening and every 15 minutes while active, and stores successful observations locally for offline viewing.

Important: this is a benchmark/spot-derived 22K metal value, not a jeweller retail quote. GST, making charges, wastage and dealer premiums are not included.

Android/browser PWAs cannot guarantee network execution while fully closed. For guaranteed scheduled background updates, a server/push mechanism is required.
