"""Shared pytest fixtures and fakes.

``FakePage`` mimics the small slice of the Playwright async API that the
page-state helpers and the JSON-LD extractor use, so those async functions can
be tested without a real browser.
"""

import pytest


class FakePage:
    """Minimal async stand-in for a Playwright Page.

    Pass canned ``title`` / ``content`` strings and an optional list of
    ``json_ld`` block texts (returned by ``evaluate``).
    """

    def __init__(self, title="", content="", json_ld=None, raise_on=None):
        self._title = title
        self._content = content
        self._json_ld = json_ld if json_ld is not None else []
        # Set of method names that should raise, to exercise error paths.
        self._raise_on = raise_on or set()

    async def title(self):
        if "title" in self._raise_on:
            raise RuntimeError("boom")
        return self._title

    async def content(self):
        if "content" in self._raise_on:
            raise RuntimeError("boom")
        return self._content

    async def evaluate(self, _script):
        if "evaluate" in self._raise_on:
            raise RuntimeError("boom")
        return self._json_ld


@pytest.fixture
def fake_page():
    return FakePage
