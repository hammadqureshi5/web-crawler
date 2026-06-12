"""Tests for the Settings dataclass and the defaults -> env -> CLI precedence."""

import argparse

import pytest

from web_crawler.config import DEFAULTS, Settings, load_settings
from web_crawler.proxy import WEBSHARE_ROTATING_ENDPOINT


def _ns(**kw):
    """Build an argparse.Namespace with every CLI attribute defaulting to None/False."""
    base = dict(
        input=None, output=None, start=None, end=None,
        resume=False, no_resume=False, retry_failed=False,
        chrome_path=None, user_data_dir=None, profile=None, cdp_port=None,
        proxy=None, no_proxy=False,
    )
    base.update(kw)
    return argparse.Namespace(**base)


def test_defaults_are_stable():
    assert DEFAULTS.min_match_score == 0.5
    assert DEFAULTS.max_retries == 3
    assert DEFAULTS.resume is True          # auto-resume default
    assert DEFAULTS.headless is False       # manual CAPTCHA needs a window
    assert DEFAULTS.profile_dir == "Profile 11"
    # The Webshare rotating endpoint is the default — proxied unless --no-proxy.
    assert DEFAULTS.proxy_server == WEBSHARE_ROTATING_ENDPOINT


def test_viewport_property():
    s = Settings(viewport_width=800, viewport_height=600)
    assert s.viewport == {"width": 800, "height": 600}


def test_load_settings_none_returns_defaults():
    s = load_settings(None)
    assert s.resume is True
    assert s.proxy_server == WEBSHARE_ROTATING_ENDPOINT


def test_no_proxy_flag_disables_proxy():
    assert load_settings(_ns(no_proxy=True)).proxy_server == ""
    assert load_settings(_ns()).proxy_server == WEBSHARE_ROTATING_ENDPOINT


def test_cli_overrides_defaults():
    s = load_settings(_ns(input="in.csv", output="out.csv", proxy="host:9000",
                          start=2, end=9, profile="Profile 1", cdp_port=9333))
    assert s.input_csv == "in.csv"
    assert s.output_csv == "out.csv"
    assert s.proxy_server == "host:9000"
    assert s.start_row == 2 and s.end_row == 9
    assert s.profile_dir == "Profile 1"
    assert s.cdp_port == 9333


def test_no_resume_flag_disables_resume():
    assert load_settings(_ns(no_resume=True)).resume is False
    assert load_settings(_ns(resume=True)).resume is True
    assert load_settings(_ns()).resume is True  # default stays True


def test_env_overrides_default_but_cli_wins(monkeypatch):
    monkeypatch.setenv("WEB_CRAWLER_PROXY_SERVER", "envhost:1111")
    monkeypatch.setenv("WEB_CRAWLER_MAX_RETRIES", "7")
    # env applies when no CLI value
    s_env = load_settings(_ns())
    assert s_env.proxy_server == "envhost:1111"
    assert s_env.max_retries == 7
    # CLI beats env
    s_cli = load_settings(_ns(proxy="clihost:2222"))
    assert s_cli.proxy_server == "clihost:2222"


def test_env_malformed_value_ignored(monkeypatch):
    monkeypatch.setenv("WEB_CRAWLER_CDP_PORT", "not-an-int")
    s = load_settings(None)
    assert s.cdp_port == DEFAULTS.cdp_port  # falls back, doesn't crash


def test_load_settings_accepts_dict():
    s = load_settings({"input": "d.csv"})
    assert s.input_csv == "d.csv"
