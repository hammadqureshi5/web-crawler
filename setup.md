# Setup Guide — TruePeopleSearch Scraper

## Prerequisites

- **Windows 10/11**
- **Python 3.10+** on PATH
- **Google Chrome** installed (auto-detected; pass `--chrome-path` if it's in a
  non-standard location)
- The Chrome profile used for scraping must have the **NopeCHA** extension
  installed and enabled (handles CAPTCHAs) — install it once in Chrome
- *(Recommended)* a **VPN**
- *(Optional)* a **US residential proxy** with IP-whitelist auth, if you need IP
  rotation at the Chrome level — pass `--proxy host:port`

---

## 1. Create & activate a virtual environment

```powershell
python -m venv venv
.\venv\Scripts\activate
```

## 2. Install dependencies

```powershell
pip install -r requirements.txt        # runtime only
# or, to also get the `tps-scraper` command:
pip install .
playwright install chromium
```

## 3. Prepare your input CSV

Replace `input.csv` with your data. A header row is required; columns are matched
by name (case-insensitive). Typical columns:

| Column           | Example       |
|------------------|---------------|
| Name             | John Adams    |
| Property Address | 2612 Taylor St |
| Property City    | Commerce      |
| Property State   | TX            |

## 4. Record your VPN baseline (once)

With the **VPN OFF**, record your real public IP so the scraper can later confirm
the VPN is active:

```powershell
python -m web_crawler --set-baseline
```

This writes `.vpn_baseline` (git-ignored).

## 5. Run

```powershell
python -m web_crawler --input input.csv
```

Turn your VPN **on** when prompted. Watch the console and the Chrome window
(CAPTCHAs are solved by NopeCHA or by you, manually).

---

## CLI reference

| Flag | Description |
|------|-------------|
| `--input PATH` | Input CSV of addresses (default `input.csv`) |
| `--output PATH` | Results CSV path; `results.xlsx` is written alongside it |
| `--start N` / `--end N` | Process only input rows N..N (1-based, inclusive) |
| `--resume` / `--no-resume` | Resume is the default; `--no-resume` re-scrapes saved rows |
| `--retry-failed` | Re-process rows previously recorded `FAILED` |
| `--chrome-path PATH` | Path to `chrome.exe` (auto-detected if omitted) |
| `--user-data-dir PATH` | Chrome user-data dir (auto-detected if omitted) |
| `--profile NAME` | Chrome profile directory (e.g. `Profile 11`) |
| `--cdp-port N` | Chrome remote-debugging port (default 9222) |
| `--proxy host:port` | Route Chrome through a proxy (no inline credentials) |
| `--set-baseline` | Record your real (no-VPN) IP, then exit |
| `--require-vpn` | Abort unless the VPN is verified active |
| `--skip-vpn-check` | Skip the VPN prompt/verification |
| `--export-xlsx` | Rebuild `results.xlsx` from `results.csv` and exit |

All flags can also be set via environment variables prefixed `WEB_CRAWLER_`
(e.g. `WEB_CRAWLER_PROXY_SERVER`, `WEB_CRAWLER_MAX_RETRIES`). Precedence:
defaults → environment → CLI.

---

## Output

`results.csv` (crash-safe, written per row) and `results.xlsx` (formatted export
— styled, auto-filtered table with colour-coded `Status` plus a `Summary` sheet
of per-status counts). One row per input location. Columns:

```
Input Row #, Target Name, Property Address, Property City, Property State, Property Zip,
Mailing Address, Mailing City, Mailing State, Mailing Zip,
Phone Numbers, Emails, Agent Name, Agent Address, Match Score, Status
```

`Target Name` is the name from your input CSV; `Agent Name` is who was actually
found on the matched profile — compare them (with `Match Score`/`Status`) to
confirm each location resolved to the right person. `Status` is one of
`SUCCESS`, `LOW_CONFIDENCE`, `NOT_FOUND`, `FAILED`.

Logs go to `scraper.log`.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Chrome not found | Pass `--chrome-path "C:\path\to\chrome.exe"`. |
| CDP port never opens | Close all Chrome windows; run `python tools/test_chrome_diag.py`. |
| 403 Forbidden | Your IP may be rate-limited — switch VPN server, or use `--proxy`. |
| CAPTCHA not solving | Ensure NopeCHA is enabled in the scraping profile, or solve it manually. |
| Empty results | Site may have changed selectors — check `scraper.log`. |
| VPN check fails | Re-record the baseline with `--set-baseline` (VPN off), or use `--skip-vpn-check`. |
| Can't write results | Close `results.csv`/`results.xlsx` in Excel; a timestamped copy is written as fallback. |
| Resume appends duplicates | You have an old-format `results.csv` (no `Input Row #`) — archive it. |


## ip check

Methods to Find Your Public Network 
IPMethod 1: Using Command PromptOpen CMD: Press Windows Key + R, type cmd, and press Enter.
Run Curl: Type curl ifconfig.me or curl icanhazip.com and hit Enter.
View Result: The single line of numbers that appears is your public network IP.Method 
2: Using an Online Browser SearchOpen any web browser (like Chrome or Edge).Type "What is my IP" directly into the search bar.The search engine will display your public network IP address at the top of the results page.


## how to run

python -m web_crawler --input input.csv --proxy p.webshare.io:80 --skip-vpn-check --start 61 --end 64

● That command runs rows 61–64. A couple of things to know before you launch it:

  - It will open Chrome and pause for manual steps — entering the proxy login in Chrome's sign‑in dialog, and solving any CAPTCHA. So it can't run fully unattended.
  - Run it in your own terminal (or prefix with ! here) so the live Chrome window and prompts work:

  .venv\Scripts\python.exe -m web_crawler --input input.csv --proxy p.webshare.io:80 --skip-vpn-check --start 61 --end 64

  If rows 61–64 were already scraped, they'll be skipped (auto‑resume) — add --no-resume to force them, or --retry-failed to redo only failed ones