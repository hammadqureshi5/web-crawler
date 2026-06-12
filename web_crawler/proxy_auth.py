# ============================================================
# proxy_auth.py — Answer Chrome's proxy login over CDP
# ============================================================
"""Programmatic proxy authentication for the Webshare rotating proxy.

Chrome's ``--proxy-server`` flag cannot carry credentials, and its native
proxy sign-in dialog does **not** block CDP-driven navigations — ``page.goto``
fails instantly with ``net::ERR_INVALID_AUTH_CREDENTIALS`` before the user
could ever type a login. So when proxy credentials are configured we answer
the challenge ourselves over CDP: ``Fetch.enable(handleAuthRequests=True)``
plus ``Fetch.continueWithAuth`` (the same mechanism as puppeteer's
``page.authenticate``). Chrome still connects *directly* to the proxy — there
is no relay/midpoint process, which previously broke the target site.

Enabling the Fetch domain pauses every request on the session, so the
``Fetch.requestPaused`` handler must resume each one immediately; for that
reason the whole machinery is a no-op unless credentials are actually
configured — credential-less runs get zero interception.

The decision logic (:func:`classify_nav_error`, :func:`decide_auth_response`,
:func:`should_enable_proxy_auth`) is pure and unit-tested; the
:class:`ProxyAuthHandler` event plumbing never raises into Playwright's
dispatcher.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

# Classifications returned by classify_nav_error().
NAV_PROXY_AUTH = "PROXY_AUTH"   # the proxy rejected/required credentials
NAV_PROXY = "PROXY"             # the proxy itself is unreachable/broken
NAV_OTHER = "OTHER"             # anything else (site down, timeout, ...)

_PROXY_AUTH_ERRORS = ("ERR_INVALID_AUTH_CREDENTIALS",)
_PROXY_ERRORS = (
    "ERR_PROXY_CONNECTION_FAILED",
    "ERR_TUNNEL_CONNECTION_FAILED",
    "ERR_NO_SUPPORTED_PROXIES",
    "ERR_SOCKS_CONNECTION_FAILED",
    "ERR_PROXY_AUTH_UNSUPPORTED",
)


def classify_nav_error(msg: str) -> str:
    """Classify a navigation error message (``str(exception)`` from a failed
    ``page.goto``) as a proxy-auth failure, a general proxy failure, or other."""
    text = msg or ""
    if any(code in text for code in _PROXY_AUTH_ERRORS):
        return NAV_PROXY_AUTH
    if any(code in text for code in _PROXY_ERRORS):
        return NAV_PROXY
    return NAV_OTHER


def should_enable_proxy_auth(proxy) -> bool:
    """True when CDP auth answering should be switched on: a proxy is in use
    AND a username is configured. Without credentials we must not enable the
    Fetch domain at all (it intercepts every request for nothing)."""
    return bool(getattr(proxy, "enabled", False)) and bool(getattr(proxy, "username", ""))


def decide_auth_response(source: str, already_attempted: bool,
                         username: str, password: str) -> dict:
    """Pick the ``authChallengeResponse`` for a ``Fetch.authRequired`` event.

    Credentials are offered only for *proxy* challenges, and only once per
    request — a second challenge for the same request means the proxy rejected
    them, so we fall back to ``Default`` (the request then fails fast with
    ``ERR_INVALID_AUTH_CREDENTIALS`` instead of looping forever). Server-side
    HTTP auth (``source == "Server"``) is never answered with proxy creds.
    """
    if source == "Proxy" and not already_attempted:
        return {"response": "ProvideCredentials",
                "username": username, "password": password}
    return {"response": "Default"}


class ProxyAuthHandler:
    """Answers proxy auth challenges on one page's CDP session.

    Event callbacks are synchronous (Playwright dispatches them off pyee) and
    schedule the actual CDP sends as tasks; every send is wrapped because a
    navigation can invalidate an interception id mid-flight.
    """

    def __init__(self, cdp, username: str, password: str):
        self._cdp = cdp
        self._username = username
        self._password = password
        self._attempted: set[str] = set()   # requestIds already given creds
        self._creds_rejected = False        # log the rejection only once

    # ── sync pyee callbacks ─────────────────────────────────
    def on_request_paused(self, event):
        asyncio.ensure_future(self._continue(event))

    def on_auth_required(self, event):
        asyncio.ensure_future(self._authenticate(event))

    # ── async workers (unit-testable directly) ──────────────
    async def _continue(self, event):
        try:
            await self._cdp.send("Fetch.continueRequest",
                                 {"requestId": event["requestId"]})
        except Exception as e:
            logger.debug(f"[PROXY-AUTH] continueRequest failed (page navigated?): {e}")

    async def _authenticate(self, event):
        rid = event.get("requestId", "")
        source = (event.get("authChallenge") or {}).get("source", "")
        response = decide_auth_response(source, rid in self._attempted,
                                        self._username, self._password)
        if response["response"] == "ProvideCredentials":
            self._attempted.add(rid)
        elif source == "Proxy" and not self._creds_rejected:
            self._creds_rejected = True
            logger.error("[PROXY-AUTH] The proxy rejected the configured "
                         "credentials — check --proxy-user/--proxy-pass.")
        try:
            await self._cdp.send("Fetch.continueWithAuth",
                                 {"requestId": rid, "authChallengeResponse": response})
        except Exception as e:
            logger.debug(f"[PROXY-AUTH] continueWithAuth failed: {e}")


async def enable_proxy_auth(page, proxy) -> "ProxyAuthHandler | None":
    """Start answering proxy auth challenges for *page*, if credentials are
    configured. Returns the handler, or ``None`` when disabled or on failure
    (never raises — mirrors ``force_page_active``'s contract).

    Must be called again for any newly opened page (e.g. the crash-recovery
    tab in cli.py): the session is page-scoped.
    """
    if not should_enable_proxy_auth(proxy):
        return None
    try:
        cdp = await page.context.new_cdp_session(page)
        handler = ProxyAuthHandler(cdp, proxy.username, proxy.password)
        # Register handlers BEFORE enabling, or the first paused request is
        # dropped and the page load hangs.
        cdp.on("Fetch.requestPaused", handler.on_request_paused)
        cdp.on("Fetch.authRequired", handler.on_auth_required)
        await cdp.send("Fetch.enable", {"handleAuthRequests": True})
        logger.info(f"[PROXY-AUTH] Answering the proxy login over CDP "
                    f"(user: {proxy.username})")
        return handler
    except Exception as e:
        logger.warning(f"[PROXY-AUTH] Could not enable the CDP auth handler: {e}")
        return None
