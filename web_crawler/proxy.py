# ============================================================
# proxy.py — Webshare rotating-proxy manager
# ============================================================
"""Automatic IP rotation via Webshare's rotating proxy endpoint.

Instead of pinning one static proxy IP (which gets rate-limited / blocked and
has to be swapped out by hand), we send traffic through Webshare's single
*rotating* endpoint — ``p.webshare.io:9999`` — which hands out a fresh exit IP
per connection. There is no IP list to maintain: rotation is automatic.

Two consumers, one config:

- **Chrome** (the real scraper) gets ``host:port`` for ``--proxy-server``. Chrome
  cannot take credentials on the command line, so when the proxy needs a
  username/password Chrome shows its **own native proxy sign-in dialog** the
  first time a page loads — the user types the credentials there. Nothing is
  stored; this matches the project's attended, headful model (the same window
  where CAPTCHAs are solved).
- **Python HTTP** (the optional ``--verify-proxy`` IP check) uses the full proxy
  URL, which carries ``username:password`` inline — exactly like the working
  ``requests.get(..., proxies={"https": "http://user:pass@p.webshare.io:80/"})``
  example. ``requests`` handles credentialed proxies natively.

requests vs. curl: we use ``requests`` (not a ``curl`` subprocess). It's native
Python — no external binary to ship to a non-technical Windows client, real
exceptions instead of parsing stdout/exit codes, connection pooling, and it is
trivially mockable in tests. The provided ``requests.get(..., proxies=...)``
example maps directly onto :meth:`ProxyManager.as_requests_proxies`.
"""

import logging
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)

# Webshare's rotating endpoint: one host:port, a new exit IP per connection.
# Port 80 is the credentialed rotating endpoint; country-filtered usernames
# (e.g. "<user>-US-rotate") require username/password auth, not IP auth.
WEBSHARE_ROTATING_ENDPOINT = "p.webshare.io:80"
# Returns the caller's exit IP as plain text — ideal for confirming rotation.
WEBSHARE_IP_CHECK_URL = "https://ipv4.webshare.io/"


@dataclass
class ProxyManager:
    """Single source of truth for proxy configuration.

    Build one directly, or from a :class:`~web_crawler.config.Settings` via
    :meth:`from_settings`. An empty ``endpoint`` means "no proxy" (direct
    connection) so the same code path works with or without a proxy.
    """

    endpoint: str = WEBSHARE_ROTATING_ENDPOINT
    username: str = ""
    password: str = ""
    scheme: str = "http"
    ip_check_url: str = WEBSHARE_IP_CHECK_URL

    @classmethod
    def from_settings(cls, settings) -> "ProxyManager":
        """Build from a Settings-like object. An empty ``proxy_server`` disables
        the proxy. ``proxy_username``/``proxy_password`` are optional."""
        return cls(
            endpoint=(getattr(settings, "proxy_server", "") or "").strip(),
            username=(getattr(settings, "proxy_username", "") or "").strip(),
            password=(getattr(settings, "proxy_password", "") or ""),
        )

    @property
    def enabled(self) -> bool:
        """True when a proxy endpoint is configured."""
        return bool(self.endpoint)

    @property
    def host_port(self) -> str:
        """Upstream ``host:port`` for Chrome's ``--proxy-server`` (never includes
        credentials). If the proxy requires a login, Chrome prompts for it in its
        native sign-in dialog when the first page loads."""
        return self.endpoint

    def proxy_url(self) -> str:
        """Full proxy URL for ``requests``/``urllib`` (includes credentials when
        configured). Empty string when no proxy is set."""
        if not self.endpoint:
            return ""
        creds = f"{self.username}:{self.password}@" if self.username else ""
        return f"{self.scheme}://{creds}{self.endpoint}/"

    def as_requests_proxies(self) -> dict:
        """The mapping to pass to ``requests``' ``proxies=`` argument (empty dict
        when disabled, which ``requests`` treats as a direct connection)."""
        url = self.proxy_url()
        return {"http": url, "https": url} if url else {}

    def current_ip(self, timeout: int = 10) -> "str | None":
        """Return the exit IP seen through the proxy right now, or ``None`` on
        failure. Each call opens a new connection, so successive calls may
        return different IPs — that is the rotation in action."""
        if not self.enabled:
            return None
        try:
            resp = requests.get(
                self.ip_check_url,
                proxies=self.as_requests_proxies(),
                timeout=timeout,
            )
            resp.raise_for_status()
            return resp.text.strip() or None
        except requests.RequestException as e:
            logger.warning(f"[PROXY] IP check failed: {e}")
            return None

    def verify_rotation(self, samples: int = 3, timeout: int = 10) -> dict:
        """Sample the exit IP *samples* times to confirm rotation is working.

        Returns ``{"ips": [...], "unique": <int>, "rotating": <bool>}``;
        ``rotating`` is True when more than one distinct IP came back. Failed
        samples are dropped, so an empty ``ips`` list means the proxy was
        unreachable (e.g. your IP isn't authorised in the Webshare dashboard)."""
        ips = []
        for _ in range(max(1, samples)):
            ip = self.current_ip(timeout=timeout)
            if ip:
                ips.append(ip)
        unique = sorted(set(ips))
        return {"ips": ips, "unique": len(unique), "rotating": len(unique) > 1}
