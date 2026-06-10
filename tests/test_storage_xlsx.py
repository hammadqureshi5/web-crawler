"""Tests for the xlsx export."""

import csv

import pytest

from web_crawler.records import OUTPUT_FIELDNAMES, STATUS_SUCCESS
from web_crawler.storage import export_xlsx

openpyxl = pytest.importorskip("openpyxl")


def _write_csv(path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_FIELDNAMES, extrasaction="ignore")
        w.writeheader()
        w.writerow({"Input Row #": 2, "Agent Name": "John Adams",
                    "Phone Numbers": "(903) 886-6607", "Status": STATUS_SUCCESS})
        w.writerow({"Input Row #": 3, "Agent Name": "Betty Adams",
                    "Status": STATUS_SUCCESS})


def test_export_xlsx_matches_csv(tmp_path):
    csv_path = tmp_path / "results.csv"
    xlsx_path = tmp_path / "results.xlsx"
    _write_csv(csv_path)

    assert export_xlsx(str(csv_path), str(xlsx_path)) is True
    assert xlsx_path.exists()

    wb = openpyxl.load_workbook(xlsx_path)
    ws = wb.active
    assert ws.title == "Results"
    # Header row matches the canonical fieldnames.
    header = [c.value for c in ws[1]]
    assert header == OUTPUT_FIELDNAMES
    # Two data rows present.
    assert ws.max_row == 3
    # Header is bold and frozen.
    assert ws["A1"].font.bold is True
    assert ws.freeze_panes == "A2"


def test_export_xlsx_no_data_returns_false(tmp_path):
    csv_path = tmp_path / "missing.csv"
    xlsx_path = tmp_path / "out.xlsx"
    assert export_xlsx(str(csv_path), str(xlsx_path)) is False
    assert not xlsx_path.exists()


def test_export_xlsx_empty_file_returns_false(tmp_path):
    csv_path = tmp_path / "empty.csv"
    csv_path.write_text("", encoding="utf-8")
    assert export_xlsx(str(csv_path), str(tmp_path / "out.xlsx")) is False
