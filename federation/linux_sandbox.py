"""Linux execution in a pinned, empty Docker image with explicit library mounts.

Only an operator can set the image digest. No project, credentials, Docker
socket, host namespace or network is exposed inside the container.
"""
import asyncio
import os
from pathlib import Path
import re
import shutil
import sys
import uuid


def available():
    return (sys.platform == 'linux' and bool(shutil.which('docker')) and
            bool(re.fullmatch(r'sha256:[a-f0-9]{64}', os.environ.get('WEIMING_SANDBOX_IMAGE', ''))))


def command(directory, executable, arguments, environment, python=False):
    if not available():
        raise ValueError('Linux 隔离运行器未配置；未在宿主裸跑代码')
    directory = Path(directory).resolve()
    executable = Path(executable).absolute()
    name = 'weiming-sandbox-' + uuid.uuid4().hex
    args = [shutil.which('docker'), 'run', '--rm', '--pull=never', '--name', name, '-i',
            '--network=none', '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges',
            '--pids-limit=256', '--cpus=2', '--memory=1g', '--memory-swap=1g',
            '--ulimit=nofile=128:128', '--ulimit=fsize=12000000:12000000',
            '--ulimit=cpu=30:30', '--user', f'{os.getuid()}:{os.getgid()}',
            '--workdir', str(directory), '--tmpfs', '/tmp:rw,nosuid,nodev,size=64m,mode=1777']
    mounts = {Path('/usr/lib'), Path('/lib'), Path('/lib64'), Path('/usr/share/zoneinfo')}
    if python:
        mounts.update({Path(sys.prefix), Path('/usr/bin/python3'), Path('/usr/bin/python3.12'), Path('/usr/share/fonts')})
    else:
        mounts.add(executable.resolve())
    for path in sorted(mounts):
        if path.exists():
            args.extend(['--mount', f'type=bind,src={path.resolve()},dst={path},readonly'])
    args.extend(['--mount', f'type=bind,src={directory},dst={directory}'])
    for key, value in environment.items():
        if key in {'HOME', 'TMPDIR', 'MPLCONFIGDIR', 'LANG', 'PYTHONIOENCODING', 'OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS'}:
            args.extend(['--env', key + '=' + value])
    args.extend([os.environ['WEIMING_SANDBOX_IMAGE'], str(executable), *map(str, arguments)])
    return args, name


async def remove(name):
    if not name:
        return
    proc = await asyncio.create_subprocess_exec(shutil.which('docker'), 'rm', '-f', name,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    try:
        await asyncio.wait_for(proc.wait(), 10)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
