"""Tests for the page-state detection helpers (no real browser needed)."""

import pytest

from tests.conftest import FakePage
from web_crawler.browser_search import (
    is_blocked, is_cloudflare_challenge, is_no_results_page,
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
