"""Tests for Chrome executable / user-data-dir resolution."""

import os

import pytest

from web_crawler import chrome
from web_crawler.chrome import default_user_data_dir, find_chrome_executable


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
