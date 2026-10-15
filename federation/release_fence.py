"""Cross-process release admission and activity locks; failed releases stay closed.

Only a host-side release owner may change the durable fence. HTTP clients can
inspect it, but cannot open it or acquire release ownership. No expiry can race
with a delayed restart. Existing admitted work drains under shared activity locks.
"""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
from .core import _now, _write_json


class ReleaseDraining(Exception):
    pass


class ReleaseFence:
    def __init__(self, base):
        self.root = Path(base) / 'metadata/runtime-release'
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.root / 'state.json'
        self.activities = 0

    def state(self):
        try:
            if not self.path.exists(): return {'phase': 'open', 'owner': None}
            value = json.loads(self.path.read_text())
            if value.get('phase') not in {'open', 'draining', 'sealed'}:
                raise ValueError('Invalid phase')
            return value
        except (OSError, ValueError, TypeError, AttributeError):
            return {'phase': 'invalid', 'owner': None}

    def closed(self):
        return self.state()['phase'] != 'open'

    def lock(self, name, exclusive=False):
        fd = os.open(self.root / (name + '.lock'), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BaseException:
            os.close(fd)
            raise
        return fd

    @contextmanager
    def activity(self, *, admitted=False, draft=False):
        try:
            fd = self.lock('activity')
        except BlockingIOError:
            raise ReleaseDraining() from None
        try:
            phase = self.state()['phase']
            if not admitted and phase != 'open' and not (draft and phase == 'draining'):
                raise ReleaseDraining()
            self.activities += 1
            try: yield
            finally: self.activities -= 1
        finally:
            os.close(fd)

    @contextmanager
    def background(self):
        """Reject only the next iteration; never cancel an active iteration."""
        lease = self.activity()
        try: lease.__enter__()
        except ReleaseDraining:
            yield False
            return
        try: yield True
        finally: lease.__exit__(None, None, None)

    def idle(self):
        try: fd = self.lock('activity', exclusive=True)
        except BlockingIOError: return False
        os.close(fd)
        return True

    def write(self, owner, phase):
        # Called only with the host-side owner lock held, never from HTTP.
        current = self.state()
        if current['phase'] != 'open' and current.get('owner') != owner:
            raise ValueError('Another release owns the fence; inspect and recover it explicitly')
        _write_json(self.path, {'version': 1, 'owner': owner, 'phase': phase, 'updated_at': _now()})


class ReleaseAdmission:
    """Hold admission through the full ASGI response, including threadpool writes."""
    def __init__(self, app, fence):
        self.app, self.fence = app, fence

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] in {'GET', 'HEAD', 'OPTIONS'}:
            return await self.app(scope, receive, send)
        # Drafts may persist while old work drains. They still hold the same
        # activity lock, so sealing atomically excludes these writes too.
        draft = scope.get('path', '').startswith('/api/browser-state/')
        lease = self.fence.activity(draft=draft)
        try: lease.__enter__()
        except ReleaseDraining:
            from starlette.responses import JSONResponse
            response = JSONResponse({'detail': '正在安全发布，已受理的任务继续处理。请保留输入，稍后重新发送。',
                                     'code': 'release_draining', 'accepted': False}, status_code=503,
                                    headers={'Retry-After': '5', 'Cache-Control': 'no-store'})
            return await response(scope, receive, send)
        try: return await self.app(scope, receive, send)
        finally: lease.__exit__(None, None, None)
