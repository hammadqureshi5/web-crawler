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

# 3. Run it — the Webshare rotating proxy is on by default; pass its login:
python -m web_crawler --input input.csv --proxy-user <user> --proxy-pass <pw>
```

After `pip install .` you can also run it as a command: `tps-scraper --input input.csv`.

---

## Requirements on the machine that runs it

- **Windows** with **Google Chrome** installed (auto-detected; override with `--chrome-path`).
- The Chrome **profile you scrape with must already have the NopeCHA extension
  installed and enabled** — that is how CAPTCHAs get solved. This cannot be
  shipped in code; install it once in Chrome on the target PC.
- **Python 3.10+**.
- A **Webshare rotating proxy** account (the default endpoint is
  `p.webshare.io:80`). Pass its username/password with
  `--proxy-user`/`--proxy-pass` — the scraper answers the proxy login
  automatically. Or run with `--no-proxy` to use your direct connection.

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
  `--export-xlsx`): a styled, auto-filtered **Results** table with a frozen header,
  wrapped phone/email lists and colour-coded `Status`, plus a **Summary** sheet of
  per-status counts.

Each input location produces exactly one row. Alongside the scraped `Agent Name`,
the output records the `Target Name` you searched for plus a `Match Score` and
`Status` (`SUCCESS`, `LOW_CONFIDENCE`, `NOT_FOUND`, `FAILED`), so you can confirm
each address resolved to the right person.

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

## Proxy & IP rotation

Traffic goes through Webshare's **rotating endpoint** by default
(`p.webshare.io:80` — a fresh exit IP per connection, no IP list to maintain).
Chrome's `--proxy-server` can't carry credentials and its sign-in dialog doesn't
work for automated runs, so the scraper answers the proxy login itself over the
DevTools protocol using `--proxy-user`/`--proxy-pass` (or
`WEB_CRAWLER_PROXY_USERNAME`/`WEB_CRAWLER_PROXY_PASSWORD`). Without credentials
the proxy must allow your machine's IP (Webshare dashboard → IP authorization);
if it doesn't, the run prompts for the login once at startup.

- `--proxy host:port` — use a different proxy endpoint.
- `--no-proxy` — direct connection, no proxy.
- `--verify-proxy` — sample the exit IP a few times to confirm rotation, then exit.

---

## Common commands

```powershell
python -m web_crawler --input input.csv --proxy-user U --proxy-pass P   # scrape (auto-resume)
python -m web_crawler --input input.csv --start 1 --end 50
python -m web_crawler --no-resume                          # re-scrape everything
python -m web_crawler --retry-failed                       # retry only FAILED rows
python -m web_crawler --export-xlsx                        # rebuild results.xlsx from CSV
python -m web_crawler --chrome-path "C:\path\chrome.exe" --profile "Profile 1"
python -m web_crawler --no-proxy                           # direct connection
python -m web_crawler --proxy-user U --proxy-pass P --verify-proxy  # check IP rotation
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
