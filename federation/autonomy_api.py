"""Local controls and observable receipts for continuous industry learning."""
import re
from pathlib import Path
from typing import Optional, Literal

from fastapi import HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .autonomy import read_json
from .core import _now, _write_json


class Settings(BaseModel):
    enabled: bool
    code_enabled: bool
    interval_hours: int = Field(default=24, ge=6, le=168)
    daily_model_calls: int = Field(default=96, ge=1, le=300)
    pages_per_run: int = Field(default=2, ge=1, le=3)
    conversation_online: Optional[bool] = None
    conversation_refresh: Optional[bool] = None
    continuous_learning: Optional[bool] = None
    model_policy: Optional[Literal['tool_agent', 'local']] = None


class RunRequest(BaseModel):
    agent_id: str = ''
    kind: str = 'learning'


def install(app, manager):
    web = Path(__file__).parent / 'web'

    @app.get('/api/autonomy')
    async def status():
        return manager.snapshot()

    @app.put('/api/autonomy/settings')
    async def configure(data: Settings):
        return manager.configure({**data.model_dump(exclude_none=True),
            'authorization': '用户授权各 Agent 按行业持续学习，默认结合本地知识和联网原文；启用对话复查时自动核实并修订过时知识，保留历史。在启用代码开关时执行隔离测试后的代码改进。'})

    @app.post('/api/autonomy/run')
    async def request_run(data: RunRequest):
        if not manager.settings()['enabled']:
            raise HTTPException(409, '自主运行已暂停，请先开启')
        if data.kind == 'learning':
            manager.request(data.agent_id or None)
        elif data.kind == 'code_upgrade' and manager.settings()['code_enabled']:
            _write_json(manager.root / 'upgrade.json', {'next_at': _now(), 'requested': True})
            manager.wake.set()
        else:
            raise HTTPException(400, '自主任务类型无效或代码升级已关闭')
        return manager.snapshot()

    @app.get('/api/autonomy/runs/{identifier}')
    async def get_run(identifier: str):
        if not re.fullmatch(r'[a-f0-9]{32}', identifier):
            raise HTTPException(404, '自主任务不存在')
        directory = manager.root / 'runs' / identifier
        run = read_json(directory / 'run.json', None)
        if not run:
            raise HTTPException(404, '自主任务不存在')
        return {'run': run, 'draft': read_json(directory / 'draft.json', None),
                'review': read_json(directory / 'review.json', None),
                'tests': read_json(directory / 'tests.json', None),
                'proposal': read_json(directory / 'proposal.json', None)}

    @app.get('/autonomy')
    async def page():
        return FileResponse(web / 'autonomy.html', headers={'Content-Security-Policy':
            "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"})

    @app.get('/autonomy/{filename}')
    async def asset(filename: str):
        if filename not in {'autonomy.js', 'autonomy.css'}:
            raise HTTPException(404, '文件不存在')
        return FileResponse(web / filename, media_type='text/javascript' if filename.endswith('.js') else 'text/css')
