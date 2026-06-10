# ============================================================
# browser_search.py — Async search flow + page-state detection
# ============================================================
"""The Playwright-driven search: navigate, fill the address form, submit, pick
the best-matching result card, and hand the detail page to the extractor.

Page-state helpers (``is_cloudflare_challenge``, ``is_no_results_page``,
``is_blocked``) take only a page object and no settings, so they're easy to
unit-test against a fake page.
"""

import asyncio
import logging

from web_crawler.extractor import extract_profile_data
from web_crawler.records import (
    STATUS_LOW_CONFIDENCE, STATUS_SUCCESS, score_name_match,
)

logger = logging.getLogger(__name__)

# Selector that indicates the address search form has loaded and is usable.
FORM_READY_SELECTOR = (
    '#StreetAddress, input[name="StreetAddress"], '
    '#searchAddress-tab, input[placeholder*="Address" i]'
)
# Selector that indicates a results list or a profile detail page has loaded.
RESULTS_READY_SELECTOR = '.card, .person-detail, .result-item'
# Selector that indicates a profile detail page (the page we extract from) loaded.
DETAIL_READY_SELECTOR = 'h1, .person-detail, script[type="application/ld+json"]'

# Phrases the site shows on a genuinely empty result set. Detection requires a
# marker phrase (not just "0 cards found") so a selector drift can't silently
# turn every row into NOT_FOUND.
NO_RESULTS_MARKERS = (
    "no results found",
    "0 records found",
    "we could not find any records",
    "did not return any results",
    "couldn't find any results",
    "no records were found",
)


async def is_cloudflare_challenge(page) -> bool:
    """Check if the current page is a Cloudflare challenge/block page."""
    try:
        title = (await page.title()).lower()
        content = (await page.content())[:3000].lower()
        if "just a moment" in title:
            return True
        if "attention required" in title:
            return True
        if "cf-challenge-running" in content or "challenge-form" in content:
            return True
        if "checking your browser" in content or "verify you are human" in content:
            return True
        return False
    except Exception:
        return False


async def is_no_results_page(page) -> bool:
    """True on the site's 'no results' page. A genuinely empty result set should
    be recorded as NOT_FOUND and not retried."""
    try:
        content = (await page.content()).lower()
        return any(marker in content for marker in NO_RESULTS_MARKERS)
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


async def wait_for_any(page, selector: str, timeout: int) -> bool:
    """Wait until any element matching the (comma-separated) CSS selector becomes
    visible. Returns True if found, False on timeout — never raises. Replaces
    blind sleeps: we proceed the instant the page is ready, capped at *timeout*."""
    try:
        await page.wait_for_selector(selector, timeout=timeout, state="visible")
        return True
    except Exception:
        return False


async def wait_for_manual_captcha_solve(page, timeout_seconds: int) -> bool:
    """Wait for the CAPTCHA to be solved — by the NopeCHA extension or manually.
    Polls every 3 seconds. Returns True if resolved, False on timeout."""
    logger.info("=" * 50)
    logger.info("[CAPTCHA] CAPTCHA/Challenge detected!")
    logger.info("[CAPTCHA] Waiting for your extension or manual solve...")
    logger.info(f"[CAPTCHA] Timeout: {timeout_seconds}s - solve it in the browser window")
    logger.info("=" * 50)

    start = asyncio.get_event_loop().time()
    while asyncio.get_event_loop().time() - start < timeout_seconds:
        try:
            if not await is_cloudflare_challenge(page):
                elapsed = asyncio.get_event_loop().time() - start
                logger.info(f"[CAPTCHA] Challenge resolved after {elapsed:.1f}s")
                return True
        except Exception as e:
            logger.debug(f"[CAPTCHA] Check error (normal during navigation): {e}")
        await asyncio.sleep(3)

    logger.error(f"[CAPTCHA] Timed out after {timeout_seconds}s — challenge not solved")
    return False


async def log_public_ip(page, proxy_server: str = "") -> str | None:
    """Fetch and log the current outbound public IP via the browser context, so
    you can confirm the proxy (if configured) is actually taking effect."""
    try:
        resp = await page.request.get("https://api.ipify.org?format=json", timeout=10000)
        ip = (await resp.json()).get("ip")
        tag = f"via proxy {proxy_server}" if proxy_server else "direct connection"
        logger.info(f"[IP] Outbound IP: {ip} ({tag})")
        return ip
    except Exception as e:
        logger.warning(f"[IP] Could not determine outbound IP: {e}")
        return None


async def search_property(page, target_name, address, city, state, settings) -> dict | None:
    """Core scraping logic: navigate, fill form, submit, extract data.

    Returns an extracted data dict (with 'Status' and 'Match Score' set), or one
    of the sentinel strings "CHALLENGE_FAILED" / "NO_RESULTS", or None on failure.
    """
    from web_crawler.config import TARGET_URL

    page_timeout = settings.page_load_timeout
    el_timeout = settings.element_timeout

    city_state = f"{city}, {state}"
    logger.info(f"[SEARCH] Looking up: {target_name} at {address}, {city_state}")

    # Step 1: Navigate to the homepage
    try:
        await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=page_timeout)
        if not await wait_for_any(page, FORM_READY_SELECTOR, timeout=10000):
            logger.debug("[SEARCH] Search form not visible yet (possible challenge page)")
    except Exception as e:
        logger.error(f"[SEARCH] Failed to load homepage: {e}")
        return None

    # Step 2: Handle Cloudflare challenge — wait for extension/manual solve
    if await is_cloudflare_challenge(page):
        logger.info("[SEARCH] Cloudflare challenge detected, waiting for solve...")
        solved = await wait_for_manual_captcha_solve(page, settings.captcha_solve_timeout)
        if not solved:
            logger.error("[SEARCH] Could not solve Cloudflare challenge (timed out)")
            return "CHALLENGE_FAILED"
        logger.info("[SEARCH] Waiting for page to settle after CAPTCHA solve...")
        await wait_for_any(page, FORM_READY_SELECTOR, timeout=15000)
        if await is_cloudflare_challenge(page):
            logger.error("[SEARCH] Still on challenge page after solving")
            return "CHALLENGE_FAILED"

    # Step 3: Check for blocks
    if await is_blocked(page):
        logger.warning("[SEARCH] Page is blocked (403/Forbidden)")
        return None

    # Step 4: Click the Address search tab
    try:
        address_tab = page.locator(
            '#searchAddress-tab, '
            'a:has-text("Address"), '
            'button:has-text("Address"), '
            '[data-tab="address"], '
            'li:has-text("Address") a'
        ).first
        await address_tab.click(timeout=el_timeout)
        await wait_for_any(page, '#StreetAddress, input[name="StreetAddress"]', timeout=el_timeout)
        logger.info("[SEARCH] Clicked Address tab")
    except Exception as e:
        logger.warning(f"[SEARCH] Could not click address tab (may already be active): {e}")

    # Step 5: Fill in the address fields
    try:
        street_field = page.locator(
            '#StreetAddress, input[name="StreetAddress"], '
            'input[placeholder*="Street" i], input[placeholder*="Address" i]'
        ).first
        await street_field.fill("")
        await street_field.fill(address)
        logger.info(f"[SEARCH] Filled street: {address}")

        city_field = page.locator(
            '#CityStateZip, input[name="CityStateZip"], '
            'input[placeholder*="City" i], input[placeholder*="Location" i]'
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
            '#btnSubmit, button[type="submit"], '
            'input[type="submit"], button:has-text("Search")'
        ).first
        await submit_btn.click(timeout=el_timeout)
        logger.info("[SEARCH] Submitted search")
    except Exception as e:
        logger.error(f"[SEARCH] Could not click submit: {e}")
        return None

    # Step 7: Wait for results page
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=page_timeout)
        await wait_for_any(page, RESULTS_READY_SELECTOR, timeout=el_timeout)
    except Exception as e:
        logger.warning(f"[SEARCH] Timeout waiting for results: {e}")

    # Step 8: Post-search Cloudflare or blocks
    if await is_cloudflare_challenge(page):
        logger.info("[SEARCH] Post-search Cloudflare challenge — waiting for solve...")
        solved = await wait_for_manual_captcha_solve(page, settings.captcha_solve_timeout)
        if not solved:
            return None
        await wait_for_any(page, RESULTS_READY_SELECTOR, timeout=10000)

    if await is_blocked(page):
        logger.warning("[SEARCH] Blocked after search submission")
        return None

    # Step 8b: Genuinely empty result set — record NOT_FOUND, never retry.
    if await is_no_results_page(page):
        logger.info("[SEARCH] Site reports no results for this address")
        return "NO_RESULTS"

    # Step 9: Look for result links and click the best matching name
    match_score = None  # stays None when we never scored a card (direct detail page)
    try:
        try:
            await page.wait_for_selector('.card, .person-detail, .result-item', timeout=10000)
        except Exception:
            logger.warning("[SEARCH] No clear result cards found, proceeding anyway.")

        if await page.locator('.person-detail, h1:has-text("Current Address")').count() > 0:
            logger.info("[SEARCH] Redirected directly to details page")
        else:
            result_cards = page.locator('.card, .result-item, div[class*="row mb-3"]')
            count = await result_cards.count()

            if count == 0:
                result_link = page.locator(
                    'a[href*="/find/address/"], a[href*="/results?"], a.link-to-details'
                ).first
                if await result_link.is_visible(timeout=el_timeout):
                    await result_link.click()
                    await page.wait_for_load_state("domcontentloaded", timeout=page_timeout)
                    await wait_for_any(page, DETAIL_READY_SELECTOR, timeout=el_timeout)
                    logger.info("[SEARCH] Clicked first result link (fallback)")
            else:
                best_score = -1
                best_link = None
                best_name = ""
                for i in range(count):
                    card = result_cards.nth(i)
                    name_locator = card.locator('.h4, h4, .title, [class*="name"]')
                    if await name_locator.count() > 0:
                        card_name = await name_locator.first.inner_text()
                    else:
                        card_name = await card.inner_text()
                    card_name = card_name.replace('\n', ' ').strip()

                    final_score = score_name_match(target_name, card_name)
                    if final_score > best_score:
                        best_score = final_score
                        link = card.locator('a.btn, a[href*="/find/person/"]').first
                        if not await link.is_visible():
                            link = card.locator('a').first
                        best_link = link
                        best_name = card_name

                logger.info(f"[SEARCH] Best match: '{best_name}' with score {best_score:.2f} "
                            f"(Target: '{target_name}')")
                match_score = best_score
                if match_score < settings.min_match_score:
                    logger.warning(f"[SEARCH] Score {match_score:.2f} is below min_match_score "
                                   f"({settings.min_match_score}) — result flagged LOW_CONFIDENCE")

                if best_link and await best_link.is_visible():
                    await best_link.click()
                    await page.wait_for_load_state("domcontentloaded", timeout=page_timeout)
                    await wait_for_any(page, DETAIL_READY_SELECTOR, timeout=el_timeout)
                    logger.info(f"[SEARCH] Clicked best matching link for '{best_name}'")
                else:
                    logger.warning("[SEARCH] Found best match but no clickable link. Trying alternate.")
                    try:
                        await result_cards.nth(0).click()
                        await page.wait_for_load_state("domcontentloaded", timeout=page_timeout)
                        await wait_for_any(page, DETAIL_READY_SELECTOR, timeout=el_timeout)
                    except Exception:
                        logger.warning("[SEARCH] Could not click card, trying first link found.")
                        await page.locator('a[href*="/find/person/"]').first.click()
                        await page.wait_for_load_state("domcontentloaded", timeout=page_timeout)
    except Exception:
        logger.info("[SEARCH] No clickable results, extracting from current page")

    # Step 10: Extract profile data
    data = await extract_profile_data(page)
    if isinstance(data, dict):
        if match_score is not None:
            data["Match Score"] = f"{match_score:.2f}"
            data["Status"] = (STATUS_SUCCESS if match_score >= settings.min_match_score
                              else STATUS_LOW_CONFIDENCE)
        else:
            data["Match Score"] = ""
            data["Status"] = STATUS_SUCCESS
    return data
