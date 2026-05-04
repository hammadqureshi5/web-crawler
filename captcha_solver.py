# ============================================================
# captcha_solver.py — CapSolver / Cloudflare Challenge Integration
# ============================================================
"""
Handles two types of Cloudflare protection:
1. Managed Challenge ("Just a moment..." JS verification) — most common
2. Turnstile CAPTCHA widget — less common, requires sitekey

Strategy:
- First, wait for the JS challenge to auto-resolve (stealth browser can pass)
- Try clicking the Turnstile checkbox via bounding-box click on iframe
- If that fails, use CapSolver API to solve the challenge
"""

import asyncio
import json
import logging
import time
import httpx
import capsolver
from config import CAPSOLVER_API_KEY, CAPTCHA_SOLVE_TIMEOUT

logger = logging.getLogger(__name__)

# Set the global API key for the capsolver library
capsolver.api_key = CAPSOLVER_API_KEY

# CapSolver direct API endpoint
CAPSOLVER_API_URL = "https://api.capsolver.com"


def _is_challenge_page(title: str, content_snippet: str) -> bool:
    """
    Check if the page title/content indicates a Cloudflare challenge.
    Uses strict checks to avoid false positives.
    """
    title_lower = title.lower()
    content_lower = content_snippet.lower()

    # Strong indicators (title-based — most reliable)
    if "just a moment" in title_lower:
        return True
    if "attention required" in title_lower:
        return True

    # Content-based indicators (check multiple to reduce false positives)
    has_challenge_form = "cf-challenge-running" in content_lower or "challenge-form" in content_lower
    has_checking = "checking your browser" in content_lower or "verify you are human" in content_lower

    return has_challenge_form or has_checking


async def wait_for_challenge_resolve(page, timeout_seconds: int = 30) -> bool:
    """
    Wait for Cloudflare's managed JS challenge to resolve naturally.

    Args:
        page: Playwright page object
        timeout_seconds: Max seconds to wait for auto-resolution

    Returns:
        True if the challenge resolved, False if still on challenge page
    """
    logger.info(f"[CAPTCHA] Waiting up to {timeout_seconds}s for challenge to resolve...")

    start = time.time()
    check_interval = 2

    while time.time() - start < timeout_seconds:
        try:
            title = await page.title()
            content = (await page.content())[:3000]

            if not _is_challenge_page(title, content):
                elapsed = time.time() - start
                logger.info(f"[CAPTCHA] ✅ Challenge resolved after {elapsed:.1f}s")
                return True

        except Exception as e:
            logger.debug(f"[CAPTCHA] Check error (normal during navigation): {e}")

        await page.wait_for_timeout(int(check_interval * 1000))

    logger.warning(f"[CAPTCHA] Challenge did NOT resolve within {timeout_seconds}s")
    return False


async def click_turnstile_checkbox(page) -> bool:
    """
    Find the Cloudflare Turnstile iframe and click its checkbox
    using bounding-box coordinates (most reliable method).

    Returns:
        True if a click was performed on the iframe
    """
    try:
        # Find the Turnstile iframe
        iframe = page.locator('iframe[src*="challenges.cloudflare.com"]').first

        # Wait for it to appear
        try:
            await iframe.wait_for(state="visible", timeout=5000)
        except Exception:
            logger.debug("[CAPTCHA] Turnstile iframe not visible")
            return False

        # Get its bounding box
        box = await iframe.bounding_box()
        if not box:
            logger.debug("[CAPTCHA] Could not get iframe bounding box")
            return False

        logger.info(f"[CAPTCHA] Turnstile iframe found at ({box['x']:.0f}, {box['y']:.0f}), "
                     f"size {box['width']:.0f}x{box['height']:.0f}")

        # The checkbox is typically in the left portion of the widget
        # Click at approximately 30px from left, center vertically
        click_x = box['x'] + 28
        click_y = box['y'] + box['height'] / 2

        # Human-like: move to the area first, pause, then click
        await page.mouse.move(click_x + 50, click_y - 20)
        await page.wait_for_timeout(300)
        await page.mouse.move(click_x + 10, click_y + 5)
        await page.wait_for_timeout(200)
        await page.mouse.click(click_x, click_y)
        logger.info(f"[CAPTCHA] Clicked Turnstile checkbox at ({click_x:.0f}, {click_y:.0f})")

        return True

    except Exception as e:
        logger.warning(f"[CAPTCHA] Failed to click Turnstile checkbox: {e}")
        return False


async def detect_sitekey(page) -> str | None:
    """
    Auto-detect the Cloudflare Turnstile site key from the page.
    Checks: data-sitekey attribute, iframe src URL parameters, script tags.
    """
    try:
        sitekey = await page.evaluate("""
            () => {
                // Method 1: data-sitekey attribute on any element
                const el = document.querySelector('[data-sitekey]');
                if (el) return el.getAttribute('data-sitekey');

                // Method 2: Extract from iframe src URL
                const iframes = document.querySelectorAll(
                    'iframe[src*="challenges.cloudflare.com"]'
                );
                for (const iframe of iframes) {
                    const src = iframe.getAttribute('src') || '';
                    // Look for k= parameter
                    const kMatch = src.match(/[?&]k=([^&]+)/);
                    if (kMatch) return kMatch[1];
                    // Look for sitekey= parameter
                    const skMatch = src.match(/sitekey=([^&]+)/);
                    if (skMatch) return skMatch[1];
                }

                // Method 3: Search inline scripts for Turnstile render calls
                const scripts = document.querySelectorAll('script');
                for (const script of scripts) {
                    const text = script.textContent || '';
                    // Match patterns like turnstile.render({sitekey: '0x...'})
                    const m = text.match(/sitekey['":=\\s]+['"]?(0x[a-fA-F0-9]+)['"]?/);
                    if (m) return m[1];
                }

                return null;
            }
        """)
        if sitekey:
            logger.info(f"[CAPTCHA] Auto-detected Turnstile site key: {sitekey[:20]}...")
        else:
            logger.info("[CAPTCHA] No Turnstile site key found on page")
        return sitekey
    except Exception as e:
        logger.warning(f"[CAPTCHA] Failed to detect site key: {e}")
        return None


async def solve_with_capsolver_turnstile(website_url: str, site_key: str) -> str | None:
    """
    Solve a Cloudflare Turnstile challenge using CapSolver (proxyless).

    Args:
        website_url: The URL of the page with the Turnstile challenge.
        site_key: The Turnstile site key (data-sitekey value).

    Returns:
        The solved token string, or None if solving fails.
    """
    logger.info(f"[CAPTCHA] Requesting Turnstile solve via CapSolver...")
    logger.info(f"[CAPTCHA] URL: {website_url}")
    logger.info(f"[CAPTCHA] Site key: {site_key}")

    for attempt in range(1, 4):
        try:
            solution = capsolver.solve({
                "type": "AntiTurnstileTaskProxyLess",
                "websiteURL": website_url,
                "websiteKey": site_key,
            })

            token = solution.get("token")
            if token:
                logger.info(f"[CAPTCHA] ✅ Turnstile solved via CapSolver on attempt {attempt}")
                logger.info(f"[CAPTCHA] Token: {token[:50]}...")
                return token
            else:
                logger.warning(f"[CAPTCHA] Attempt {attempt}: Solution returned but no token: {solution}")

        except Exception as e:
            logger.error(f"[CAPTCHA] CapSolver attempt {attempt} failed: {e}")
            if attempt < 3:
                wait = attempt * 5
                logger.info(f"[CAPTCHA] Retrying in {wait}s...")
                await asyncio.sleep(wait)

    logger.error("[CAPTCHA] ❌ All CapSolver Turnstile attempts exhausted.")
    return None


async def inject_captcha_token(page, token: str) -> bool:
    """
    Inject the solved Turnstile token into the page and trigger callbacks.

    Args:
        page: Playwright page object.
        token: The solved CAPTCHA token from CapSolver.

    Returns:
        True if injection succeeded, False otherwise.
    """
    try:
        injected = await page.evaluate("""
            (token) => {
                let success = false;

                // Inject into cf-turnstile-response field
                const responseFields = document.querySelectorAll(
                    'input[name="cf-turnstile-response"], ' +
                    'textarea[name="cf-turnstile-response"]'
                );
                responseFields.forEach(f => { f.value = token; success = true; });

                // Also try g-recaptcha-response (some sites alias it)
                const gFields = document.querySelectorAll(
                    'textarea[name="g-recaptcha-response"]'
                );
                gFields.forEach(f => { f.value = token; success = true; });

                // Try triggering Turnstile callbacks
                try {
                    if (window.turnstile && window.turnstile._widgets) {
                        for (const [id, widget] of Object.entries(window.turnstile._widgets)) {
                            if (widget.callback) widget.callback(token);
                        }
                    }
                } catch(e) {}

                // Try the global callback
                try {
                    if (typeof window.__turnstileCallback === 'function') {
                        window.__turnstileCallback(token);
                    }
                } catch(e) {}

                // Try submitting the challenge form
                try {
                    const form = document.querySelector('#challenge-form, form[action*="challenge"]');
                    if (form) {
                        // Set the token in any hidden inputs
                        const hiddenInputs = form.querySelectorAll('input[type="hidden"]');
                        hiddenInputs.forEach(input => {
                            if (input.name.includes('response') || input.name.includes('token')) {
                                input.value = token;
                                success = true;
                            }
                        });
                    }
                } catch(e) {}

                return success;
            }
        """, token)

        if injected:
            logger.info("[CAPTCHA] ✅ Token injected into page successfully")
        else:
            logger.warning("[CAPTCHA] ⚠️ No response fields found, trying form submit...")

        return True  # Always return True to proceed with form submission

    except Exception as e:
        logger.error(f"[CAPTCHA] Failed to inject token: {e}")
        return False


async def submit_challenge_form(page) -> bool:
    """Try to submit the Cloudflare challenge form after token injection."""
    try:
        # Method 1: Submit the challenge form directly
        submitted = await page.evaluate("""
            () => {
                const form = document.querySelector('#challenge-form, form[action*="challenge"]');
                if (form) {
                    form.submit();
                    return true;
                }
                return false;
            }
        """)
        if submitted:
            logger.info("[CAPTCHA] Submitted challenge form")
            return True

        # Method 2: Click any verify/submit button
        verify_btn = page.locator(
            'button:has-text("Verify"), '
            'input[type="submit"], '
            'button[type="submit"]'
        ).first
        if await verify_btn.is_visible(timeout=2000):
            await verify_btn.click()
            logger.info("[CAPTCHA] Clicked verify/submit button")
            return True

    except Exception:
        pass

    return False


async def handle_cloudflare_challenge(page, url: str, site_key: str = None) -> bool:
    """
    Complete end-to-end Cloudflare challenge handler.

    Strategy (in order):
    1. Wait briefly for JS challenge to auto-resolve (stealth browser)
    2. Click the Turnstile checkbox via bounding-box (most common case)
    3. If sitekey found, solve via CapSolver Turnstile API + inject token
    4. Reload and retry with longer timeouts

    Args:
        page: Playwright page object.
        url: The current page URL.
        site_key: Optional pre-known site key. Auto-detected if None.

    Returns:
        True if challenge was handled, False otherwise.
    """
    # ── Strategy 1: Wait for auto-resolve (10s) ─────────────
    # Sometimes the stealth browser passes the JS check on its own
    resolved = await wait_for_challenge_resolve(page, timeout_seconds=10)
    if resolved:
        return True

    # ── Strategy 2: Click the Turnstile checkbox ─────────────
    # This is the most common scenario — a visible checkbox in an iframe
    logger.info("[CAPTCHA] Attempting to click Turnstile checkbox...")

    for click_attempt in range(3):
        clicked = await click_turnstile_checkbox(page)
        if clicked:
            # Wait for the verification to process after clicking
            logger.info(f"[CAPTCHA] Waiting for verification after click (attempt {click_attempt + 1})...")
            resolved = await wait_for_challenge_resolve(page, timeout_seconds=15)
            if resolved:
                return True
            logger.info("[CAPTCHA] Click didn't resolve, trying again...")
            await page.wait_for_timeout(2000)
        else:
            # No iframe found, skip further click attempts
            break

    # ── Strategy 3: Solve via CapSolver API ──────────────────
    # Detect the sitekey and use CapSolver to get a token
    if not site_key:
        site_key = await detect_sitekey(page)

    if site_key:
        logger.info("[CAPTCHA] Using CapSolver API to solve Turnstile...")
        token = await solve_with_capsolver_turnstile(url, site_key)
        if token:
            await inject_captcha_token(page, token)
            await page.wait_for_timeout(1000)
            await submit_challenge_form(page)
            await page.wait_for_timeout(5000)

            # Check if challenge is gone
            resolved = await wait_for_challenge_resolve(page, timeout_seconds=10)
            if resolved:
                return True
            logger.warning("[CAPTCHA] CapSolver token injection didn't resolve challenge")

    # ── Strategy 4: Human-like interaction + reload ──────────
    logger.info("[CAPTCHA] Trying page reload with human-like interaction...")
    try:
        # Simulate human mouse movements
        await page.mouse.move(300, 200)
        await page.wait_for_timeout(500)
        await page.mouse.move(600, 400)
        await page.wait_for_timeout(300)
        await page.mouse.move(450, 350)
        await page.wait_for_timeout(500)

        await page.reload(wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(5000)

        # Try auto-resolve after reload
        resolved = await wait_for_challenge_resolve(page, timeout_seconds=10)
        if resolved:
            return True

        # Try clicking again after reload
        clicked = await click_turnstile_checkbox(page)
        if clicked:
            resolved = await wait_for_challenge_resolve(page, timeout_seconds=15)
            if resolved:
                return True

    except Exception as e:
        logger.warning(f"[CAPTCHA] Reload attempt failed: {e}")

    logger.error("[CAPTCHA] ❌ All challenge bypass strategies failed")
    logger.error("[CAPTCHA] Consider rotating VPN for a fresh IP address")
    return False
