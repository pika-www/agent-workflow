import asyncio
import json
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from federation.app import create_app
from federation.core import _write_json
from federation.video_intent import video_intent, recent_video_context
from federation.video_status import query_video_status


CASES = json.loads((Path(__file__).parent / 'fixtures/video-intent-cases.json').read_text())


@pytest.mark.parametrize('text,selected,recent,expected', CASES)
def test_intent(text, selected, recent, expected):
    assert video_intent(text, selected, recent) == expected


def test_topic_change_ends_implicit_video_context():
    messages = [{'role': 'assistant', 'response_origin': 'host_video_submission'}]
    assert recent_video_context({'messages': messages})
    messages.append({'role': 'user', 'content': '帮我检查代码'})
    assert not recent_video_context({'messages': messages})


@pytest.fixture
def api(tmp_path):
    calls, model_calls = [], []
    async def runner(job, store):
        model_calls.append(job.copy())
        job.update(answer='你好，我是未明。', response_origin='simple_chat_model')
    app = create_app(base=tmp_path / 'video-intent-isolated', runner=runner)
    service = app.state.video_submission
    def provider(request):
        calls.append((request.method, request.url.path))
        assert request.method == 'GET', 'Status queries must never create video jobs'
        assert request.headers.get('x-api-key') == 'fixture-key'
        return httpx.Response(200, json={'status': 'running', 'files': []})
    service.client_factory = lambda: httpx.AsyncClient(transport=httpx.MockTransport(provider))
    service.save_config({'enabled': True, 'base_url': 'http://video.test', 'api_key': 'fixture-key'})
    with TestClient(app) as client:
        room = app.state.chat.primary_room()
        yield app, client, room, calls, model_calls


def seed(service, room, identifier='a' * 32, **values):
    job = {'id': identifier, 'chat_room_id': room['id'], 'status': 'submitted',
           'created_at': '2026-10-12T00:00:00+00:00', 'workflow': 'reference_4step_sla_server_upload',
           'parameters': {'prompt': '一只猫在海边散步'}, 'receipt': {'promptId': identifier},
           'message': '提示词已提交。', **values}
    _write_json(service.job_path(identifier), job)
    service.sync_chat(job)
    return job


@pytest.mark.parametrize('selected', [True, False])
def test_status_bypasses_model_and_generation_even_with_stale_mode(api, selected):
    app, client, room, calls, models = api
    service = app.state.video_submission
    seed(service, room)
    # Ignore a pre-fix status question accidentally sent as a generation prompt.
    seed(service, room, 'b' * 32, created_at='2026-10-12T00:01:00+00:00',
         parameters={'prompt': '检查一下视频生成好了吗？'})
    response = client.post('/api/chat/rooms/' + room['id'] + '/messages', json={
        'content': '检查一下视频生成好了吗？', 'video_generation': selected})
    assert response.status_code == 200, response.text
    value = response.json()
    assert value['intent'] == 'video_status' and value['video_status']['status'] == 'running'
    assert value['message']['response_origin'] == 'host_video_status'
    assert calls == [('GET', '/api/jobs/' + 'a' * 32)] and not models
    assert len(service.jobs()) == 2


def test_no_task_and_cross_room_do_not_leak_or_create(api):
    app, client, room, calls, models = api
    other = app.state.chat.create_room('direct', ['central'])
    seed(app.state.video_submission, other)
    response = client.post('/api/chat/rooms/' + room['id'] + '/messages', json={
        'content': '检查视频进度 ' + 'a' * 32, 'video_generation': True})
    assert response.json()['video_status']['status'] == 'not_found'
    assert not calls and not models


def test_latest_valid_job_uses_creation_time_not_last_modified(api):
    app, client, room, calls, models = api
    service = app.state.video_submission
    seed(service, room, 'b' * 32, created_at='2026-10-12T00:01:00+00:00')
    seed(service, room)  # Older job was just written again.
    result = asyncio.run(query_video_status(service, room['id'], '视频进度'))
    assert result['prompt_id'] == 'b' * 32
    assert calls == [('GET', '/api/jobs/' + 'b' * 32)]


def test_normal_question_in_video_mode_is_still_chat(api):
    app, client, room, calls, models = api
    response = client.post('/api/chat/rooms/' + room['id'] + '/messages', json={
        'content': '你好你叫什么？', 'video_generation': True, 'request_id': 'c' * 32})
    assert response.status_code == 200, response.text
    identifier = response.json()['job']['id']
    for _ in range(100):
        job = client.get('/api/jobs/' + identifier).json()
        if job['status'] in {'completed', 'failed'}:
            break
        time.sleep(.02)
    assert job['status'] == 'completed' and models
    assert not calls and not app.state.video_submission.jobs()


@pytest.mark.parametrize('status', ['pending', 'success', 'error', 'unknown', 'unexpected'])
def test_provider_states_are_not_assumed_uploaded(api, status):
    app, client, room, calls, models = api
    service = app.state.video_submission
    seed(service, room)
    service.client_factory = lambda: httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={'status': status, 'files': [{'downloadUrl': 'http://untrusted.test'}]})))
    value = asyncio.run(query_video_status(service, room['id'], '视频完成了吗'))
    assert value['status'] == (status if status != 'unexpected' else 'unknown')
    if status == 'success':
        assert '尚未核对' in value['message']
    assert 'untrusted' not in json.dumps(value)


def test_timeout_is_bounded_without_resubmit(api, monkeypatch):
    import federation.video_status as module
    app, client, room, calls, models = api
    service = app.state.video_submission
    seed(service, room)
    async def slow(request):
        calls.append(request.method)
        await asyncio.sleep(10)
    service.client_factory = lambda: httpx.AsyncClient(transport=httpx.MockTransport(slow))
    monkeypatch.setattr(module, 'STATUS_TIMEOUT', .03)
    start = time.monotonic()
    result = asyncio.run(query_video_status(service, room['id'], '视频完成了吗'))
    assert time.monotonic() - start < 1
    assert result['status'] == 'unavailable' and calls == ['GET']
    assert len(service.jobs()) == 1
