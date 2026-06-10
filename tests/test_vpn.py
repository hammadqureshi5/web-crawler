"""Tests for the VPN gate: pure evaluate_vpn, baseline I/O, and get_public_ip."""

import pytest

from web_crawler import vpn
from web_crawler.config import Settings
from web_crawler.vpn import (
    VPN_NO_BASELINE, VPN_NO_INTERNET, VPN_OFF, VPN_ON, ensure_vpn, evaluate_vpn,
    get_public_ip, read_baseline, set_baseline_interactive, write_baseline,
)


# ── evaluate_vpn truth table ────────────────────────────────
def test_evaluate_no_internet():
    assert evaluate_vpn(None, "1.2.3.4") == VPN_NO_INTERNET


def test_evaluate_no_baseline():
    assert evaluate_vpn("5.6.7.8", None) == VPN_NO_BASELINE


def test_evaluate_vpn_off_when_same():
    assert evaluate_vpn("1.2.3.4", "1.2.3.4") == VPN_OFF
    assert evaluate_vpn(" 1.2.3.4 ", "1.2.3.4") == VPN_OFF  # whitespace tolerant


def test_evaluate_vpn_on_when_different():
    assert evaluate_vpn("9.9.9.9", "1.2.3.4") == VPN_ON


# ── baseline read/write ─────────────────────────────────────
def test_baseline_roundtrip(tmp_path):
    p = tmp_path / ".vpn_baseline"
    write_baseline(str(p), "1.2.3.4")
    assert read_baseline(str(p)) == "1.2.3.4"


def test_read_baseline_missing(tmp_path):
    assert read_baseline(str(tmp_path / "nope")) is None


# ── get_public_ip (mocked network) ──────────────────────────
def test_get_public_ip_success(monkeypatch):
    class FakeResp:
        def read(self):
            return b'{"ip": "203.0.113.5"}'
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    monkeypatch.setattr(vpn.urllib.request, "urlopen", lambda *a, **k: FakeResp())
    assert get_public_ip() == "203.0.113.5"


def test_get_public_ip_failure(monkeypatch):
    def boom(*a, **k):
        raise OSError("no network")
    monkeypatch.setattr(vpn.urllib.request, "urlopen", boom)
    assert get_public_ip() is None


# ── ensure_vpn orchestration ────────────────────────────────
def test_ensure_vpn_skip(tmp_path):
    s = Settings(skip_vpn_check=True, vpn_baseline_file=str(tmp_path / "b"))
    assert ensure_vpn(s, prompt=lambda *a: "") is True


def test_ensure_vpn_on_proceeds(tmp_path, monkeypatch):
    p = tmp_path / "b"
    write_baseline(str(p), "1.1.1.1")
    s = Settings(vpn_baseline_file=str(p), require_vpn=True)
    monkeypatch.setattr(vpn, "get_public_ip", lambda *a, **k: "2.2.2.2")  # changed -> VPN on
    assert ensure_vpn(s, prompt=lambda *a: "") is True


def test_ensure_vpn_off_with_require_aborts(tmp_path, monkeypatch):
    p = tmp_path / "b"
    write_baseline(str(p), "1.1.1.1")
    s = Settings(vpn_baseline_file=str(p), require_vpn=True)
    monkeypatch.setattr(vpn, "get_public_ip", lambda *a, **k: "1.1.1.1")  # same -> VPN off
    assert ensure_vpn(s, prompt=lambda *a: "") is False


def test_ensure_vpn_off_without_require_proceeds(tmp_path, monkeypatch):
    p = tmp_path / "b"
    write_baseline(str(p), "1.1.1.1")
    s = Settings(vpn_baseline_file=str(p), require_vpn=False)
    monkeypatch.setattr(vpn, "get_public_ip", lambda *a, **k: "1.1.1.1")
    assert ensure_vpn(s, prompt=lambda *a: "") is True


def test_ensure_vpn_no_baseline_require_aborts(tmp_path):
    s = Settings(vpn_baseline_file=str(tmp_path / "absent"), require_vpn=True)
    assert ensure_vpn(s, prompt=lambda *a: "") is False


def test_set_baseline_interactive_writes(tmp_path, monkeypatch):
    p = tmp_path / "b"
    s = Settings(vpn_baseline_file=str(p))
    monkeypatch.setattr(vpn, "get_public_ip", lambda *a, **k: "8.8.8.8")
    assert set_baseline_interactive(s, prompt=lambda *a: "") is True
    assert read_baseline(str(p)) == "8.8.8.8"
