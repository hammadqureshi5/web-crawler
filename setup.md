# Setup Guide — TruePeopleSearch Scraper

## Prerequisites

- **Python 3.11+** installed and on PATH
- **Google Chrome** with the **NopeCHA** extension installed in the profile used for scraping (handles CAPTCHAs)
- *(Optional)* A **US residential proxy** with IP-whitelist auth, if you need IP rotation — set `PROXY_SERVER` in `config.py`

---

## Quick Start

### 1. Create & Activate Virtual Environment

```powershell
cd "c:\Users\DELL\Desktop\web scraping"
python -m venv venv
.\venv\Scripts\activate
```

### 2. Install Dependencies

```powershell
pip install -r requirements.txt
```

### 3. Install Playwright Browsers

```powershell
playwright install chromium
```

### 4. Prepare Your Input CSV

Replace the sample `input.csv` with your real data. Required columns:

| Column Name      | Example       |
|------------------|---------------|
| Property Address | 123 Main St   |
| Property city    | New York      |
| property state   | NY            |

### 5. (Optional) Configure a proxy for IP rotation

If your own IP gets blocked/rate-limited, sign up with a US residential proxy
provider, whitelist your current public IP in their dashboard (so no
username/password is needed), and set the endpoint in `config.py`:

```python
PROXY_SERVER = "us.gate.iproyal.com:12321"   # empty "" = no proxy
```

On startup the scraper logs the outbound IP so you can confirm the proxy is
in effect. Leave `PROXY_SERVER = ""` to run on your direct connection.

### 6. Run Phase 1 Test

```powershell
python scraper.py
```

This processes only the first CSV row. Watch the console and browser window.

### 7. Switch to Full Batch Mode

Edit `config.py` and set:

```python
PHASE_1_TESTING = False
```

Then run `python scraper.py` again.

---

## Configuration (config.py)

| Setting              | Description                                    |
|----------------------|------------------------------------------------|
| `PHASE_1_TESTING`    | `True` = first row only, `False` = all rows    |
| `CAPTCHA_SOLVE_TIMEOUT` | Seconds to wait for NopeCHA / manual solve  |
| `HEADLESS`           | `False` = visible browser, `True` = headless   |
| `MAX_RETRIES`        | Retry attempts per address (default: 3)        |
| `REQUEST_DELAY_MIN`  | Min seconds between searches (default: 3)      |
| `REQUEST_DELAY_MAX`  | Max seconds between searches (default: 7)      |

---

## Output

Results are saved to `results.csv` with these columns:

```
Property Address, Property City, Property State, Property Zip,
Mailing Address, Mailing City, Mailing State, Mailing Zip,
Phone Numbers, Emails, Agent Name, Agent Address
```

Logs are saved to `scraper.log`.

---

## Troubleshooting

| Problem                  | Solution                                          |
|--------------------------|---------------------------------------------------|
| 403 Forbidden            | Your IP may be rate-limited. Set `PROXY_SERVER` in config.py to rotate IPs. |
| CAPTCHA not solving      | Make sure NopeCHA is enabled in the Chrome profile, or solve it manually in the browser window. |
| Empty results            | Site may have changed selectors. Check logs.       |
| Proxy not taking effect  | Check the `[IP]` line in the logs; whitelist your IP in the provider dashboard. |
| Browser detected as bot  | Try setting `HEADLESS = False` in config.py.       |
