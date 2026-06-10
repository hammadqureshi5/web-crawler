"""Tests for the pure record helpers in records.py."""

from web_crawler.records import (
    STATUS_NOT_FOUND, _is_site_email, _is_valid_record, make_status_record,
    score_name_match,
)


def test_is_site_email():
    assert _is_site_email("support@truepeoplesearch.com") is True
    assert _is_site_email("SUPPORT@TruePeopleSearch.COM") is True
    assert _is_site_email("jadams@icqmail.com") is False


def test_is_valid_record():
    assert _is_valid_record({"Agent Name": "John Adams"}) is True
    assert _is_valid_record({"Phone Numbers": "(903) 886-6607"}) is True
    assert _is_valid_record({"Agent Name": "  ", "Phone Numbers": ""}) is False
    assert _is_valid_record({}) is False


def test_score_exact_match_is_high():
    assert score_name_match("John Adams", "John Adams") == 1.0


def test_score_orders_partial_above_unrelated():
    target = "John M Adams"
    partial = score_name_match(target, "John Adams")
    unrelated = score_name_match(target, "Betty Smith")
    assert partial > unrelated
    assert 0.0 <= unrelated < partial <= 1.0


def test_score_handles_empty():
    assert score_name_match("", "John") == 0.0
    assert score_name_match("John", "") == 0.0
    assert score_name_match("", "") == 0.0


def test_score_is_case_insensitive():
    assert score_name_match("john adams", "JOHN ADAMS") == 1.0


def test_make_status_record():
    row = {
        "Input Row #": 5, "Property Address": "2612 Taylor St",
        "Property City": "Commerce", "Property State": "TX",
    }
    rec = make_status_record(row, STATUS_NOT_FOUND)
    assert rec["Input Row #"] == 5
    assert rec["Property Address"] == "2612 Taylor St"
    assert rec["Status"] == STATUS_NOT_FOUND
    assert rec["Property Zip"] == ""
