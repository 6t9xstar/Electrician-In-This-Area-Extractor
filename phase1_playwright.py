"""
Phase 1 scraper using Playwright headless browser to bypass JS/captcha challenges.
"""

import argparse
import csv
import json
import logging
import os
import random
import time
from pathlib import Path
from typing import Iterable, List, Set, Tuple
from urllib.parse import urljoin, urlparse

from playwright.sync_api import sync_playwright, Page, BrowserContext


BASE_DOMAIN = "electricianinthisarea.net"
DEFAULT_TIMEOUT = 15000  # ms


def configure_logger(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%H:%M:%S",
    )


def get_proxy_config() -> dict | None:
    proxy_url = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
    if not proxy_url:
        return None
    # Support http/https and basic auth
    parsed = urlparse(proxy_url)
    return {
        "server": f"{parsed.scheme}://{parsed.netloc}",
        "username": parsed.username,
        "password": parsed.password,
    }


def human_like_interaction(page: Page) -> None:
    """Add random mouse moves and keypress to look human."""
    # Random mouse move
    viewport = page.viewport_size
    if viewport:
        x = random.randint(0, viewport["width"])
        y = random.randint(0, viewport["height"])
        page.mouse.move(x, y)
    # Random scroll
    page.evaluate("window.scrollBy(0, Math.random()*200)")
    # Small random pause
    time.sleep(random.uniform(0.5, 2.0))


def read_urls(path: Path, limit: int | None = None) -> List[str]:
    urls: List[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            candidate = line.strip()
            if candidate:
                urls.append(candidate)
            if limit and len(urls) >= limit:
                break
    logging.info("Loaded %s pagination URLs from %s", len(urls), path)
    return urls


def is_listing_link(href: str) -> bool:
    parsed = urlparse(href)
    if parsed.netloc and parsed.netloc != BASE_DOMAIN:
        return False
    return "/listing/" in parsed.path


def extract_listing_links(base_url: str, page: Page) -> Set[str]:
    links: Set[str] = set()
    # Wait a moment for any dynamic content
    page.wait_for_load_state("networkidle", timeout=DEFAULT_TIMEOUT)
    for tag in page.query_selector_all("a[href]"):
        href = tag.get_attribute("href")
        if not href:
            continue
        absolute = urljoin(base_url, href)
        if is_listing_link(absolute):
            links.add(absolute.split("#", 1)[0])
    return links


def write_outputs(
    rows: Iterable[Tuple[str, str]], csv_path: Path, json_path: Path
) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    rows_list = list(rows)
    with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["source_page", "listing_url"])
        writer.writerows(rows_list)
    logging.info("Wrote %s rows to %s", len(rows_list), csv_path)

    listings_only = sorted({listing for _, listing in rows_list})
    with json_path.open("w", encoding="utf-8") as json_file:
        json.dump(listings_only, json_file, indent=2)
    logging.info("Wrote %s unique listings to %s", len(listings_only), json_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 1 listing link scraper (Playwright).")
    parser.add_argument(
        "--urls-file",
        type=Path,
        default=Path("urls.txt"),
        help="Path to pagination URL list.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="Directory to store CSV/JSON outputs.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Optional limit on number of pagination URLs to process.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=1.0,
        help="Seconds to pause between page loads to be polite.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=True,
        help="Run browser in headless mode (default: True).",
    )
    parser.add_argument(
        "--no-headless",
        dest="headless",
        action="store_false",
        help="Run browser headed (visible).",
    )
    args = parser.parse_args()
    configure_logger(args.verbose)

    urls = read_urls(args.urls_file, args.limit)
    all_rows: List[Tuple[str, str]] = []
    seen: Set[str] = set()

    with sync_playwright() as p:
        proxy_cfg = get_proxy_config()
        browser = p.chromium.launch(headless=args.headless, proxy=proxy_cfg)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            locale="en-US",
            timezone_id="America/New_York",
            extra_http_headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
            },
        )
        # Reduce automation signals
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
            });
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5],
            });
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en'],
            });
        """)
        page = context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT)

        for idx, page_url in enumerate(urls, start=1):
            logging.info("(%s/%s) Loading %s", idx, len(urls), page_url)
            retries = 2
            for attempt in range(retries):
                try:
                    response = page.goto(page_url, wait_until="networkidle")
                    if response and response.status >= 400:
                        logging.error(
                            "Failed to load %s: HTTP %s", page_url, response.status
                        )
                        break
                    # Ensure page is fully stable
                    page.wait_for_load_state("domcontentloaded", timeout=DEFAULT_TIMEOUT)
                    page.wait_for_load_state("networkidle", timeout=DEFAULT_TIMEOUT)
                    # Human-like interaction before extraction
                    human_like_interaction(page)
                    # Quick check for captcha/challenge page
                    page_content = page.content()
                    if "sgcaptcha" in page_content or "Robot Challenge" in page_content:
                        if attempt == retries - 1:
                            logging.warning(
                                "Captcha/challenge page encountered for %s. Skipping.", page_url
                            )
                            break
                        else:
                            logging.info(
                                "Captcha/challenge page on %s; retrying after delay...", page_url
                            )
                            time.sleep(5)
                            continue
                    listing_links = extract_listing_links(page_url, page)
                    logging.debug("Page title: %s", page.title())
                    logging.debug("Page snippet (first 800 chars): %s", page_content[:800])
                    new_links = [link for link in listing_links if link not in seen]
                    for link in new_links:
                        seen.add(link)
                        all_rows.append((page_url, link))
                    logging.info(
                        "Found %s listing links (%s new, %s total unique)",
                        len(listing_links),
                        len(new_links),
                        len(seen),
                    )
                    time.sleep(max(args.sleep, 0))
                    break  # success; exit retry loop
                except Exception as exc:  # noqa: BLE001
                    logging.error("Exception on %s (attempt %s): %s", page_url, attempt + 1, exc)
                    if attempt == retries - 1:
                        break
                    time.sleep(3)

        browser.close()

    if not all_rows:
        logging.warning("No listing links collected.")
        return

    csv_path = args.output_dir / "listing_links.csv"
    json_path = args.output_dir / "listing_links.json"
    write_outputs(all_rows, csv_path, json_path)
    logging.info("Done. Collected %s unique listing URLs.", len(seen))


if __name__ == "__main__":
    main()
