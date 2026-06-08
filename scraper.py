# ============================================================
# scraper.py — Main Orchestrator
# ============================================================
"""
TruePeopleSearch Address-Based Data Extraction Script
Phase 1: Processes only the first CSV row for testing.
Set PHASE_1_TESTING = False in config.py for full batch mode.

MODIFICATIONS:
- Uses personal Chrome profile (Default = Work) with extensions
- CAPTCHA solver disabled — relies on browser extension + manual solve
- IP rotation (VPN) temporarily disabled
"""

import asyncio
import csv
import logging
import os
import random
import subprocess
import sys
import time

from playwright.async_api import async_playwright

from config import (
    PHASE_1_TESTING, TARGET_URL, INPUT_CSV, OUTPUT_CSV, LOG_FILE,
    USER_AGENT, VIEWPORT, PAGE_LOAD_TIMEOUT, ELEMENT_TIMEOUT,
    REQUEST_DELAY_MIN, REQUEST_DELAY_MAX, MAX_RETRIES, CAPTCHA_SOLVE_TIMEOUT,
)
# VPN rotation disabled — imports kept for reference but not used
# from vpn_manager import initial_connect, rotate_vpn
from data_extractor import (
    extract_profile_data, save_results, save_single_result,
    display_record, load_completed_rows,
)

# ── Logging Setup ───────────────────────────────────────────
# Fix for Windows console encoding
if sys.stdout.encoding.lower() != 'utf-8':
    try:
        import codecs
        sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())
    except Exception:
        pass

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

# ── Chrome Profile Configuration ────────────────────────────
CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
CHROME_USER_DATA_DIR = r"C:\Users\DELL\AppData\Local\Google\Chrome\User Data"
CHROME_PROFILE_DIR = "Profile 11"  # Your "Work" profile
CDP_PORT = 9222  # Port for Chrome DevTools Protocol


def kill_existing_chrome():
    """
    Kill all running Chrome processes so we can launch a fresh instance
    with --remote-debugging-port (Chrome ignores the flag if an existing
    instance already owns the user-data-dir).
    """
    logger.info("[CHROME] Closing any existing Chrome processes...")
    try:
        subprocess.run(
            ["taskkill", "/F", "/IM", "chrome.exe"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception as e:
        logger.debug(f"[CHROME] taskkill note: {e}")

    # Wait until all chrome.exe processes are truly gone (file locks released)
    for _ in range(10):
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq chrome.exe"],
            capture_output=True, text=True, timeout=5,
        )
        if "chrome.exe" not in result.stdout.lower():
            break
        time.sleep(1)
    else:
        logger.warning("[CHROME] Some Chrome processes may still be running")

    time.sleep(3)  # Extra wait for file lock release
    logger.info("[CHROME] Existing Chrome processes terminated")


def wait_for_cdp_ready(port: int, timeout: int = 15) -> bool:
    """
    Poll http://127.0.0.1:{port}/json/version until Chrome's CDP is ready.
    """
    import urllib.request
    import urllib.error

    url = f"http://127.0.0.1:{port}/json/version"
    start = time.time()
    while time.time() - start < timeout:
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except (urllib.error.URLError, OSError):
            time.sleep(1)
    return False


def launch_chrome_with_profile():
    """
    Launch Chrome with the personal profile and remote debugging enabled.
    This preserves all extensions, cookies, and saved sessions.
    """
    # MUST kill existing Chrome first — otherwise the new process just
    # signals the running one and exits, so debugging port never opens.
    kill_existing_chrome()

    logger.info(f"[CHROME] Launching Chrome with profile: {CHROME_PROFILE_DIR}")
    logger.info(f"[CHROME] User data dir: {CHROME_USER_DATA_DIR}")

    chrome_args_list = [
        f'--remote-debugging-port={CDP_PORT}',
        f'--user-data-dir={CHROME_USER_DATA_DIR}',
        f'--profile-directory={CHROME_PROFILE_DIR}',
        '--no-first-run',
        '--no-default-browser-check',
        '--start-maximized'
    ]
    # Join with commas and wrap each in quotes for PowerShell array
    chrome_args_string = ", ".join([f"'{a}'" for a in chrome_args_list])

    ps_cmd = (
        f'Start-Process -FilePath "{CHROME_EXE}"'
        f' -ArgumentList {chrome_args_string}'
    )
    logger.info(f"[CHROME] PS Command: {ps_cmd}")
    logger.info(f"[CHROME] Launching via PowerShell...")

    subprocess.run(
        ["powershell", "-Command", ps_cmd],
        capture_output=True, text=True, timeout=10,
    )
    logger.info("[CHROME] Chrome launch command sent, waiting for CDP ready...")

    # Wait until the debugging port is actually accepting connections
    if wait_for_cdp_ready(CDP_PORT, timeout=20):
        logger.info(f"[CHROME] CDP port {CDP_PORT} is ready")
    else:
        logger.error(f"[CHROME] CDP port {CDP_PORT} not responding after 20s")
        raise RuntimeError("Chrome debugging port never became available. Is Chrome installed correctly?")


def _find_column(header: list[str], must_contain: str, prefer: str = None,
                 avoid: str = None, default: int = None) -> int | None:
    """Return the index of the best-matching header column.

    Matches columns whose (lowercased) name contains `must_contain`. When several
    match, a column also containing `prefer` wins (e.g. prefer 'property' over
    'mailing'); columns containing `avoid` are only used as a last resort. Falls
    back to `default` if nothing matches.

    Positional parsing is used (not csv.DictReader) because the real input file
    has blank, duplicated headers — the target-name column has an empty header —
    which DictReader would silently merge and drop."""
    candidates = [i for i, c in enumerate(header) if must_contain in c.lower()]
    if avoid:
        # Avoided columns are removed entirely; if that empties the pool, the
        # caller's default wins (e.g. 'Agent Name' is never used as Target Name).
        candidates = [i for i in candidates if avoid not in header[i].lower()]
    if not candidates:
        return default
    if prefer:
        preferred = [i for i in candidates if prefer in header[i].lower()]
        if preferred:
            return preferred[0]
    return candidates[0]


def read_input_csv(path: str) -> list[dict]:
    """Read addresses from the input CSV file using a positional reader for robustness.
    Each row dict includes 'Input Row #' — the 1-based row number from the CSV
    (excluding the header), so it matches the line the user sees in Excel/Sheets."""
    rows = []
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if not header:
            return []

        logger.info(f"[INPUT] CSV Header: {header}")

        # Resolve column indices, preferring the PROPERTY columns over MAILING,
        # and a name column that isn't the scraped "Agent Name". Defaults assume
        # the legacy layout: [name, address, city, state, ...].
        name_idx = _find_column(header, "name", avoid="agent", default=0)
        addr_idx = _find_column(header, "addres", prefer="property", default=1)
        city_idx = _find_column(header, "city", prefer="property", default=2)
        state_idx = _find_column(header, "state", prefer="property", default=3)

        logger.info(f"[INPUT] Column map: Name={name_idx}, Addr={addr_idx}, City={city_idx}, State={state_idx}")

        def cell(line, idx):
            return line[idx].strip() if idx is not None and len(line) > idx else ""

        for row_num, line in enumerate(reader, start=2):  # start=2 because row 1 is header
            if not line or not any(c.strip() for c in line):
                continue

            rows.append({
                "Input Row #": row_num,
                "Target Name": cell(line, name_idx),
                "Property Address": cell(line, addr_idx),
                "Property City": cell(line, city_idx),
                "Property State": cell(line, state_idx),
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


async def wait_for_manual_captcha_solve(page, timeout_seconds: int = CAPTCHA_SOLVE_TIMEOUT) -> bool:
    """
    Wait for the CAPTCHA to be solved — either by the NopeCHA browser
    extension or manually by the user. Polls every 3 seconds.

    Args:
        page: Playwright page object
        timeout_seconds: Max seconds to wait (default: 5 minutes)

    Returns:
        True if challenge was resolved, False if timed out
    """
    logger.info("=" * 50)
    logger.info("[CAPTCHA] CAPTCHA/Challenge detected!")
    logger.info("[CAPTCHA] Waiting for your extension or manual solve...")
    logger.info(f"[CAPTCHA] Timeout: {timeout_seconds}s - solve it in the browser window")
    logger.info("=" * 50)

    start = time.time()
    check_interval = 3  # Check every 3 seconds

    while time.time() - start < timeout_seconds:
        try:
            if not await is_cloudflare_challenge(page):
                elapsed = time.time() - start
                logger.info(f"[CAPTCHA] Challenge resolved after {elapsed:.1f}s")
                return True
        except Exception as e:
            logger.debug(f"[CAPTCHA] Check error (normal during navigation): {e}")

        await asyncio.sleep(check_interval)

    logger.error(f"[CAPTCHA] ❌ Timed out after {timeout_seconds}s — challenge not solved")
    return False


# Selector that indicates the address search form has loaded and is usable.
FORM_READY_SELECTOR = (
    '#StreetAddress, input[name="StreetAddress"], '
    '#searchAddress-tab, input[placeholder*="Address" i]'
)
# Selector that indicates a results list or a profile detail page has loaded.
RESULTS_READY_SELECTOR = '.card, .person-detail, .result-item'
# Selector that indicates a profile detail page (the page we extract from) loaded.
DETAIL_READY_SELECTOR = 'h1, .person-detail, script[type="application/ld+json"]'


async def wait_for_any(page, selector: str, timeout: int = ELEMENT_TIMEOUT) -> bool:
    """Wait until any element matching the (comma-separated) CSS selector becomes
    visible. Returns True if found, False on timeout — never raises.

    This replaces blind `wait_for_timeout` sleeps: we proceed the instant the page
    is actually ready instead of always waiting a fixed number of seconds, while
    still capping the wait so a missing element can't hang the run."""
    try:
        await page.wait_for_selector(selector, timeout=timeout, state="visible")
        return True
    except Exception:
        return False


async def search_property(page, target_name: str, address: str, city: str, state: str) -> dict | None:
    """
    Core scraping logic: navigate, fill form, submit, extract data.

    Args:
        page: Playwright page object
        target_name: The name of the person we are looking for
        address: Street address (e.g., "123 Main St")
        city: City name (e.g., "New York")
        state: State abbreviation (e.g., "NY")

    Returns:
        Extracted data dict, or None on failure.
    """
    city_state = f"{city}, {state}"
    logger.info(f"[SEARCH] Looking up: {target_name} at {address}, {city_state}")

    # Step 1: Navigate to the homepage
    try:
        await page.goto(TARGET_URL, wait_until="domcontentloaded",
                        timeout=PAGE_LOAD_TIMEOUT)
        # Proceed as soon as the search form appears rather than always sleeping.
        # On a Cloudflare challenge the form won't show — that's handled in Step 2.
        if not await wait_for_any(page, FORM_READY_SELECTOR, timeout=10000):
            logger.debug("[SEARCH] Search form not visible yet (possible challenge page)")
    except Exception as e:
        logger.error(f"[SEARCH] Failed to load homepage: {e}")
        return None

    # Step 2: Handle Cloudflare challenge — wait for extension/manual solve
    if await is_cloudflare_challenge(page):
        logger.info("[SEARCH] Cloudflare challenge detected, waiting for solve...")
        solved = await wait_for_manual_captcha_solve(page)
        if not solved:
            logger.error("[SEARCH] Could not solve Cloudflare challenge (timed out)")
            return "CHALLENGE_FAILED"
        # Wait for the real page (search form) to load after the challenge clears,
        # up to 15s — returns early the moment the form appears.
        logger.info("[SEARCH] Waiting for page to settle after CAPTCHA solve...")
        await wait_for_any(page, FORM_READY_SELECTOR, timeout=15000)
        # Check if we're still on the challenge page
        if await is_cloudflare_challenge(page):
            logger.error("[SEARCH] Still on challenge page after solving")
            return "CHALLENGE_FAILED"

    # Step 3: Check for blocks
    if await is_blocked(page):
        logger.warning("[SEARCH] Page is blocked (403/Forbidden)")
        return None

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
        # Wait for the street field to become visible instead of a fixed 1s sleep.
        await wait_for_any(page, '#StreetAddress, input[name="StreetAddress"]', timeout=ELEMENT_TIMEOUT)
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
        # Wait for results/detail content to appear rather than a blind 3s sleep.
        await wait_for_any(page, RESULTS_READY_SELECTOR, timeout=ELEMENT_TIMEOUT)
    except Exception as e:
        logger.warning(f"[SEARCH] Timeout waiting for results: {e}")

    # Step 8: Check for post-search Cloudflare or blocks
    if await is_cloudflare_challenge(page):
        logger.info("[SEARCH] Post-search Cloudflare challenge — waiting for solve...")
        solved = await wait_for_manual_captcha_solve(page)
        if not solved:
            return None
        await wait_for_any(page, RESULTS_READY_SELECTOR, timeout=10000)

    if await is_blocked(page):
        logger.warning("[SEARCH] Blocked after search submission")
        return None

    # Step 9: Look for result links and click the best matching name
    try:
        import difflib
        
        # Wait for either result cards or detail page
        try:
            await page.wait_for_selector('.card, .person-detail, .result-item', timeout=10000)
        except Exception:
            logger.warning("[SEARCH] No clear result cards found, proceeding anyway.")

        # Check if we went straight to a detail page
        if await page.locator('.person-detail, h1:has-text("Current Address")').count() > 0:
            logger.info("[SEARCH] Redirected directly to details page")
            # Proceed to extract
        else:
            # We are on a results list page.
            # Find all result cards/links
            result_cards = page.locator('.card, .result-item, div[class*="row mb-3"]')
            count = await result_cards.count()
            
            if count == 0:
                # Fallback to the old simple selector if no cards are found
                result_link = page.locator(
                    'a[href*="/find/address/"], '
                    'a[href*="/results?"], '
                    'a.link-to-details'
                ).first

                if await result_link.is_visible(timeout=ELEMENT_TIMEOUT):
                    await result_link.click()
                    await page.wait_for_load_state("domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
                    await wait_for_any(page, DETAIL_READY_SELECTOR, timeout=ELEMENT_TIMEOUT)
                    logger.info("[SEARCH] Clicked first result link (fallback)")
            else:
                best_score = -1
                best_link = None
                best_name = ""
                
                # Iterate through cards and find the best match
                for i in range(count):
                    card = result_cards.nth(i)
                    # Name is usually in an h4, a, or div with class h4
                    name_locator = card.locator('.h4, h4, .title, [class*="name"]')
                    if await name_locator.count() > 0:
                        card_name = await name_locator.first.inner_text()
                    else:
                        card_name = await card.inner_text() # fallback, might be messy
                    
                    card_name = card_name.replace('\n', ' ').strip()
                    
                    # Compute similarity score
                    # Basic approach: sequence matcher
                    score = difflib.SequenceMatcher(None, target_name.lower(), card_name.lower()).ratio()
                    
                    # Alternatively, check if target name parts are in card name
                    target_parts = target_name.lower().split()
                    parts_found = sum(1 for part in target_parts if part in card_name.lower())
                    part_score = parts_found / max(1, len(target_parts))
                    
                    # Combine scores
                    final_score = score * 0.5 + part_score * 0.5
                    
                    if final_score > best_score:
                        best_score = final_score
                        
                        # Find the link within this card
                        link = card.locator('a.btn, a[href*="/find/person/"]').first
                        if not await link.is_visible():
                            link = card.locator('a').first
                            
                        best_link = link
                        best_name = card_name

                logger.info(f"[SEARCH] Best match: '{best_name}' with score {best_score:.2f} (Target: '{target_name}')")
                
                if best_link and await best_link.is_visible():
                    await best_link.click()
                    await page.wait_for_load_state("domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
                    await wait_for_any(page, DETAIL_READY_SELECTOR, timeout=ELEMENT_TIMEOUT)
                    logger.info(f"[SEARCH] Clicked best matching link for '{best_name}'")
                else:
                    logger.warning("[SEARCH] Found best match but could not find a clickable link. Trying alternate.")
                    # Try clicking anywhere in the card
                    try:
                        await result_cards.nth(0).click()
                        await page.wait_for_load_state("domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
                        await wait_for_any(page, DETAIL_READY_SELECTOR, timeout=ELEMENT_TIMEOUT)
                    except Exception:
                        logger.warning("[SEARCH] Could not click card, trying first link found.")
                        await page.locator('a[href*="/find/person/"]').first.click()
                        await page.wait_for_load_state("domcontentloaded", timeout=PAGE_LOAD_TIMEOUT)
    except Exception:
        logger.info("[SEARCH] No clickable results, extracting from current page")

    # Step 10: Extract profile data
    data = await extract_profile_data(page)
    return data


async def main():
    """Main entry point — orchestrates the full scraping pipeline."""
    # ── Step 1: VPN Setup (DISABLED) ────────────────────
    logger.info("[INIT] VPN/IP rotation is DISABLED — running with current IP")
    # vpn_ok = initial_connect(max_retries=3, wait_after_connect=10)
    # if not vpn_ok:
    #     logger.warning("[INIT] VPN initial connection failed — will try rotation during loop")
    # else:
    #     logger.info("[INIT] VPN is ACTIVE and connected")

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

    # ── Step 3: Select Row Range ─────────────────────────
    print("\n" + "=" * 50)
    print(f" CSV LOADED: {len(rows)} total records")
    print("=" * 50)
    
    try:
        start_input = input(f"Enter START row number (1-{len(rows)}, default 1): ").strip()
        start_idx = int(start_input) if start_input else 1
        
        end_input = input(f"Enter END row number ({start_idx}-{len(rows)}, default {len(rows)}): ").strip()
        end_idx = int(end_input) if end_input else len(rows)
        
        # Slice the rows (subtract 1 for 0-based indexing)
        rows_to_process = rows[max(0, start_idx-1) : end_idx]
        
        if not rows_to_process:
            logger.error(f"[INIT] Invalid range: {start_idx} to {end_idx}. Exiting.")
            return
            
        logger.info(f"[INIT] Selected range: Rows {start_idx} to {end_idx} (Total: {len(rows_to_process)})")
        rows = rows_to_process
    except ValueError:
        logger.warning("[INIT] Invalid numeric input. Defaulting to ALL rows.")
    print("=" * 50 + "\n")

    # ── Step 3b: Skip rows already saved in results.csv (resume) ──
    completed = load_completed_rows(OUTPUT_CSV)
    if completed:
        already = [r for r in rows if r["Input Row #"] in completed]
        if already:
            answer = input(
                f"Found {len(already)} of these rows already in {os.path.basename(OUTPUT_CSV)}. "
                "Skip them and resume? [Y/n]: "
            ).strip().lower()
            if answer in ("", "y", "yes"):
                rows = [r for r in rows if r["Input Row #"] not in completed]
                logger.info(f"[RESUME] Skipping {len(already)} already-scraped row(s); {len(rows)} remaining")
                if not rows:
                    logger.info("[RESUME] Nothing left to process — all selected rows are already done.")
                    return
            else:
                logger.info("[RESUME] Re-scraping all selected rows (duplicates may be appended)")

    # ── Step 4: Launch Chrome with Personal Profile ──────
    launch_chrome_with_profile()
    results = []
    failed = []

    try:
        async with async_playwright() as pw:
            # Connect to the running Chrome instance via CDP
            logger.info(f"[INIT] Connecting to Chrome via CDP on port {CDP_PORT}...")
            browser = await pw.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")

            # Get the default context (which has our profile + extensions)
            contexts = browser.contexts
            if contexts:
                context = contexts[0]
                logger.info(f"[INIT] Connected to existing browser context ({len(context.pages)} open tabs)")
            else:
                context = await browser.new_context()
                logger.info("[INIT] Created new browser context")

            # Always open a new tab to ensure a clean state
            page = await context.new_page()
            logger.info("[INIT] Opened new tab for scraping")
            
            # Close any blank/data tabs if possible to keep it clean
            for p in context.pages:
                if p != page and (p.url == "about:blank" or p.url.startswith("data:")):
                    try:
                        await p.close()
                    except Exception:
                        pass

            logger.info("[INIT] Browser ready with personal profile + extensions")

            # ── Step 5: Process Each Row ─────────────────────
            for idx, row in enumerate(rows, 1):
                csv_row_num = row["Input Row #"]
                target_name = row["Target Name"]
                address = row["Property Address"]
                city = row["Property City"]
                state = row["Property State"]

                logger.info(f"\n{'─' * 50}")
                logger.info(f"[ROW {idx}/{len(rows)}] (Input CSV Row #{csv_row_num}) {target_name} | {address}, {city}, {state}")
                logger.info(f"{'─' * 50}")

                success = False
                for attempt in range(1, MAX_RETRIES + 1):
                    logger.info(f"[ROW {idx}] Attempt {attempt}/{MAX_RETRIES}")

                    data = await search_property(page, target_name, address, city, state)

                    if data == "CHALLENGE_FAILED":
                        # Challenge could not be solved — VPN rotation disabled
                        logger.warning(f"[ROW {idx}] Challenge failed — VPN rotation disabled, retrying...")
                        # rotate_vpn(max_retries=5, wait_after_connect=15)
                        await page.wait_for_timeout(10000)

                    elif data and isinstance(data, dict):
                        # Merge input fields with extracted data
                        data["Input Row #"] = csv_row_num
                        data["Property Address"] = address
                        data["Property City"] = city
                        data["Property State"] = state
                        # Property Zip is not in input CSV
                        data.setdefault("Property Zip", "")
                        
                        # Display results to user
                        display_record(data)
                        
                        # Save this result to CSV IMMEDIATELY
                        save_single_result(data, OUTPUT_CSV)
                        
                        results.append(data)
                        logger.info(f"[ROW {idx}] SUCCESS - {data.get('Agent Name', 'N/A')}")
                        success = True
                        break

                    elif await is_blocked(page):
                        # Blocked — VPN rotation disabled
                        logger.warning(f"[ROW {idx}] Blocked (403) — VPN rotation disabled, retrying...")
                        # rotate_vpn(max_retries=5, wait_after_connect=15)
                        logger.info(f"[ROW {idx}] Waiting 10s before retry...")
                        await page.wait_for_timeout(10000)

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

            # Do NOT close the browser — it's the user's personal Chrome
            logger.info("[CLEANUP] Disconnecting from Chrome (browser stays open)")
            # browser.close() - REMOVED to keep browser open

    except Exception as e:
        logger.error(f"[ERROR] Fatal error: {e}")
        logger.error("[ERROR] Make sure Chrome is not already running, or close all Chrome windows first")
        raise
    finally:
        # Don't kill Chrome — user may want to keep it open
        pass

    # ── Step 6: Final Summary (results already saved incrementally) ──
    if not results:
        logger.warning("[OUTPUT] No successful extractions were saved")
    else:
        logger.info(f"[OUTPUT] All {len(results)} result(s) were saved incrementally to {OUTPUT_CSV}")

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
