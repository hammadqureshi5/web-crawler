# ============================================================
# config.py — Centralized Configuration
# ============================================================

import os

# ── Phase Control ───────────────────────────────────────────
# Set to True to process ONLY the first row of the CSV (for testing)
# Set to False to process ALL rows
PHASE_1_TESTING = True

# ── CAPTCHA Handling ────────────────────────────────────────
# CAPTCHAs are solved by the NopeCHA Chrome extension (loaded via the
# personal Chrome profile) or manually in the browser window. No external
# CAPTCHA-solving API is used.

# ── Proxy Configuration ─────────────────────────────────────
# Route Chrome through a (US residential) proxy so the target site sees a
# rotating / different IP instead of your own. Leave PROXY_SERVER empty ("")
# to run directly on your current connection (no proxy).
#
# Format:  "host:port"  or  "http://host:port"  or  "socks5://host:port"
# Examples:
#   "gate.smartproxy.com:7000"          (rotating endpoint — new IP per request)
#   "us.gate.iproyal.com:12321"         (US sticky/rotating endpoint)
#
# AUTH: Chrome's --proxy-server does NOT accept inline user:pass credentials.
#   → Use your provider's "IP whitelist" / "allowed IPs" auth: add your current
#     public IP in the provider dashboard, then no username/password is needed.
#   → If your provider only supports user:pass auth, tell the maintainer — that
#     path needs launch_persistent_context (a larger change), not --proxy-server.
PROXY_SERVER = ""  # e.g. "us.gate.iproyal.com:12321"  (empty = no proxy)

# Optional: hosts that should bypass the proxy (comma-separated, Chrome syntax).
PROXY_BYPASS = "localhost,127.0.0.1"

# ── File Paths ──────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_CSV = os.path.join(BASE_DIR, "input.csv")
OUTPUT_CSV = os.path.join(BASE_DIR, "results.csv")
LOG_FILE = os.path.join(BASE_DIR, "scraper.log")

# ── Target Website ──────────────────────────────────────────
TARGET_URL = "https://www.truepeoplesearch.com/"

# ── Timing & Retry Settings ─────────────────────────────────
REQUEST_DELAY_MIN = 3       # Minimum seconds between searches
REQUEST_DELAY_MAX = 7       # Maximum seconds between searches
PAGE_LOAD_TIMEOUT = 30000   # Milliseconds for page loads
ELEMENT_TIMEOUT = 15000     # Milliseconds for element waits
MAX_RETRIES = 3             # Max retries per address before skipping
CAPTCHA_SOLVE_TIMEOUT = 300 # Seconds to wait for the extension/manual CAPTCHA solve

# ── Browser Settings ────────────────────────────────────────
HEADLESS = False  # Set True for production; False to watch the browser
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)
VIEWPORT = {"width": 1366, "height": 768}
