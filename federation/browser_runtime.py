"""Operator-configured Chrome path; page content cannot choose executables."""
import os
from pathlib import Path
import shutil
import sys


def executable():
    configured = os.environ.get('WEIMING_CHROME_PATH')
    if configured:
        path = Path(configured)
        if not path.is_absolute():
            return None
    elif sys.platform == 'darwin':
        path = Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
    else:
        path = Path(shutil.which('google-chrome') or '/opt/google/chrome/chrome')
    return path if path.is_file() and os.access(path, os.X_OK) else None


def launch_options():
    if os.environ.get('WEIMING_CHROME_PATH'):
        path = executable()
        if path is None:
            raise ValueError('配置的 Chrome 程序不存在或不可执行')
        return {'executable_path': str(path), 'headless': True}
    return {'channel': 'chrome', 'headless': True}
