"""Report routing configuration and fail-closed API behavior, no paid provider."""
import json
from pathlib import Path
import tempfile

import pytest
from fastapi.testclient import TestClient

from federation.app import create_app
from federation.core import FederationStore
from federation.report_model import (validate_config, config_path, _write_private,
                                     require_report_model, report_model_status, report_model_environment)


@pytest.fixture
def store(tmp_path):
    return FederationStore(tmp_path / 'data')


def fixture_config():
    return {'provider':'openai-compatible','model':'fixture-strong-model',
            'base_url':'https://reports.example.test/v1','api_key':'REPORT_SECRET_FIXTURE', 'responses_api':False}


def test_required_report_is_pending_without_changing_agent_config(store):
    agent_env = store.base / 'central/state/.env'
    agent_env.parent.mkdir(parents=True)
    original = b'OPENWIKI_PROVIDER=openai-compatible\nOPENWIKI_MODEL_ID=qwen3.5:9b\n'
    agent_env.write_bytes(original)
    require_report_model(store)
    require_report_model(store)
    state = report_model_status(store)
    assert state['required'] and not state['configured'] and state['fallback'] == 'disabled'
    with pytest.raises(ValueError, match='等待强模型配置'):
        report_model_environment(store)
    assert agent_env.read_bytes() == original


def test_private_config_has_redacted_public_status_and_backup(store):
    first = validate_config(fixture_config())
    _write_private(config_path(store), first)
    require_report_model(store)
    state = report_model_status(store)
    assert state['model'] == first['model'] and state['fallback'] == 'disabled'
    assert 'REPORT_SECRET_FIXTURE' not in json.dumps(state)
    environment, _ = report_model_environment(store)
    assert environment == {'FEDERATION_REPORT_MODEL_CONFIG':str(config_path(store))}
    assert 'REPORT_SECRET_FIXTURE' not in json.dumps(environment)
    _write_private(config_path(store), {**first,'model':'fixture-next-model'})
    backups = list(config_path(store).parent.glob('report-model-before-*.json'))
    assert len(backups) == 1 and json.loads(backups[0].read_text()) == first
    assert config_path(store).stat().st_mode & 0o077 == 0
    assert backups[0].stat().st_mode & 0o077 == 0


@pytest.mark.parametrize('change', [
    {'base_url':'http://remote.example/v1'}, {'base_url':'https://user:secret@reports.example/v1'},
    {'base_url':'https://reports.example/v1?key=SECRET'}, {'model':'model\nOTHER=value'},
    {'provider':'openai-chatgpt'}, {'responses_api':'true'}, {'reasoning_effort':'minimal'},
    {'provider':'gemini','base_url':'https://reports.example'}, {'unknown':'value'},
])
def test_reject_invalid_or_unrequested_auth_config(change):
    with pytest.raises(ValueError):
        validate_config({**fixture_config(),**change})


def test_invalid_private_config_and_policy_fail_closed(store):
    path = config_path(store)
    path.parent.mkdir(parents=True)
    path.write_text('{"api_key":"SECRET_BROKEN_JSON",')
    path.chmod(0o600)
    state = report_model_status(store)
    assert not state['configured'] and 'SECRET_BROKEN_JSON' not in json.dumps(state)
    with pytest.raises(ValueError):report_model_environment(store)
    path.write_text(json.dumps(fixture_config()))
    path.chmod(0o644)
    assert not report_model_status(store)['configured']
    policy = store.base / 'metadata/report-model-policy.json'
    policy.parent.mkdir(parents=True)
    policy.write_text('broken')
    policy.chmod(0o600)
    assert report_model_status(store)['fallback'] == 'disabled'


def test_api_redacts_key_and_pending_report_does_not_call_model(tmp_path):
    base = tmp_path / 'api-data'
    calls, research_calls = [], []
    async def runner(job, _store):
        calls.append(job['id'])
        job['answer'] = '普通聊天仍可回答。'
    async def researcher(*args):
        research_calls.append(args)
        return {'status':'ready','sources':[]}
    app = create_app(base=base, runner=runner, researcher=researcher)
    store = FederationStore(base)
    with TestClient(app) as client:
        require_report_model(store)
        pending = client.get('/api/agents/report-model').json()
        assert pending['fallback'] == 'disabled' and not pending['configured']
        room = client.post('/api/chat/primary', json={}).json()
        response = client.post('/api/chat/rooms/' + room['id'] + '/messages', json={
            'content':'https://product.example.test 拆解这个产品，分析实现、运营、盈利，并生成可下载文档。'})
        assert response.status_code == 200
        import time
        for _ in range(100):
            saved = client.get('/api/chat/rooms/' + room['id']).json()
            if saved['status'] not in {'queued','running'}:break
            time.sleep(0.01)
        assert saved['status'] == 'failed'
        assert not calls and not research_calls
        assert '等待强模型配置' in json.dumps(saved, ensure_ascii=False)
        assert saved['messages'][0]['role'] == 'user'
        response = client.post('/api/chat/rooms/' + room['id'] + '/messages', json={'content':'你好'})
        assert response.status_code == 200
        for _ in range(100):
            saved = client.get('/api/chat/rooms/' + room['id']).json()
            if saved['status'] not in {'queued','running'}:break
            time.sleep(0.01)
        assert saved['status'] == 'idle' and calls
        assert saved['messages'][-1]['content'] == '普通聊天仍可回答。'
        _write_private(config_path(store),fixture_config())
        assert 'REPORT_SECRET_FIXTURE' not in client.get('/api/agents/report-model').text
        assert 'REPORT_SECRET_FIXTURE' not in client.get('/api/workspace').text
