# ============================================================
# scraper.py — Main Orchestrator
# ============================================================
"""
TruePeopleSearch Address-Based Data Extraction Script
Phase 1: Processes only the first CSV row for testing.
Set PHASE_1_TESTING = False in config.py for full batch mode.
"""

import asyncio
import csv
import logging
import random
import sys
import time

from playwright.async_api import async_playwright
from playwright_stealth import Stealth

from config import (
    PHASE_1_TESTING, TARGET_URL, INPUT_CSV, OUTPUT_CSV, LOG_FILE,
    HEADLESS, USER_AGENT, VIEWPORT, PAGE_LOAD_TIMEOUT, ELEMENT_TIMEOUT,
    REQUEST_DELAY_MIN, REQUEST_DELAY_MAX, MAX_RETRIES, TURNSTILE_SITE_KEY,
)
from captcha_solver import handle_cloudflare_challenge
from vpn_manager import initial_connect, rotate_vpn
from data_extractor import extract_profile_data, save_results

# ── Logging Setup ───────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


def read_input_csv(path: str) -> list[dict]:
    """Read addresses from the input CSV file."""
    rows = []
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Handle typo in Excel: 'Property Addres' vs 'Property Address'
            address = (row.get("Property Address") or row.get("Property Addres", "")).strip()
            rows.append({
                "Property Address": address,
                "Property City": row.get("Property city", "").strip(),
                "Property State": row.get("property state", "").strip(),
            })
    logger.info(f"[INPUT] Loaded {len(rows)} rows from {path}")
    return rows


async def is_cloudflare_challenge(page) -> bool:
    """Check if the current page is a Cloudflare challenge/block page."""
    try:
        title = await page.title()
        content = (await page.content())[:3000].lower()
        title_lower = title.lower()
        # Title-based checks (most reliable)
        if "just a moment" in title_lower:
            return True
        if "attention required" in title_lower:
            return True
        # Content-based checks (use specific markers, not generic 'turnstile')
        if "cf-challenge-running" in content or "challenge-form" in content:
            return True
        if "checking your browser" in content or "verify you are human" in content:
            return True
        return False
    except Exception:
        return False


async def is_blocked(page) -> bool:
    """Check if the page returned a 403 or soft block."""
    try:
        title = await page.title()
        content = await page.content()
        indicators = [
            "403" in title,
            "forbidden" in title.lower(),
            "access denied" in content.lower()[:500],
            "blocked" in content.lower()[:500],
        ]
        return any(indicators)
    except Exception:
        return False


async def search_property(page, address: str, city: str, state: str) -> dict | None:
    """
    Core scraping logic: navigate, fill form, submit, extract data.

    Args:
        page: Playwright page object
        address: Street address (e.g., "123 Main St")
        city: City name (e.g., "New York")
        state: State abbreviation (e.g., "NY")

    Returns:
        Extracted data dict, or None on failure.
    """
    city_state = f"{city}, {state}"
    logger.info(f"[SEARCH] Looking up: {address}, {city_state}")

    # Step 1: Navigate to the homepage
    try:
        await page.goto(TARGET_URL, wait_until="domcontentloaded",
                        timeout=PAGE_LOAD_TIMEOUT)
        # Give page more time to settle (Cloudflare JS needs time)
        await page.wait_for_timeout(8000)
    except Exception as e:
        logger.error(f"[SEARCH] Failed to load homepage: {e}")
        return None

    # Step 2: Handle Cloudflare challenge if present
    if await is_cloudflare_challenge(page):
        logger.info("[SEARCH] Cloudflare challenge detected, solving...")
        solved = await handle_cloudflare_challenge(page, TARGET_URL, TURNSTILE_SITE_KEY)
        if not solved:
            logger.error("[SEARCH] Could not solve Cloudflare challenge")
            return "CHALLENGE_FAILED"  # Signal to rotate VPN
        # Wait for the page to reload after challenge
        await page.wait_for_timeout(5000)
        # Check if we're still on the challenge page
        if await is_cloudflare_challenge(page):
            logger.error("[SEARCH] Still on challenge page after solving")
            return "CHALLENGE_FAILED"

    # Step 3: Check for blocks
    if await is_blocked(page):
        logger.warning("[SEARCH] Page is blocked (403/Forbidden)")
        return None  # Caller will trigger VPN rotation

    # Step 4: Click the Address search tab
    try:
        # Try multiple selectors for the address tab
        address_tab = page.locator(
            '#searchAddress-tab, '
            'a:has-text("Address"), '
            'button:has-text("Address"), '
            '[data-tab="address"], '
            'li:has-text("Address") a'
        ).first
        await address_tab.click(timeout=ELEMENT_TIMEOUT)
        await page.wait_for_timeout(1000)
        logger.info("[SEARCH] Clicked Address tab")
    except Exception as e:
        logger.warning(f"[SEARCH] Could not click address tab (may already be active): {e}")

    # Step 5: Fill in the address fields
    try:
        # Street address field
        street_field = page.locator(
            '#StreetAddress, '
            'input[name="StreetAddress"], '
            'input[placeholder*="Street" i], '
            'input[placeholder*="Address" i]'
        ).first
        await street_field.fill("")
        await street_field.fill(address)
        logger.info(f"[SEARCH] Filled street: {address}")

        # City/State/Zip field
        city_field = page.locator(
            '#CityStateZip, '
            'input[name="CityStateZip"], '
            'input[placeholder*="City" i], '
            'input[placeholder*="Location" i]'
        ).first
        await city_field.fill("")
        await city_field.fill(city_state)
        logger.info(f"[SEARCH] Filled city/state: {city_state}")
    except Exception as e:
        logger.error(f"[SEARCH] Could not fill form fields: {e}")
        return None

    # Step 6: Submit the search
    try:
        submit_btn = page.locator(
            '#btnSubmit, '
            'button[type="submit"], '
            'input[type="submit"], '
            'button:has-text("Search")'
        ).first
        await submit_btn.click(timeout=ELEMENT_TIMEOUT)
        logger.info("[SEARCH] Submitted search")
    except Exception as e:
        logger.error(f"[SEARCH] Could not click submit: {e}")
        return None

    # Step 7: Wait for results page
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
        await page.wait_for_timeout(3000)
    except Exception as e:
        logger.warning(f"[SEARCH] Timeout waiting for results: {e}")

    # Step 8: Check for post-search Cloudflare or blocks
    if await is_cloudflare_challenge(page):
        logger.info("[SEARCH] Post-search Cloudflare challenge")
        solved = await handle_cloudflare_challenge(page, page.url, TURNSTILE_SITE_KEY)
        if not solved:
            return None
        await page.wait_for_timeout(5000)

    if await is_blocked(page):
        logger.warning("[SEARCH] Blocked after search submission")
        return None

    # Step 9: Look for result links and click the first one
    try:
        result_link = page.locator(
            'a[href*="/find/address/"], '
            'a[href*="/results?"], '
            '.result-item a, '
            '.card a[href*="truepeoplesearch"], '
            'a.link-to-details'
        ).first

        if await result_link.is_visible(timeout=ELEMENT_TIMEOUT):
            await result_link.click()
            logger.info("[SEARCH] Clicked first result link")
            await page.wait_for_load_state("domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
            await page.wait_for_timeout(2000)
        else:
            logger.info("[SEARCH] No result links found, trying extraction on current page")
    except Exception:
        logger.info("[SEARCH] No clickable results, extracting from current page")

    # Step 10: Extract profile data
    data = await extract_profile_data(page)
    return data


async def main():
    """Main entry point — orchestrates the full scraping pipeline."""
    logger.info("=" * 60)
    logger.info("TruePeopleSearch Data Extraction Script")
    logger.info(f"Mode: {'PHASE 1 (single row testing)' if PHASE_1_TESTING else 'FULL BATCH'}")
    logger.info("=" * 60)

    # ── Step 1: VPN Setup ────────────────────────────────
    logger.info("[INIT] Setting up VPN connection...")
    vpn_ok = initial_connect()
    if not vpn_ok:
        logger.warning("[INIT] VPN connection failed — continuing without VPN")
        logger.warning("[INIT] You may get blocked. Consider fixing VPN and restarting.")

    # ── Step 2: Read Input CSV ───────────────────────────
    try:
        rows = read_input_csv(INPUT_CSV)
    except FileNotFoundError:
        logger.error(f"[INIT] Input CSV not found: {INPUT_CSV}")
        logger.error("  → Place your CSV file at the path above and retry.")
        return
    except Exception as e:
        logger.error(f"[INIT] Error reading CSV: {e}")
        return

    if not rows:
        logger.error("[INIT] No rows found in CSV file")
        return

    # Phase 1: only first row
    if PHASE_1_TESTING:
        rows = rows[:1]
        logger.info("[INIT] Phase 1 mode: processing first row only")

    # ── Step 3: Launch Browser ───────────────────────────
    results = []
    failed = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=HEADLESS,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
                "--window-size=1366,768",
            ],
        )
        stealth = Stealth()
        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport=VIEWPORT,
            locale="en-US",
            timezone_id="America/New_York",
        )
        page = await context.new_page()
        await stealth.apply_stealth_async(page)

        logger.info("[INIT] Browser launched with stealth mode")

        # ── Step 4: Process Each Row ─────────────────────
        for idx, row in enumerate(rows, 1):
            address = row["Property Address"]
            city = row["Property City"]
            state = row["Property State"]

            logger.info(f"\n{'─' * 50}")
            logger.info(f"[ROW {idx}/{len(rows)}] {address}, {city}, {state}")
            logger.info(f"{'─' * 50}")

            success = False
            for attempt in range(1, MAX_RETRIES + 1):
                logger.info(f"[ROW {idx}] Attempt {attempt}/{MAX_RETRIES}")

                data = await search_property(page, address, city, state)

                if data == "CHALLENGE_FAILED":
                    # Cloudflare challenge could not be solved — rotate VPN
                    logger.warning(f"[ROW {idx}] Challenge failed — rotating VPN for fresh IP...")
                    vpn_rotated = rotate_vpn()
                    if not vpn_rotated:
                        logger.error(f"[ROW {idx}] VPN rotation failed")
                    await context.clear_cookies()
                    await page.wait_for_timeout(5000)

                elif data and isinstance(data, dict):
                    # Merge input fields with extracted data
                    data["Property Address"] = address
                    data["Property City"] = city
                    data["Property State"] = state
                    # Property Zip is not in input CSV
                    data.setdefault("Property Zip", "")
                    results.append(data)
                    logger.info(f"[ROW {idx}] ✅ SUCCESS — {data.get('Agent Name', 'N/A')}")
                    success = True
                    break

                elif await is_blocked(page):
                    logger.warning(f"[ROW {idx}] Blocked — rotating VPN...")
                    vpn_rotated = rotate_vpn()
                    if not vpn_rotated:
                        logger.error(f"[ROW {idx}] VPN rotation failed")
                    # Clear cookies and retry with fresh session
                    await context.clear_cookies()
                    await page.wait_for_timeout(3000)

                else:
                    logger.warning(f"[ROW {idx}] Attempt {attempt} failed, retrying...")
                    await page.wait_for_timeout(2000)

            if not success:
                logger.error(f"[ROW {idx}] ❌ FAILED after {MAX_RETRIES} attempts — skipping")
                failed.append(row)

            # Random delay between rows (skip after last row)
            if idx < len(rows):
                delay = random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
                logger.info(f"[DELAY] Waiting {delay:.1f}s before next search...")
                await page.wait_for_timeout(int(delay * 1000))

        await browser.close()

    # ── Step 5: Save Results ─────────────────────────────
    if results:
        save_results(results, OUTPUT_CSV)
    else:
        logger.warning("[OUTPUT] No successful extractions to save")

    # ── Summary ──────────────────────────────────────────
    logger.info("\n" + "=" * 60)
    logger.info("SCRAPING COMPLETE")
    logger.info(f"  Total processed:  {len(rows)}")
    logger.info(f"  Successful:       {len(results)}")
    logger.info(f"  Failed:           {len(failed)}")
    if results:
        logger.info(f"  Output saved to:  {OUTPUT_CSV}")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
