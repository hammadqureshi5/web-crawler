# ============================================================
# vpn_manager.py — ExpressVPN Rotation & Management
# ============================================================

import logging
import subprocess
import time
from config import (
    EXPRESSVPN_CLI_PATH,
    VPN_US_LOCATIONS,
    VPN_CONNECT_WAIT,
    VPN_DISCONNECT_WAIT,
)

logger = logging.getLogger(__name__)

# Track the current VPN location index for round-robin rotation
_current_location_index = 0


def _run_vpn_command(*args, timeout=30) -> tuple[bool, str]:
    """
    Execute an ExpressVPN CLI command.

    Returns:
        Tuple of (success: bool, output: str)
    """
    cmd = [EXPRESSVPN_CLI_PATH] + list(args)
    cmd_str = " ".join(cmd)
    logger.debug(f"[VPN] Running: {cmd_str}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (result.stdout + result.stderr).strip()
        success = result.returncode == 0
        if not success:
            logger.warning(f"[VPN] Command failed (rc={result.returncode}): {output}")
        return success, output
    except FileNotFoundError:
        logger.error(
            f"[VPN] ❌ expressvpnctl not found at: {EXPRESSVPN_CLI_PATH}\n"
            "  → Make sure ExpressVPN is installed and the path in config.py is correct."
        )
        return False, "File not found"
    except subprocess.TimeoutExpired:
        logger.error(f"[VPN] Command timed out after {timeout}s: {cmd_str}")
        return False, "Timeout"
    except Exception as e:
        logger.error(f"[VPN] Unexpected error: {e}")
        return False, str(e)


def check_vpn_status() -> dict:
    """
    Check the current VPN connection status.

    Returns:
        Dict with keys: connected (bool), location (str|None), output (str)
    """
    success, output = _run_vpn_command("status")
    connected = success and "connected" in output.lower()
    location = None

    if connected:
        # Try to extract location from output
        for line in output.splitlines():
            if "connected to" in line.lower() or "location" in line.lower():
                location = line.strip()
                break

    return {
        "connected": connected,
        "location": location,
        "output": output,
    }


def disconnect_vpn() -> bool:
    """Disconnect from the current VPN server."""
    logger.info("[VPN] Disconnecting...")
    success, output = _run_vpn_command("disconnect")

    if success or "not connected" in output.lower():
        logger.info("[VPN] Disconnected successfully")
        time.sleep(VPN_DISCONNECT_WAIT)
        return True

    logger.warning(f"[VPN] Disconnect may have failed: {output}")
    time.sleep(VPN_DISCONNECT_WAIT)
    return False


def connect_vpn(location: str) -> bool:
    """
    Connect to a specific VPN server location.

    Args:
        location: ExpressVPN location name (e.g., "USA - New York")

    Returns:
        True if connection succeeded.
    """
    logger.info(f"[VPN] Connecting to: {location}")
    success, output = _run_vpn_command("connect", location)

    if success or "connected" in output.lower():
        logger.info(f"[VPN] ✅ Connected to {location}")
        time.sleep(VPN_CONNECT_WAIT)
        return True

    logger.error(f"[VPN] ❌ Failed to connect to {location}: {output}")
    return False


def rotate_vpn() -> bool:
    """
    Rotate to the next US VPN server in the round-robin list.
    Disconnects current connection, then connects to the next location.

    Returns:
        True if rotation succeeded.
    """
    global _current_location_index

    # Disconnect first
    disconnect_vpn()

    # Pick the next location
    location = VPN_US_LOCATIONS[_current_location_index % len(VPN_US_LOCATIONS)]
    _current_location_index += 1

    logger.info(f"[VPN] 🔄 Rotating to: {location} (index {_current_location_index})")
    success = connect_vpn(location)

    if not success:
        # Try the next location as fallback
        fallback = VPN_US_LOCATIONS[_current_location_index % len(VPN_US_LOCATIONS)]
        _current_location_index += 1
        logger.info(f"[VPN] Fallback: trying {fallback}")
        success = connect_vpn(fallback)

    return success


def initial_connect() -> bool:
    """
    Ensure VPN is connected at script startup.
    If already connected, log the status. Otherwise, connect to the first US location.

    Returns:
        True if VPN is connected after this call.
    """
    logger.info("[VPN] Checking initial connection status...")
    status = check_vpn_status()

    if status["connected"]:
        logger.info(f"[VPN] Already connected: {status['location'] or 'unknown location'}")
        return True

    logger.info("[VPN] Not connected. Establishing initial connection...")
    return connect_vpn(VPN_US_LOCATIONS[0])
