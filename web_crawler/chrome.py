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

import logging
import os
import shutil
import subprocess
import time

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


def kill_existing_chrome():
    """Kill all running Chrome processes so we can launch a fresh instance with
    --remote-debugging-port (Chrome ignores the flag if an existing instance
    already owns the user-data-dir)."""
    logger.info("[CHROME] Closing any existing Chrome processes...")
    try:
        subprocess.run(
            ["taskkill", "/F", "/IM", "chrome.exe"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception as e:
        logger.debug(f"[CHROME] taskkill note: {e}")

    # Wait until all chrome.exe processes are truly gone (file locks released).
    for _ in range(10):
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq chrome.exe"],
            capture_output=True, text=True, timeout=5,
        )
        if "chrome.exe" not in result.stdout.lower():
            break
        time.sleep(1)
    else:
        logger.warning("[CHROME] Some Chrome processes may still be running")

    time.sleep(3)  # Extra wait for file lock release
    logger.info("[CHROME] Existing Chrome processes terminated")


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

    # MUST kill existing Chrome first — otherwise the new process just signals
    # the running one and exits, so the debugging port never opens.
    kill_existing_chrome()

    logger.info(f"[CHROME] Launching Chrome with profile: {settings.profile_dir}")
    logger.info(f"[CHROME] User data dir: {user_data_dir}")

    chrome_args_list = [
        f'--remote-debugging-port={settings.cdp_port}',
        f'--user-data-dir={user_data_dir}',
        f'--profile-directory={settings.profile_dir}',
        '--no-first-run',
        '--no-default-browser-check',
        '--start-maximized',
    ]

    # Route through a proxy if configured. Chrome's --proxy-server takes only
    # host:port (no inline credentials) — use the provider's IP-whitelist auth.
    if settings.proxy_server:
        chrome_args_list.append(f'--proxy-server={settings.proxy_server}')
        if settings.proxy_bypass:
            chrome_args_list.append(f'--proxy-bypass-list={settings.proxy_bypass}')
        logger.info(f"[CHROME] Using proxy: {settings.proxy_server}")
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
