# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Playwright-based scraper that looks up property addresses on truepeoplesearch.com and extracts owner contact info (name, mailing address, phones, emails) into `results.csv` and `results.xlsx`. Windows-only by design — it drives the user's personal Chrome installation and profile (Chrome path/profile are auto-detected, overridable via CLI).

## Commands

```powershell
pip install -r requirements.txt        # runtime deps (playwright, openpyxl)
pip install -r requirements-dev.txt    # + pytest, pytest-asyncio
pip install .                          # installs the `tps-scraper` console command
playwright install chromium

python -m web_crawler --help           # CLI reference
python -m web_crawler --set-baseline   # record real (no-VPN) IP for the VPN check
python -m web_crawler --input input.csv

pytest                                 # run the unit test suite
python tools/test_chrome_diag.py       # diagnostic: can Chrome launch with CDP on 9222?
```

The run is interactive at the **VPN gate only** (prompts to enable the VPN); row
range and resume are now CLI flags, so with `--skip-vpn-check` it can run
unattended.

## Architecture

The code is a package, `web_crawler/`, run via `python -m web_crawler` (zero
install) or the `tps-scraper` entry point (after `pip install .`).

- `config.py` — a `Settings` dataclass holding every tunable. `load_settings(args)` merges **defaults → environment (`WEB_CRAWLER_*`) → CLI args** (CLI wins). `DEFAULTS` is the stable baseline used by tests. `PROXY_SERVER` must be host:port only; Chrome's `--proxy-server` does not accept inline credentials, so providers must use IP-whitelist auth.
- `cli.py` — argparse, run orchestration, logging setup, xlsx export trigger. Entry point: `main()`.
- `chrome.py` — Chrome discovery (`find_chrome_executable`, `default_user_data_dir`) + the kill/launch/CDP-ready lifecycle.
- `vpn.py` — VPN gate (public IP, baseline file, the pure `evaluate_vpn`, and the interactive `ensure_vpn`).
- `browser_search.py` — the async search flow (`search_property`) and page-state detectors (`is_cloudflare_challenge`, `is_no_results_page`, `is_blocked`, `wait_for_*`).
- `extractor.py` — profile-page parsing (JSON-LD first, HTML fallback).
- `records.py` — `OUTPUT_FIELDNAMES` (canonical output column order), `STATUS_*`, `make_status_record`, `display_record`, and the pure `score_name_match`.
- `storage.py` — input CSV reading, results CSV read/write (resume), and `export_xlsx`.
- `gui.py` — optional Tkinter front-end (`tps-scraper-gui` entry point) that collects the input file, row range, proxy, and profile, persists them to `.gui_prefs.json`, and runs the exact `cli._run` pipeline on a worker thread; the CLI stays the source of truth.

Tests live in `tests/` (pytest + pytest-asyncio); `tests/conftest.py` has a `FakePage` for the async page helpers. A standalone Chrome diagnostic is `tools/test_chrome_diag.py` (not a pytest).

### Chrome via CDP, not Playwright's bundled browser

The defining design decision: the scraper does **not** use Playwright's own Chromium. Instead it relaunches a real Chrome with `--remote-debugging-port=9222` and connects via `connect_over_cdp`, preserving the profile's cookies and the **NopeCHA extension**, which is how CAPTCHAs get solved — there is no CAPTCHA-solving API. The browser is intentionally never closed at the end of a run.

**Dedicated profile + scoped kill.** `Settings.user_data_dir` defaults to a project-local `.chrome-profile/` dir (config.py `_default_user_data_dir`), *not* the user's everyday `Chrome\User Data`. On launch we must close any Chrome already holding that user-data dir's lock (Chrome ignores the debugging-port flag otherwise), but `kill_project_chrome(user_data_dir)` scopes the kill to **only** the processes whose command line uses that dir — the user's other Chrome windows stay open. The matching is done by the pure, unit-tested `_pids_using_user_data_dir(processes, user_data_dir)` over a CIM process list (`_chrome_processes`). A brand-new `.chrome-profile/` is created on first run, with a one-time-setup warning to install NopeCHA + log in (the profile is empty otherwise). Override `--user-data-dir` (or `WEB_CRAWLER_USER_DATA_DIR`) to share your real profile instead. `default_user_data_dir()` still resolves the everyday `Chrome\User Data` path and is used as a fallback.

### VPN gate (baseline-IP method)

`vpn.py` records the user's real (no-VPN) public IP once via `--set-baseline`, then before each run `ensure_vpn` prompts to enable the VPN and requires the live IP to differ from the baseline. `evaluate_vpn(live, baseline)` is the pure, unit-tested core returning `VPN_ON/VPN_OFF/NO_BASELINE/NO_INTERNET`. `--require-vpn` makes a failed check abort; `--skip-vpn-check` bypasses it.

### CAPTCHA / block handling

`is_cloudflare_challenge()` detects challenge pages by title/content markers; `wait_for_manual_captcha_solve()` then polls every 3s for up to `captcha_solve_timeout` (default 5 min) while NopeCHA or the user solves it. `search_property()` returns the sentinel `"CHALLENGE_FAILED"` (vs. a dict on success, `"NO_RESULTS"` on an empty result set, or `None` on failure) to drive the retry loop in `cli.py`. Keep `headless=False` — the manual-solve path needs a visible window.

### Input CSV parsing is positional, on purpose

`read_input_csv()` (storage.py) uses `csv.reader` with `_find_column()` header matching, **not** `csv.DictReader`, because real input files have blank and duplicated headers that DictReader silently merges/drops. It prefers "property" columns over "mailing" ones and avoids "Agent Name" as the target-name column. Every row carries `"Input Row #"` (1-based, header excluded) so it matches what the user sees in Excel.

### Incremental output, resume, and xlsx

Each successful row is appended to `results.csv` immediately (`save_single_result`), so a crash loses nothing. `results.xlsx` is a **derived** formatted export (`export_xlsx`) produced at the end of a run and via `--export-xlsx` — the CSV stays the crash-safe source of truth. On startup, `load_completed_rows()` reads existing `Input Row #` values; **resume is the default** (`Settings.resume=True`), so completed rows are skipped silently. `--no-resume` re-scrapes; `--retry-failed` re-runs `FAILED` rows. If `results.csv`/`results.xlsx` is locked (open in Excel), writers fall back to a timestamped copy.

### Extraction strategy

`extract_profile_data()` (extractor.py) tries JSON-LD (`script[type="application/ld+json"]` Person objects) first, then falls back to HTML selectors. When the site changes, JSON-LD parsing is the first place to look; selector constants for page-readiness live at the top of `browser_search.py` (`FORM_READY_SELECTOR`, `RESULTS_READY_SELECTOR`, `DETAIL_READY_SELECTOR`).

## Notes

- `results.csv`, `results.xlsx`, `scraper.log`, and `.vpn_baseline` contain PII / your real IP and are gitignored — never commit them or weaken those ignore rules.
- Result matching against the target name uses `records.score_name_match` (blended `difflib` similarity + word-overlap), called in `search_property()` Step 9.
- Waits are selector-based (`wait_for_any`), not fixed sleeps — keep it that way when adding steps.
- Every pure function has unit tests; when adding logic, prefer extracting a pure helper (like `score_name_match` / `evaluate_vpn`) so it can be tested without a browser or network.
