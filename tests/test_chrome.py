"""Tests for Chrome executable / user-data-dir resolution."""

import os

import pytest

from web_crawler import chrome
from web_crawler.chrome import (
    _pids_using_user_data_dir,
    build_chrome_args,
    default_user_data_dir,
    find_chrome_executable,
)
from web_crawler.config import Settings


def test_explicit_path_used_when_exists(tmp_path):
    exe = tmp_path / "chrome.exe"
    exe.write_text("", encoding="utf-8")
    assert find_chrome_executable(str(exe)) == str(exe)


def test_explicit_path_missing_raises():
    with pytest.raises(FileNotFoundError):
        find_chrome_executable(r"C:\nope\chrome.exe")


def test_autodetect_picks_first_existing(tmp_path, monkeypatch):
    real = tmp_path / "chrome.exe"
    real.write_text("", encoding="utf-8")
    # Point the common-paths list at our fake exe.
    monkeypatch.setattr(chrome, "_COMMON_CHROME_PATHS", [str(real)])
    monkeypatch.setattr(chrome, "_localappdata_chrome", lambda: "")
    monkeypatch.setattr(chrome, "_registry_chrome", lambda: None)
    monkeypatch.setattr(chrome.shutil, "which", lambda *a: None)
    assert find_chrome_executable(None) == str(real)


def test_autodetect_none_found_raises(monkeypatch):
    monkeypatch.setattr(chrome, "_COMMON_CHROME_PATHS", [])
    monkeypatch.setattr(chrome, "_localappdata_chrome", lambda: "")
    monkeypatch.setattr(chrome, "_registry_chrome", lambda: None)
    monkeypatch.setattr(chrome.shutil, "which", lambda *a: None)
    with pytest.raises(FileNotFoundError):
        find_chrome_executable(None)


def test_autodetect_falls_through_to_registry(tmp_path, monkeypatch):
    reg = tmp_path / "chrome.exe"
    reg.write_text("", encoding="utf-8")
    monkeypatch.setattr(chrome, "_COMMON_CHROME_PATHS", [r"C:\nope\chrome.exe"])
    monkeypatch.setattr(chrome, "_localappdata_chrome", lambda: "")
    monkeypatch.setattr(chrome, "_registry_chrome", lambda: str(reg))
    monkeypatch.setattr(chrome.shutil, "which", lambda *a: None)
    assert find_chrome_executable(None) == str(reg)


def test_default_user_data_dir(monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\Someone\AppData\Local")
    expected = os.path.join(r"C:\Users\Someone\AppData\Local", "Google", "Chrome", "User Data")
    assert default_user_data_dir() == expected


# ── scoped kill: only the project profile's PIDs are matched ───────────────

_PROJECT_DIR = r"C:\proj\.chrome-profile"
_REAL_DIR = r"C:\Users\Someone\AppData\Local\Google\Chrome\User Data"


def test_pids_match_only_project_profile():
    procs = [
        {"ProcessId": 100, "CommandLine": f'chrome.exe --user-data-dir={_PROJECT_DIR} --profile-directory="Profile 11"'},
        {"ProcessId": 101, "CommandLine": f'chrome.exe --type=renderer --user-data-dir={_PROJECT_DIR}'},
        {"ProcessId": 200, "CommandLine": f'chrome.exe --user-data-dir={_REAL_DIR}'},   # everyday Chrome
        {"ProcessId": 300, "CommandLine": "chrome.exe"},                                 # everyday Chrome, no flag
    ]
    pids = _pids_using_user_data_dir(procs, _PROJECT_DIR)
    assert pids == [100, 101]


def test_pids_match_is_case_insensitive():
    procs = [{"ProcessId": 7, "CommandLine": f"chrome.exe --user-data-dir={_PROJECT_DIR.upper()}"}]
    assert _pids_using_user_data_dir(procs, _PROJECT_DIR) == [7]


def test_pids_empty_when_none_match():
    procs = [{"ProcessId": 200, "CommandLine": f"chrome.exe --user-data-dir={_REAL_DIR}"}]
    assert _pids_using_user_data_dir(procs, _PROJECT_DIR) == []


def test_pids_tolerate_missing_commandline():
    procs = [{"ProcessId": 1, "CommandLine": None}, {"ProcessId": 2}]
    assert _pids_using_user_data_dir(procs, _PROJECT_DIR) == []


# ── chrome launch args ──────────────────────────────────────────────────────

def test_build_chrome_args_disables_occlusion_so_captcha_solves_when_covered():
    # If another window covers Chrome, without this flag the page goes "hidden"
    # and the CAPTCHA solver stalls. The flag keeps it treated as visible.
    args = build_chrome_args(Settings(), r"C:\proj\.chrome-profile")
    assert "--disable-features=CalculateNativeWinOcclusion" in args
    assert "--disable-backgrounding-occluded-windows" in args
    assert r"--user-data-dir=C:\proj\.chrome-profile" in args


def test_build_chrome_args_includes_proxy_when_set():
    args = build_chrome_args(Settings(), r"C:\p", proxy_server="p.webshare.io:80")
    assert "--proxy-server=p.webshare.io:80" in args
    assert "--proxy-bypass-list=localhost,127.0.0.1" in args


def test_build_chrome_args_no_proxy_flag_when_unset():
    args = build_chrome_args(Settings(), r"C:\p", proxy_server="")
    assert not any(a.startswith("--proxy-server") for a in args)
