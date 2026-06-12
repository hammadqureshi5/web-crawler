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

    def __init__(self, title="", content="", json_ld=None, raise_on=None,
                 goto_error=None, evaluate_result=None):
        self._title = title
        self._content = content
        self._json_ld = json_ld if json_ld is not None else []
        # Set of method names that should raise, to exercise error paths.
        self._raise_on = raise_on or set()
        # Exception instance for goto() to raise (None = goto succeeds).
        self._goto_error = goto_error
        # Overrides the evaluate() return value (else json_ld is returned).
        self._evaluate_result = evaluate_result

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
        if self._evaluate_result is not None:
            return self._evaluate_result
        return self._json_ld

    async def goto(self, url, **kwargs):
        if self._goto_error is not None:
            raise self._goto_error


@pytest.fixture
def fake_page():
    return FakePage
