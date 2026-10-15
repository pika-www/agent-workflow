import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from federation.browser_state import install
from federation.core import FederationStore


@pytest.fixture
def state_api(tmp_path):
    app = FastAPI()
    store = FederationStore(base=tmp_path / 'remote-data')
    install(app, store, Path('federation/web'))
    with TestClient(app) as client:
        yield client, store


def test_notes_survive_client_recreation_and_parallel_edits(state_api):
    client, store = state_api
    original = {'notes': {'one': '原笔记'}, 'visits': ['one'], 'bookmarks': ['one']}
    assert client.post('/api/browser-state/journal', json={'value': original}).status_code == 200
    a = {**original, 'notes': {**original['notes'], 'two': '另一页笔记'}}
    b = {**original, 'notes': {**original['notes'], 'three': '第二个窗口'}, 'bookmarks': []}
    client.post('/api/browser-state/journal', json={'before': original, 'value': a})
    client.post('/api/browser-state/journal', json={'before': original, 'value': b})
    reread = client.get('/api/browser-state/journal').json()['value']
    assert reread['notes'] == {'one': '原笔记', 'two': '另一页笔记', 'three': '第二个窗口'}
    assert reread['bookmarks'] == []
    path = store.base / 'metadata/browser-state/journal.json'
    assert json.loads(path.read_text())['value'] == reread
    assert path.stat().st_mode & 0o777 == 0o600


def test_legacy_import_preserves_existing_server_notes_and_original_copy(state_api):
    client, store = state_api
    server = {'notes': {'same': '服务器新稿'}, 'visits': ['server']}
    legacy = {'notes': {'same': '浏览器旧稿', 'legacy': '未迁移笔记'}, 'visits': ['local']}
    client.post('/api/browser-state/journal', json={'value': server})
    response = client.post('/api/browser-state/journal', json={'value': legacy, 'migrate': True}).json()
    assert response['saved'] is True
    assert response['value']['notes'] == {'same': '服务器新稿', 'legacy': '未迁移笔记'}
    assert set(response['value']['visits']) == {'server', 'local'}
    assert json.loads((store.base / response['archive']).read_text()) == legacy
    repeated = client.post('/api/browser-state/journal', json={'value': legacy, 'migrate': True}).json()
    assert repeated['value'] == response['value']


def test_unrelated_room_drafts_are_not_erased_by_another_tab(state_api):
    client, _ = state_api
    url = '/api/browser-state/chat-' + 'a' * 32
    first = {'drafts': [['room-one', '尚未发送']], 'submissions': []}
    client.post(url, json={'value': first})
    client.post(url, json={'before': first, 'value': {'drafts': [*first['drafts'], ['room-two', '另一份草稿']], 'submissions': []}})
    client.post(url, json={'before': first, 'value': {'drafts': [], 'submissions': [['room-one', {'content': '尚未发送'}]]}})
    value = client.get(url).json()['value']
    assert value['drafts'] == [['room-two', '另一份草稿']]
    assert value['submissions'] == [['room-one', {'content': '尚未发送'}]]


def test_paths_are_bounded_and_reads_do_not_initialize_content(state_api):
    client, store = state_api
    assert client.get('/api/browser-state/journal').json() == {'revision': 0, 'value': {}}
    assert not (store.base / 'metadata/browser-state').exists()
    assert client.post('/api/browser-state/not-allowed', json={'value': {}}).status_code == 400
    assert client.post('/api/browser-state/journal', json={'value': {'x': 'x' * 8_000_001}}).status_code == 413
