# Address Lookup Tool — User Guide (CLI)

A step-by-step guide for everyday use. You run the tool from a **command
prompt**. You only do the **Setup** once; after that each run is a single
command.

---

## Contents

1. [What you need before starting](#1-what-you-need-before-starting)
2. [One-time setup](#2-one-time-setup-do-this-once)
3. [Preparing your address list](#3-preparing-your-address-list)
4. [Running a lookup](#4-running-a-lookup)
5. [Reading your results](#5-reading-your-results)
6. [Retrying and continuing](#6-retrying-and-continuing)
7. [Troubleshooting](#7-troubleshooting)
8. [Quick reference card](#8-quick-reference-card)

---

## 1. What you need before starting

These are installed by hand, one time only:

| You install (once) | Where to get it | Notes |
|--------------------|-----------------|-------|
| **Windows 10 or 11** | — | The tool only runs on Windows. |
| **Python 3.12** | <https://www.python.org/downloads/> | ⚠️ **Use 3.12. Do NOT install 3.14** — it is too new and setup will fail. During install, **tick "Add python.exe to PATH"**. |
| **Google Chrome** | <https://www.google.com/chrome/> | The tool drives your real Chrome. |
| **NopeCHA extension** | Chrome Web Store | Installed once into the tool's dedicated Chrome profile (see Setup). Solves the "verify you are human" checks automatically. |
| **Proxy details** | Provided to you | A rotating proxy as `host:port` (e.g. `p.webshare.io:80`) plus a **username and password**. |

The tool installs the rest **for you** during Setup: its components
(`playwright`, `openpyxl`, `requests`) and a browser engine it controls.

---

## 2. One-time setup (do this once)

1. Confirm **Python 3.12** and **Chrome** are installed.
2. Open the tool's folder and **double-click `setup.bat`**.
3. A black window installs everything automatically (a few minutes the first
   time — it downloads a browser).
4. When you see **"Setup complete!"**, press a key to close the window.

**First real run sets up the proxy profile:** the very first time you run a
lookup, a fresh, dedicated Chrome profile opens. In that window, **install the
NopeCHA extension and log into truepeoplesearch.com once**. Every later run
reuses it.

> **If setup says no compatible Python was found:** install **Python 3.12**
> (tick "Add python.exe to PATH"), then run `setup.bat` again.

---

## 3. Preparing your address list

1. Open **`input.csv`** (it opens in Excel).
2. Keep the column titles in the first row, one address per row. The tool needs:

   | Column | Example |
   |--------|---------|
   | Name | John Adams |
   | Property Address | 2612 Taylor St |
   | Property City | Commerce |
   | Property State | TX |

3. **Save and close** the file. (If `input.csv` or `results.xlsx` is left open in
   Excel, the tool can't read/write it.)

---

## 4. Running a lookup

1. Open a terminal **in the tool's folder** (in File Explorer, type `cmd` in the
   address bar and press Enter).
2. Run the command (this does rows 1–5 as a first test):

   ```
   .venv\Scripts\python.exe -m web_crawler --input input.csv --proxy-user <user> --proxy-pass <pw> --start 1 --end 5
   ```

   - `--start` / `--end` pick the rows to process (1-based, inclusive). Leave both
     off to do the whole list. *Tip: start with a small range the first time.*
   - `--proxy-user` / `--proxy-pass` are your proxy **username and password** —
     the tool signs into the proxy for you (the rotating proxy
     `p.webshare.io:80` is already the default endpoint).

3. **Chrome opens by itself and starts searching.**
   - If a "verify you are human" check appears, NopeCHA usually solves it. If not,
     **click through it yourself in that Chrome window** — the tool waits.
   - **Leave the Chrome window open** until the run finishes.
4. Watch the terminal for live progress. At the end it prints a summary
   (Successful / Not found / Failed).

---

## 5. Reading your results

Results are saved to **`results.xlsx`** (and `results.csv`), one row per address.
Key columns:

| Column | What it means |
|--------|---------------|
| **Target Name** | The person you searched for (from your list). |
| **Agent Name** | The person actually found on the website. |
| **Phone Numbers / Emails** | The contact details found. |
| **Match Score** | Confidence of the match (higher = better). |
| **Status** | Colour-coded — see below. |

**The `Status` column tells you how much to trust each row:**

| Colour | Status | Meaning |
|--------|--------|---------|
| 🟩 Green | **SUCCESS** | Confident match — good to use. |
| 🟨 Yellow | **LOW_CONFIDENCE** | Found something, but it may be the wrong person. **Double-check** (compare *Target Name* vs *Agent Name*). |
| ⬜ Grey | **NOT_FOUND** | The website had no record for that address. |
| 🟥 Red | **FAILED** | The lookup couldn't finish (e.g. interrupted). You can retry these. |

There is also a **Summary** tab in the spreadsheet.

---

## 6. Retrying and continuing

- **Continuing:** resume is on by default — if you stop and run the same command
  again, it **continues where it left off** (finished rows are not repeated).
- **Re-doing failures:** add **`--retry-failed`** to re-attempt only rows marked
  FAILED.
- **Forcing a re-scrape:** add **`--no-resume`** to redo rows even if already done.

```
.venv\Scripts\python.exe -m web_crawler --input input.csv --proxy-user <user> --proxy-pass <pw> --retry-failed
```

---

## 7. Troubleshooting

| Problem | What to do |
|---------|-----------|
| **Setup fails mentioning "greenlet" or "Visual C++"** | You're on **Python 3.14**. Install **Python 3.12** and run `setup.bat` again. |
| **"No compatible Python was found"** | Install **Python 3.12** (tick "Add python.exe to PATH"), then re-run `setup.bat`. |
| **`python` not recognized / nothing happens** | Use the full path shown above: `.venv\Scripts\python.exe -m web_crawler ...`, run from the tool's folder. |
| **A second tab shows `client_connect_invalid_ip`** | Harmless — that's a leftover tab hitting the proxy. Close it; the scraping tab is separate. |
| **The spreadsheet won't update** | `results.xlsx`/`results.csv` is open in Excel. **Close it**, then run again. |
| **Lots of CAPTCHAs / "verify you are human"** | Make sure **NopeCHA** is installed and on in the tool's Chrome profile. Solve any it misses by hand in the Chrome window, and keep that window open. |
| **Everything comes back NOT_FOUND or FAILED** | Check your internet and that the **proxy** address + login are correct. Confirm rotation with `--verify-proxy` (see below). |
| **Check the proxy itself** | `.venv\Scripts\python.exe -m web_crawler --proxy p.webshare.io:80 --proxy-user <user> --proxy-pass <pw> --verify-proxy` |
| **A row's Agent Name looks wrong / score is low** | That's why it's flagged **LOW_CONFIDENCE** — review it manually. |
| **See every option** | `.venv\Scripts\python.exe -m web_crawler --help` |

---

## 8. Quick reference card

```
FIRST TIME (once):
  1. Install Python 3.12  +  Chrome
  2. Double-click  setup.bat   ->  wait for "Setup complete!"
  3. On the first run, install NopeCHA + log into the site in the
     Chrome window that opens.

EVERY LOOKUP (run from the tool's folder):
  .venv\Scripts\python.exe -m web_crawler --input input.csv ^
      --proxy-user <user> --proxy-pass <pw> --start 1 --end 5

  - The tool signs into the proxy for you with --proxy-user/--proxy-pass.
  - Solve any CAPTCHA in the Chrome window; leave it open.
  - Drop --start/--end to run the whole list.
  - Add --retry-failed to redo only failed rows.

RESULTS  (results.xlsx):
  Green = good | Yellow = double-check | Grey = not found | Red = retry
```

---

*Your finished work is always saved in `results.csv`, so nothing is lost if you
stop and resume.*
