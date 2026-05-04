# TruePeopleSearch Data Extractor 🚀

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Playwright](https://img.shields.io/badge/Playwright-Stealth-green)](https://playwright.dev/)

**Professional web scraper for TruePeopleSearch.com** – Extract property owner/agent data (names, addresses, phones, emails) from address-based searches. Production-ready with:

- 🛡️ **Anti-Detection**: Playwright Stealth + ExpressVPN rotation + CapSolver Turnstile solving
- ⚡ **Robust**: Auto-retries, Cloudflare challenge handling, block detection
- 📊 **Batch Processing**: CSV input → CSV output, Phase 1 testing mode
- 🔧 **Configurable**: Timings, retries, headless mode via `config.py`

## ✨ Features

| Feature | Description |
|---------|-------------|
| **Address Search** | Processes `input.csv` → `results.csv` with property/agent data |
| **CAPTCHA Solving** | Automatic Turnstile/Cloudflare via CapSolver API |
| **VPN Rotation** | ExpressVPN US server rotation on blocks/challenges |
| **Stealth Browser** | Undetectable Chromium + realistic UA/viewport |
| **Error Recovery** | Max retries per row, VPN rotate on 403/challenges |
| **Logging** | Detailed console + `scraper.log` |
| **Testing Mode** | `PHASE_1_TESTING=True` processes 1st CSV row only |

## 📋 Quick Start (Linux/macOS)

### 1. Setup Virtual Environment
```bash
cd /home/hamza/Repos/scraping
python -m venv venv
source venv/bin/activate  # Linux/macOS
# .\venv\Scripts\activate  # Windows
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
playwright install chromium
```

### 3. Configure
- **CapSolver**: Add your API key to `config.py` → `CAPSOLVER_API_KEY`
- **ExpressVPN**: Install [ExpressVPN CLI](https://www.expressvpn.com/support/vpn-setup/app-for-linux/), update `EXPRESSVPN_CLI_PATH` in `config.py`
- **Input CSV**: Edit `input.csv` with columns: `Property Address`, `Property city`, `property state`

### 4. Test Phase 1 (1st row only)
```bash
python scraper.py
```

### 5. Full Batch Mode
Set `PHASE_1_TESTING = False` in `config.py`, then:
```bash
python scraper.py
```

## ⚙️ Configuration (`config.py`)

| Setting | Default | Purpose |
|---------|---------|---------|
| `PHASE_1_TESTING` | `True` | Single row test vs full batch |
| `CAPSOLVER_API_KEY` | `your-key` | Turnstile solving |
| `HEADLESS` | `False` | Watch browser (set `True` for prod) |
| `MAX_RETRIES` | `3` | Attempts per address |
| `REQUEST_DELAY_MIN/MAX` | `3-7s` | Random delays between searches |

**VPN Servers** (`VPN_US_LOCATIONS`): NY, LA, Chicago, Dallas, Miami, Seattle, Denver, Atlanta (round-robin).

## 📤 Output Format (`results.csv`)

```
Property Address,Property City,Property State,Property Zip,Mailing Address,Mailing City,Mailing State,Mailing Zip,Phone Numbers,Emails,Agent Name,Agent Address
```

## 🛠 Troubleshooting

| Issue | Solution |
|-------|----------|
| **403 Forbidden** | Auto VPN rotation. Ensure ExpressVPN running + CLI accessible |
| **CAPTCHA Fail** | Check CapSolver balance/API key. Verify `TURNSTILE_SITE_KEY` |
| **No Results** | Site changed selectors? Check `scraper.log`. Test Phase 1 |
| **VPN Not Found** | Update `EXPRESSVPN_CLI_PATH` in `config.py` |
| **Bot Detected** | `HEADLESS=False`, slower `REQUEST_DELAY_*` |

## 📁 Project Structure
```
.
├── scraper.py          # Main orchestrator
├── data_extractor.py   # Profile data parsing
├── captcha_solver.py   # CapSolver integration
├── vpn_manager.py      # ExpressVPN CLI wrapper
├── config.py           # Settings
├── input.csv           # Your addresses ➡️
├── results.csv         # Extracted data ⬅️
├── requirements.txt
└── scraper.log         # Debug logs
```

## ⚖️ Disclaimer
- For **educational/research purposes only**.
- Respect `robots.txt`, rate limits, ToS.
- Use responsibly – scraping may violate site policies.

## 🤝 Contributing
1. Fork & create PR
2. Update `TODO.md` for progress
3. Test with `PHASE_1_TESTING=True`

**Happy Scraping!** 🕷️

---

*Built with ❤️ using Playwright, CapSolver, ExpressVPN*

