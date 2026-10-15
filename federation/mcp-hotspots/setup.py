"""Run with Python 3.10+ to install the local MCP in an isolated project venv.

    python3.12 federation/mcp-hotspots/setup.py

The application itself can keep using its existing Python environment.
Only the pinned open-source read-only feed provider uses this environment.
"""
from pathlib import Path
import subprocess
import sys
import venv


if __name__ == '__main__':
    if sys.version_info < (3, 10):
        raise SystemExit('The MCP SDK requires Python 3.10 or newer.')
    root = Path(__file__).resolve().parents[2]
    target = root / '.venv-mcp-hotspots'
    if not target.exists():
        venv.EnvBuilder(with_pip=True).create(target)
    subprocess.run([str(target / 'bin/python'), '-m', 'pip', 'install',
        '-r', str(Path(__file__).with_name('requirements.lock.txt'))], check=True)
    print('Installed local read-only MCP: ' + str(target))
