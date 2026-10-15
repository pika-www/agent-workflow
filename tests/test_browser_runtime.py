import pytest
from federation import browser_runtime


def test_default_launch_keeps_existing_chrome_channel(monkeypatch):
    monkeypatch.delenv('WEIMING_CHROME_PATH', raising=False)
    assert browser_runtime.launch_options() == {'channel': 'chrome', 'headless': True}


def test_explicit_browser_must_be_absolute_and_executable(tmp_path, monkeypatch):
    monkeypatch.setenv('WEIMING_CHROME_PATH', 'relative/chrome')
    with pytest.raises(ValueError):
        browser_runtime.launch_options()
    chrome = tmp_path / 'chrome'
    chrome.write_text('#!/bin/sh\nexit 0\n')
    monkeypatch.setenv('WEIMING_CHROME_PATH', str(chrome))
    with pytest.raises(ValueError):
        browser_runtime.launch_options()
    chrome.chmod(0o700)
    assert browser_runtime.launch_options() == {'executable_path': str(chrome), 'headless': True}
