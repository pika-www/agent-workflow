import asyncio
import json
from pathlib import Path

import pytest

from federation import linux_sandbox
from federation.autonomy_strategy import sandbox_node


def test_docker_command_has_explicit_isolation_and_no_project_mount(tmp_path, monkeypatch):
    monkeypatch.setattr(linux_sandbox, 'available', lambda: True)
    monkeypatch.setenv('WEIMING_SANDBOX_IMAGE', 'sha256:' + 'a' * 64)
    monkeypatch.setattr(linux_sandbox.shutil, 'which', lambda _: '/usr/bin/docker')
    args, name = linux_sandbox.command(tmp_path, '/usr/bin/node', ['probe.mjs'],
        {'HOME': str(tmp_path), 'SECRET_API_KEY': 'must-not-pass'})
    assert all(flag in args for flag in ['--network=none', '--read-only', '--cap-drop=ALL',
                                        '--security-opt=no-new-privileges', '--memory=1g'])
    assert not any('SECRET_API_KEY' in arg or '/var/run/docker.sock' in arg for arg in args)
    assert name.startswith('weiming-sandbox-')
    assert '--pull=never' in args


@pytest.mark.skipif(not linux_sandbox.available(), reason='Needs configured Linux Docker isolation')
def test_real_node_container_denies_host_files_writes_and_network(tmp_path):
    import shutil
    sentinel = tmp_path.parent / 'outside-sandbox.txt'
    sentinel.write_text('host-only')
    script = tmp_path / 'probe.mjs'
    script.write_text('''import fs from 'node:fs'; import net from 'node:net';
const denied = {};
try { fs.readFileSync(%s); denied.read = false; } catch { denied.read = true; }
try { fs.writeFileSync('/outside-workspace.txt','x'); denied.write = false; } catch { denied.write = true; }
denied.network = await new Promise(resolve => {
 const socket = net.createConnection({host:'1.1.1.1',port:443});
 socket.on('connect',()=>{socket.destroy();resolve(false)});
 socket.on('error',()=>resolve(true));socket.setTimeout(2000,()=>{socket.destroy();resolve(true)});
});
fs.writeFileSync('result.txt','42');console.log(JSON.stringify(denied));
''' % json.dumps(str(sentinel)))
    code, out, err = asyncio.run(sandbox_node(shutil.which('node'), tmp_path, script))
    assert code == 0, err.decode()
    assert json.loads(out) == {'read': True, 'write': True, 'network': True}
    assert (tmp_path / 'result.txt').read_text() == '42'
    assert sentinel.read_text() == 'host-only'
