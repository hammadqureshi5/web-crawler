"""Tests for the Webshare rotating-proxy ProxyManager.

The pure URL/config builders are tested directly; the HTTP methods
(current_ip / verify_rotation) are tested against a fake requests.get, so no
network or real proxy is involved."""

import pytest

from web_crawler import proxy as proxy_mod
from web_crawler.config import Settings
from web_crawler.proxy import WEBSHARE_ROTATING_ENDPOINT, ProxyManager


# ── pure config / URL building ─────────────────────────────────────────────

def test_default_endpoint_is_webshare_rotating():
    assert ProxyManager().endpoint == WEBSHARE_ROTATING_ENDPOINT
    assert ProxyManager().enabled is True


def test_disabled_when_no_endpoint():
    pm = ProxyManager(endpoint="")
    assert pm.enabled is False
    assert pm.proxy_url() == ""
    assert pm.as_requests_proxies() == {}
    assert pm.host_port == ""


def test_host_port_never_includes_credentials():
    pm = ProxyManager(endpoint="p.webshare.io:9999", username="user", password="pw")
    # Chrome's --proxy-server can't take inline creds — host:port only.
    assert pm.host_port == "p.webshare.io:9999"


def test_proxy_url_without_credentials_is_ip_authorised():
    pm = ProxyManager(endpoint="p.webshare.io:9999")
    assert pm.proxy_url() == "http://p.webshare.io:9999/"


def test_proxy_url_with_credentials():
    pm = ProxyManager(endpoint="p.webshare.io:9999", username="bob", password="s3cret")
    assert pm.proxy_url() == "http://bob:s3cret@p.webshare.io:9999/"


def test_as_requests_proxies_maps_both_schemes():
    pm = ProxyManager(endpoint="p.webshare.io:9999")
    proxies = pm.as_requests_proxies()
    assert proxies == {
        "http": "http://p.webshare.io:9999/",
        "https": "http://p.webshare.io:9999/",
    }


def test_from_settings_reads_proxy_fields():
    s = Settings(proxy_server="  host:8080  ", proxy_username="u", proxy_password="p")
    pm = ProxyManager.from_settings(s)
    assert pm.endpoint == "host:8080"   # trimmed
    assert pm.username == "u"
    assert pm.password == "p"


def test_from_settings_empty_proxy_is_disabled():
    pm = ProxyManager.from_settings(Settings(proxy_server=""))
    assert pm.enabled is False


# ── HTTP methods against a fake requests.get ───────────────────────────────

class _FakeResp:
    def __init__(self, text, status=200):
        self.text = text
        self._status = status

    def raise_for_status(self):
        if self._status >= 400:
            raise proxy_mod.requests.HTTPError(f"status {self._status}")


def _patch_get(monkeypatch, responses):
    """Make requests.get pop from *responses* (a list of _FakeResp or Exception)
    and record the proxies it was called with."""
    calls = []

    def fake_get(url, proxies=None, timeout=None):
        calls.append({"url": url, "proxies": proxies, "timeout": timeout})
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(proxy_mod.requests, "get", fake_get)
    return calls


def test_current_ip_returns_trimmed_ip(monkeypatch):
    calls = _patch_get(monkeypatch, [_FakeResp("  1.2.3.4\n")])
    pm = ProxyManager(endpoint="p.webshare.io:9999")
    assert pm.current_ip() == "1.2.3.4"
    # Confirms the request actually went through the proxy.
    assert calls[0]["proxies"] == pm.as_requests_proxies()
    assert calls[0]["url"] == pm.ip_check_url


def test_current_ip_disabled_returns_none(monkeypatch):
    # Should not even call requests.get when no proxy is configured.
    _patch_get(monkeypatch, [_FakeResp("nope")])
    assert ProxyManager(endpoint="").current_ip() is None


def test_current_ip_swallows_request_errors(monkeypatch):
    _patch_get(monkeypatch, [proxy_mod.requests.ConnectionError("boom")])
    assert ProxyManager(endpoint="p.webshare.io:9999").current_ip() is None


def test_verify_rotation_detects_rotation(monkeypatch):
    _patch_get(monkeypatch, [_FakeResp("1.1.1.1"), _FakeResp("2.2.2.2"), _FakeResp("3.3.3.3")])
    result = ProxyManager(endpoint="p.webshare.io:9999").verify_rotation(samples=3)
    assert result["ips"] == ["1.1.1.1", "2.2.2.2", "3.3.3.3"]
    assert result["unique"] == 3
    assert result["rotating"] is True


def test_verify_rotation_flags_single_ip(monkeypatch):
    _patch_get(monkeypatch, [_FakeResp("9.9.9.9"), _FakeResp("9.9.9.9")])
    result = ProxyManager(endpoint="p.webshare.io:9999").verify_rotation(samples=2)
    assert result["unique"] == 1
    assert result["rotating"] is False


def test_verify_rotation_drops_failed_samples(monkeypatch):
    _patch_get(monkeypatch, [
        _FakeResp("1.1.1.1"),
        proxy_mod.requests.Timeout("slow"),
        _FakeResp("2.2.2.2"),
    ])
    result = ProxyManager(endpoint="p.webshare.io:9999").verify_rotation(samples=3)
    assert result["ips"] == ["1.1.1.1", "2.2.2.2"]   # the timeout sample is dropped
    assert result["rotating"] is True


def test_chrome_proxy_server_value_has_no_credentials():
    # Chrome gets the bare upstream host:port; the login is entered in Chrome's
    # native sign-in dialog, never passed on the command line.
    pm = ProxyManager(endpoint="p.webshare.io:80", username="u", password="pw")
    assert pm.host_port == "p.webshare.io:80"
