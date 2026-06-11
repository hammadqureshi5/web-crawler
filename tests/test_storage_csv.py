"""Tests for input CSV reading, resume loading, and results CSV writing."""

import csv

import pytest

from web_crawler import storage
from web_crawler.records import OUTPUT_FIELDNAMES, STATUS_FAILED, STATUS_SUCCESS
from web_crawler.storage import (
    _find_column, load_completed_rows, read_input_csv, save_single_result,
)


# ── _find_column ────────────────────────────────────────────
def test_find_column_prefers_property_over_mailing():
    header = ["Mailing Address", "Property Address"]
    assert _find_column(header, "addres", prefer="property") == 1


def test_find_column_avoid_drops_agent_name():
    header = ["Agent Name", "Owner Name"]
    # 'agent' is avoided, so the non-agent name column wins.
    assert _find_column(header, "name", avoid="agent") == 1


def test_find_column_avoid_empties_pool_uses_default():
    header = ["Agent Name"]
    assert _find_column(header, "name", avoid="agent", default=0) == 0


def test_find_column_default_when_no_match():
    assert _find_column(["foo", "bar"], "zzz", default=3) == 3


# ── read_input_csv ──────────────────────────────────────────
def test_read_input_csv_positional_with_blank_dup_headers(tmp_path):
    p = tmp_path / "input.csv"
    # Blank target-name header + duplicate 'Address' the way real files look.
    p.write_text(
        "Name,Property Address,Property City,Property State\n"
        "John Adams,2612 Taylor St,Commerce,TX\n"
        "\n"  # blank line should be skipped
        "Betty Adams,2628 Sterling Hart Dr,Commerce,TX\n",
        encoding="utf-8",
    )
    rows = read_input_csv(str(p))
    assert len(rows) == 2
    assert rows[0]["Input Row #"] == 2  # 1-based, header excluded
    assert rows[0]["Target Name"] == "John Adams"
    assert rows[0]["Property Address"] == "2612 Taylor St"
    assert rows[1]["Input Row #"] == 4  # blank line consumed row 3's number
    assert rows[1]["Property City"] == "Commerce"


def test_read_input_csv_empty_file(tmp_path):
    p = tmp_path / "empty.csv"
    p.write_text("", encoding="utf-8")
    assert read_input_csv(str(p)) == []


# ── load_completed_rows ─────────────────────────────────────
def test_load_completed_rows_new_format(tmp_path):
    p = tmp_path / "results.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_FIELDNAMES, extrasaction="ignore")
        w.writeheader()
        w.writerow({"Input Row #": 2, "Status": STATUS_SUCCESS})
        w.writerow({"Input Row #": 5, "Status": STATUS_FAILED})
    completed = load_completed_rows(str(p))
    assert completed == {2: STATUS_SUCCESS, 5: STATUS_FAILED}


def test_load_completed_rows_missing_status_defaults_success(tmp_path):
    p = tmp_path / "results.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_FIELDNAMES, extrasaction="ignore")
        w.writeheader()
        w.writerow({"Input Row #": 9})  # no Status cell
    assert load_completed_rows(str(p)) == {9: STATUS_SUCCESS}


def test_load_completed_rows_old_format_returns_empty(tmp_path):
    p = tmp_path / "old.csv"
    p.write_text("Property Address,Phone Numbers\n2612 Taylor St,(903) 886-6607\n",
                 encoding="utf-8")
    # No 'Input Row #' column -> cannot resume -> empty dict.
    assert load_completed_rows(str(p)) == {}


def test_load_completed_rows_missing_file(tmp_path):
    assert load_completed_rows(str(tmp_path / "nope.csv")) == {}


# ── save_single_result ──────────────────────────────────────
def test_save_single_result_roundtrip(tmp_path):
    p = tmp_path / "results.csv"
    save_single_result({"Input Row #": 2, "Agent Name": "John Adams",
                        "Status": STATUS_SUCCESS}, str(p))
    save_single_result({"Input Row #": 3, "Agent Name": "Betty Adams",
                        "Status": STATUS_SUCCESS}, str(p))
    with open(p, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert [r["Input Row #"] for r in rows] == ["2", "3"]
    assert rows[0]["Agent Name"] == "John Adams"
    # Header written exactly once.
    assert p.read_text(encoding="utf-8").count("Input Row #") == 1


def test_save_single_result_upsert_replaces_placeholder(tmp_path):
    """A FAILED placeholder is overwritten when the same row later succeeds —
    one row per Input Row #, real data winning over the placeholder."""
    p = tmp_path / "results.csv"
    save_single_result({"Input Row #": 4, "Status": STATUS_FAILED}, str(p))
    save_single_result({"Input Row #": 4, "Agent Name": "John Adams",
                        "Status": STATUS_SUCCESS}, str(p))
    with open(p, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert [r["Input Row #"] for r in rows] == ["4"]  # not duplicated
    assert rows[0]["Status"] == STATUS_SUCCESS
    assert rows[0]["Agent Name"] == "John Adams"


def test_save_single_result_upsert_keeps_real_over_later_placeholder(tmp_path):
    """A later FAILED placeholder must NOT clobber an existing real result."""
    p = tmp_path / "results.csv"
    save_single_result({"Input Row #": 7, "Agent Name": "Jane", "Status": STATUS_SUCCESS}, str(p))
    save_single_result({"Input Row #": 7, "Status": STATUS_FAILED}, str(p))
    with open(p, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert [r["Input Row #"] for r in rows] == ["7"]
    assert rows[0]["Status"] == STATUS_SUCCESS
    assert rows[0]["Agent Name"] == "Jane"


def test_save_single_result_permission_error_falls_back(tmp_path, monkeypatch):
    target = tmp_path / "results.csv"
    # Seed a valid file so the upsert path reads, then fails on the atomic
    # replace (the realistic Excel-lock failure mode).
    save_single_result({"Input Row #": 1, "Agent Name": "seed",
                        "Status": STATUS_SUCCESS}, str(target))

    calls = {"n": 0}

    def fake_replace(src, dst):
        calls["n"] += 1
        raise PermissionError("locked in Excel")

    monkeypatch.setattr(storage.os, "replace", fake_replace)
    save_single_result({"Input Row #": 2, "Agent Name": "X",
                        "Status": STATUS_SUCCESS}, str(target))
    assert calls["n"] == 1
    # A timestamped fallback file was created instead.
    fallbacks = list(tmp_path.glob("results_*.csv"))
    assert len(fallbacks) == 1
