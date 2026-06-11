"""Tests for the page-state detection helpers (no real browser needed)."""

import pytest

from tests.conftest import FakePage
from web_crawler.browser_search import (
    force_page_active, is_blocked, is_cloudflare_challenge, is_no_results_page,
)


# ── is_cloudflare_challenge ─────────────────────────────────
@pytest.mark.asyncio
async def test_cloudflare_by_title():
    assert await is_cloudflare_challenge(FakePage(title="Just a moment...")) is True
    assert await is_cloudflare_challenge(FakePage(title="Attention Required! | Cloudflare")) is True


@pytest.mark.asyncio
async def test_cloudflare_by_content():
    assert await is_cloudflare_challenge(
        FakePage(title="x", content="<div>Checking your browser before access</div>")) is True
    assert await is_cloudflare_challenge(
        FakePage(title="x", content="<form class='challenge-form'>")) is True


@pytest.mark.asyncio
async def test_cloudflare_negative():
    assert await is_cloudflare_challenge(
        FakePage(title="TruePeopleSearch", content="<h1>Results</h1>")) is False


@pytest.mark.asyncio
async def test_cloudflare_swallows_errors():
    assert await is_cloudflare_challenge(FakePage(raise_on={"title"})) is False


# ── is_no_results_page ──────────────────────────────────────
@pytest.mark.asyncio
async def test_no_results_positive():
    assert await is_no_results_page(
        FakePage(content="<p>No Results Found for that address</p>")) is True
    assert await is_no_results_page(
        FakePage(content="We could not find any records")) is True


@pytest.mark.asyncio
async def test_no_results_negative():
    assert await is_no_results_page(
        FakePage(content="<div class='card'>John Adams</div>")) is False


# ── is_blocked ──────────────────────────────────────────────
@pytest.mark.asyncio
async def test_blocked_by_title():
    assert await is_blocked(FakePage(title="403 Forbidden", content="")) is True


@pytest.mark.asyncio
async def test_blocked_by_content():
    assert await is_blocked(FakePage(title="x", content="Access Denied")) is True


@pytest.mark.asyncio
async def test_not_blocked():
    assert await is_blocked(FakePage(title="TruePeopleSearch", content="<h1>ok</h1>")) is False


# ── force_page_active (keeps the CAPTCHA solver alive when occluded) ──
class _FakeCDPSession:
    """Records CDP commands; can be told to fail on specific methods."""

    def __init__(self, fail_on=None):
        self.sent = []
        self._fail_on = fail_on or set()

    async def send(self, method, params=None):
        if method in self._fail_on:
            raise RuntimeError(f"{method} not supported")
        self.sent.append((method, params))


class _FakeContextWithCDP:
    def __init__(self, session=None, raise_session=False):
        self.session = session if session is not None else _FakeCDPSession()
        self._raise_session = raise_session

    async def new_cdp_session(self, page):
        if self._raise_session:
            raise RuntimeError("CDP not available")
        return self.session


class _FakePageWithContext:
    def __init__(self, context):
        self.context = context


@pytest.mark.asyncio
async def test_force_page_active_pins_focus_and_lifecycle():
    ctx = _FakeContextWithCDP()
    page = _FakePageWithContext(ctx)
    assert await force_page_active(page) is True
    methods = [m for m, _ in ctx.session.sent]
    # Both native overrides that keep the renderer "visible" are issued.
    assert methods == ["Emulation.setFocusEmulationEnabled", "Page.setWebLifecycleState"]
    assert ("Emulation.setFocusEmulationEnabled", {"enabled": True}) in ctx.session.sent
    assert ("Page.setWebLifecycleState", {"state": "active"}) in ctx.session.sent


@pytest.mark.asyncio
async def test_force_page_active_returns_false_when_cdp_unavailable():
    page = _FakePageWithContext(_FakeContextWithCDP(raise_session=True))
    assert await force_page_active(page) is False


@pytest.mark.asyncio
async def test_force_page_active_partial_support_still_applies():
    # An older Chrome may lack one command; the other should still be applied.
    session = _FakeCDPSession(fail_on={"Page.setWebLifecycleState"})
    page = _FakePageWithContext(_FakeContextWithCDP(session=session))
    assert await force_page_active(page) is True
    assert [m for m, _ in session.sent] == ["Emulation.setFocusEmulationEnabled"]
