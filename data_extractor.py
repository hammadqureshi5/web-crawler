# ============================================================
# data_extractor.py — Profile Page Parsing & Data Extraction
# ============================================================

import csv
import json
import logging
import os
from config import OUTPUT_CSV

logger = logging.getLogger(__name__)


async def extract_from_json_ld(page) -> dict | None:
    """Extract person data from JSON-LD structured data on a profile page."""
    try:
        json_ld_blocks = await page.evaluate("""
            () => {
                const scripts = document.querySelectorAll('script[type="application/ld+json"]');
                return Array.from(scripts).map(s => s.textContent);
            }
        """)
        if not json_ld_blocks:
            logger.warning("[EXTRACT] No JSON-LD blocks found")
            return None

        for block_text in json_ld_blocks:
            try:
                data = json.loads(block_text)
                person = _find_person(data)
                if person:
                    logger.info("[EXTRACT] Found Person JSON-LD data")
                    return _parse_person(person)
            except json.JSONDecodeError:
                continue
        return None
    except Exception as e:
        logger.error(f"[EXTRACT] JSON-LD error: {e}")
        return None


def _find_person(data):
    """Locate a Person object within JSON-LD data."""
    if isinstance(data, dict):
        if data.get("@type") == "Person":
            return data
        for key in ("mainEntity", "about"):
            if key in data and isinstance(data[key], dict):
                if data[key].get("@type") == "Person":
                    return data[key]
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and item.get("@type") == "Person":
                return item
    return None


def _parse_person(person: dict) -> dict:
    """Parse a Person JSON-LD object into our output format."""
    result = {
        "Agent Name": "", "Mailing Address": "", "Mailing City": "",
        "Mailing State": "", "Mailing Zip": "", "Phone Numbers": "",
        "Emails": "", "Agent Address": "",
    }
    # Name
    name = person.get("name", "")
    if not name:
        name = f"{person.get('givenName', '')} {person.get('familyName', '')}".strip()
    result["Agent Name"] = name

    # Addresses
    addresses = person.get("address", [])
    if isinstance(addresses, dict):
        addresses = [addresses]
    if addresses and isinstance(addresses[0], dict):
        a = addresses[0]
        result["Mailing Address"] = a.get("streetAddress", "")
        result["Mailing City"] = a.get("addressLocality", "")
        result["Mailing State"] = a.get("addressRegion", "")
        result["Mailing Zip"] = a.get("postalCode", "")
    addr_strs = []
    for a in addresses:
        if isinstance(a, dict):
            parts = [a.get("streetAddress", ""), a.get("addressLocality", ""),
                     a.get("addressRegion", ""), a.get("postalCode", "")]
            addr_strs.append(", ".join(p for p in parts if p))
    result["Agent Address"] = " | ".join(addr_strs)

    # Phones
    phones = person.get("telephone", [])
    if isinstance(phones, str):
        phones = [phones]
    for cp in (person.get("contactPoint", []) if isinstance(person.get("contactPoint"), list) else [person.get("contactPoint", {})]):
        if isinstance(cp, dict) and cp.get("telephone"):
            phones.append(cp["telephone"])
    result["Phone Numbers"] = " | ".join(phones)

    # Emails
    emails = person.get("email", [])
    if isinstance(emails, str):
        emails = [emails]
    result["Emails"] = " | ".join(emails)

    logger.info(f"[EXTRACT] Parsed: {name} | {len(phones)} phones | {len(emails)} emails")
    return result


async def extract_from_html(page) -> dict | None:
    """Fallback: Extract data from HTML elements on the profile page."""
    try:
        result = {
            "Agent Name": "", "Mailing Address": "", "Mailing City": "",
            "Mailing State": "", "Mailing Zip": "", "Phone Numbers": "",
            "Emails": "", "Agent Address": "",
        }
        # Name
        try:
            name_el = page.locator('h1').first
            if await name_el.is_visible(timeout=3000):
                result["Agent Name"] = (await name_el.text_content()).strip()
        except Exception:
            pass

        # Phones
        try:
            phone_links = page.locator('a[href^="tel:"]')
            phones = []
            for i in range(min(await phone_links.count(), 10)):
                t = (await phone_links.nth(i).text_content()).strip()
                if t:
                    phones.append(t)
            result["Phone Numbers"] = " | ".join(phones)
        except Exception:
            pass

        # Emails
        try:
            email_links = page.locator('a[href^="mailto:"]')
            emails = []
            for i in range(min(await email_links.count(), 10)):
                t = (await email_links.nth(i).text_content()).strip()
                if t and "@" in t:
                    emails.append(t)
            result["Emails"] = " | ".join(emails)
        except Exception:
            pass

        has_data = any(v for v in result.values() if v)
        if has_data:
            logger.info(f"[EXTRACT] HTML extraction: {result['Agent Name']}")
            return result
        return None
    except Exception as e:
        logger.error(f"[EXTRACT] HTML error: {e}")
        return None


async def extract_profile_data(page) -> dict | None:
    """Main extraction entry point. Tries JSON-LD first, falls back to HTML."""
    data = await extract_from_json_ld(page)
    if not data:
        logger.info("[EXTRACT] JSON-LD failed, trying HTML fallback")
        data = await extract_from_html(page)
    return data


def save_results(results: list[dict], output_path: str = None):
    """Save results to CSV. Creates file with headers or appends."""
    if not output_path:
        output_path = OUTPUT_CSV
    fieldnames = [
        "Property Address", "Property City", "Property State", "Property Zip",
        "Mailing Address", "Mailing City", "Mailing State", "Mailing Zip",
        "Phone Numbers", "Emails", "Agent Name", "Agent Address",
    ]
    file_exists = os.path.exists(output_path)
    with open(output_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        writer.writerows(results)
    logger.info(f"[OUTPUT] Saved {len(results)} record(s) to {output_path}")
