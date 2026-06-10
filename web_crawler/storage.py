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
def _fallback_path(output_path: str) -> str:
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return output_path.replace(".csv", f"_{timestamp}.csv")


def save_single_result(data: dict, output_path: str):
    """Append a single result row to CSV immediately after extraction.
    Creates the file with headers if it doesn't exist yet. On PermissionError
    (file open in Excel) falls back to a timestamped copy so data isn't lost."""
    file_exists = os.path.exists(output_path) and os.path.getsize(output_path) > 0
    try:
        with open(output_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDNAMES, extrasaction="ignore")
            if not file_exists:
                writer.writeheader()
            writer.writerow(data)
        logger.info(f"[OUTPUT] Saved row {data.get('Input Row #', '?')} to {output_path}")
    except PermissionError:
        logger.error(f"[ERROR] COULD NOT SAVE TO {output_path} — file is open in another program")
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


def save_results(results: list, output_path: str):
    """Save a list of results to CSV (append). Mostly used for batch flushes;
    the live run uses save_single_result for crash safety."""
    file_exists = os.path.exists(output_path) and os.path.getsize(output_path) > 0
    try:
        with open(output_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDNAMES, extrasaction="ignore")
            if not file_exists:
                writer.writeheader()
            writer.writerows(results)
        logger.info(f"[OUTPUT] Saved {len(results)} record(s) to {output_path}")
    except PermissionError:
        logger.error(f"[ERROR] COULD NOT SAVE TO {output_path} — file is open in another program")
        fallback = _fallback_path(output_path)
        try:
            with open(fallback, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDNAMES, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(results)
            logger.info(f"[OUTPUT] Backup saved to: {fallback}")
        except Exception as e:
            logger.error(f"[ERROR] Fallback save failed: {e}")


# ── xlsx export ─────────────────────────────────────────────
def export_xlsx(csv_path: str, xlsx_path: str) -> bool:
    """Export results.csv to a formatted results.xlsx.

    The CSV remains the crash-safe source of truth; the xlsx is a derived view
    (bold + frozen header, reasonable column widths). Returns True on success,
    False if there was nothing to export. Raises on a locked xlsx so the caller
    can report it clearly."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    if not os.path.exists(csv_path) or os.path.getsize(csv_path) == 0:
        logger.warning(f"[XLSX] No data to export — {csv_path} is missing or empty.")
        return False

    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if not rows:
        logger.warning(f"[XLSX] No rows found in {csv_path}.")
        return False

    wb = Workbook()
    ws = wb.active
    ws.title = "Results"

    for row in rows:
        ws.append(row)

    # Style the header row and freeze it.
    bold = Font(bold=True)
    for cell in ws[1]:
        cell.font = bold
    ws.freeze_panes = "A2"

    # Width each column to the longest value (capped to keep it sane).
    col_count = max(len(r) for r in rows)
    for col in range(1, col_count + 1):
        longest = max(
            (len(str(r[col - 1])) for r in rows if len(r) >= col),
            default=10,
        )
        ws.column_dimensions[get_column_letter(col)].width = min(max(longest + 2, 10), 60)

    wb.save(xlsx_path)
    logger.info(f"[XLSX] Exported {len(rows) - 1} data row(s) to {xlsx_path}")
    return True
