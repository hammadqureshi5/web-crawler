# ============================================================
# cli.py — Command-line entry point & run orchestration
# ============================================================
"""Parse CLI args, build Settings, launch Chrome over CDP, process the
selected rows (auto-resuming by default), and export results.xlsx.

Usage:
    python -m web_crawler [options]      # zero-install
    tps-scraper [options]                # after `pip install .`

See README.md for the full flag reference and examples.
"""

import argparse
import asyncio
import getpass
import logging
import os
import random
import sys
from playwright.async_api import async_playwright

from web_crawler import chrome
from web_crawler.browser_search import (
    force_page_active, is_blocked, log_public_ip, search_property,
)
from web_crawler.config import load_settings
from web_crawler.proxy import ProxyManager
from web_crawler.proxy_auth import NAV_PROXY_AUTH, enable_proxy_auth
from web_crawler.records import (
    STATUS_FAILED, STATUS_LOW_CONFIDENCE, STATUS_NOT_FOUND, STATUS_SUCCESS,
    display_record, make_status_record,
)
from web_crawler.storage import (
    dedupe_results_file, export_xlsx, load_completed_rows, read_input_csv,
    save_single_result,
)

logger = logging.getLogger(__name__)


def _setup_logging(log_file: str):
    """Configure logging to stdout + the run log file (UTF-8)."""
    # Fix Windows console encoding so emoji/box-drawing chars don't crash.
    try:
        if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
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
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )


def parse_args(argv=None):
    """Define and parse CLI flags. All are optional; sensible defaults let the
    client run with just an input file."""
    p = argparse.ArgumentParser(
        prog="web_crawler",
        description="TruePeopleSearch address scraper - see README.md.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # Input / output
    p.add_argument("--input", help="Path to the input CSV of addresses")
    p.add_argument("--output", help="Path to the results CSV (xlsx is written alongside it)")
    p.add_argument("--start", type=int, help="First input row to process (1-based)")
    p.add_argument("--end", type=int, help="Last input row to process (inclusive)")

    # Resume
    resume = p.add_mutually_exclusive_group()
    resume.add_argument("--resume", action="store_true",
                        help="Skip rows already in results.csv (this is the default)")
    resume.add_argument("--no-resume", action="store_true",
                        help="Re-scrape rows even if already in results.csv")
    p.add_argument("--retry-failed", action="store_true",
                   help="Re-process rows whose saved status is FAILED")

    # Chrome / CDP
    p.add_argument("--chrome-path", help="Path to chrome.exe (auto-detected if omitted)")
    p.add_argument("--user-data-dir", help="Chrome user-data dir (auto-detected if omitted)")
    p.add_argument("--profile", help="Chrome profile directory name (e.g. 'Profile 11')")
    p.add_argument("--cdp-port", type=int, help="Chrome remote debugging port")
    prox = p.add_mutually_exclusive_group()
    prox.add_argument("--proxy",
                      help="Rotating proxy as host:port "
                           "(default: the Webshare rotating endpoint; "
                           "Chrome --proxy-server takes no inline creds — "
                           "use --proxy-user/--proxy-pass or authorise by IP)")
    prox.add_argument("--no-proxy", action="store_true",
                      help="Disable the proxy and use your direct connection")
    p.add_argument("--proxy-user",
                   help="Proxy username — answered to the proxy over CDP during "
                        "the scrape, and used by the requests IP check")
    p.add_argument("--proxy-pass", help="Proxy password (see --proxy-user)")
    p.add_argument("--verify-proxy", action="store_true",
                   help="Sample the proxy exit IP a few times to confirm rotation, then exit")

    # Maintenance
    p.add_argument("--export-xlsx", action="store_true",
                   help="Regenerate results.xlsx from results.csv and exit")

    return p.parse_args(argv)


def _select_rows(rows, settings):
    """Apply the --start/--end range, then resume/retry filtering. Returns the
    final list of rows to process (may be empty)."""
    total = len(rows)
    start_idx = settings.start_row if settings.start_row is not None else 1
    end_idx = settings.end_row if settings.end_row is not None else total
    selected = rows[max(0, start_idx - 1):end_idx]
    logger.info(f"[INIT] Selected rows {start_idx}-{end_idx} ({len(selected)} of {total})")

    completed = load_completed_rows(settings.output_csv)  # {Input Row #: Status}
    if settings.retry_failed:
        retryable = [n for n, s in completed.items() if s == STATUS_FAILED]
        if retryable:
            logger.info(f"[RESUME] --retry-failed: {len(retryable)} FAILED row(s) will be re-processed")
        completed = {n: s for n, s in completed.items() if s != STATUS_FAILED}

    if completed and settings.resume:
        before = len(selected)
        selected = [r for r in selected if r["Input Row #"] not in completed]
        skipped = before - len(selected)
        if skipped:
            logger.info(f"[RESUME] Auto-resume: skipped {skipped} already-completed row(s); "
                        f"{len(selected)} remaining")
    elif completed and not settings.resume:
        logger.info("[RESUME] --no-resume: re-scraping all selected rows (duplicates may append)")

    return selected


def prompt_for_proxy_credentials(prompt=input, getpass_fn=None,
                                 isatty=None) -> "tuple[str, str] | None":
    """Interactively ask for the Webshare proxy username/password.

    Returns ``(username, password)``, or ``None`` when stdin is not a terminal
    or the user enters an empty username (declined). ``prompt``/``getpass_fn``/
    ``isatty`` are injectable for tests."""
    tty = isatty if isatty is not None else sys.stdin.isatty
    if not tty():
        return None
    getpass_fn = getpass_fn or getpass.getpass
    print("\n" + "=" * 60)
    print(" The proxy requires a login (Webshare username/password).")
    print(" Enter it now, or press Enter to abort the run.")
    print("=" * 60)
    try:
        username = prompt(" Proxy username: ").strip()
        if not username:
            return None
        password = getpass_fn(" Proxy password: ")
        return username, password
    except (EOFError, KeyboardInterrupt):
        return None


async def _run(settings):
    """Async core: launch Chrome, connect over CDP, process rows."""
    try:
        rows = read_input_csv(settings.input_csv)
    except FileNotFoundError:
        logger.error(f"[INIT] Input CSV not found: {settings.input_csv}")
        logger.error("  -> Place your CSV at the path above or pass --input.")
        return
    except Exception as e:
        logger.error(f"[INIT] Error reading CSV: {e}")
        return

    if not rows:
        logger.error("[INIT] No rows found in CSV file")
        return

    logger.info(f"[INIT] CSV loaded: {len(rows)} total records")
    rows = _select_rows(rows, settings)
    if not rows:
        logger.info("[INIT] Nothing left to process — all selected rows are already done.")
        return

    chrome.launch_chrome_with_profile(settings)
    results, failed, not_found = [], [], []

    async with async_playwright() as pw:
        logger.info(f"[INIT] Connecting to Chrome via CDP on port {settings.cdp_port}...")
        browser = await pw.chromium.connect_over_cdp(f"http://127.0.0.1:{settings.cdp_port}")

        contexts = browser.contexts
        if contexts:
            context = contexts[0]
            logger.info(f"[INIT] Connected to existing context ({len(context.pages)} open tabs)")
        else:
            context = await browser.new_context()
            logger.info("[INIT] Created new browser context")

        page = await context.new_page()
        logger.info("[INIT] Opened new tab for scraping")
        for p in context.pages:
            if p != page and (p.url == "about:blank" or p.url.startswith("data:")):
                try:
                    await p.close()
                except Exception:
                    pass

        # Answer the proxy login over CDP when credentials are configured
        # (Chrome's native sign-in dialog never blocks CDP navigations).
        proxy = ProxyManager.from_settings(settings)
        auth_handler = await enable_proxy_auth(page, proxy)
        # Keep the CAPTCHA solver alive even if another window covers Chrome.
        await force_page_active(page)
        ip, ip_err = await log_public_ip(page, settings.proxy_server)

        if ip is None and proxy.enabled and ip_err == NAV_PROXY_AUTH:
            if auth_handler is not None:
                logger.error("[INIT] The proxy rejected the configured credentials "
                             "— aborting. Check --proxy-user/--proxy-pass, or run "
                             "with --no-proxy.")
                return
            creds = prompt_for_proxy_credentials()
            if creds is None:
                logger.error("[INIT] The proxy requires a login — aborting. "
                             "Re-run with --proxy-user/--proxy-pass (or set "
                             "WEB_CRAWLER_PROXY_USERNAME/PASSWORD), or use "
                             "--no-proxy.")
                return
            proxy.username, proxy.password = creds
            await enable_proxy_auth(page, proxy)
            ip, ip_err = await log_public_ip(page, settings.proxy_server)
            if ip is None:
                logger.error("[INIT] Still cannot reach the internet through the "
                             "proxy — aborting.")
                return

        stopped_early = False
        for idx, row in enumerate(rows, 1):
            csv_row_num = row["Input Row #"]
            target_name = row["Target Name"]
            address = row["Property Address"]
            city = row["Property City"]
            state = row["Property State"]

            logger.info(f"\n{'-' * 50}")
            logger.info(f"[ROW {idx}/{len(rows)}] (Input CSV Row #{csv_row_num}) "
                        f"{target_name} | {address}, {city}, {state}")
            logger.info(f"{'-' * 50}")

            success = False
            no_results = False
            fatal = False
            try:
                for attempt in range(1, settings.max_retries + 1):
                    logger.info(f"[ROW {idx}] Attempt {attempt}/{settings.max_retries}")
                    data = await search_property(page, target_name, address, city, state, settings)

                    if data == "PROXY_AUTH_FAILED":
                        logger.error(f"[ROW {idx}] Proxy authentication failed mid-run "
                                     "— aborting. Provide --proxy-user/--proxy-pass "
                                     "or run with --no-proxy, then re-run to resume.")
                        fatal = True
                        break
                    elif data == "CHALLENGE_FAILED":
                        logger.warning(f"[ROW {idx}] Challenge failed, retrying after backoff...")
                        await asyncio.sleep(10)
                    elif data == "NO_RESULTS":
                        logger.info(f"[ROW {idx}] No results on the site — recording NOT_FOUND")
                        no_results = True
                        break
                    elif data and isinstance(data, dict):
                        data["Input Row #"] = csv_row_num
                        data["Target Name"] = target_name
                        data["Property Address"] = address
                        data["Property City"] = city
                        data["Property State"] = state
                        data.setdefault("Property Zip", "")
                        display_record(data)
                        save_single_result(data, settings.output_csv)
                        results.append(data)
                        logger.info(f"[ROW {idx}] {data.get('Status', STATUS_SUCCESS)} - "
                                    f"{data.get('Agent Name', 'N/A')}")
                        success = True
                        break
                    elif await is_blocked(page):
                        logger.warning(f"[ROW {idx}] Blocked (403), retrying after backoff...")
                        await asyncio.sleep(10)
                    else:
                        logger.warning(f"[ROW {idx}] Attempt {attempt} failed, retrying...")
                        await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"[ROW {idx}] Unexpected error: {e}")
                if page.is_closed():
                    logger.warning(f"[ROW {idx}] Tab was closed — opening a fresh one")
                    try:
                        page = await context.new_page()
                        # Re-arm the new tab: the CDP sessions are page-scoped.
                        await enable_proxy_auth(page, proxy)
                        await force_page_active(page)  # re-pin focus on the new tab
                    except Exception:
                        logger.warning(f"[ROW {idx}] Browser is gone — ending run.")
                        stopped_early = True
                        break

            if fatal:
                # Do NOT record this row as FAILED — the proxy broke, not the
                # row; resume will pick it up on the next run.
                stopped_early = True
                break

            if no_results:
                not_found.append(row)
                save_single_result(make_status_record(row, STATUS_NOT_FOUND), settings.output_csv)
            elif not success:
                logger.error(f"[ROW {idx}] FAILED after {settings.max_retries} attempts — skipping")
                failed.append(row)
                save_single_result(make_status_record(row, STATUS_FAILED), settings.output_csv)

            if idx < len(rows):
                delay = random.uniform(settings.request_delay_min, settings.request_delay_max)
                logger.info(f"[DELAY] Waiting {delay:.1f}s before next search...")
                await asyncio.sleep(delay)

        # Do NOT close the browser — it's the user's personal Chrome.
        logger.info("[CLEANUP] Disconnecting from Chrome (browser stays open)")

    # Export xlsx from the crash-safe CSV.
    _export(settings)

    low_confidence = [r for r in results if r.get("Status") == STATUS_LOW_CONFIDENCE]
    processed = len(results) + len(failed) + len(not_found)
    logger.info("\n" + "=" * 60)
    logger.info("SCRAPING STOPPED EARLY" if stopped_early else "SCRAPING COMPLETE")
    logger.info(f"  Total processed:  {processed} of {len(rows)} selected")
    logger.info(f"  Successful:       {len(results)}")
    if low_confidence:
        logger.info(f"    (low confidence: {len(low_confidence)} — check 'Status' column)")
    logger.info(f"  Not found:        {len(not_found)}")
    logger.info(f"  Failed:           {len(failed)}")
    if failed:
        logger.info("    (re-run with --retry-failed to try these again)")
    logger.info(f"  Output saved to:  {settings.output_csv}")
    logger.info("=" * 60)


def _export(settings):
    """Export results.xlsx next to results.csv, reporting a locked file cleanly.
    Dedupes the CSV first so the workbook has one row per input location."""
    try:
        dedupe_results_file(settings.output_csv)
    except PermissionError:
        logger.warning("[OUTPUT] Could not dedupe results.csv (locked) — exporting as-is.")
    except Exception as e:
        logger.warning(f"[OUTPUT] Dedupe skipped: {e}")

    xlsx_path = settings.output_csv.replace(".csv", ".xlsx")
    try:
        export_xlsx(settings.output_csv, xlsx_path)
    except PermissionError:
        logger.error(f"[XLSX] Could not write {xlsx_path} — it is open in Excel. "
                     "Close it and re-run with --export-xlsx.")
    except Exception as e:
        logger.error(f"[XLSX] Export failed: {e}")


def _verify_proxy(settings):
    """Sample the proxy exit IP a few times and report whether it rotates."""
    proxy = ProxyManager.from_settings(settings)
    if not proxy.enabled:
        logger.error("[PROXY] No proxy configured. Pass --proxy p.webshare.io:9999 "
                     "(or set WEB_CRAWLER_PROXY_SERVER).")
        return
    logger.info(f"[PROXY] Checking IP rotation through {proxy.host_port} ...")
    result = proxy.verify_rotation(samples=5)
    if not result["ips"]:
        logger.error("[PROXY] Could not reach the IP check through the proxy. "
                     "Is your IP authorised in the Webshare dashboard (or your "
                     "username/password correct)?")
        return
    logger.info(f"[PROXY] Exit IPs seen: {result['ips']}")
    if result["rotating"]:
        logger.info(f"[PROXY] {result['unique']} unique IPs across "
                    f"{len(result['ips'])} samples — rotation is working.")
    else:
        logger.warning(f"[PROXY] Only 1 IP across {len(result['ips'])} samples — "
                       "sticky session or a single static IP, not rotating.")


def main(argv=None):
    """Console entry point."""
    args = parse_args(argv)
    settings = load_settings(args)
    _setup_logging(settings.log_file)

    # --export-xlsx: regenerate the workbook from the CSV and exit.
    if args.export_xlsx:
        _export(settings)
        return

    # --verify-proxy: prove the rotating proxy hands out changing IPs, then exit.
    if args.verify_proxy:
        _verify_proxy(settings)
        return

    proxy = ProxyManager.from_settings(settings)
    if proxy.enabled:
        creds_note = ("credentials configured — the proxy login is answered "
                      "automatically over CDP" if proxy.username
                      else "no credentials — the proxy must allow this "
                           "machine's IP, or pass --proxy-user/--proxy-pass")
        logger.info(f"[INIT] Automatic IP rotation via Webshare proxy: "
                    f"{proxy.host_port} ({creds_note})")
    else:
        logger.info("[INIT] No proxy configured — running on your direct IP")

    try:
        asyncio.run(_run(settings))
    except KeyboardInterrupt:
        logger.warning("\n[INIT] Interrupted by user. Progress is saved in results.csv — "
                       "re-run to auto-resume.")
    except Exception as e:
        logger.error(f"[ERROR] Fatal error: {e}")
        raise


if __name__ == "__main__":
    main()
