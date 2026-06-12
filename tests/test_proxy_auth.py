"""Tests for the CDP proxy-auth machinery: the pure classifiers/deciders and
the ProxyAuthHandler / enable_proxy_auth plumbing (no real browser needed)."""

import pytest

from web_crawler.proxy import ProxyManager
from web_crawler.proxy_auth import (
    NAV_OTHER, NAV_PROXY, NAV_PROXY_AUTH, ProxyAuthHandler, classify_nav_error,
    decide_auth_response, enable_proxy_auth, should_enable_proxy_auth,
)


# ── classify_nav_error ──────────────────────────────────────
def test_classify_auth_error_full_playwright_message():
    msg = ("Page.goto: net::ERR_INVALID_AUTH_CREDENTIALS at "
           "https://www.truepeoplesearch.com/")
    assert classify_nav_error(msg) == NAV_PROXY_AUTH


@pytest.mark.parametrize("code", [
    "ERR_PROXY_CONNECTION_FAILED",
    "ERR_TUNNEL_CONNECTION_FAILED",
    "ERR_NO_SUPPORTED_PROXIES",
    "ERR_SOCKS_CONNECTION_FAILED",
    "ERR_PROXY_AUTH_UNSUPPORTED",
])
def test_classify_proxy_errors(code):
    assert classify_nav_error(f"Page.goto: net::{code} at https://x/") == NAV_PROXY


def test_classify_other():
    assert classify_nav_error("Timeout 30000ms exceeded.") == NAV_OTHER
    assert classify_nav_error("") == NAV_OTHER
    assert classify_nav_error(None) == NAV_OTHER


# ── should_enable_proxy_auth ────────────────────────────────
def test_should_enable_with_creds():
    assert should_enable_proxy_auth(
        ProxyManager(endpoint="p.webshare.io:80", username="u", password="x")) is True


def test_should_not_enable_without_username():
    assert should_enable_proxy_auth(ProxyManager(endpoint="p.webshare.io:80")) is False


def test_should_not_enable_without_endpoint():
    assert should_enable_proxy_auth(
        ProxyManager(endpoint="", username="u", password="x")) is False


# ── decide_auth_response ────────────────────────────────────
def test_decide_first_proxy_challenge_provides_creds():
    assert decide_auth_response("Proxy", False, "u", "p") == {
        "response": "ProvideCredentials", "username": "u", "password": "p"}


def test_decide_repeat_challenge_falls_back():
    # Second challenge for the same request = creds rejected; don't loop.
    assert decide_auth_response("Proxy", True, "u", "p") == {"response": "Default"}


def test_decide_server_challenge_never_gets_proxy_creds():
    assert decide_auth_response("Server", False, "u", "p") == {"response": "Default"}


# ── ProxyAuthHandler ────────────────────────────────────────
class _FakeCDPSession:
    """Records sends + registered handlers; can be told to fail on send."""

    def __init__(self, fail_on=None):
        self.sent = []
        self.handlers = []
        self.handlers_at_send = []   # how many handlers existed at each send
        self._fail_on = fail_on or set()

    def on(self, event, cb):
        self.handlers.append((event, cb))

    async def send(self, method, params=None):
        self.handlers_at_send.append(len(self.handlers))
        if method in self._fail_on:
            raise RuntimeError(f"{method} failed")
        self.sent.append((method, params))


@pytest.mark.asyncio
async def test_handler_answers_proxy_challenge_with_creds():
    cdp = _FakeCDPSession()
    handler = ProxyAuthHandler(cdp, "user1", "pw1")
    await handler._authenticate(
        {"requestId": "r1", "authChallenge": {"source": "Proxy"}})
    assert cdp.sent == [("Fetch.continueWithAuth", {
        "requestId": "r1",
        "authChallengeResponse": {"response": "ProvideCredentials",
                                  "username": "user1", "password": "pw1"},
    })]


@pytest.mark.asyncio
async def test_handler_repeat_challenge_same_request_falls_back():
    cdp = _FakeCDPSession()
    handler = ProxyAuthHandler(cdp, "user1", "pw1")
    event = {"requestId": "r1", "authChallenge": {"source": "Proxy"}}
    await handler._authenticate(event)
    await handler._authenticate(event)  # proxy asked again → creds rejected
    assert cdp.sent[1] == ("Fetch.continueWithAuth", {
        "requestId": "r1", "authChallengeResponse": {"response": "Default"}})


@pytest.mark.asyncio
async def test_handler_resumes_paused_requests():
    cdp = _FakeCDPSession()
    handler = ProxyAuthHandler(cdp, "u", "p")
    await handler._continue({"requestId": "r9"})
    assert cdp.sent == [("Fetch.continueRequest", {"requestId": "r9"})]


@pytest.mark.asyncio
async def test_handler_swallows_send_failures():
    # Interception ids go stale across navigations — sends must never raise.
    cdp = _FakeCDPSession(fail_on={"Fetch.continueRequest", "Fetch.continueWithAuth"})
    handler = ProxyAuthHandler(cdp, "u", "p")
    await handler._continue({"requestId": "r1"})
    await handler._authenticate(
        {"requestId": "r1", "authChallenge": {"source": "Proxy"}})


# ── enable_proxy_auth ───────────────────────────────────────
class _FakeContext:
    def __init__(self, session=None, raise_session=False):
        self.session = session if session is not None else _FakeCDPSession()
        self._raise_session = raise_session
        self.cdp_sessions_opened = 0

    async def new_cdp_session(self, page):
        self.cdp_sessions_opened += 1
        if self._raise_session:
            raise RuntimeError("CDP not available")
        return self.session


class _FakePageWithContext:
    def __init__(self, context):
        self.context = context


@pytest.mark.asyncio
async def test_enable_proxy_auth_enables_fetch_after_registering_handlers():
    ctx = _FakeContext()
    page = _FakePageWithContext(ctx)
    proxy = ProxyManager(endpoint="p.webshare.io:80", username="u", password="p")
    handler = await enable_proxy_auth(page, proxy)
    assert handler is not None
    assert ctx.session.sent == [("Fetch.enable", {"handleAuthRequests": True})]
    assert [e for e, _ in ctx.session.handlers] == [
        "Fetch.requestPaused", "Fetch.authRequired"]
    # Handlers must be registered BEFORE Fetch.enable, or the first paused
    # request is dropped and the page load hangs.
    assert ctx.session.handlers_at_send == [2]


@pytest.mark.asyncio
async def test_enable_proxy_auth_noop_without_creds():
    ctx = _FakeContext()
    page = _FakePageWithContext(ctx)
    assert await enable_proxy_auth(page, ProxyManager(endpoint="p.webshare.io:80")) is None
    assert ctx.cdp_sessions_opened == 0  # zero interception when no creds


@pytest.mark.asyncio
async def test_enable_proxy_auth_returns_none_when_cdp_unavailable():
    page = _FakePageWithContext(_FakeContext(raise_session=True))
    proxy = ProxyManager(endpoint="p.webshare.io:80", username="u", password="p")
    assert await enable_proxy_auth(page, proxy) is None
