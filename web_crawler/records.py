# ============================================================
# records.py — Output schema, statuses, and pure record helpers
# ============================================================
"""Canonical output columns, row statuses, and small pure helpers shared by
the storage layer and the scraper. Nothing here touches the network or a
browser, so every function is directly unit-testable."""

import difflib
import logging

logger = logging.getLogger(__name__)

# Canonical output column order — shared by all CSV/xlsx writers.
OUTPUT_FIELDNAMES = [
    "Input Row #",
    "Property Address", "Property City", "Property State", "Property Zip",
    "Mailing Address", "Mailing City", "Mailing State", "Mailing Zip",
    "Phone Numbers", "Emails", "Agent Name", "Agent Address",
    "Match Score", "Status",
]

# Row statuses written to the 'Status' output column.
STATUS_SUCCESS = "SUCCESS"
STATUS_LOW_CONFIDENCE = "LOW_CONFIDENCE"
STATUS_NOT_FOUND = "NOT_FOUND"
STATUS_FAILED = "FAILED"


def _is_site_email(email: str) -> bool:
    """True for the site's own contact addresses (e.g. the footer
    support@truepeoplesearch.com mailto link), which are page furniture,
    not data about the person being looked up."""
    return "truepeoplesearch.com" in email.lower()


def _is_valid_record(result: dict) -> bool:
    """A record is only worth saving if we identified a person: a name or at
    least one phone number. A record with neither (e.g. just the site's footer
    email scraped off a 'no results' page) is a false positive."""
    return bool(result.get("Agent Name", "").strip()
                or result.get("Phone Numbers", "").strip())


def score_name_match(target_name: str, candidate_name: str) -> float:
    """Blended name-similarity score in [0.0, 1.0] used to pick the best result
    card. Combines a difflib sequence ratio with a word-overlap ratio so that a
    candidate sharing all of the target's name parts scores highly even when the
    full strings differ (extra middle names, suffixes, etc.).

    Pure function — extracted from the old inline scoring so it can be tested
    and reused."""
    target = (target_name or "").lower().strip()
    candidate = (candidate_name or "").lower().strip()
    if not target or not candidate:
        return 0.0

    seq_score = difflib.SequenceMatcher(None, target, candidate).ratio()

    target_parts = target.split()
    parts_found = sum(1 for part in target_parts if part in candidate)
    part_score = parts_found / max(1, len(target_parts))

    return seq_score * 0.5 + part_score * 0.5


def make_status_record(row: dict, status: str) -> dict:
    """Build an output record carrying only the input fields plus a status,
    for rows that produced no extractable person (NOT_FOUND / FAILED). Saving
    these to results.csv gives resume a complete picture of what was attempted."""
    return {
        "Input Row #": row.get("Input Row #", ""),
        "Property Address": row.get("Property Address", ""),
        "Property City": row.get("Property City", ""),
        "Property State": row.get("Property State", ""),
        "Property Zip": "",
        "Status": status,
    }


def display_record(data: dict):
    """Print a formatted summary of the extracted data to the log."""
    logger.info("\n" + "═" * 50)
    logger.info(" MATCH FOUND")
    logger.info("═" * 50)
    logger.info(f" NAME:    {data.get('Agent Name', 'N/A')}")
    logger.info(f" PHONE:   {data.get('Phone Numbers', 'N/A')}")
    logger.info(f" EMAIL:   {data.get('Emails', 'N/A')}")
    logger.info(f" ZIP:     {data.get('Mailing Zip', 'N/A')}")

    addr = data.get("Mailing Address", "")
    city = data.get("Mailing City", "")
    state = data.get("Mailing State", "")
    zip_code = data.get("Mailing Zip", "")
    full_addr = f"{addr}, {city}, {state} {zip_code}".strip(", ")
    logger.info(f" ADDRESS: {full_addr or 'N/A'}")

    logger.info("═" * 50 + "\n")
