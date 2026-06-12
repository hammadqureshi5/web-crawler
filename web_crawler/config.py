# ============================================================
# config.py — Centralized configuration (Settings dataclass)
# ============================================================
"""All tunables live on a single ``Settings`` dataclass so the same values can
come from built-in defaults, environment variables, or CLI flags — in that
order of increasing precedence (CLI wins).

This replaces the old module-level constants. ``DEFAULTS`` is exposed as a
stable baseline for tests and for callers that want the unmodified values.

Environment variables use the ``WEB_CRAWLER_`` prefix, e.g.
``WEB_CRAWLER_PROXY_SERVER=p.webshare.io:80`` (Webshare's rotating endpoint),
with ``WEB_CRAWLER_PROXY_USERNAME`` / ``WEB_CRAWLER_PROXY_PASSWORD`` for
credentialed (country-filtered) proxies.
"""

import os
import sys
from dataclasses import dataclass, field, fields, replace
from typing import Optional

from web_crawler.proxy import WEBSHARE_ROTATING_ENDPOINT

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Project root is the directory that contains the package. In a PyInstaller
# one-file exe, __file__ lives in the throwaway _MEIxxxx extraction dir (wiped
# on exit), so anchor to the exe's own folder instead — otherwise the Chrome
# profile, results.csv, and logs land in temp and vanish after every run.
if getattr(sys, "frozen", False):
    PROJECT_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    PROJECT_DIR = os.path.dirname(BASE_DIR)

# ── Target Website ──────────────────────────────────────────
TARGET_URL = "https://www.truepeoplesearch.com/"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


def _default_input() -> str:
    return os.path.join(PROJECT_DIR, "input.csv")


def _default_output() -> str:
    return os.path.join(PROJECT_DIR, "results.csv")


def _default_log() -> str:
    return os.path.join(PROJECT_DIR, "scraper.log")


def _default_user_data_dir() -> str:
    """A dedicated, project-local Chrome user-data dir.

    Using our own dir (instead of the user's everyday ``Chrome\\User Data``)
    is what lets the scraper kill ONLY its own Chrome on relaunch — your normal
    Chrome windows are never touched. The profile is created on first run; you
    install the NopeCHA extension and log into the site in it once.
    """
    return os.path.join(PROJECT_DIR, ".chrome-profile")


@dataclass
class Settings:
    """Every tunable for a scraping run. Build one with :func:`load_settings`."""

    # ── File paths ──────────────────────────────────────────
    input_csv: str = field(default_factory=_default_input)
    output_csv: str = field(default_factory=_default_output)
    log_file: str = field(default_factory=_default_log)

    # ── Chrome / CDP ────────────────────────────────────────
    # chrome_path defaults to None → auto-detect in chrome.py. user_data_dir
    # defaults to a dedicated project-local profile so the scraper only kills
    # its own Chrome (never your everyday windows); override to share your real
    # profile if you prefer.
    chrome_path: Optional[str] = None
    user_data_dir: str = field(default_factory=_default_user_data_dir)
    profile_dir: str = "Profile 11"
    cdp_port: int = 9222

    # ── Proxy (Webshare rotating endpoint → automatic IP rotation) ──
    # proxy_server is host:port: the rotating endpoint that hands out a fresh
    # exit IP per connection. It is what Chrome's --proxy-server uses and cannot
    # carry inline creds. proxy_username/password, when set, are answered to
    # the proxy over CDP during the scrape (proxy_auth.py) and used by the
    # Python requests path (proxy.ProxyManager) for the IP check; without them
    # the proxy must allow this machine's IP (Webshare dashboard). The Webshare
    # endpoint is the DEFAULT — runs are proxied unless --no-proxy (or an
    # overriding --proxy/WEB_CRAWLER_PROXY_SERVER) is given.
    proxy_server: str = WEBSHARE_ROTATING_ENDPOINT
    proxy_bypass: str = "localhost,127.0.0.1"
    proxy_username: str = ""
    proxy_password: str = ""

    # ── Result matching ─────────────────────────────────────
    min_match_score: float = 0.5

    # ── Timing & retries (ms unless noted) ──────────────────
    request_delay_min: float = 3.0      # seconds between searches
    request_delay_max: float = 7.0      # seconds between searches
    page_load_timeout: int = 30000      # ms
    element_timeout: int = 15000        # ms
    max_retries: int = 3
    captcha_solve_timeout: int = 300    # seconds

    # ── Browser ─────────────────────────────────────────────
    headless: bool = False              # keep False — manual CAPTCHA needs a window
    viewport_width: int = 1366
    viewport_height: int = 768

    # ── Row range & resume ──────────────────────────────────
    start_row: Optional[int] = None
    end_row: Optional[int] = None
    resume: bool = True                 # auto-resume is the default
    retry_failed: bool = False

    @property
    def viewport(self) -> dict:
        return {"width": self.viewport_width, "height": self.viewport_height}


# Stable baseline for tests / callers that want untouched defaults.
DEFAULTS = Settings()


# Maps Settings field -> (env var name, converter). Only fields that make sense
# to override via the environment are listed.
_ENV_MAP = {
    "input_csv": ("WEB_CRAWLER_INPUT_CSV", str),
    "output_csv": ("WEB_CRAWLER_OUTPUT_CSV", str),
    "log_file": ("WEB_CRAWLER_LOG_FILE", str),
    "chrome_path": ("WEB_CRAWLER_CHROME_PATH", str),
    "user_data_dir": ("WEB_CRAWLER_USER_DATA_DIR", str),
    "profile_dir": ("WEB_CRAWLER_PROFILE", str),
    "cdp_port": ("WEB_CRAWLER_CDP_PORT", int),
    "proxy_server": ("WEB_CRAWLER_PROXY_SERVER", str),
    "proxy_bypass": ("WEB_CRAWLER_PROXY_BYPASS", str),
    "proxy_username": ("WEB_CRAWLER_PROXY_USERNAME", str),
    "proxy_password": ("WEB_CRAWLER_PROXY_PASSWORD", str),
    "min_match_score": ("WEB_CRAWLER_MIN_MATCH_SCORE", float),
    "max_retries": ("WEB_CRAWLER_MAX_RETRIES", int),
    "captcha_solve_timeout": ("WEB_CRAWLER_CAPTCHA_TIMEOUT", int),
}

# Maps Settings field -> argparse attribute name (when they differ / to be
# explicit about which CLI flags feed which setting).
_CLI_MAP = {
    "input_csv": "input",
    "output_csv": "output",
    "chrome_path": "chrome_path",
    "user_data_dir": "user_data_dir",
    "profile_dir": "profile",
    "cdp_port": "cdp_port",
    "proxy_server": "proxy",
    "proxy_username": "proxy_user",
    "proxy_password": "proxy_pass",
    "start_row": "start",
    "end_row": "end",
    "retry_failed": "retry_failed",
}

_FIELD_NAMES = {f.name for f in fields(Settings)}


def _apply_env(settings: Settings) -> Settings:
    """Return a copy of *settings* with any present env vars applied."""
    updates = {}
    for attr, (env_name, conv) in _ENV_MAP.items():
        raw = os.environ.get(env_name)
        if raw is None or raw == "":
            continue
        try:
            updates[attr] = conv(raw)
        except (ValueError, TypeError):
            # Ignore malformed env values rather than crash the run.
            pass
    return replace(settings, **updates) if updates else settings


def load_settings(args=None) -> Settings:
    """Build a :class:`Settings` from defaults → environment → CLI args.

    *args* is the ``argparse.Namespace`` from :func:`web_crawler.cli.parse_args`
    (or any object/dict with the same attribute names); pass ``None`` for the
    pure defaults+env result. CLI values that are ``None`` are treated as
    "not provided" and do not override.
    """
    settings = _apply_env(Settings())

    if args is None:
        return settings

    get = (args.get if isinstance(args, dict) else lambda k, d=None: getattr(args, k, d))

    updates = {}
    for attr, cli_name in _CLI_MAP.items():
        val = get(cli_name, None)
        if val is not None:
            updates[attr] = val

    # --no-proxy clears the (defaulted) proxy endpoint → direct connection.
    # argparse makes --proxy/--no-proxy mutually exclusive, so no conflict here.
    if get("no_proxy", False):
        updates["proxy_server"] = ""

    # resume is a tri-state from two mutually-exclusive flags.
    no_resume = get("no_resume", False)
    resume_flag = get("resume", False)
    if no_resume:
        updates["resume"] = False
    elif resume_flag:
        updates["resume"] = True
    # else: keep the default (True)

    return replace(settings, **updates) if updates else settings
