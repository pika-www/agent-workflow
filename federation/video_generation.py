"""Opt-in Comfy workflow submission. Generation/upload stay with the provider.

Persist before dispatch and never replay an uncertain POST after a restart.
Credentials are private; provider response URLs are never fetched or rendered.
"""
import asyncio
import base64
import hashlib
import json
import math
import re
import uuid
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from PIL import Image

from .core import _write_json
from .report_model import _read, _write_private

WORKFLOWS = {
    'reference_4step_sla': ('基础文字生成', None),
    'derope_4plus4_sla': ('Derope 4+4 文字生成', None),
    'derope_dyrope_pb3049_warm375': ('Derope / Dyrope 文字生成', None),
    'i2v_fl2v_4step_sla': ('首帧 / 首尾帧生成', 'lastImage'),
    'ref2va_4step_sla': ('参考图生成', 'referenceImage2'),
}
RANGES = {
    'duration': (1, 60, False), 'megapixels': (.1, 4, False),
    'seed': (0, 2147483646, True), 'fps': (1, 60, True), 'steps': (1, 50, True),
    'videoShift': (0, 30, False), 'audioShift': (0, 30, False),
    'slaSparsity': (0, 1, False), 'secondPassAudioStrength': (0, 1, False),
    'secondPassInject': (0, 1, False),
}
RATIOS = ['1:1', '2:3', '3:2', '3:4', '4:3', '9:16', '16:9', '21:9']
ID = re.compile(r'^[a-f0-9]{32}$')
MAX_IMAGE = 25 * 1024 * 1024


def now():
    return datetime.now(timezone.utc).isoformat()


def workflow(name):
    if not isinstance(name, str):
        raise ValueError('请选择工作流')
    base = name.removesuffix('_server_upload')
    if base not in WORKFLOWS or name not in {base, base + '_server_upload'}:
        raise ValueError('工作流不在接入文档范围内')
    return base, WORKFLOWS[base]


def validate_url(value):
    if not isinstance(value, str) or len(value) > 2000 or any(c.isspace() for c in value):
        raise ValueError('接口地址格式无效')
    parsed = urlsplit(value)
    if (parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise ValueError('填写 HTTP(S) BASE_URL，不包含密钥、查询参数或片段')
    try:
        parsed.port
    except ValueError:
        raise ValueError('接口端口无效') from None
    return value.rstrip('/')


class VideoSubmission:
    def __init__(self, store, client_factory=None, chat=None):
        self.store = store
        self.chat = chat
        self.client_factory = client_factory or (lambda: httpx.AsyncClient(
            timeout=httpx.Timeout(120, connect=10), follow_redirects=False, trust_env=False))
        self.tasks = set()
        self.lock = None

    def path(self, relative):
        return self.store._safe(self.store.base, relative)

    def config(self):
        path = self.path('private/video-generation.json')
        return _read(path) if path.exists() else {}

    def public_config(self):
        config = self.config()
        return {'enabled': config.get('enabled', False), 'base_url': config.get('base_url', ''),
                'has_api_key': bool(config.get('api_key')), 'configured': bool(config.get('base_url')),
                'default_workflow': config.get('default_workflow', 'reference_4step_sla_server_upload'),
                'workflows': [{'name': base + suffix, 'label': label + ('并上传服务器' if suffix else ''),
                               'image_required': extra is not None, 'extra_image': extra}
                              for base, (label, extra) in WORKFLOWS.items()
                              for suffix in ('_server_upload', '')], 'aspect_ratios': RATIOS}

    def save_config(self, value):
        if not isinstance(value, dict) or set(value) - {'enabled', 'base_url', 'api_key', 'clear_api_key', 'default_workflow'}:
            raise ValueError('配置字段无效')
        current = self.config()
        for field in ('enabled', 'clear_api_key'):
            if field in value and not isinstance(value[field], bool):
                raise ValueError('开关必须为布尔值')
        if 'base_url' in value:
            if not isinstance(value['base_url'], str):
                raise ValueError('接口地址必须为字符串')
            current['base_url'] = validate_url(value['base_url']) if value['base_url'] else ''
        if 'default_workflow' in value:
            workflow(value['default_workflow'])
            current['default_workflow'] = value['default_workflow']
        if 'api_key' in value:
            key = value['api_key']
            if not isinstance(key, str) or len(key) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in key):
                raise ValueError('API 密钥格式无效')
            if key:
                current['api_key'] = key
        if value.get('clear_api_key'):
            current.pop('api_key', None)
        current['enabled'] = value.get('enabled', current.get('enabled', False))
        if current['enabled'] and not current.get('base_url'):
            raise ValueError('启用前请填写生成服务的 BASE_URL')
        _write_private(self.path('private/video-generation.json'), current)
        return self.public_config()

    def upload(self, data):
        if not isinstance(data, dict) or set(data) != {'filename', 'data_base64'}:
            raise ValueError('上传内容无效')
        name = data['filename']
        if (not isinstance(name, str) or not name or len(name) > 150 or Path(name).name != name
                or '\\' in name or any(ord(c) < 32 for c in name)):
            raise ValueError('图片文件名无效')
        if not isinstance(data['data_base64'], str):
            raise ValueError('图片编码无效')
        raw = base64.b64decode(data['data_base64'], validate=True)
        if not raw or len(raw) > MAX_IMAGE:
            raise ValueError('每张图片不得超过 25 MiB')
        with Image.open(BytesIO(raw)) as picture:
            fmt = picture.format
            if fmt not in {'PNG', 'JPEG', 'WEBP'} or picture.width * picture.height > 40_000_000:
                raise ValueError('图片需为 PNG、JPEG 或 WebP，且不超过四千万像素')
            picture.verify()
        identifier = uuid.uuid4().hex
        directory = self.path('video-generation/inputs/' + identifier)
        directory.mkdir(parents=True, mode=0o700)
        # Normalize the filename suffix to its verified content type.
        item = {'id': identifier, 'name': Path(name).stem + {'PNG': '.png', 'JPEG': '.jpg', 'WEBP': '.webp'}[fmt],
                'media_type': Image.MIME[fmt], 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
        target = directory / 'data'
        target.write_bytes(raw)
        target.chmod(0o600)
        _write_json(directory / 'metadata.json', item)
        return item

    def image(self, identifier):
        if not isinstance(identifier, str) or not ID.fullmatch(identifier):
            raise ValueError('图片编号无效')
        root = 'video-generation/inputs/' + identifier
        item = _read(self.path(root + '/metadata.json'))
        path = self.path(root + '/data')
        raw = path.read_bytes()
        if len(raw) > MAX_IMAGE or hashlib.sha256(raw).hexdigest() != item.get('sha256'):
            raise ValueError('图片完整性检查失败')
        return item['name'], raw, item['media_type']

    def validate_submission(self, value):
        if not isinstance(value, dict) or set(value) - {'request_id', 'workflow', 'parameters', 'images'}:
            raise ValueError('提交字段无效')
        identifier = value.get('request_id')
        if not isinstance(identifier, str) or not ID.fullmatch(identifier):
            raise ValueError('请求编号无效')
        base, (_, extra) = workflow(value.get('workflow'))
        params = value.get('parameters')
        if not isinstance(params, dict) or set(params) - ({'prompt', 'aspectRatio'} | set(RANGES)):
            raise ValueError('视频参数字段无效')
        prompt = params.get('prompt')
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 20000:
            raise ValueError('请填写提示词，最多两万字')
        clean = {'prompt': prompt}
        for field, value_ in params.items():
            if field in {'prompt', 'aspectRatio'}:
                continue
            if field.startswith('secondPass') and not base.startswith('derope_'):
                raise ValueError('二阶段参数只适用于 Derope 工作流')
            if isinstance(value_, bool) or not isinstance(value_, (str, int, float)):
                raise ValueError(field + ' 数值无效')
            try:
                number = float(value_)
            except (ValueError, OverflowError):
                raise ValueError(field + ' 数值无效') from None
            low, high, integer = RANGES[field]
            if not math.isfinite(number) or not low <= number <= high or integer and not number.is_integer():
                raise ValueError(f'{field} 需在 {low}～{high} 之间' + ('，并为整数' if integer else ''))
            clean[field] = int(number) if integer else number
        if 'aspectRatio' in params:
            if params['aspectRatio'] not in RATIOS:
                raise ValueError('画面比例无效')
            clean['aspectRatio'] = params['aspectRatio']
        images = value.get('images', {})
        allowed_images = {'image', extra} if extra else set()
        if not isinstance(images, dict) or set(images) - allowed_images:
            raise ValueError('所选工作流不接受这些图片参数')
        if extra and not images.get('image'):
            raise ValueError('所选工作流需要第一张图片')
        for image_id in images.values():
            self.image(image_id)
        return identifier, clean, images

    def job_path(self, identifier):
        if not ID.fullmatch(identifier):
            raise ValueError('任务编号无效')
        return self.path('video-generation/jobs/' + identifier + '.json')

    def jobs(self):
        directory = self.path('video-generation/jobs')
        paths = sorted(directory.glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True)[:100]
        return [_read(self.job_path(path.stem)) for path in paths]

    async def submit_chat(self, room_id, content, request_id):
        if self.chat is None:
            raise ValueError('聊天服务未连接')
        self.chat._identifier(room_id)
        self.chat._text(content, 6000, '提示词')
        name = self.config().get('default_workflow', 'reference_4step_sla_server_upload')
        # Retries bind to the original endpoint, even if configuration changed.
        path = self.job_path(request_id)
        if path.exists():
            previous = _read(path)
            if previous.get('chat_room_id') != room_id:
                raise ValueError('请求编号不属于当前聊天')
            name = previous['workflow']
        if workflow(name)[1][1] or not name.endswith('_server_upload'):
            raise ValueError('聊天生成视频需要选择带服务器上传的文字工作流，请检查视频连接配置')
        return await self.submit({'request_id': request_id, 'workflow': name,
                                  'parameters': {'prompt': content}}, chat_room_id=room_id)

    def sync_chat(self, job):
        if not self.chat or not job.get('chat_room_id'):
            return
        with self.chat._lock:
            room = self.chat.get_room(job['chat_room_id'])
            original = json.dumps(room, sort_keys=True)
            messages = [m for m in room['messages'] if m.get('video_submission_id') == job['id']]
            def message(role, text, speaker=None):
                return {'id': uuid.uuid4().hex, 'role': role, 'content': text, 'agent_id': speaker,
                        'agent_name': '你' if role == 'user' else '视频接口', 'status': 'completed',
                        'phase': 'video_prompt' if role == 'user' else 'video_submission',
                        'created_at': now(), 'round_id': job['id'], 'video_submission_id': job['id']}
            if not any(m['role'] == 'user' for m in messages):
                room['messages'].append(message('user', job['parameters']['prompt']))
            reply = next((m for m in messages if m['role'] == 'assistant'), None)
            text = job['message']
            if job.get('receipt', {}).get('promptId'):
                text += '\n\n外部任务 ID：' + job['receipt']['promptId']
            if reply is None:
                speaker = 'central' if 'central' in room['participants'] else room['participants'][0]
                reply = message('assistant', text, speaker)
                room['messages'].append(reply)
            reply.update(content=text, video_submission_id=job['id'], response_origin='host_video_submission',
                         video_submission={'status': job['status'], 'workflow': job['workflow']}, model=None)
            if json.dumps(room, sort_keys=True) != original:
                self.chat.save_room(room)

    async def submit(self, data, chat_room_id=None):
        identifier, parameters, images = self.validate_submission(data)
        payload = {'workflow': data['workflow'], 'parameters': parameters, 'images': images}
        if chat_room_id:
            payload['chat_room_id'] = chat_room_id
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        if self.lock is None:
            self.lock = asyncio.Lock()
        async with self.lock:
            path = self.job_path(identifier)
            if path.exists():
                previous = _read(path)
                if previous['request_sha256'] != digest:
                    raise ValueError('此请求编号已用于不同参数，请重新提交')
                self.sync_chat(previous)
                return previous
            config = self.config()
            if not config.get('enabled') or not config.get('base_url'):
                raise ValueError('视频接口尚未启用，请先保存连接配置')
            if len(self.tasks) >= 2:
                raise ValueError('已有两个请求正在提交，请稍后再试')
            if chat_room_id and self.chat.get_room(chat_room_id)['status'] in {'running', 'queued'}:
                raise ValueError('当前聊天正在处理消息，请稍后发送视频提示词')
            job = {**payload, 'id': identifier, 'request_sha256': digest, 'created_at': now(),
                   'provider_base_url': config['base_url'],
                   'status': 'submitting', 'message': '正在提交视频提示词，等待接口回执。' if chat_room_id else '正在提交参数，尚未取得外部任务 ID'}
            _write_json(path, job)
            self.sync_chat(job)
            task = asyncio.create_task(self.dispatch(job, config))
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
            return job.copy()

    async def dispatch(self, job, config):
        try:
            files = {field: self.image(identifier) for field, identifier in job['images'].items()}
            headers = {'x-api-key': config['api_key']} if config.get('api_key') else {}
            url = config['base_url'] + '/api/workflows/' + job['workflow'] + '/run'
            body = {'data': job['parameters'], 'files': files} if files else {'json': job['parameters']}
            async with self.client_factory() as client:
                async with client.stream('POST', url, headers=headers, **body) as response:
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 1_048_576:
                            raise ValueError('接口响应超过限制')
                    if response.status_code != 202:
                        # Only a definite client rejection proves no accepted task.
                        job.update(status='rejected' if response.status_code in {400, 401, 403, 404, 413, 422, 429} else 'submission_unknown',
                                   http_status=response.status_code,
                                   message=f'接口返回 HTTP {response.status_code}，未取得接收回执；未自动重试')
                    else:
                        data = json.loads(raw)
                        prompt_id = data.get('promptId') if isinstance(data, dict) else None
                        if not isinstance(prompt_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}', prompt_id):
                            raise ValueError('响应缺少有效 promptId')
                        receipt = {'promptId': prompt_id}
                        for field in ('queueNumber', 'seed', 'duration', 'megapixels', 'fps', 'steps'):
                            number = data.get(field)
                            if isinstance(number, (int, float)) and not isinstance(number, bool) and math.isfinite(number):
                                receipt[field] = number
                        if data.get('aspectRatio') in RATIOS:
                            receipt['aspectRatio'] = data['aspectRatio']
                        job.update(status='submitted', receipt=receipt,
                                   message='提示词已提交，等待外部工作流生成视频并上传服务器。' if job.get('chat_room_id') else '参数已提交；生成与上传由外部工作流处理，本回执不表示视频已完成')
        except asyncio.CancelledError:
            job.update(status='submission_unknown', message='提交期间服务中断；对方可能已接收，请核对后再决定是否新建任务')
            raise
        except (httpx.HTTPError, ValueError, OSError):
            job.update(status='submission_unknown', message='连接中断、超时或回执无效；对方可能已接收，未自动重试')
        finally:
            job['updated_at'] = now()
            _write_json(self.job_path(job['id']), job)
            self.sync_chat(job)

    def recover(self):
        # All records, not only the latest 100 displayed in the UI.
        for path in self.path('video-generation/jobs').glob('*.json'):
            job = _read(self.job_path(path.stem))
            if job.get('status') == 'submitting':
                job.update(status='submission_unknown', updated_at=now(),
                           message='上次提交期间服务中断；未重复发送，请先核对外部队列')
                _write_json(path, job)
            self.sync_chat(job)

    async def close(self):
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
