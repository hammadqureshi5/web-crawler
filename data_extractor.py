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
        name_selectors = [
            'h1', 
            '.oh-h1', 
            '.person-name', 
            'div.h2',
            'span.h1',
            '.record-name'
        ]
        for sel in name_selectors:
            try:
                el = page.locator(sel).first
                if await el.is_visible(timeout=1000):
                    result["Agent Name"] = (await el.text_content()).strip()
                    break
            except:
                continue

        # Phones
        try:
            phone_links = page.locator('a[href^="tel:"]')
            phones = []
            count = await phone_links.count()
            for i in range(min(count, 15)):
                t = (await phone_links.nth(i).text_content()).strip()
                if t:
                    phones.append(t)
            # Remove duplicates while preserving order
            seen = set()
            result["Phone Numbers"] = " | ".join([x for x in phones if not (x in seen or seen.add(x))])
        except Exception:
            pass

        # Emails
        try:
            email_links = page.locator('a[href^="mailto:"]')
            emails = []
            count = await email_links.count()
            for i in range(min(count, 15)):
                t = (await email_links.nth(i).text_content()).strip()
                if t and "@" in t:
                    emails.append(t)
            # Remove duplicates while preserving order
            seen = set()
            result["Emails"] = " | ".join([x for x in emails if not (x in seen or seen.add(x))])
        except Exception:
            pass

        # Mailing Address (Fallback from HTML)
        try:
            # Look for address in common containers
            addr_selectors = [
                '.oh-address',
                'div:has-text("Current Address") + div',
                '.address-container',
                'a[href*="/find/address/"]'
            ]
            for sel in addr_selectors:
                el = page.locator(sel).first
                if await el.is_visible(timeout=1000):
                    addr_text = (await el.text_content()).strip()
                    if addr_text and len(addr_text) > 5:
                        result["Agent Address"] = addr_text.replace('\n', ' ').strip()
                        # Simple parsing for Mailing Address fields if empty
                        if not result["Mailing Address"]:
                            parts = [p.strip() for p in addr_text.split(',')]
                            if len(parts) >= 3:
                                result["Mailing Address"] = parts[0]
                                result["Mailing City"] = parts[1]
                                # State and Zip are usually in the last part "TX 75428"
                                last_part = parts[-1].split()
                                if len(last_part) >= 2:
                                    result["Mailing State"] = last_part[0]
                                    result["Mailing Zip"] = last_part[1]
                        break
        except Exception:
            pass

        has_data = any(v for v in result.values() if v)
        if has_data:
            logger.info(f"[EXTRACT] HTML extraction success for: {result['Agent Name']}")
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


def display_record(data: dict):
    """Print a formatted summary of the extracted data to the log."""
    logger.info("\n" + "═" * 50)
    logger.info(" MATCH FOUND")
    logger.info("═" * 50)
    logger.info(f" NAME:    {data.get('Agent Name', 'N/A')}")
    logger.info(f" PHONE:   {data.get('Phone Numbers', 'N/A')}")
    logger.info(f" EMAIL:   {data.get('Emails', 'N/A')}")
    logger.info(f" ZIP:     {data.get('Mailing Zip', 'N/A')}")
    
    # Mail Address
    addr = data.get("Mailing Address", "")
    city = data.get("Mailing City", "")
    state = data.get("Mailing State", "")
    zip_code = data.get("Mailing Zip", "")
    full_addr = f"{addr}, {city}, {state} {zip_code}".strip(", ")
    logger.info(f" ADDRESS: {full_addr or 'N/A'}")
    
    logger.info("═" * 50 + "\n")


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
    
    try:
        with open(output_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            if not file_exists:
                writer.writeheader()
            writer.writerows(results)
        logger.info(f"[OUTPUT] Saved {len(results)} record(s) to {output_path}")
    except PermissionError:
        logger.error(f"\n{'!' * 60}")
        logger.error(f"[ERROR] COULD NOT SAVE TO {output_path}")
        logger.error("The file is currently OPEN in another program (Excel, etc.)")
        logger.error("Please CLOSE the file and run the script again to save these results.")
        logger.error(f"{'!' * 60}\n")
        
        # Fallback: Save to a timestamped file so data isn't lost
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fallback_path = output_path.replace(".csv", f"_{timestamp}.csv")
        try:
            with open(fallback_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(results)
            logger.info(f"[OUTPUT] Backup saved to: {fallback_path}")
        except Exception as e:
            logger.error(f"[ERROR] Fallback save failed: {e}")
