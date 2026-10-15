"""Host-only, source-only activation with a durable admission fence.

Stage and test sources before invoking. An interrupted activation leaves the
fence closed; recover with the same release directory after inspecting evidence.
Does not pause settings, replay jobs, expire a lease, or overwrite runtime data.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from urllib.request import ProxyHandler, build_opener
from federation.release_fence import ReleaseFence


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


class ReleaseSession:
    def __init__(self, base, owner, url='http://127.0.0.1:18732'):
        self.fence, self.owner, self.url = ReleaseFence(base), owner, url
        self.owner_fd, self.seal_fd = None, None
        self.http = build_opener(ProxyHandler({}))

    def status(self):
        with self.http.open(self.url + '/api/release/status', timeout=10) as response:
            return json.load(response)

    def begin(self):
        self.owner_fd = self.fence.lock('owner', exclusive=True)
        try: self.fence.write(self.owner, 'draining')
        except BaseException:
            self.close()
            raise

    def seal(self, timeout=120):
        deadline = time.monotonic() + timeout
        while True:
            status = self.status()
            if status.get('protocol') != 1 or status.get('owner') != self.owner:
                raise RuntimeError('Release protocol or owner mismatch')
            if status['ready']:
                try: self.seal_fd = self.fence.lock('activity', exclusive=True)
                except BlockingIOError: pass
                else:
                    # With admissions fenced and all activities excluded, verify
                    # durable queues as well. No snapshot-to-restart race remains.
                    status = self.status()
                    if (status['active_jobs'] or status['active_run'] or status['video_dispatches']
                            or status['activities'] or status['background_summary']):
                        os.close(self.seal_fd); self.seal_fd = None
                    else:
                        self.fence.write(self.owner, 'sealed')
                        return status
            if time.monotonic() >= deadline:
                raise TimeoutError('Drain deadline reached; no task was stopped')
            time.sleep(.5)

    def reopen(self):
        if self.owner_fd is None: raise RuntimeError('Release ownership is required')
        self.fence.write(self.owner, 'open')
        self.close()

    def close(self):
        for name in ('seal_fd', 'owner_fd'):
            fd = getattr(self, name)
            if fd is not None: os.close(fd); setattr(self, name, None)


def activate(project, release, timeout=120):
    from deploy.server.state_receipt import receipt
    project, release = Path(project).resolve(), Path(release).resolve()
    manifest = json.loads((release / 'manifest.json').read_text())
    paths = []
    for name, hashes in manifest.items():
        rel = Path(name)
        if rel.is_absolute() or '..' in rel.parts or rel.parts[0] not in {'federation', 'deploy', 'tests'}:
            raise ValueError('Only explicit source paths may be deployed')
        target, staged = project / rel, release / 'staged' / rel
        if any(parent.is_symlink() for parent in target.parents if parent != project.parent):
            raise ValueError('Source parents cannot be symlinks: ' + name)
        if target.is_symlink() or staged.is_symlink() or digest(staged) != hashes['after'] or digest(target) != hashes['before']:
            raise ValueError('Source changed or staged hash mismatch: ' + name)
        paths.append((rel, target, staged))
    if (release / 'drained.json').exists(): raise ValueError('Use a fresh activation directory')
    session = ReleaseSession(project / 'openwiki-federation', release.name)
    restarted = False
    mutated = False
    try:
        session.begin()
        drained = session.seal(timeout)
        (release / 'drained.json').write_text(json.dumps(drained, indent=2))
        before = receipt(session.url)
        (release / 'before-state.json').write_text(json.dumps(before, ensure_ascii=False, indent=2))
        for rel, target, staged in paths:
            if digest(target) != manifest[str(rel)]['before'] or digest(staged) != manifest[str(rel)]['after']:
                raise RuntimeError('Source changed while draining: ' + str(rel))
        for rel, target, staged in paths:
            if target.exists():
                backup = release / 'source-backup' / rel
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name('.' + target.name + '.release-tmp')
            shutil.copy2(staged, temporary)
            mutated = True
            os.replace(temporary, target)
        restarted = True
        subprocess.run(['systemctl', '--user', 'restart', 'weiming-api.service'], check=True)
        deadline = time.monotonic() + 120
        while True:
            try:
                after = session.status()
                if after['pid'] != drained['pid'] and after['phase'] == 'sealed' and after['owner'] == session.owner: break
            except (OSError, ValueError): pass
            if time.monotonic() > deadline: raise TimeoutError('New API not verified; fence remains sealed')
            time.sleep(.5)
        verified = receipt(session.url)
        if before['rooms'] != verified['rooms']:
            raise RuntimeError('History verification failed; fence remains sealed')
        if before['settings'] != verified['settings']:
            raise RuntimeError('Settings verification failed; fence remains sealed')
        if before['pending'] != verified['pending'] or before['agent_ids'] != verified['agent_ids']:
            raise RuntimeError('Pending work verification failed; fence remains sealed')
        if any(digest(target) != manifest[str(rel)]['after'] for rel, target, _ in paths):
            raise RuntimeError('Runtime source hash mismatch; fence remains sealed')
        (release / 'verified-state.json').write_text(json.dumps(verified, ensure_ascii=False, indent=2))
        (release / 'activation.json').write_text(json.dumps({'before_pid': drained['pid'], 'after_pid': after['pid'],
            'files_verified': len(paths), 'history_equal': True, 'settings_equal': True, 'pending_equal': True}, indent=2))
        session.reopen()
    except BaseException:
        # A timed-out drain may safely reopen: code and process are untouched.
        if not restarted and not mutated and session.owner_fd is not None: session.reopen()
        raise
    finally: session.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--release', type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=120)
    args = parser.parse_args()
    activate(args.project, args.release, args.timeout)
