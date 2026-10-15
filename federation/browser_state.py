"""Server persistence for browser drafts, reading notes and view preferences."""
import fcntl
import hashlib
import json
import os
import re
from contextlib import contextmanager

from fastapi import HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .core import _write_json


class StateInput(BaseModel):
    before: dict = Field(default_factory=dict)
    value: dict
    migrate: bool = False


MISSING = object()


def merge_changes(current, before, value):
    """Apply only the client's edits, preserving other tabs' unrelated edits."""
    if before == value:
        return current
    if all(isinstance(v, dict) for v in (current, before, value)):
        result = dict(current)
        for key in set(before) | set(value):
            old, new = before.get(key, MISSING), value.get(key, MISSING)
            if old == new:
                continue
            if new is MISSING:
                result.pop(key, None)
            else:
                empty = {} if isinstance(new, dict) else [] if isinstance(new, list) else None
                result[key] = merge_changes(current.get(key, empty), empty if old is MISSING else old, new)
        return result
    if all(isinstance(v, list) for v in (current, before, value)):
        lists = (current, before, value)
        if all(isinstance(item, str) for items in lists for item in items):
            removed = set(before) - set(value)
            return list(dict.fromkeys([*value, *(v for v in current if v not in removed)]))[:500]
        if all(isinstance(item, list) and len(item) == 2 and isinstance(item[0], str)
               for items in lists for item in items):
            return list(map(list, merge_changes(dict(current), dict(before), dict(value)).items()))
    return value


class BrowserState:
    def __init__(self, store):
        self.store = store

    def path(self, key):
        if not re.fullmatch(r'journal|chat-[a-f0-9]{32}', key):
            raise HTTPException(400, '浏览器状态标识无效')
        return self.store._safe(self.store.base, 'metadata/browser-state/' + key + '.json')

    def read(self, key):
        path = self.path(key)
        return json.loads(path.read_text()) if path.is_file() else {'revision': 0, 'value': {}}

    @contextmanager
    def locked(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path.with_suffix('.lock'), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def save(self, key, data):
        raw = json.dumps(data.value, ensure_ascii=False).encode()
        if len(raw) > 8_000_000 or len(json.dumps(data.before).encode()) > 8_000_000:
            raise HTTPException(413, '浏览器草稿或手记超过保存大小限制')
        path = self.path(key)
        with self.locked(path):
            current = self.read(key)
            archive = None
            # Before removing a legacy browser copy, retain its exact JSON on
            # the server. Divergent tabs also retain recoverable source values.
            if data.migrate or current['value'] != data.before:
                digest = hashlib.sha256(raw).hexdigest()
                archive = f'metadata/browser-state/imports/{key}-{digest}.json'
                _write_json(self.store._safe(self.store.base, archive), data.value)
                if current['value'] and not data.migrate:
                    _write_json(self.store._safe(self.store.base,
                        f'metadata/browser-state/conflicts/{key}-{current["revision"]}.json'), current['value'])
            if data.migrate:
                # Existing server entries win a migration conflict; the old
                # browser value remains intact in the import receipt above.
                value = merge_changes(data.value, {}, current['value'])
            else:
                value = merge_changes(current['value'], data.before, data.value)
            saved = {'revision': current['revision'] + 1, 'value': value}
            _write_json(path, saved)
            return {**saved, 'saved': True, 'archive': archive}


def install(app, store, web):
    state = BrowserState(store)

    @app.get('/api/browser-state/{key}')
    async def get_state(key: str):
        return state.read(key)

    @app.post('/api/browser-state/{key}')
    async def save_state(key: str, data: StateInput):
        return state.save(key, data)

    @app.get('/browser-state.js')
    async def browser_state_script():
        return FileResponse(web / 'browser-state.js', media_type='text/javascript')
