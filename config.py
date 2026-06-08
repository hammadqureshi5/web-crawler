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

# ── ExpressVPN Configuration ────────────────────────────────
EXPRESSVPN_CLI_PATH = r"C:\Program Files (x86)\ExpressVPN\services\ExpressVPN.CLI.exe"

# US server locations to rotate through (round-robin)
VPN_US_LOCATIONS = [
    "USA - New York",
    "USA - Los Angeles",
    "USA - Chicago",
    "USA - Dallas",
    "USA - Miami",
    "USA - Seattle",
    "USA - Denver",
    "USA - Atlanta",
]

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
VPN_CONNECT_WAIT = 6        # Seconds to wait after VPN connect
VPN_DISCONNECT_WAIT = 3     # Seconds to wait after VPN disconnect

# ── Browser Settings ────────────────────────────────────────
HEADLESS = False  # Set True for production; False to watch the browser
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)
VIEWPORT = {"width": 1366, "height": 768}
