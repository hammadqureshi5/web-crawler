"""Tests for the GUI pause/stop control used by cli._run."""

import asyncio

from web_crawler.cli import RunControl


def test_initial_state():
    c = RunControl()
    assert c.stopped is False


def test_stop_sets_stopped():
    c = RunControl()
    c.stop()
    assert c.stopped is True


async def test_pause_blocks_until_resume():
    c = RunControl()
    c.pause()
    task = asyncio.create_task(c.wait_while_paused())
    await asyncio.sleep(0.2)
    assert not task.done()  # still blocked while paused
    c.resume()
    await asyncio.wait_for(task, timeout=2)  # released


async def test_stop_releases_paused_loop():
    c = RunControl()
    c.pause()
    task = asyncio.create_task(c.wait_while_paused())
    await asyncio.sleep(0.2)
    assert not task.done()
    c.stop()
    await asyncio.wait_for(task, timeout=2)  # stop un-blocks a paused wait
    assert c.stopped is True


async def test_not_paused_returns_immediately():
    c = RunControl()
    await asyncio.wait_for(c.wait_while_paused(), timeout=1)  # no-op when not paused
