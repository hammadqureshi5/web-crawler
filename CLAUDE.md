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
# The Webshare rotating proxy (p.webshare.io:80) is the DEFAULT — no flag
# needed. Pass the proxy login with --proxy-user/--proxy-pass (or the env
# vars); proxy_auth.py answers it over CDP. Without creds the proxy must
# allow this machine's IP (Webshare dashboard), or you get prompted once:
python -m web_crawler --input input.csv --proxy-user <user> --proxy-pass <pw>
python -m web_crawler --input input.csv --no-proxy      # direct connection
python -m web_crawler --input input.csv --proxy other.host:9999  # different endpoint
# --verify-proxy is a requests-based diagnostic of IP rotation:
python -m web_crawler --proxy p.webshare.io:80 --proxy-user <user> --proxy-pass <pw> --verify-proxy

pytest                                 # run the unit test suite
python tools/test_chrome_diag.py       # diagnostic: can Chrome launch with CDP on 9222?
```

Row range and resume are CLI flags, so with credentials supplied the run is
unattended apart from CAPTCHA solving (NopeCHA usually handles it). If the
proxy needs a login and no credentials were given, the run prompts for them
once at startup (interactive terminals only).

## Architecture

The code is a package, `web_crawler/`, run via `python -m web_crawler` (zero
install) or the `tps-scraper` entry point (after `pip install .`).

- `config.py` — a `Settings` dataclass holding every tunable. `load_settings(args)` merges **defaults → environment (`WEB_CRAWLER_*`) → CLI args** (CLI wins). `DEFAULTS` is the stable baseline used by tests. `proxy_server` must be host:port only; Chrome's `--proxy-server` does not accept inline credentials — `proxy_username`/`proxy_password` are answered to the proxy over CDP (`proxy_auth.py`) and used by the Python requests path.
- `proxy.py` — `ProxyManager` (Webshare rotating-proxy helper). See "Automatic IP rotation" below.
- `proxy_auth.py` — answers the proxy login over CDP (`Fetch.enable(handleAuthRequests)` + `Fetch.continueWithAuth`) when credentials are configured, plus the pure `classify_nav_error` used for fail-fast proxy diagnostics.
- `cli.py` — argparse, run orchestration, logging setup, xlsx export trigger. Entry point: `main()`.
- `chrome.py` — Chrome discovery (`find_chrome_executable`, `default_user_data_dir`) + the kill/launch/CDP-ready lifecycle.
- `browser_search.py` — the async search flow (`search_property`) and page-state detectors (`is_cloudflare_challenge`, `is_no_results_page`, `is_blocked`, `wait_for_*`).
- `extractor.py` — profile-page parsing (JSON-LD first, HTML fallback).
- `records.py` — `OUTPUT_FIELDNAMES` (canonical output column order), `STATUS_*`, `make_status_record`, `display_record`, and the pure `score_name_match`.
- `storage.py` — input CSV reading, results CSV read/write (resume), and `export_xlsx`.

This is a **CLI-only** tool (`python -m web_crawler` / `tps-scraper`). There is no GUI.

Tests live in `tests/` (pytest + pytest-asyncio); `tests/conftest.py` has a `FakePage` for the async page helpers. A standalone Chrome diagnostic is `tools/test_chrome_diag.py` (not a pytest).

### Chrome via CDP, not Playwright's bundled browser

The defining design decision: the scraper does **not** use Playwright's own Chromium. Instead it relaunches a real Chrome with `--remote-debugging-port=9222` and connects via `connect_over_cdp`, preserving the profile's cookies and the **NopeCHA extension**, which is how CAPTCHAs get solved — there is no CAPTCHA-solving API. The browser is intentionally never closed at the end of a run.

**Dedicated profile + scoped kill.** `Settings.user_data_dir` defaults to a project-local `.chrome-profile/` dir (config.py `_default_user_data_dir`), *not* the user's everyday `Chrome\User Data`. On launch we must close any Chrome already holding that user-data dir's lock (Chrome ignores the debugging-port flag otherwise), but `kill_project_chrome(user_data_dir)` scopes the kill to **only** the processes whose command line uses that dir — the user's other Chrome windows stay open. The matching is done by the pure, unit-tested `_pids_using_user_data_dir(processes, user_data_dir)` over a CIM process list (`_chrome_processes`). A brand-new `.chrome-profile/` is created on first run, with a one-time-setup warning to install NopeCHA + log in (the profile is empty otherwise). Override `--user-data-dir` (or `WEB_CRAWLER_USER_DATA_DIR`) to share your real profile instead. `default_user_data_dir()` still resolves the everyday `Chrome\User Data` path and is used as a fallback.

### Automatic IP rotation (Webshare rotating proxy)

`proxy.py`'s `ProxyManager` is the single source of truth for proxy config. Rather than pinning a static proxy IP (which gets blocked and swapped by hand), traffic goes through Webshare's **rotating endpoint** `p.webshare.io:80` — one host:port that returns a fresh exit IP per connection, so rotation is automatic with no IP list to maintain. Build with `ProxyManager.from_settings(settings)`; an empty `proxy_server` means a direct connection (`enabled` is False). `Settings.proxy_server` **defaults to the Webshare rotating endpoint**, so runs are proxied unless `--no-proxy` clears it (or `--proxy`/`WEB_CRAWLER_PROXY_SERVER` overrides it).

The two consumers handle proxy auth **differently**, which is the crux:
- **Chrome** (the real scraper) gets `proxy.host_port` for `--proxy-server`, which **cannot** carry credentials (no Chrome flag exists), and Chrome's native proxy sign-in dialog does **not** block CDP-driven navigations — `page.goto` fails instantly with `net::ERR_INVALID_AUTH_CREDENTIALS` before anyone could type a login. So when the proxy needs a login (Webshare *country-filtered* rotating proxies disallow IP auth and require a username/password), `proxy_auth.enable_proxy_auth()` answers the challenge over CDP — `Fetch.enable(handleAuthRequests=True)` + `Fetch.continueWithAuth` with the configured `--proxy-user`/`--proxy-pass` (the same mechanism as puppeteer's `page.authenticate`). The Fetch domain is enabled **only when credentials are configured** (it intercepts every request on the page, so credential-less runs get zero interference), and each newly opened page needs `enable_proxy_auth` re-applied (the CDP session is page-scoped). Don't reintroduce a credential-injecting relay/midpoint — it broke truepeoplesearch's connections; Chrome still connects to Webshare directly.
- **Python requests** (the optional `--verify-proxy` IP check) uses `proxy.as_requests_proxies()` / `proxy.proxy_url()`, which carries `username:password` inline (same `--proxy-user`/`--proxy-pass` or `WEB_CRAWLER_PROXY_USERNAME/PASSWORD`) — `requests` handles credentialed proxies natively.

`requests` (not a `curl` subprocess) is used deliberately — native Python, real exceptions, mockable in tests, no binary to ship. `--verify-proxy` (cli `_verify_proxy`) samples the exit IP a few times via `verify_rotation()` and reports whether it actually rotates. Note: the *page* scraping must stay on Chrome (Cloudflare/NopeCHA) — the rotating proxy feeds Chrome; requests is only for the IP check/verification.

### Startup IP check & proxy fail-fast

Before the row loop, `log_public_ip()` (browser_search.py) navigates to an IP echo service through Chrome — a real navigation, because `page.request` bypasses Chrome's proxy — both to confirm the proxy took effect and to exercise the proxy login once before scraping. It returns `(ip, error_classification)`; on a `PROXY_AUTH` failure `cli.py` aborts (or prompts interactively for credentials if none were given) **before** touching any rows. Mid-run, `search_property()` returns the sentinel `"PROXY_AUTH_FAILED"` for the same condition, which the row loop treats as fatal: the run stops without writing a `FAILED` record for the current row, so plain resume picks it up next time. (There is no VPN gate anymore — the rotating proxy replaced it.)

### CAPTCHA / block handling

`is_cloudflare_challenge()` detects challenge pages by title/content markers; `wait_for_manual_captcha_solve()` then polls every 3s for up to `captcha_solve_timeout` (default 5 min) while NopeCHA or the user solves it. `search_property()` returns the sentinel `"CHALLENGE_FAILED"` (vs. a dict on success, `"NO_RESULTS"` on an empty result set, `"PROXY_AUTH_FAILED"` on a fatal proxy-auth error, or `None` on failure) to drive the retry loop in `cli.py`. Keep `headless=False` — the manual-solve path needs a visible window.

**The CAPTCHA solver needs the page treated as visible.** NopeCHA/Cloudflare pause when the page reports `hidden`, so `build_chrome_args()` (chrome.py) sets the anti-throttling flags *plus* `--disable-features=CalculateNativeWinOcclusion`, and `force_page_active()` (browser_search.py) pins focus/visibility over CDP. Occlusion calculation is what flips the page to hidden when another OS window covers Chrome, which stalls the solver so the Cloudflare challenge never clears. The timer/renderer flags alone don't cover it. `build_chrome_args` is pure and unit-tested, so the flag set can't silently regress.

### Input CSV parsing is positional, on purpose

`read_input_csv()` (storage.py) uses `csv.reader` with `_find_column()` header matching, **not** `csv.DictReader`, because real input files have blank and duplicated headers that DictReader silently merges/drops. It prefers "property" columns over "mailing" ones and avoids "Agent Name" as the target-name column. Every row carries `"Input Row #"` (1-based, header excluded) so it matches what the user sees in Excel.

### Incremental output, resume, and xlsx

Each successful row is appended to `results.csv` immediately (`save_single_result`), so a crash loses nothing. `results.xlsx` is a **derived** formatted export (`export_xlsx`) produced at the end of a run and via `--export-xlsx` — the CSV stays the crash-safe source of truth. On startup, `load_completed_rows()` reads existing `Input Row #` values; **resume is the default** (`Settings.resume=True`), so completed rows are skipped silently. `--no-resume` re-scrapes; `--retry-failed` re-runs `FAILED` rows. If `results.csv`/`results.xlsx` is locked (open in Excel), writers fall back to a timestamped copy.

### Extraction strategy

`extract_profile_data()` (extractor.py) tries JSON-LD (`script[type="application/ld+json"]` Person objects) first, then falls back to HTML selectors. When the site changes, JSON-LD parsing is the first place to look; selector constants for page-readiness live at the top of `browser_search.py` (`FORM_READY_SELECTOR`, `RESULTS_READY_SELECTOR`, `DETAIL_READY_SELECTOR`).

## Notes

- `results.csv`, `results.xlsx`, and `scraper.log` contain PII and are gitignored — never commit them or weaken those ignore rules.
- Result matching against the target name uses `records.score_name_match` (blended `difflib` similarity + word-overlap), called in `search_property()` Step 9.
- Waits are selector-based (`wait_for_any`), not fixed sleeps — keep it that way when adding steps.
- Every pure function has unit tests; when adding logic, prefer extracting a pure helper (like `score_name_match` / `classify_nav_error`) so it can be tested without a browser or network.
