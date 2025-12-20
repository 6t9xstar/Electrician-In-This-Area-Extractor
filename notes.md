# Phase 1 Scraper Notes


## What we tried
- `phase1_scraper.py` (requests+BeautifulSoup): blocked with 403 → 202 meta-refresh → JS/captcha challenge.
- `phase1_playwright.py` (headless Chromium): still hits 403/captcha despite stealth headers and anti-automation scripts.



## Current status
- The site aggressively blocks automated access (likely Cloudflare/SGCaptcha).
- Playwright can reach the page but still gets a challenge page; we skip those URLs.
- No listing links collected yet.



## Next options to bypass
1. **Residential proxy/rotating IPs** – use a rotating proxy service (BrightData, Oxylabs, etc.) with Playwright.
2. **Manual solve in headed mode** – run `--no-headless`, pause on captcha, allow manual solve, then continue.
3. **Human-like delays + mouse/keyboard simulation** – add random delays and page interactions before extraction.
4. **Alternative data source** – if the site is too hard, consider other public contractor directories.



## Phase 2 target fields (once we have listing URLs)
- `listing_url`
- `company_name`
- `website_url` (if present)
- `email` (if present)
- `verified` flag (text indicates “Verified listing”)


## Commands


```bash
# Try manual solve (headed mode) on a few URLs
python phase1_playwright.py --limit 3 --no-headless --sleep 2



# With a proxy (set HTTPS_PROXY env var or pass via Playwright context)

export HTTPS_PROXY=http://user:pass@proxy:port
python phase1_playwright.py --limit 5
```
