import asyncio
import json
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace

import pytest


def adapter(tmp_path, monkeypatch):
    chrome = tmp_path / 'chrome'
    chrome.write_text('#!/bin/sh\nexit 0\n')
    chrome.chmod(0o700)
    monkeypatch.setenv('WEIMING_CHROME_PATH', str(chrome))
    class Context:
        closed = False
        cookies = None
        async def add_cookies(self, value): self.cookies = value
        async def close(self): self.closed = True
    class Browser:
        name = 'chromium'
        async def launch(self, *args, **kwargs):
            self.options = kwargs
            self.context = Context()
            return self.context
        launch_persistent_context = launch
    monkeypatch.setitem(sys.modules, 'playwright.async_api', SimpleNamespace(BrowserType=Browser))
    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'deploy/server/playwright_override/sitecustomize.py'))
    return Browser(), chrome


def test_browser_override_preserves_profile_and_headless_choice(tmp_path, monkeypatch):
    browser, chrome = adapter(tmp_path, monkeypatch)
    asyncio.run(browser.launch_persistent_context(tmp_path / 'profile', channel='chrome', headless=False))
    assert browser.options == {'headless': False, 'executable_path': str(chrome)}
    browser.name = 'firefox'
    asyncio.run(browser.launch(headless=True))
    assert browser.options == {'headless': True}


def test_credentials_are_applied_only_to_exact_tieba_profile(tmp_path, monkeypatch):
    browser, _ = adapter(tmp_path, monkeypatch)
    profile = tmp_path / 'tieba'
    cookies = tmp_path / 'cookies.json'
    saved = [{'name': 'example', 'value': 'synthetic', 'domain': '.baidu.com', 'path': '/'}]
    cookies.write_text(json.dumps(saved)); cookies.chmod(0o600)
    monkeypatch.setenv('WEIMING_TIEBA_PROFILE', str(profile))
    monkeypatch.setenv('WEIMING_TIEBA_COOKIES', str(cookies))
    other = asyncio.run(browser.launch_persistent_context(tmp_path / 'other'))
    assert other.cookies is None
    expected = asyncio.run(browser.launch_persistent_context(profile))
    assert expected.cookies == saved
    cookies.chmod(0o644)
    with pytest.raises(ValueError, match='private'):
        asyncio.run(browser.launch_persistent_context(profile))
    assert browser.context.closed
