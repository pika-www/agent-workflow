import asyncio
import base64
import json
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from federation.core import FederationStore, _write_json
from federation.video_api import install
from federation.video_generation import VideoSubmission, WORKFLOWS


@pytest.fixture
def service(tmp_path):
    store = FederationStore(base=tmp_path / 'isolated-video-data')
    return VideoSubmission(store)


def payload(**params):
    return {'request_id': 'a' * 32, 'workflow': 'reference_4step_sla_server_upload',
            'parameters': {'prompt': ' 清晨的海面，波浪轻拍礁石 ', **params}}


def configured(service, handler):
    service.save_config({'enabled': True, 'base_url': 'http://comfy.test:3000', 'api_key': 'test-private-key'})
    service.client_factory = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def finish(service, value):
    job = await service.submit(value)
    await asyncio.gather(*list(service.tasks))
    return json.loads(service.job_path(job['id']).read_text())


def image_id(service):
    buffer = BytesIO()
    Image.new('RGB', (2, 2), 'blue').save(buffer, 'PNG')
    return service.upload({'filename': '参考.png', 'data_base64': base64.b64encode(buffer.getvalue()).decode()})['id']


def test_disabled_default_and_config_does_not_send(service):
    assert service.public_config()['enabled'] is False
    with pytest.raises(ValueError, match='尚未启用'):
        asyncio.run(service.submit(payload()))
    with pytest.raises(ValueError, match='BASE_URL'):
        service.save_config({'enabled': True})
    result = service.save_config({'enabled': True, 'base_url': 'http://192.168.1.20:3000', 'api_key': 'secret'})
    assert result['has_api_key'] and 'api_key' not in result
    assert not service.jobs()
    assert service.path('private/video-generation.json').stat().st_mode & 0o777 == 0o600
    service.save_config({'api_key': ''})
    assert service.config()['api_key'] == 'secret'
    service.save_config({'clear_api_key': True})
    assert not service.public_config()['has_api_key']


@pytest.mark.parametrize('url', ['ssh winfield@192.168.1.12', 'file:///etc/passwd', 'http://a:b@localhost', 'https://host?key=secret', 'http://host:bad'])
def test_invalid_base_urls(service, url):
    with pytest.raises(ValueError):
        service.save_config({'base_url': url})


@pytest.mark.parametrize('parameters', [{'duration': 0}, {'duration': 'nan'}, {'megapixels': 4.1}, {'seed': 2147483647}, {'seed': 1.5}, {'fps': True}, {'steps': 51}, {'videoShift': -1}, {'slaSparsity': 1.1}, {'aspectRatio': '2:2'}, {'secondPassInject': .5}, {'callbackUrl': 'http://example.com'}, {'prompt': '  '}])
def test_invalid_parameters_rejected_before_dispatch(service, parameters):
    with pytest.raises(ValueError):
        service.validate_submission(payload(**parameters))
    assert service.jobs() == []


def test_json_request_receipt_and_idempotency(service):
    requests = []
    def handler(request):
        requests.append(request)
        assert request.url.path == '/api/workflows/reference_4step_sla_server_upload/run'
        assert request.headers['x-api-key'] == 'test-private-key'
        assert json.loads(request.content) == {'prompt': ' 清晨的海面，波浪轻拍礁石 ', 'duration': 10, 'seed': 0, 'fps': 24, 'aspectRatio': '9:16'}
        return httpx.Response(202, json={'promptId': 'remote-task-123', 'queueNumber': 0, 'seed': 0, 'statusUrl': 'https://evil.test', 'secret': 'never-expose'})
    configured(service, handler)
    data = payload(duration='10', seed=0, fps='24', aspectRatio='9:16')
    async def run():
        first = await finish(service, data)
        second = await service.submit(data)
        assert second == first
        changed = {**data, 'parameters': {'prompt': '不同内容'}}
        with pytest.raises(ValueError, match='不同参数'):
            await service.submit(changed)
    asyncio.run(run())
    assert len(requests) == 1
    job = service.jobs()[0]
    assert job['status'] == 'submitted' and job['receipt']['promptId'] == 'remote-task-123'
    assert 'evil.test' not in json.dumps(job) and 'never-expose' not in json.dumps(job)
    assert 'test-private-key' not in json.dumps(job)


@pytest.mark.parametrize('workflow,extra', [('i2v_fl2v_4step_sla_server_upload', 'lastImage'), ('ref2va_4step_sla', 'referenceImage2')])
def test_multipart_fields_and_optional_images(service, workflow, extra):
    seen = []
    def handler(request):
        body = request.read()
        assert request.headers['content-type'].startswith('multipart/form-data; boundary=')
        for field in ('image', extra, 'prompt', 'duration'):
            assert f'name="{field}"'.encode() in body
        assert b'\x89PNG' in body
        seen.append(request)
        return httpx.Response(202, json={'promptId': 'img-result'})
    configured(service, handler)
    identifier = image_id(service)
    data = {**payload(duration=2), 'workflow': workflow, 'images': {'image': identifier, extra: identifier}}
    assert asyncio.run(finish(service, data))['status'] == 'submitted'
    assert len(seen) == 1
    with pytest.raises(ValueError, match='需要第一张图片'):
        service.validate_submission({**data, 'images': {}})
    with pytest.raises(ValueError):
        service.validate_submission({**payload(), 'images': {'image': identifier}})


def test_all_workflows_and_derope_parameters(service):
    fid = image_id(service)
    for name, (_, extra) in WORKFLOWS.items():
        for suffix in ('', '_server_upload'):
            value = {**payload(), 'workflow': name + suffix}
            if extra:
                value['images'] = {'image': fid}
            if name.startswith('derope_'):
                value['parameters'].update(secondPassAudioStrength='0', secondPassInject=1)
            service.validate_submission(value)


@pytest.mark.parametrize('response,status', [(httpx.Response(401), 'rejected'), (httpx.Response(503), 'submission_unknown'), (httpx.Response(202, json={}), 'submission_unknown'), (httpx.Response(200, json={'promptId': 'wrong'}), 'submission_unknown'), (httpx.Response(302, headers={'Location': 'https://other.test'}), 'submission_unknown')])
def test_failed_submissions_not_replayed(service, response, status):
    calls = []
    configured(service, lambda request: calls.append(request) or response)
    job = asyncio.run(finish(service, payload()))
    assert job['status'] == status
    assert asyncio.run(service.submit(payload()))['status'] == status
    assert len(calls) == 1


def test_timeout_and_restart_keep_uncertainty(service):
    def timeout(request):
        raise httpx.ReadTimeout('private-url-and-key-must-not-leak')
    configured(service, timeout)
    job = asyncio.run(finish(service, payload()))
    assert job['status'] == 'submission_unknown'
    assert 'private-url' not in json.dumps(job)
    job.update(status='submitting')
    _write_json(service.job_path(job['id']), job)
    recovered = VideoSubmission(service.store)
    recovered.recover()
    assert recovered.jobs()[0]['status'] == 'submission_unknown'
    assert not recovered.tasks


def test_shutdown_preserves_request_and_does_not_resubmit(service):
    async def slow(request):
        await asyncio.sleep(60)
    configured(service, slow)
    async def run():
        await service.submit(payload())
        await asyncio.sleep(0)
        await service.close()
    asyncio.run(run())
    assert service.jobs()[0]['status'] == 'submission_unknown'


def test_no_api_key_when_not_required(service):
    def handler(request):
        assert 'x-api-key' not in request.headers
        return httpx.Response(202, json={'promptId': 'no-key'})
    configured(service, handler)
    service.save_config({'clear_api_key': True})
    assert asyncio.run(finish(service, payload()))['status'] == 'submitted'


def test_api_origin_size_and_secret_boundaries(service):
    app = FastAPI()
    install(app, service.store, Path('federation/web'))
    with TestClient(app) as client:
        assert client.get('/video-generation').status_code == 200
        assert client.get('/video-generation/not-an-asset').status_code == 404
        assert client.put('/api/video-generation/config', json={'enabled': False}, headers={'Origin': 'https://evil.test'}).status_code == 403
        assert client.put('/api/video-generation/config', content='x', headers={'Content-Type': 'text/plain'}).status_code == 415
        assert client.post('/api/video-generation/jobs', json={'data': 'a' * 100001}).status_code == 413
        assert client.post('/api/video-generation/jobs', json=[]).status_code == 400
        result = client.put('/api/video-generation/config', json={'enabled': False, 'api_key': 'secret'}).json()
        assert result['has_api_key'] and 'secret' not in json.dumps(result)
        assert client.get('/api/video-generation/jobs').json() == {'jobs': []}
