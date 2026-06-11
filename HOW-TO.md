# Address Lookup Tool — User Guide

A step-by-step guide for everyday use. **No technical knowledge required.**
You only do the **Setup** once. After that, every lookup is two double-clicks.

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

A few things must be installed on the computer **first**. These are installed by
hand, one time only:

| You install (once) | Where to get it | Notes |
|--------------------|-----------------|-------|
| **Windows 10 or 11** | — | The tool only runs on Windows. |
| **Python 3.12** | <https://www.python.org/downloads/> | ⚠️ **Use 3.12. Do NOT install 3.14** — it is too new and setup will fail. During install, **tick "Add python.exe to PATH"**. |
| **Google Chrome** | <https://www.google.com/chrome/> | The tool uses your normal Chrome. |
| **NopeCHA extension** | Chrome Web Store | Added to the Chrome profile you'll use. This solves the "verify you are human" checks automatically. |
| **Internet + proxy details** | Provided to you | A proxy address in the form `host:port` (for example `38.154.203.95:5863`). |

The tool then installs the rest **for you** during Setup (see next section) — you
do **not** install those by hand:

- The program's components (`playwright`, `openpyxl`)
- A dedicated browser engine (Chromium) it controls

---

## 2. One-time setup (do this once)

1. Confirm the items in Section 1 are installed — especially **Python 3.12** and
   **Chrome with NopeCHA**.
2. Open the tool's folder and **double-click `setup.bat`**.
3. A black window opens and installs everything automatically. This takes a few
   minutes the first time (it downloads a browser).
4. When you see **"Setup complete!"**, press any key to close the window.

That's it — you never need to run `setup.bat` again unless you move the tool to a
new computer.

> **If setup says no compatible Python was found:** install **Python 3.12** from the
> link above (tick "Add python.exe to PATH"), then run `setup.bat` again.

---

## 3. Preparing your address list

1. Open **`input.csv`** (it opens in Excel).
2. Keep the column titles in the first row. Fill in one address per row. The tool
   needs these columns:

   | Column | Example |
   |--------|---------|
   | Name | John Adams |
   | Property Address | 2612 Taylor St |
   | Property City | Commerce |
   | Property State | TX |

3. **Save and close** the file. (Important: if `input.csv` or `results.xlsx` is left
   open in Excel, the tool can't read/write it.)

---

## 4. Running a lookup

1. **Double-click `run_gui.bat`.** The **Address Lookup Tool** window opens.
2. Fill in the window:
   - **Input CSV** — already set to `input.csv`. (Use *Browse…* to pick a different file.)
   - **Rows start / end** — leave **blank** to do the whole list, or enter numbers to
     do part of it (e.g. start `1`, end `50`). *Tip: start with a small range like 1–5
     the first time to confirm everything works.*
   - **Proxy** — type the proxy address you were given, as `host:port`.
   - **Chrome profile** — the profile that has NopeCHA installed (your provider set this).
   - Leave **Resume** ticked. Leave **Retry previously failed rows** unticked (for now).
3. Click **Start scraping**.
4. **Chrome opens by itself and starts searching.**
   - ⚠️ Starting a run **closes any Chrome windows you already have open** — save your
     work in Chrome first.
   - If a puzzle / "verify you are human" appears, it is usually solved automatically.
     If it isn't, **click through it yourself in that Chrome window** — the tool waits.
5. Watch the **Progress** box for live updates.
6. When it finishes, it asks if you want to **open the results spreadsheet** — click **Yes**.

---

## 5. Reading your results

Results are saved to **`results.xlsx`** (and `results.csv`). There is **one row per
address** you searched. Key columns:

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
| 🟨 Yellow | **LOW_CONFIDENCE** | Found something, but it may be the wrong person. **Please double-check** (compare *Target Name* vs *Agent Name*). |
| ⬜ Grey | **NOT_FOUND** | The website had no record for that address. |
| 🟥 Red | **FAILED** | The lookup couldn't finish (e.g. interrupted). You can retry these. |

There is also a **Summary** tab in the spreadsheet showing how many of each status.

---

## 6. Retrying and continuing

- **Stopping and restarting:** because **Resume** is ticked by default, if you stop
  the tool and run it again, it **continues where it left off** — finished rows are
  not repeated.
- **Retrying failures:** to re-attempt only the rows marked **FAILED**, open
  `run_gui.bat` again, tick **"Retry previously failed rows"**, and click Start.

---

## 7. Troubleshooting

| Problem | What to do |
|---------|-----------|
| **Setup fails mentioning "greenlet" or "Visual C++"** | You're on **Python 3.14**. Install **Python 3.12** and run `setup.bat` again. |
| **"No compatible Python was found"** | Install **Python 3.12** (tick "Add python.exe to PATH"), then re-run `setup.bat`. |
| **`run_gui.bat` says "not set up yet"** | Run `setup.bat` first. |
| **The spreadsheet won't update** | `results.xlsx` (or `results.csv`) is open in Excel. **Close it**, then run again. |
| **Lots of CAPTCHAs / "verify you are human"** | Make sure **NopeCHA** is installed and turned on in the Chrome profile you selected. Solve any it misses by hand in the Chrome window. |
| **Everything comes back NOT_FOUND or FAILED** | Check your internet and that the **proxy** address is correct and active. |
| **A row's Agent Name looks wrong / score is low** | That's why it's flagged **LOW_CONFIDENCE** — review it manually; the website may have listed a different person at that address. |
| **Something else** | Take a screenshot of the **Progress** box and send it for support. |

---

## 8. Quick reference card

```
FIRST TIME (once):
  1. Install Python 3.12  +  Chrome  +  NopeCHA extension
  2. Double-click  setup.bat   →  wait for "Setup complete!"

EVERY LOOKUP:
  1. Put addresses in  input.csv  (save & close it)
  2. Double-click  run_gui.bat
  3. Enter proxy + row range  →  Start scraping
  4. Solve any CAPTCHA in the Chrome window if needed
  5. Open  results.xlsx  when it finishes

RESULTS:
  Green = good | Yellow = double-check | Grey = not found | Red = retry
```

---

*Need help? Send a screenshot of the Progress box. Your finished work is always saved
in `results.csv`, so nothing is lost if you stop and resume.*
