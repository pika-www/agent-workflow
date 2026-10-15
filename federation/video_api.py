"""Same-origin controls for explicitly enabled external video submissions."""
import asyncio
import json
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse

from .video_generation import VideoSubmission, MAX_IMAGE


def install(app, store, web):
    service = VideoSubmission(store, chat=getattr(app.state, 'chat', None))
    app.state.video_submission = service

    async def body(request, limit=100_000):
        origin = request.headers.get('origin')
        if origin and urlsplit(origin).netloc != request.headers.get('host'):
            raise HTTPException(403, '只接受当前页面的操作')
        if not request.headers.get('content-type', '').startswith('application/json'):
            raise HTTPException(415, '请求需要 JSON 格式')
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > limit:
                raise HTTPException(413, '请求内容超过大小限制')
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(400, 'JSON 内容无效') from None
        if not isinstance(value, dict):
            raise HTTPException(400, '请求需要 JSON 对象')
        return value

    @app.get('/api/video-generation/config')
    async def config():
        return service.public_config()

    @app.put('/api/video-generation/config')
    async def save_config(request: Request):
        try:
            return service.save_config(await body(request))
        except ValueError as error:
            raise HTTPException(400, str(error)) from None

    @app.post('/api/video-generation/images', status_code=201)
    async def upload_image(request: Request):
        value = await body(request, 4 * ((MAX_IMAGE + 2) // 3) + 2000)
        try:
            return await asyncio.to_thread(service.upload, value)
        except (ValueError, OSError):
            raise HTTPException(400, '图片无效：支持 PNG、JPEG、WebP，每张最多 25 MiB、四千万像素') from None

    @app.post('/api/video-generation/jobs', status_code=202)
    async def submit(request: Request):
        try:
            return await service.submit(await body(request))
        except (ValueError, OSError) as error:
            message = str(error) if isinstance(error, ValueError) else '图片不存在或无法读取，请重新上传'
            raise HTTPException(400, message) from None

    @app.get('/api/video-generation/jobs')
    async def jobs():
        return {'jobs': service.jobs()}

    @app.get('/video-generation')
    async def page():
        return FileResponse(web / 'video-generation.html', media_type='text/html', headers={
            'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"})

    @app.get('/video-generation/{filename}')
    async def asset(filename: str):
        allowed = {'video-generation.js': 'text/javascript', 'video-generation.css': 'text/css'}
        if filename not in allowed:
            raise HTTPException(404, '资源不存在')
        return FileResponse(web / filename, media_type=allowed[filename])

    return service
