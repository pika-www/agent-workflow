"""Execute learned policy code in a disposable OS sandbox, without credentials."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import signal
import tempfile


def sandbox_profile(directory, node):
    roots = {str(Path(directory).resolve()), str(Path(node).resolve().parent.parent),
             '/System/Library', '/usr/lib', '/usr/share', '/private/var/db/timezone'}
    q = lambda x: json.dumps(str(x), ensure_ascii=False)
    exceptions = ['(require-not (subpath ' + q(r) + '))' for r in roots]
    parents = {str(parent) for root in roots for parent in Path(root).parents}
    exceptions += ['(require-not (literal ' + q(parent) + '))' for parent in parents]
    exceptions += ['(require-not (literal ' + q(r) + '))' for r in ['/dev/null', '/dev/random', '/dev/urandom']]
    return '\n'.join(['(version 1)', '(allow default)', '(deny network*)',
        '(deny file-read-data (require-all ' + ' '.join(exceptions) + '))',
        '(deny file-write* (require-all (require-not (subpath ' + q(Path(directory).resolve()) + ')) (require-not (literal "/dev/null"))))',
        '(deny process-exec (require-not (literal ' + q(Path(node).resolve()) + ')))',
        '(deny mach-lookup)', '(deny process-info* (require-not (target self)))'])


async def sandbox_node(node, directory, script, timeout=20, stdin=b''):
    from . import linux_sandbox
    container = None
    env = {'PATH': '/usr/bin:/bin', 'TMPDIR': str(directory), 'LANG': 'en_US.UTF-8'}
    if linux_sandbox.available():
        command, container = linux_sandbox.command(directory, Path(node).resolve(), [script], env)
    elif Path('/usr/bin/sandbox-exec').exists():
        profile = Path(directory) / 'sandbox.sb'
        profile.write_text(sandbox_profile(directory, node))
        command = ['/usr/bin/sandbox-exec', '-f', str(profile), str(Path(node).resolve()), str(script)]
    else:
        raise ValueError('当前环境缺少代码升级隔离运行器')
    process = await asyncio.create_subprocess_exec(*command, cwd=directory, env=env, start_new_session=True,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(process.communicate(stdin), timeout)
        if len(out) + len(err) > 100000:
            raise ValueError('隔离代码输出超过预算')
        return process.returncode, out, err
    except BaseException:
        if process.returncode is None:
            os.killpg(process.pid, signal.SIGKILL)
            await process.wait()
        raise
    finally:
        await asyncio.shield(linux_sandbox.remove(container))


async def strategy(store, operation, **data):
    with tempfile.TemporaryDirectory(prefix='weiming-policy-') as tmp:
        directory = Path(tmp)
        for filename in ('learning-strategy.mjs', 'autonomy-strategy-runner.mjs'):
            source = store.project_root / 'federation' / filename
            if source.is_symlink():
                raise ValueError('学习策略不允许符号链接')
            shutil.copyfile(source, directory / filename)
        code, out, err = await sandbox_node(store.node, directory, directory / 'autonomy-strategy-runner.mjs',
            stdin=json.dumps({'operation': operation, **data}, ensure_ascii=False).encode())
        if code != 0:
            raise ValueError('行业学习策略运行失败：' + err.decode(errors='replace')[-500:])
        return json.loads(out)
