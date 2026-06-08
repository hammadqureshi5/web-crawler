# ============================================================
# config.py — Centralized Configuration
# ============================================================

import os

# Load variables from a local .env file if python-dotenv is installed.
# Falls back silently to real environment variables if it isn't.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

# ── Phase Control ───────────────────────────────────────────
# Set to True to process ONLY the first row of the CSV (for testing)
# Set to False to process ALL rows
PHASE_1_TESTING = True

# ── CapSolver Configuration ─────────────────────────────────
# Read from environment so the secret is never committed to git.
# Set it in a local .env file (see .env.example) or your shell:
#   PowerShell:  $env:CAPSOLVER_API_KEY = "CAP-..."
CAPSOLVER_API_KEY = os.environ.get("CAPSOLVER_API_KEY", "")

# Turnstile site key (auto-detected at runtime; fallback hardcoded here)
TURNSTILE_SITE_KEY = None  # Will be auto-detected from the page

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
CAPTCHA_SOLVE_TIMEOUT = 120 # Seconds to wait for CAPTCHA solve
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
