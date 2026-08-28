# Chennai 22K Gold PWA

A mobile-first Progressive Web App for tracking the Chennai 22K reference gold rate.

## Main display
- **8 grams / 1 sovereign is the primary prominent rate**
- 1 gram and 10 gram secondary rates
- Automatic 8g = 1g × 8 calculation

## Graph
- 7D, 30D, 90D and 1Y ranges
- Toggle between 8g and 1g
- Automatic scale
- High/low/change/average statistics
- Point tooltips
- Uses every available historical observation

## Data
The GitHub Actions workflow updates `data.json` from the configured Chennai 22K reference source. This is a reference market rate; jewellery invoices can differ because of making charges, GST, offers and dealer premiums.

## Files to replace
1. `index.html`
2. `sw.js`
3. `data.json`
4. `.github/workflows/update-gold.yml`
