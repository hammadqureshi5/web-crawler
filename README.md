# TruePeopleSearch Address Scraper

Looks up property addresses on **truepeoplesearch.com** and extracts the owner's
contact info (name, mailing address, phone numbers, emails) into
`results.csv` **and** `results.xlsx`.

Windows-only by design: it drives your own installed Google Chrome (with its
extensions, including **NopeCHA** for CAPTCHAs) over the DevTools protocol.

---

## Quick start

```powershell
# 1. Install Python deps
pip install -r requirements.txt        # or: pip install .
playwright install chromium

# 2. Put your addresses in input.csv (see "Input format" below)

# 3. Record your real IP once (with the VPN OFF) so the VPN check works later
python -m web_crawler --set-baseline

# 4. Run it (turn your VPN ON when prompted)
python -m web_crawler --input input.csv
```

After `pip install .` you can also run it as a command: `tps-scraper --input input.csv`.

---

## Requirements on the machine that runs it

- **Windows** with **Google Chrome** installed (auto-detected; override with `--chrome-path`).
- The Chrome **profile you scrape with must already have the NopeCHA extension
  installed and enabled** — that is how CAPTCHAs get solved. This cannot be
  shipped in code; install it once in Chrome on the target PC.
- **Python 3.10+**.
- A **VPN** (recommended) — the scraper prompts you to enable it and verifies it
  is active before running.

---

## Input format

A CSV with a header row. Column names are matched flexibly (case-insensitive,
"property" columns preferred over "mailing"); a typical file looks like:

| Name        | Property Address      | Property City | Property State |
|-------------|-----------------------|---------------|----------------|
| John Adams  | 2612 Taylor St        | Commerce      | TX             |

Blank and duplicated headers are tolerated. Each output row records its 1-based
input row number so it lines up with what you see in Excel.

---

## Output

- **`results.csv`** — written one row at a time, immediately, so a crash or stop
  never loses completed work. This is the source of truth and what resume reads.
- **`results.xlsx`** — a formatted copy generated at the end of each run (and via
  `--export-xlsx`).

Both contain personal data and are git-ignored. If `results.csv` is open in Excel
when the scraper tries to write, it falls back to a timestamped copy.

---

## Auto-resume

Resume is **on by default**. Re-running the same command skips any input rows
already present in `results.csv` (no prompt), so you can stop with `Ctrl+C` and
just run it again to continue.

- `--no-resume` — re-scrape rows even if already saved.
- `--retry-failed` — re-process rows previously recorded as `FAILED`.

> If you have an **old** `results.csv` from before this version (no `Input Row #`
> column), archive/rename it before running so resume can start clean.

---

## VPN check

The scraper verifies your VPN using a baseline-IP method:

1. `python -m web_crawler --set-baseline` (VPN **off**) records your real public IP.
2. On a normal run it prompts you to turn the VPN **on**, then confirms the live
   public IP differs from the baseline.

- `--require-vpn` — abort the run unless the VPN is verified active.
- `--skip-vpn-check` — bypass the check entirely.

---

## Common commands

```powershell
python -m web_crawler --set-baseline                      # record real IP (VPN off)
python -m web_crawler --input input.csv                   # scrape all rows (auto-resume)
python -m web_crawler --input input.csv --start 1 --end 50
python -m web_crawler --input input.csv --require-vpn      # refuse to run without VPN
python -m web_crawler --no-resume                          # re-scrape everything
python -m web_crawler --retry-failed                       # retry only FAILED rows
python -m web_crawler --export-xlsx                        # rebuild results.xlsx from CSV
python -m web_crawler --chrome-path "C:\path\chrome.exe" --profile "Profile 1"
python -m web_crawler --proxy us.gate.iproyal.com:12321    # route Chrome via a proxy
```

Run `python -m web_crawler --help` for the full flag list, and see
[`setup.md`](setup.md) for detailed setup and troubleshooting.

---

## Development

```powershell
pip install -r requirements-dev.txt
pytest
```

Diagnostic for CDP/Chrome launch problems: `python tools/test_chrome_diag.py`.
