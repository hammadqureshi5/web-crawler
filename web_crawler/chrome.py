# ============================================================
# chrome.py — Chrome discovery + CDP launch lifecycle
# ============================================================
"""Find the user's Chrome installation and launch it with remote debugging so
Playwright can connect over CDP. Nothing is hardcoded to one machine: the
executable and the user-data dir are auto-detected (with CLI/env overrides via
:class:`~web_crawler.config.Settings`).

The defining design (preserved from the original): we do NOT use Playwright's
bundled Chromium. We kill any running Chrome, relaunch the user's real Chrome
profile (with its extensions, incl. NopeCHA) on a debugging port, and connect
to it. The kill step is mandatory — Chrome ignores the debugging-port flag if
another instance already owns the user-data-dir.
"""

import json
import logging
import os
import shutil
import subprocess
import time

from web_crawler.proxy import ProxyManager

logger = logging.getLogger(__name__)

# Common fixed install locations, tried before the registry / PATH.
_COMMON_CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def _localappdata_chrome() -> str:
    local = os.environ.get("LOCALAPPDATA", "")
    return os.path.join(local, "Google", "Chrome", "Application", "chrome.exe") if local else ""


def _registry_chrome() -> str | None:
    """Look up chrome.exe via the Windows 'App Paths' registry keys.
    Returns the path string or None (also None on non-Windows)."""
    try:
        import winreg  # noqa: WPS433 (Windows-only import)
    except ImportError:
        return None
    subkey = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(root, subkey) as key:
                value, _ = winreg.QueryValueEx(key, None)
                if value:
                    return value
        except OSError:
            continue
    return None


def find_chrome_executable(explicit: str | None = None) -> str:
    """Resolve the Chrome executable path.

    Order: explicit override → common Program Files paths → %LOCALAPPDATA% →
    Windows registry App Paths → PATH (``where``/``shutil.which``).

    Raises ``FileNotFoundError`` with actionable guidance if none is found, so
    the client knows to pass ``--chrome-path``.
    """
    if explicit:
        if os.path.isfile(explicit):
            return explicit
        raise FileNotFoundError(
            f"--chrome-path was set to '{explicit}' but no file exists there."
        )

    candidates = list(_COMMON_CHROME_PATHS)
    local = _localappdata_chrome()
    if local:
        candidates.append(local)
    reg = _registry_chrome()
    if reg:
        candidates.append(reg)
    which = shutil.which("chrome") or shutil.which("chrome.exe")
    if which:
        candidates.append(which)

    for path in candidates:
        if path and os.path.isfile(path):
            logger.info(f"[CHROME] Found Chrome at: {path}")
            return path

    raise FileNotFoundError(
        "Could not locate chrome.exe automatically. Install Google Chrome, or "
        "pass --chrome-path \"C:\\path\\to\\chrome.exe\"."
    )


def default_user_data_dir() -> str:
    """Default Chrome user-data directory for the current Windows user, derived
    from %LOCALAPPDATA% (never a hardcoded username)."""
    local = os.environ.get("LOCALAPPDATA", "")
    return os.path.join(local, "Google", "Chrome", "User Data") if local else ""


def _pids_using_user_data_dir(processes, user_data_dir):
    """Pure: from a list of ``{"ProcessId", "CommandLine"}`` dicts, return the
    PIDs of the chrome.exe processes whose command line uses *user_data_dir*.

    This is how we scope the kill to ONLY the project's own Chrome — your
    everyday Chrome (a different user-data dir) is matched out and left running.
    Matching is path-normalized and case-insensitive (Windows paths)."""
    needle = os.path.normpath(user_data_dir).lower()
    pids = []
    for proc in processes:
        cmd = (proc.get("CommandLine") or "").lower().replace("/", "\\")
        if needle and needle in cmd:
            pid = proc.get("ProcessId")
            if pid is not None:
                pids.append(int(pid))
    return pids


def _chrome_processes():
    """Query running chrome.exe processes with their command lines (Windows,
    via CIM). Returns a list of ``{"ProcessId", "CommandLine"}`` dicts; empty
    on any failure (so callers degrade gracefully)."""
    ps_cmd = (
        "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
        "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=15,
        )
    except Exception as e:  # pragma: no cover - subprocess/platform issues
        logger.debug(f"[CHROME] process query failed: {e}")
        return []
    raw = (result.stdout or "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):  # ConvertTo-Json emits a bare object for one item
        return [data]
    return data if isinstance(data, list) else []


def kill_project_chrome(user_data_dir):
    """Kill ONLY the Chrome processes that use *user_data_dir* (the project's
    dedicated profile), so a relaunch can bind the debugging port without
    disturbing the user's everyday Chrome windows.

    Chrome ignores --remote-debugging-port if an instance already owns the
    user-data dir, so the matching instance must be closed first — but nothing
    else needs to be."""
    pids = _pids_using_user_data_dir(_chrome_processes(), user_data_dir)
    if not pids:
        logger.info(
            "[CHROME] No project Chrome running — your other Chrome windows are left untouched"
        )
        return

    logger.info(f"[CHROME] Closing {len(pids)} project Chrome process(es) only: {pids}")
    for pid in pids:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, text=True, timeout=10,
            )
        except Exception as e:
            logger.debug(f"[CHROME] taskkill PID {pid} note: {e}")

    # Wait until our instance is truly gone (file locks released).
    for _ in range(10):
        if not _pids_using_user_data_dir(_chrome_processes(), user_data_dir):
            break
        time.sleep(1)
    else:
        logger.warning("[CHROME] A project Chrome process may still be running")

    time.sleep(2)  # Extra wait for file lock release
    logger.info("[CHROME] Project Chrome processes terminated")


# Backwards-compatible alias for the dedicated-profile kill.
def kill_existing_chrome(user_data_dir=None):
    """Deprecated name kept for callers. Scopes to *user_data_dir* when given,
    otherwise the default project profile."""
    from web_crawler.config import DEFAULTS
    kill_project_chrome(user_data_dir or DEFAULTS.user_data_dir)


def wait_for_cdp_ready(port: int, timeout: int = 15) -> bool:
    """Poll http://127.0.0.1:{port}/json/version until Chrome's CDP is ready."""
    import urllib.error
    import urllib.request

    url = f"http://127.0.0.1:{port}/json/version"
    start = time.time()
    while time.time() - start < timeout:
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except (urllib.error.URLError, OSError):
            time.sleep(1)
    return False


def build_chrome_args(settings, user_data_dir: str, proxy_server: str = "") -> list:
    """Build Chrome's command-line args. Pure (no I/O) so it can be unit-tested.

    *proxy_server* is the ``host:port`` for ``--proxy-server`` (empty = none).
    """
    args = [
        f'--remote-debugging-port={settings.cdp_port}',
        f'--user-data-dir={user_data_dir}',
        f'--profile-directory={settings.profile_dir}',
        '--no-first-run',
        '--no-default-browser-check',
        '--start-maximized',
        # Keep the page's JS (Cloudflare challenge + NopeCHA solver) running at
        # full speed even when the Chrome window is occluded or sits behind
        # another window. Without these, background-tab timer throttling stalls
        # the solver and the CAPTCHA reloads ("reappears").
        '--disable-background-timer-throttling',
        '--disable-backgrounding-occluded-windows',
        '--disable-renderer-backgrounding',
        # The decisive one: when another window covers Chrome, native occlusion
        # detection marks the page "hidden", which pauses the CAPTCHA solver so
        # the Cloudflare challenge never clears. Disabling it keeps the page
        # treated as visible regardless of what's in front of it.
        '--disable-features=CalculateNativeWinOcclusion',
    ]
    if proxy_server:
        # --proxy-server takes only host:port (no inline credentials); when the
        # proxy needs a login, proxy_auth.py answers the challenge over CDP.
        args.append(f'--proxy-server={proxy_server}')
        if settings.proxy_bypass:
            args.append(f'--proxy-bypass-list={settings.proxy_bypass}')
    return args


def launch_chrome_with_profile(settings):
    """Launch Chrome with the user's profile and remote debugging enabled.
    Preserves all extensions, cookies, and saved sessions.

    Reads paths/port/proxy from *settings*; auto-detects the executable and
    user-data dir when those are left unset.
    """
    chrome_exe = find_chrome_executable(settings.chrome_path)
    user_data_dir = settings.user_data_dir or default_user_data_dir()
    if not user_data_dir:
        raise RuntimeError(
            "Could not determine the Chrome user-data dir. Pass --user-data-dir."
        )

    # A brand-new dedicated profile has no extensions/logins yet — tell the user
    # to do the one-time setup so CAPTCHAs solve automatically afterwards.
    profile_path = os.path.join(user_data_dir, settings.profile_dir)
    if not os.path.isdir(profile_path):
        os.makedirs(user_data_dir, exist_ok=True)
        logger.warning(
            "[CHROME] First run with a fresh dedicated profile at %s. In the "
            "Chrome window that opens, install the NopeCHA extension and log into "
            "the site once — future runs reuse this profile.", user_data_dir,
        )

    # MUST close any Chrome already using THIS profile first — otherwise the new
    # process just signals the running one and exits, so the debugging port never
    # opens. Scoped to our user-data dir, so other Chrome windows stay open.
    kill_project_chrome(user_data_dir)

    logger.info(f"[CHROME] Launching Chrome with profile: {settings.profile_dir}")
    logger.info(f"[CHROME] User data dir: {user_data_dir}")

    proxy = ProxyManager.from_settings(settings)
    proxy_server = proxy.host_port if proxy.enabled else ""
    chrome_args_list = build_chrome_args(settings, user_data_dir, proxy_server)

    if proxy.enabled:
        # Chrome can't take proxy credentials on the command line; when the
        # proxy needs a login, proxy_auth.py answers it over CDP using
        # --proxy-user/--proxy-pass.
        logger.info(f"[CHROME] Routing through rotating proxy: {proxy.host_port}")
    else:
        logger.info("[CHROME] No proxy configured — using your direct connection")

    # Launch via PowerShell Start-Process so Chrome runs fully DETACHED (its own
    # process, not a child of this script). This is what reliably binds the
    # debugging port — launching as a child process tends to hand off to any
    # surviving Chrome instance instead, leaving 9222 unbound. It also means
    # Chrome stays open after the scrape (intentional — it's the user's browser).
    chrome_args_string = ", ".join([f"'{a}'" for a in chrome_args_list])
    ps_cmd = f'Start-Process -FilePath "{chrome_exe}" -ArgumentList {chrome_args_string}'
    subprocess.run(
        ["powershell", "-Command", ps_cmd],
        capture_output=True, text=True, timeout=10,
    )
    logger.info("[CHROME] Chrome launch command sent, waiting for CDP ready...")

    if wait_for_cdp_ready(settings.cdp_port, timeout=20):
        logger.info(f"[CHROME] CDP port {settings.cdp_port} is ready")
    else:
        logger.error(f"[CHROME] CDP port {settings.cdp_port} not responding after 20s")
        raise RuntimeError(
            "Chrome debugging port never became available. Is Chrome installed "
            "correctly? Try passing --chrome-path / --user-data-dir."
        )
