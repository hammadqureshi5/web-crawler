# ============================================================
# vpn.py — VPN gate (baseline-IP method)
# ============================================================
"""Prompt the user to enable their VPN and verify it actually took effect.

The check is deliberately simple and provider-agnostic: we record the user's
real (no-VPN) public IP **once** as a baseline, then before each run we fetch
the live public IP and require it to differ from that baseline. A different IP
is strong evidence the VPN is routing traffic; the same IP means it isn't.

``evaluate_vpn`` is a pure function (the unit-tested core); ``ensure_vpn``
wraps it with network calls and interactive prompts.
"""

import json
import logging
import os
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

# VPN status returned by evaluate_vpn().
VPN_NO_INTERNET = "NO_INTERNET"   # could not reach the IP service at all
VPN_NO_BASELINE = "NO_BASELINE"   # no baseline recorded yet — can't compare
VPN_ON = "VPN_ON"                 # live IP differs from baseline → VPN active
VPN_OFF = "VPN_OFF"               # live IP equals baseline → VPN not active

_IP_SERVICE = "https://api.ipify.org?format=json"


def get_public_ip(timeout: int = 10) -> str | None:
    """Return the current outbound public IP, or None if it can't be reached.

    Uses urllib (no Playwright/browser needed) so the VPN gate can run before
    Chrome is even launched."""
    try:
        with urllib.request.urlopen(_IP_SERVICE, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return (data.get("ip") or "").strip() or None
    except (urllib.error.URLError, OSError, ValueError) as e:
        logger.warning(f"[VPN] Could not determine public IP: {e}")
        return None


def read_baseline(path: str) -> str | None:
    """Read the saved baseline (no-VPN) IP, or None if not recorded."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def write_baseline(path: str, ip: str) -> None:
    """Persist the baseline (no-VPN) IP."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(ip.strip())


def evaluate_vpn(live_ip: str | None, baseline_ip: str | None) -> str:
    """Pure decision: compare the live IP to the baseline and classify.

    - No live IP at all → NO_INTERNET
    - No baseline recorded → NO_BASELINE (caller should warn / suggest --set-baseline)
    - live == baseline → VPN_OFF
    - live != baseline → VPN_ON
    """
    if not live_ip:
        return VPN_NO_INTERNET
    if not baseline_ip:
        return VPN_NO_BASELINE
    return VPN_OFF if live_ip.strip() == baseline_ip.strip() else VPN_ON


def set_baseline_interactive(settings, prompt=input) -> bool:
    """Capture the user's real IP (VPN OFF) and save it as the baseline.

    Returns True on success. *prompt* is injectable for tests."""
    print("\n" + "=" * 60)
    print(" VPN BASELINE SETUP")
    print("=" * 60)
    print(" Make sure your VPN is currently OFF, then press Enter so we can")
    print(" record your real public IP. Later runs compare against this to")
    print(" confirm the VPN is active.")
    prompt(" Press Enter with VPN OFF... ")

    ip = get_public_ip()
    if not ip:
        logger.error("[VPN] Could not reach the internet to record a baseline IP.")
        return False

    write_baseline(settings.vpn_baseline_file, ip)
    logger.info(f"[VPN] Baseline (no-VPN) IP recorded: {ip}")
    print(f" Baseline saved: {ip}")
    print("=" * 60 + "\n")
    return True


def ensure_vpn(settings, prompt=input) -> bool:
    """Interactive VPN gate run before scraping.

    Prompts the user to enable the VPN, fetches the live IP, and verifies it
    against the baseline. Returns True if it is OK to proceed, False to abort.

    Behavior:
    - ``skip_vpn_check`` → return True immediately.
    - No baseline → warn (and, if ``require_vpn``, abort with guidance to run
      ``--set-baseline``); otherwise proceed.
    - VPN_OFF → if ``require_vpn``, re-prompt once then abort; else warn + proceed.
    - VPN_ON → log the new IP and proceed.

    *prompt* is injectable for tests.
    """
    if settings.skip_vpn_check:
        logger.info("[VPN] --skip-vpn-check set; not verifying VPN.")
        return True

    baseline = read_baseline(settings.vpn_baseline_file)

    print("\n" + "=" * 60)
    print(" VPN CHECK")
    print("=" * 60)
    if baseline is None:
        msg = ("No VPN baseline recorded yet. Run with --set-baseline (VPN OFF) "
               "first so we can verify the VPN later.")
        logger.warning(f"[VPN] {msg}")
        print(f" {msg}")
        if settings.require_vpn:
            print(" --require-vpn is set but there is no baseline to check against.")
            print("=" * 60 + "\n")
            return False

    print(" Turn ON your VPN now, then press Enter to verify connectivity.")
    prompt(" Press Enter with VPN ON... ")

    # Allow one re-prompt when the VPN doesn't appear active yet.
    for attempt in range(2):
        live_ip = get_public_ip()
        status = evaluate_vpn(live_ip, baseline)

        if status == VPN_NO_INTERNET:
            logger.error("[VPN] No internet connectivity — cannot verify VPN.")
            print(" Could not reach the internet. Check your connection / VPN.")
            if settings.require_vpn:
                if attempt == 0:
                    prompt(" Fix it and press Enter to retry... ")
                    continue
                print("=" * 60 + "\n")
                return False
            print("=" * 60 + "\n")
            return True  # not required → proceed despite the warning

        if status == VPN_ON:
            logger.info(f"[VPN] VPN active — outbound IP {live_ip} (baseline {baseline}).")
            print(f" VPN OK. Current IP: {live_ip}")
            print("=" * 60 + "\n")
            return True

        if status == VPN_NO_BASELINE:
            logger.info(f"[VPN] Proceeding without baseline. Current IP: {live_ip}")
            print(f" Current IP: {live_ip} (no baseline to compare).")
            print("=" * 60 + "\n")
            return True

        # status == VPN_OFF
        logger.warning(f"[VPN] Live IP {live_ip} equals your baseline — VPN appears OFF.")
        print(f" VPN does NOT appear active (IP {live_ip} matches your real IP).")
        if settings.require_vpn:
            if attempt == 0:
                prompt(" Turn the VPN on and press Enter to retry... ")
                continue
            logger.error("[VPN] VPN still not active and --require-vpn is set — aborting.")
            print(" Aborting because --require-vpn is set.")
            print("=" * 60 + "\n")
            return False
        print(" Proceeding anyway (VPN not required).")
        print("=" * 60 + "\n")
        return True

    return False
