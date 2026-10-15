"""Prompt-only chat forwarding, isolated data and a controlled provider."""
import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from federation.app import create_app
from federation.chat import ChatStore
from federation.core import FederationStore, _write_json
from federation.video_generation import VideoSubmission


@pytest.fixture
def connected(tmp_path):
    store = FederationStore(base=tmp_path / 'isolated-data')
    store.init()
    chat = ChatStore(store)
    room = chat.primary_room()
    calls = []
    def provider(request):
        calls.append(request)
        return httpx.Response(202, json={'promptId': 'real-contract-fixture'})
    service = VideoSubmission(store, chat=chat, client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(provider)))
    service.save_config({'base_url': 'http://provider.test:3000', 'enabled': True})
    return service, chat, room, calls


def test_chat_forwards_exact_prompt_only_and_persists_receipt(connected):
    service, chat, room, calls = connected
    prompt = '  /学习 夕阳下海边散步的猫\n镜头缓慢推进。  '
    async def run():
        first = await service.submit_chat(room['id'], prompt, 'a' * 32)
        await asyncio.gather(*service.tasks)
        again = await service.submit_chat(room['id'], prompt, 'a' * 32)
        assert first['id'] == again['id'] and again['status'] == 'submitted'
    asyncio.run(run())
    assert len(calls) == 1
    assert calls[0].url.path == '/api/workflows/reference_4step_sla_server_upload/run'
    assert json.loads(calls[0].content) == {'prompt': prompt}
    messages = chat.get_room(room['id'])['messages']
    assert len(messages) == 2 and messages[0]['content'] == prompt
    assert 'real-contract-fixture' in messages[1]['content']
    assert messages[1]['response_origin'] == 'host_video_submission' and messages[1]['model'] is None
    with pytest.raises(ValueError, match='不同参数'):
        asyncio.run(service.submit_chat(room['id'], 'different', 'a' * 32))
    assert len(calls) == 1


def test_disabled_busy_and_image_workflow_do_not_send(connected):
    service, chat, room, calls = connected
    for values, pattern in [({'enabled': False}, '尚未启用'), ({'enabled': True, 'default_workflow': 'i2v_fl2v_4step_sla_server_upload'}, '文字工作流')]:
        service.save_config(values)
        with pytest.raises(ValueError, match=pattern):
            asyncio.run(service.submit_chat(room['id'], 'prompt', 'b' * 32))
    service.save_config({'default_workflow': 'reference_4step_sla_server_upload'})
    room['status'] = 'running';chat.save_room(room)
    with pytest.raises(ValueError, match='正在处理'):
        asyncio.run(service.submit_chat(room['id'], 'prompt', 'b' * 32))
    assert not calls and not service.jobs() and not chat.get_room(room['id'])['messages']


def test_recovery_keeps_uncertainty_without_duplicate_messages(connected):
    service, chat, room, calls = connected
    async def run():
        await service.submit_chat(room['id'], 'prompt', 'c' * 32)
        await asyncio.gather(*service.tasks)
    asyncio.run(run())
    job = service.jobs()[0]
    job.update(status='submitting');_write_json(service.job_path(job['id']), job)
    recovered = VideoSubmission(service.store, chat=chat)
    recovered.recover();recovered.recover()
    assert len(chat.get_room(room['id'])['messages']) == 2
    assert chat.get_room(room['id'])['messages'][-1]['video_submission']['status'] == 'submission_unknown'
    assert not recovered.tasks and len(calls) == 1
    second = chat.create_room('direct', ['central'])
    with pytest.raises(ValueError, match='不属于当前聊天'):
        asyncio.run(recovered.submit_chat(second['id'], 'prompt', 'c' * 32))


def test_real_chat_route_skips_model_and_context(tmp_path):
    model_calls = []
    async def runner(*args, **kwargs):
        model_calls.append(True)
        raise AssertionError('Video prompt must not invoke the model')
    app = create_app(base=tmp_path / 'api-isolation', runner=runner)
    service = app.state.video_submission
    sent = []
    def provider(request):
        sent.append(json.loads(request.content))
        return httpx.Response(202, json={'promptId': 'route-fixture'})
    service.client_factory = lambda: httpx.AsyncClient(transport=httpx.MockTransport(provider))
    service.save_config({'enabled': True, 'base_url': 'http://provider.test'})
    with TestClient(app) as client:
        room = client.post('/api/chat/primary', json={}).json()
        url = '/api/chat/rooms/' + room['id'] + '/messages'
        data = {'content': '/学习 一只奔跑的猫', 'video_generation': True, 'request_id': 'd' * 32}
        reply = client.post(url, json=data)
        assert reply.status_code == 200, reply.text
        assert reply.json()['video_job']['parameters'] == {'prompt': data['content']}
        assert client.post(url, json=data).status_code == 200
        assert client.post(url, json={**data, 'research': True}).status_code == 400
        assert client.post(url, json={**data, 'file_ids': ['e' * 32]}).status_code == 400
        assert client.post(url, json={**data, 'request_id': ''}).status_code == 400
        assert client.post(url, json=data, headers={'Origin': 'https://elsewhere.test'}).status_code == 403
        assert sent == [{'prompt': data['content']}]
        assert not model_calls
