# ============================================================
# extractor.py — Profile page parsing & data extraction
# ============================================================
"""Extract a person's contact info from a profile page. Tries JSON-LD
(``script[type="application/ld+json"]`` Person objects) first, then falls back
to HTML selectors. When the site changes, JSON-LD parsing here is the first
place to look."""

import json
import logging

from web_crawler.records import _is_site_email, _is_valid_record

logger = logging.getLogger(__name__)


def _empty_result() -> dict:
    return {
        "Agent Name": "", "Mailing Address": "", "Mailing City": "",
        "Mailing State": "", "Mailing Zip": "", "Phone Numbers": "",
        "Emails": "", "Agent Address": "",
    }


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
    result = _empty_result()

    name = person.get("name", "")
    if not name:
        name = f"{person.get('givenName', '')} {person.get('familyName', '')}".strip()
    result["Agent Name"] = name

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

    phones = person.get("telephone", [])
    if isinstance(phones, str):
        phones = [phones]
    contact = person.get("contactPoint")
    for cp in (contact if isinstance(contact, list) else [contact or {}]):
        if isinstance(cp, dict) and cp.get("telephone"):
            phones.append(cp["telephone"])
    result["Phone Numbers"] = " | ".join(phones)

    emails = person.get("email", [])
    if isinstance(emails, str):
        emails = [emails]
    emails = [e for e in emails if e and not _is_site_email(e)]
    result["Emails"] = " | ".join(emails)

    logger.info(f"[EXTRACT] Parsed: {name} | {len(phones)} phones | {len(emails)} emails")
    return result


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


async def extract_from_html(page) -> dict | None:
    """Fallback: Extract data from HTML elements on the profile page."""
    try:
        result = _empty_result()

        name_selectors = ['h1', '.oh-h1', '.person-name', 'div.h2', 'span.h1', '.record-name']
        for sel in name_selectors:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=1000):
                    result["Agent Name"] = (await el.text_content()).strip()
                    break
            except Exception:
                continue

        try:
            phone_links = page.locator('a[href^="tel:"]')
            phones = []
            count = await phone_links.count()
            for i in range(min(count, 15)):
                t = (await phone_links.nth(i).text_content()).strip()
                if t:
                    phones.append(t)
            seen = set()
            result["Phone Numbers"] = " | ".join([x for x in phones if not (x in seen or seen.add(x))])
        except Exception:
            pass

        try:
            email_links = page.locator('a[href^="mailto:"]')
            emails = []
            count = await email_links.count()
            for i in range(min(count, 15)):
                t = (await email_links.nth(i).text_content()).strip()
                if t and "@" in t and not _is_site_email(t):
                    emails.append(t)
            seen = set()
            result["Emails"] = " | ".join([x for x in emails if not (x in seen or seen.add(x))])
        except Exception:
            pass

        try:
            addr_selectors = [
                '.oh-address',
                'div:has-text("Current Address") + div',
                '.address-container',
                'a[href*="/find/address/"]',
            ]
            for sel in addr_selectors:
                el = page.locator(sel).first
                if await el.is_visible(timeout=1000):
                    addr_text = (await el.text_content()).strip()
                    if addr_text and len(addr_text) > 5:
                        result["Agent Address"] = addr_text.replace('\n', ' ').strip()
                        if not result["Mailing Address"]:
                            parts = [p.strip() for p in addr_text.split(',')]
                            if len(parts) >= 3:
                                result["Mailing Address"] = parts[0]
                                result["Mailing City"] = parts[1]
                                last_part = parts[-1].split()
                                if len(last_part) >= 2:
                                    result["Mailing State"] = last_part[0]
                                    result["Mailing Zip"] = last_part[1]
                        break
        except Exception:
            pass

        if _is_valid_record(result):
            logger.info(f"[EXTRACT] HTML extraction success for: {result['Agent Name']}")
            return result
        logger.info("[EXTRACT] HTML extraction found no person (no name, no phones) — discarding")
        return None
    except Exception as e:
        logger.error(f"[EXTRACT] HTML error: {e}")
        return None


async def extract_profile_data(page) -> dict | None:
    """Main extraction entry point. Tries JSON-LD first, falls back to HTML."""
    data = await extract_from_json_ld(page)
    if data and not _is_valid_record(data):
        logger.info("[EXTRACT] JSON-LD record has no name or phones — discarding")
        data = None
    if not data:
        logger.info("[EXTRACT] JSON-LD failed, trying HTML fallback")
        data = await extract_from_html(page)
    return data
