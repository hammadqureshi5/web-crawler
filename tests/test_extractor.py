"""Tests for JSON-LD / HTML profile extraction."""

import json

import pytest

from tests.conftest import FakePage
from web_crawler.extractor import _find_person, _parse_person, extract_from_json_ld


def test_find_person_top_level():
    data = {"@type": "Person", "name": "John Adams"}
    assert _find_person(data) == data


def test_find_person_in_main_entity():
    inner = {"@type": "Person", "name": "John"}
    data = {"@type": "WebPage", "mainEntity": inner}
    assert _find_person(data) == inner


def test_find_person_in_list():
    inner = {"@type": "Person", "name": "John"}
    data = [{"@type": "WebSite"}, inner]
    assert _find_person(data) == inner


def test_find_person_none():
    assert _find_person({"@type": "Organization"}) is None
    assert _find_person([{"@type": "Thing"}]) is None


def test_parse_person_string_fields():
    person = {
        "@type": "Person",
        "name": "John M Adams",
        "telephone": "(903) 886-6607",
        "email": "jadams@icqmail.com",
        "address": {"streetAddress": "2612 Taylor St", "addressLocality": "Commerce",
                    "addressRegion": "TX", "postalCode": "75428"},
    }
    out = _parse_person(person)
    assert out["Agent Name"] == "John M Adams"
    assert out["Phone Numbers"] == "(903) 886-6607"
    assert out["Emails"] == "jadams@icqmail.com"
    assert out["Mailing Address"] == "2612 Taylor St"
    assert out["Mailing City"] == "Commerce"
    assert out["Mailing State"] == "TX"
    assert out["Mailing Zip"] == "75428"


def test_parse_person_list_fields_and_site_email_filtered():
    person = {
        "@type": "Person",
        "givenName": "Betty", "familyName": "Adams",
        "telephone": ["(903) 886-3416", "(972) 886-3416"],
        "email": ["blink@hotmail.com", "support@truepeoplesearch.com"],
        "address": [{"streetAddress": "2628 Sterling Hart Dr"}],
    }
    out = _parse_person(person)
    assert out["Agent Name"] == "Betty Adams"
    assert out["Phone Numbers"] == "(903) 886-3416 | (972) 886-3416"
    # Site email dropped.
    assert out["Emails"] == "blink@hotmail.com"


def test_parse_person_contactpoint_phone():
    person = {
        "@type": "Person", "name": "X",
        "telephone": ["111"],
        "contactPoint": [{"telephone": "222"}],
    }
    out = _parse_person(person)
    assert out["Phone Numbers"] == "111 | 222"


@pytest.mark.asyncio
async def test_extract_from_json_ld_via_fake_page():
    block = json.dumps({"@type": "Person", "name": "John Adams",
                        "telephone": "(903) 886-6607"})
    page = FakePage(json_ld=[block])
    out = await extract_from_json_ld(page)
    assert out["Agent Name"] == "John Adams"


@pytest.mark.asyncio
async def test_extract_from_json_ld_no_blocks_returns_none():
    page = FakePage(json_ld=[])
    assert await extract_from_json_ld(page) is None


@pytest.mark.asyncio
async def test_extract_from_json_ld_bad_json_skipped():
    page = FakePage(json_ld=["{not valid json"])
    assert await extract_from_json_ld(page) is None
