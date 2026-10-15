"""Read existing, room-owned video job status without creating a task."""
import asyncio
import json
import re
import uuid

import httpx

from .video_intent import video_intent
from .video_generation import now

STATUS_TIMEOUT = 8


def room_video_jobs(service, room_id):
    return sorted((job for job in service.jobs()
                   if job.get('chat_room_id') == room_id
                   # Older clients accidentally sent status questions as prompts.
                   and video_intent(job.get('parameters', {}).get('prompt', ''), True, True) == 'generate'),
                  key=lambda job: job.get('created_at', ''), reverse=True)


async def query_video_status(service, room_id, question):
    jobs = room_video_jobs(service, room_id)
    identifiers = re.findall(r'(?<![a-z0-9])[a-f0-9]{8}-[a-f0-9-]{27,}|(?<![a-z0-9])[a-f0-9]{32}(?![a-z0-9])', question.lower())
    if identifiers:
        jobs = [job for job in jobs if job['id'].lower() in identifiers or str(job.get('receipt', {}).get('promptId', '')).lower() in identifiers]
    if not jobs:
        return {'status': 'not_found', 'message': '当前聊天没有找到对应的视频生成任务。这次只查询进度，没有创建新视频任务。'}
    job = jobs[0]
    receipt = job.get('receipt', {})
    prompt_id = receipt.get('promptId')
    result = {'job_id': job['id'], 'checked_at': now(), 'status': job['status']}
    if not isinstance(prompt_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}', prompt_id):
        messages = {'submitting': '提示词还在提交，尚未取得生成服务的任务编号。',
                    'rejected': '生成服务拒绝了此前的提交，没有取得任务编号。',
                    'submission_unknown': '此前提交的结果尚未确认，没有可靠的任务编号可查询；未自动重发。'}
        return {**result, 'message': messages.get(job['status'], '这条记录没有生成服务的任务编号，暂时无法查询进度。')}
    config = service.config()
    base_url = job.get('provider_base_url') or config.get('base_url')
    result['prompt_id'] = prompt_id
    if not base_url or base_url != config.get('base_url'):
        return {**result, 'status': 'unavailable', 'message': '生成服务地址已变更或未配置，暂未查询到原任务的实时进度。'}
    headers = {'x-api-key': config['api_key']} if config.get('api_key') else {}
    try:
        # Bound the whole read, not merely each socket operation; never follow a
        # provider-supplied URL or use the POST /run endpoint during a query.
        async def fetch():
            async with service.client_factory() as client:
                async with client.stream('GET', base_url + '/api/jobs/' + prompt_id, headers=headers,
                                         timeout=STATUS_TIMEOUT, follow_redirects=False) as response:
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 1_048_576:
                            raise ValueError('Response too large')
                    response.raise_for_status()
                    return json.loads(raw)
        value = await asyncio.wait_for(fetch(), timeout=STATUS_TIMEOUT)
        if not isinstance(value, dict) or not isinstance(value.get('status'), str):
            raise ValueError('Invalid status response')
        status = value['status']
        files = value.get('files', [])
        count = len(files) if isinstance(files, list) else 0
        messages = {'pending': '视频仍在生成服务的队列中，尚未完成。',
                    'running': '视频仍在生成中，生成服务暂未返回完成结果。',
                    'success': f'生成服务报告任务已成功，返回了 {count} 个输出文件。服务器是否已收到上传文件尚未核对。',
                    'finished': f'生成服务报告任务已结束，返回了 {count} 个输出文件。服务器是否已收到上传文件尚未核对。',
                    'error': '生成服务报告任务失败；没有自动重新生成。',
                    'failed': '生成服务报告任务失败；没有自动重新生成。',
                    'unknown': '生成服务的队列和历史中暂未找到这条任务，不能据此认定已经完成。'}
        result.update(status=status if status in messages else 'unknown', output_count=count,
                      message=messages.get(status, '生成服务返回了未识别的状态，暂时无法确认是否完成。'))
    except (asyncio.TimeoutError, httpx.HTTPError, ValueError, OSError):
        result.update(status='unavailable', message='暂时未能取得生成服务的实时进度（连接超时或响应异常）。任务编号已保留；本次没有重发生成请求。')
    result['message'] += '\n\n外部任务 ID：' + prompt_id
    return result


async def status_chat(service, room_id, content, request_id=''):
    # Status reads are repeatable; do not reuse generation request identifiers.
    result = await query_video_status(service, room_id, content)
    with service.chat._lock:
        room = service.chat.get_room(room_id)
        round_id = uuid.uuid4().hex
        speaker = 'central' if 'central' in room['participants'] else room['participants'][0]
        for role, text in [('user', content), ('assistant', result['message'])]:
            room['messages'].append({'id': uuid.uuid4().hex, 'role': role, 'content': text,
                'agent_id': speaker if role == 'assistant' else None,
                'agent_name': '视频进度' if role == 'assistant' else '你', 'status': 'completed',
                'phase': 'consultation', 'created_at': now(), 'round_id': round_id,
                'video_status_query': True,
                **({'response_origin': 'host_video_status', 'video_status': result, 'model': None} if role == 'assistant' else {})})
        service.chat.save_room(room)
    return {'room': room, 'message': room['messages'][-1], 'video_status': result, 'intent': 'video_status'}
