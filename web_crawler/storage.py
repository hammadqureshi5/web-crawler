# ============================================================
# storage.py — Input CSV reading, results CSV I/O, xlsx export
# ============================================================
"""All disk I/O for the scraper.

- Input is read with a *positional* reader (not csv.DictReader) because real
  input files have blank/duplicated headers that DictReader silently merges.
- Each successful row is appended to results.csv immediately so a crash/stop
  loses nothing — this same file is what auto-resume reads.
- results.xlsx is a derived, formatted export of results.csv (the CSV stays the
  crash-safe source of truth).
"""

import csv
import datetime
import logging
import os

from web_crawler.records import OUTPUT_FIELDNAMES, STATUS_SUCCESS

logger = logging.getLogger(__name__)


# ── Input CSV ───────────────────────────────────────────────
def _find_column(header: list, must_contain: str, prefer: str = None,
                 avoid: str = None, default: int = None):
    """Return the index of the best-matching header column.

    Matches columns whose (lowercased) name contains ``must_contain``. When
    several match, a column also containing ``prefer`` wins (e.g. prefer
    'property' over 'mailing'); columns containing ``avoid`` are dropped from
    the pool. Falls back to ``default`` if nothing matches.

    Positional parsing is used (not csv.DictReader) because the real input file
    has blank, duplicated headers — the target-name column has an empty header —
    which DictReader would silently merge and drop."""
    candidates = [i for i, c in enumerate(header) if must_contain in c.lower()]
    if avoid:
        candidates = [i for i in candidates if avoid not in header[i].lower()]
    if not candidates:
        return default
    if prefer:
        preferred = [i for i in candidates if prefer in header[i].lower()]
        if preferred:
            return preferred[0]
    return candidates[0]


def read_input_csv(path: str) -> list:
    """Read addresses from the input CSV using a positional reader.

    Each row dict includes 'Input Row #' — the 1-based row number from the CSV
    (excluding the header), so it matches the line the user sees in Excel."""
    rows = []
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if not header:
            return []

        logger.info(f"[INPUT] CSV Header: {header}")

        name_idx = _find_column(header, "name", avoid="agent", default=0)
        addr_idx = _find_column(header, "addres", prefer="property", default=1)
        city_idx = _find_column(header, "city", prefer="property", default=2)
        state_idx = _find_column(header, "state", prefer="property", default=3)

        logger.info(f"[INPUT] Column map: Name={name_idx}, Addr={addr_idx}, "
                    f"City={city_idx}, State={state_idx}")

        def cell(line, idx):
            return line[idx].strip() if idx is not None and len(line) > idx else ""

        for row_num, line in enumerate(reader, start=2):  # row 1 is the header
            if not line or not any(c.strip() for c in line):
                continue
            rows.append({
                "Input Row #": row_num,
                "Target Name": cell(line, name_idx),
                "Property Address": cell(line, addr_idx),
                "Property City": cell(line, city_idx),
                "Property State": cell(line, state_idx),
            })
    logger.info(f"[INPUT] Loaded {len(rows)} rows from {path}")
    return rows


# ── Resume support ──────────────────────────────────────────
def load_completed_rows(output_path: str) -> dict:
    """Return {'Input Row #': Status} for rows already present in the output CSV.

    Used to resume a run without re-scraping rows saved previously (the status
    lets the caller offer to re-try FAILED rows). Returns an empty dict if the
    file is missing, empty, or unreadable. Rows saved before the 'Status'
    column existed count as SUCCESS."""
    completed = {}
    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        return completed
    try:
        with open(output_path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames and "Input Row #" not in reader.fieldnames:
                logger.warning("!" * 60)
                logger.warning(f"[RESUME] {os.path.basename(output_path)} is in an OLD format "
                               "without the 'Input Row #' column.")
                logger.warning("[RESUME] Resume CANNOT skip its rows — re-runs will append duplicates.")
                logger.warning("[RESUME] Archive it (e.g. rename to results_old.csv) to start clean.")
                logger.warning("!" * 60)
                return completed
            for record in reader:
                raw = (record.get("Input Row #") or "").strip()
                if raw.isdigit():
                    status = (record.get("Status") or "").strip() or STATUS_SUCCESS
                    completed[int(raw)] = status
    except Exception as e:
        logger.warning(f"[RESUME] Could not read existing results ({e}); starting fresh")
    return completed


# ── Results CSV output ──────────────────────────────────────
# Outcome ranking: a real result must never be overwritten by a later
# placeholder, but a placeholder IS replaced when the row later succeeds
# (e.g. on --retry-failed). Unknown/blank status is treated as data (2) so a
# legacy row is never clobbered by a FAILED placeholder.
_STATUS_PRIORITY = {"SUCCESS": 3, "LOW_CONFIDENCE": 2, "NOT_FOUND": 1, "FAILED": 0}


def _priority(record: dict) -> int:
    return _STATUS_PRIORITY.get((record.get("Status") or "").strip(), 2)


def _row_key(record: dict) -> str:
    return str(record.get("Input Row #", "")).strip()


def _fallback_path(output_path: str) -> str:
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return output_path.replace(".csv", f"_{timestamp}.csv")


def _read_existing(output_path: str):
    """Return the existing results as a list of dict rows, or None if the file
    is missing/empty or in an old format without 'Input Row #' (can't merge)."""
    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        return []
    with open(output_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames and "Input Row #" not in reader.fieldnames:
            return None
        return list(reader)


def _write_all(output_path: str, records: list):
    """Atomically rewrite the whole results file (temp file + os.replace) so a
    crash mid-write can't corrupt it and the header is written exactly once."""
    tmp = output_path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    os.replace(tmp, output_path)


def _append_fallback(data: dict, output_path: str):
    """Last-resort append to a timestamped copy when the main file is locked
    (open in Excel), so a row is never lost."""
    fallback = _fallback_path(output_path)
    try:
        exists = os.path.exists(fallback) and os.path.getsize(fallback) > 0
        with open(fallback, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDNAMES, extrasaction="ignore")
            if not exists:
                writer.writeheader()
            writer.writerow(data)
        logger.info(f"[OUTPUT] Backup saved to: {fallback}")
    except Exception as e:
        logger.error(f"[ERROR] Fallback save failed: {e}")


def save_single_result(data: dict, output_path: str):
    """Upsert a single result row by 'Input Row #' so the file always holds one
    row per input location: a new row replaces an existing one of equal-or-lower
    outcome rank (a real result overwrites a FAILED/NOT_FOUND placeholder, never
    the reverse). On PermissionError (file open in Excel) falls back to a
    timestamped copy so data isn't lost."""
    try:
        existing = _read_existing(output_path)
        if existing is None:
            # Old-format file we can't safely merge — append as-is (legacy).
            with open(output_path, "a", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=OUTPUT_FIELDNAMES,
                               extrasaction="ignore").writerow(data)
            logger.info(f"[OUTPUT] Appended row {data.get('Input Row #', '?')} (old-format file)")
            return

        order, by_key = [], {}
        for rec in existing:
            k = _row_key(rec)
            if k not in by_key:
                order.append(k)
            by_key[k] = rec

        key = _row_key(data)
        if key and key in by_key:
            if _priority(data) >= _priority(by_key[key]):
                by_key[key] = data
        else:
            if key not in by_key:
                order.append(key)
            by_key[key] = data

        _write_all(output_path, [by_key[k] for k in order])
        logger.info(f"[OUTPUT] Saved row {data.get('Input Row #', '?')} to {output_path}")
    except PermissionError:
        logger.error(f"[ERROR] COULD NOT SAVE TO {output_path} — file is open in another program")
        _append_fallback(data, output_path)


def save_results(results: list, output_path: str):
    """Upsert a list of results (each by 'Input Row #'). The live run uses
    save_single_result for crash safety; this is for batch flushes."""
    for record in results:
        save_single_result(record, output_path)


def dedupe_results_file(output_path: str) -> int:
    """Collapse the results file to one row per 'Input Row #', keeping the
    highest-ranked outcome and preserving first-seen order. Returns the number
    of rows removed. No-op (returns 0) if the file is missing or old-format."""
    existing = _read_existing(output_path)
    if not existing:
        return 0
    order, by_key = [], {}
    for rec in existing:
        k = _row_key(rec)
        if k in by_key:
            if _priority(rec) >= _priority(by_key[k]):
                by_key[k] = rec
        else:
            by_key[k] = rec
            order.append(k)
    deduped = [by_key[k] for k in order]
    removed = len(existing) - len(deduped)
    if removed:
        _write_all(output_path, deduped)
        logger.info(f"[OUTPUT] Deduped {output_path}: removed {removed} duplicate row(s)")
    return removed


# ── xlsx export ─────────────────────────────────────────────
# Per-column display widths (by header name). Columns not listed fall back to
# an auto width based on their longest value.
_COL_WIDTHS = {
    "Input Row #": 10, "Target Name": 22,
    "Property Address": 26, "Property City": 16, "Property State": 9, "Property Zip": 11,
    "Mailing Address": 26, "Mailing City": 16, "Mailing State": 9, "Mailing Zip": 11,
    "Phone Numbers": 42, "Emails": 38, "Agent Name": 22, "Agent Address": 42,
    "Match Score": 12, "Status": 16,
}
# Columns whose values are long " | "-joined lists — wrap them so the row stays
# readable instead of one very wide line.
_WRAP_COLS = {"Phone Numbers", "Emails", "Agent Address", "Mailing Address"}
# Status value -> (fill RGB, font RGB) for at-a-glance scanning.
_STATUS_STYLE = {
    "SUCCESS": ("C6EFCE", "006100"),
    "LOW_CONFIDENCE": ("FFEB9C", "9C6500"),
    "NOT_FOUND": ("D9D9D9", "595959"),
    "FAILED": ("FFC7CE", "9C0006"),
}


def export_xlsx(csv_path: str, xlsx_path: str) -> bool:
    """Export results.csv to a professionally formatted results.xlsx.

    The CSV remains the crash-safe source of truth; the xlsx is a derived view:
    a styled, auto-filtered "Results" table (bold + frozen header, tuned column
    widths, wrapped long fields, colour-coded Status) plus a "Summary" sheet of
    per-status counts. Returns True on success, False if there was nothing to
    export. Raises on a locked xlsx so the caller can report it clearly."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    if not os.path.exists(csv_path) or os.path.getsize(csv_path) == 0:
        logger.warning(f"[XLSX] No data to export — {csv_path} is missing or empty.")
        return False

    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if not rows:
        logger.warning(f"[XLSX] No rows found in {csv_path}.")
        return False

    header = rows[0]
    data_rows = rows[1:]
    col_index = {name: i for i, name in enumerate(header)}

    wb = Workbook()
    ws = wb.active
    ws.title = "Results"
    for row in rows:
        ws.append(row)

    # Header: dark-blue fill, white bold, centered, frozen + auto-filtered.
    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(bold=True, color="FFFFFF")
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = center
    ws.row_dimensions[1].height = 28
    ws.freeze_panes = "A2"
    last_col = get_column_letter(len(header))
    ws.auto_filter.ref = f"A1:{last_col}{ws.max_row}"

    # Column widths + wrapping for long-list columns.
    top_wrap = Alignment(vertical="top", wrap_text=True)
    top = Alignment(vertical="top")
    for i, name in enumerate(header, start=1):
        letter = get_column_letter(i)
        if name in _COL_WIDTHS:
            ws.column_dimensions[letter].width = _COL_WIDTHS[name]
        else:
            longest = max((len(str(r[i - 1])) for r in rows if len(r) >= i), default=10)
            ws.column_dimensions[letter].width = min(max(longest + 2, 10), 60)
        wrap = name in _WRAP_COLS
        for r in range(2, ws.max_row + 1):
            ws.cell(row=r, column=i).alignment = top_wrap if wrap else top

    # Colour-code the Status cells.
    status_col = col_index.get("Status")
    counts = {}
    if status_col is not None:
        for r, drow in enumerate(data_rows, start=2):
            status = drow[status_col] if len(drow) > status_col else ""
            counts[status] = counts.get(status, 0) + 1
            style = _STATUS_STYLE.get(status)
            if style:
                fill_rgb, font_rgb = style
                cell = ws.cell(row=r, column=status_col + 1)
                cell.fill = PatternFill("solid", fgColor=fill_rgb)
                cell.font = Font(bold=True, color=font_rgb)

    # Thin borders across the table for a clean grid.
    thin = Side(style="thin", color="D0D0D0")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=len(header)):
        for cell in row:
            cell.border = border

    # Summary sheet: per-status counts + total. (Results stays the active sheet.)
    summary = wb.create_sheet("Summary")
    summary.append(["Status", "Count"])
    for cell in summary[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = center
    order = ["SUCCESS", "LOW_CONFIDENCE", "NOT_FOUND", "FAILED"]
    for status in order + [s for s in counts if s not in order]:
        if status in counts:
            summary.append([status, counts[status]])
            style = _STATUS_STYLE.get(status)
            if style:
                summary.cell(row=summary.max_row, column=1).fill = PatternFill("solid", fgColor=style[0])
                summary.cell(row=summary.max_row, column=1).font = Font(bold=True, color=style[1])
    summary.append(["TOTAL", len(data_rows)])
    summary.cell(row=summary.max_row, column=1).font = Font(bold=True)
    summary.cell(row=summary.max_row, column=2).font = Font(bold=True)
    summary.column_dimensions["A"].width = 18
    summary.column_dimensions["B"].width = 10

    wb.save(xlsx_path)
    logger.info(f"[XLSX] Exported {len(data_rows)} data row(s) to {xlsx_path}")
    return True
