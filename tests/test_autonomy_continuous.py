"""Local-only routing, durable budgets and foreground priority contracts."""
import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from federation.autonomy import AutonomyDeferred, read_json
from federation.core import _write_json, _now
from federation import autonomy_model
from test_autonomy import setup_manager


def test_local_budget_does_not_spend_or_reset_cloud_budget(tmp_path):
    manager, calls = setup_manager(tmp_path)
    original = {'date': manager.budget()['date'], 'calls': 96}
    _write_json(manager.root / 'budget.json', original)
    assert manager.due() is None
    manager.configure({'model_policy': 'local', 'continuous_learning': True})
    run = asyncio.run(manager.learn(manager.store.space('software')))
    assert run['status'] == 'completed'
    assert len(calls) == 3 and manager.budget()['calls'] == 3
    assert read_json(manager.root / 'budget.json', {}) == original
    assert manager.budget_available(1000)
    manager.configure({'model_policy': 'tool_agent'})
    assert manager.budget() == original and manager.due() is None


def test_continuous_rotates_but_respects_failed_run_backoff(tmp_path):
    manager, _ = setup_manager(tmp_path)
    now = datetime.now(timezone.utc)
    states = {a['id']: {'status': 'completed', 'last_attempt': (now-timedelta(hours=1)).isoformat(),
              'next_at': (now+timedelta(hours=23)).isoformat()} for a in manager.store.spaces()}
    _write_json(manager.root / 'agents.json', states)
    assert manager.due(now) is None
    manager.configure({'continuous_learning': True})
    first = manager.due(now)['id']
    states[first].update(status='retry_pending', pending_run='a'*32)
    _write_json(manager.root / 'agents.json', states)
    assert manager.due(now)['id'] != first
    assert manager.states()[first]['pending_run'] == 'a'*32


def test_local_mode_resumes_cloud_budget_wait_without_resetting_goal(tmp_path):
    manager, _ = setup_manager(tmp_path)
    manager.configure({'daily_model_calls': 1})
    old = asyncio.run(manager.learn(manager.store.space('software')))
    assert old['status'] == 'budget_wait'
    manager.configure({'model_policy': 'local', 'continuous_learning': True})
    resumed = asyncio.run(manager.learn(manager.store.space('software')))
    assert resumed['status'] == 'completed'
    assert resumed['resumed_from'] == old['id']
    assert resumed['original_goal'] == old['original_goal']


def test_foreground_arrival_cancels_background_model_and_preserves_cursor(tmp_path):
    async def scenario():
        manager, _ = setup_manager(tmp_path)
        manager.configure({'model_policy': 'local'})
        idle = True
        manager.idle = lambda: idle
        entered, cancelled = asyncio.Event(), asyncio.Event()
        async def model(*args):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        manager.model = model
        run = {'id': '1'*32, 'cursor': 'review', 'original_goal': 'keep this goal'}
        manager.save(run)
        pending = asyncio.create_task(manager.call(run, 'review', {}))
        await entered.wait()
        idle = False
        with pytest.raises(AutonomyDeferred) as exc:
            await asyncio.wait_for(pending, 2)
        assert exc.value.status == 'foreground_wait'
        assert cancelled.is_set()
        saved = read_json(manager.root/'runs'/run['id']/'run.json', {})
        assert saved['cursor'] == 'review' and saved['original_goal'] == 'keep this goal'
    asyncio.run(scenario())


def test_local_route_ignores_proxy_and_cloud_config_and_validates_completion(tmp_path, monkeypatch):
    manager, _ = setup_manager(tmp_path)
    manager.configure({'model_policy': 'local'})
    monkeypatch.setattr(autonomy_model, 'model_config', lambda *a: pytest.fail('Cloud config was read'))
    monkeypatch.setenv('OPENAI_COMPATIBLE_BASE_URL', 'http://127.0.0.1:11436/v1')
    monkeypatch.setenv('HTTPS_PROXY', 'http://unreachable.invalid:9000')
    seen = []
    reply = {'done': True, 'done_reason': 'stop', 'model': 'qwen3.5:9b',
             'message': {'content': '{"ok":true}'}, 'prompt_eval_count': 40, 'eval_count': 6}
    async def transport(request):
        seen.append(request)
        assert str(request.url) == 'http://127.0.0.1:11436/api/chat'
        assert 'authorization' not in request.headers
        body = json.loads(request.content)
        assert body['format'] == 'json' and body['think'] is False
        return httpx.Response(200, json=reply)
    client_type = httpx.AsyncClient
    def client(**kwargs):
        assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        return client_type(**kwargs, transport=httpx.MockTransport(transport))
    monkeypatch.setattr(autonomy_model.httpx, 'AsyncClient', client)
    result, receipt = asyncio.run(autonomy_model.structured_call(manager.store, 'fixture', {'task': 'JSON'}))
    assert result == {'ok': True} and receipt['provider'] == 'local-ollama'
    assert receipt['cloud_fallback'] is False
    reply['done_reason'] = 'length'
    with pytest.raises(ValueError, match='未完整完成'):
        asyncio.run(autonomy_model.structured_call(manager.store, 'fixture', {}))
    assert len(seen) == 2


def test_server_local_only_policy_cannot_be_overridden_by_ui(tmp_path, monkeypatch):
    manager, _ = setup_manager(tmp_path)
    monkeypatch.setenv('WEIMING_AUTONOMY_LOCAL_ONLY', '1')
    manager.configure({'model_policy': 'tool_agent'})
    assert manager.settings()['model_policy'] == 'local'
    assert manager.budget_path().name == 'local-budget.json'
