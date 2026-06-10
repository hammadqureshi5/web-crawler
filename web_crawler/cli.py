# ============================================================
# cli.py — Command-line entry point & run orchestration
# ============================================================
"""Parse CLI args, build Settings, gate on the VPN, launch Chrome over CDP,
process the selected rows (auto-resuming by default), and export results.xlsx.

Usage:
    python -m web_crawler [options]      # zero-install
    tps-scraper [options]                # after `pip install .`

See README.md for the full flag reference and examples.
"""

import argparse
import asyncio
import logging
import os
import random
import sys

from playwright.async_api import async_playwright

from web_crawler import chrome, vpn
from web_crawler.browser_search import is_blocked, log_public_ip, search_property
from web_crawler.config import load_settings
from web_crawler.records import (
    STATUS_FAILED, STATUS_LOW_CONFIDENCE, STATUS_NOT_FOUND, STATUS_SUCCESS,
    display_record, make_status_record,
)
from web_crawler.storage import (
    export_xlsx, load_completed_rows, read_input_csv, save_single_result,
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
    p.add_argument("--proxy", help="Proxy as host:port (Chrome --proxy-server; no inline creds)")

    # VPN
    p.add_argument("--set-baseline", action="store_true",
                   help="Record your real (no-VPN) public IP as the VPN baseline, then exit")
    p.add_argument("--require-vpn", action="store_true",
                   help="Abort the run unless the VPN is verified active")
    p.add_argument("--skip-vpn-check", action="store_true",
                   help="Do not prompt for / verify the VPN")

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

        await log_public_ip(page, settings.proxy_server)

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
            try:
                for attempt in range(1, settings.max_retries + 1):
                    logger.info(f"[ROW {idx}] Attempt {attempt}/{settings.max_retries}")
                    data = await search_property(page, target_name, address, city, state, settings)

                    if data == "CHALLENGE_FAILED":
                        logger.warning(f"[ROW {idx}] Challenge failed, retrying after backoff...")
                        await asyncio.sleep(10)
                    elif data == "NO_RESULTS":
                        logger.info(f"[ROW {idx}] No results on the site — recording NOT_FOUND")
                        no_results = True
                        break
                    elif data and isinstance(data, dict):
                        data["Input Row #"] = csv_row_num
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
                    page = await context.new_page()

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
    logger.info("\n" + "=" * 60)
    logger.info("SCRAPING COMPLETE")
    logger.info(f"  Total processed:  {len(rows)}")
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
    """Export results.xlsx next to results.csv, reporting a locked file cleanly."""
    xlsx_path = settings.output_csv.replace(".csv", ".xlsx")
    try:
        export_xlsx(settings.output_csv, xlsx_path)
    except PermissionError:
        logger.error(f"[XLSX] Could not write {xlsx_path} — it is open in Excel. "
                     "Close it and re-run with --export-xlsx.")
    except Exception as e:
        logger.error(f"[XLSX] Export failed: {e}")


def main(argv=None):
    """Console entry point."""
    args = parse_args(argv)
    settings = load_settings(args)
    _setup_logging(settings.log_file)

    # --export-xlsx: regenerate the workbook from the CSV and exit.
    if args.export_xlsx:
        _export(settings)
        return

    # --set-baseline: record the real IP and exit.
    if args.set_baseline:
        vpn.set_baseline_interactive(settings)
        return

    if settings.proxy_server:
        logger.info(f"[INIT] IP rotation via proxy: {settings.proxy_server}")
    else:
        logger.info("[INIT] No proxy configured — running on your direct/VPN IP")

    # VPN gate before doing anything heavy.
    if not vpn.ensure_vpn(settings):
        logger.error("[INIT] VPN check failed — aborting. "
                     "Use --skip-vpn-check to bypass, or --set-baseline first.")
        return

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
