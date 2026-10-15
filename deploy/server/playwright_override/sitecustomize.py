"""Use the operator's user-space Chrome in pinned upstream crawler processes.

Enabled only by the MCP bridge's explicit PYTHONPATH. No source snapshot is
modified; upstream isolated profiles, headless choice and other options remain.
"""
import os
import json
from pathlib import Path


def configure():
    configured = os.environ.get('WEIMING_CHROME_PATH')
    if not configured:
        return
    path = Path(configured)
    if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError('Invalid operator Chrome executable')
    try:
        from playwright.async_api import BrowserType
    except ImportError:
        return
    for name in ('launch', 'launch_persistent_context'):
        original = getattr(BrowserType, name)
        def wrap(method, method_name):
            async def launch(self, *args, **kwargs):
                if self.name == 'chromium':
                    kwargs.pop('channel', None)
                    kwargs['executable_path'] = str(path)
                context = await method(self, *args, **kwargs)
                profile = args[0] if args else kwargs.get('user_data_dir')
                expected = os.environ.get('WEIMING_TIEBA_PROFILE')
                cookie_file = os.environ.get('WEIMING_TIEBA_COOKIES')
                if (method_name == 'launch_persistent_context' and self.name == 'chromium'
                        and profile and expected and cookie_file and Path(profile).resolve() == Path(expected).resolve()):
                    cookies = Path(cookie_file)
                    if cookies.is_file():
                        if cookies.is_symlink() or cookies.stat().st_mode & 0o077 or cookies.stat().st_size > 1000000:
                            await context.close()
                            raise ValueError('Invalid private Tieba cookie file')
                        await context.add_cookies(json.loads(cookies.read_text()))
                return context
            return launch
        setattr(BrowserType, name, wrap(original, name))


configure()
