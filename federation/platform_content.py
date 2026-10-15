"""Read-only chat bridge to installed platform MCP servers."""
import asyncio
from datetime import datetime, timezone
import json
import os
import re
import signal
from .platform_mcp_registry import CODE, ROOT, RUNTIME, PROVIDERS, catalog, credential_present, installed, private_path, write_private

def validate(provider, tool, args):
    if provider not in PROVIDERS or tool not in PROVIDERS[provider]['tools']: raise ValueError('此平台工具未开放；只允许搜索与读取')
    if not isinstance(args, dict) or len(json.dumps(args)) > 6000: raise ValueError('平台参数无效')
    if provider == 'tieba':
        if set(args) != ({'query'} if tool == 'search' else {'post_id'}): raise ValueError('贴吧参数无效')
        if tool == 'detail' and not re.fullmatch(r'\d{1,25}', str(args['post_id'])): raise ValueError('贴吧帖子编号无效')
    for key, value in args.items():
        if key in {'token','access_token','cookie','open_id','client_secret'}:raise ValueError('账号凭据只能由本机登录配置提供')
        if key in {'count', 'page_size', 'limit', 'per_page'} and (type(value) is not int or not 1 <= value <= 20): raise ValueError('每次最多读取20条')
        if key in {'page', 'page_index'} and (type(value) is not int or not 1 <= value <= 20): raise ValueError('页码超出范围')
        if isinstance(value, str) and (len(value) > 500 or '\0' in value): raise ValueError('平台参数过长')
        if key in {'keyword','query'} and (not isinstance(value,str) or not value.strip() or len(value)>200 or re.search(r'[\w.+-]+@[\w.-]+\.[a-z]{2,}|(?<!\d)1[3-9]\d{9}(?!\d)|(?:/Users/|api[_ -]?key|密码|密钥)',value,re.I)):
            raise ValueError('平台搜索仅接受公开主题，不发送个人资料或凭据')
    return args

async def worker(provider, action, tool=None, args=None, timeout=80):
    from .platform_mcp_registry import runtime_environment
    env = runtime_environment()
    process = await asyncio.create_subprocess_exec(str(RUNTIME/'envs/bilibili/bin/python'), str(CODE/'client.py'),
        cwd=ROOT, env=env, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, start_new_session=True)
    try:
        raw, _ = await asyncio.wait_for(process.communicate(json.dumps({'provider':provider,'action':action,'tool':tool,'args':args or {}}).encode()), timeout)
        if process.returncode or len(raw)>200000: return {'status':'failed','error':'平台 MCP 未正常返回，请检查连接状态'}
        return json.loads(raw)
    except asyncio.TimeoutError:
        return {'status':'timeout','error':'平台读取超时，已停止本次请求；未把超时当作没有评论'}
    finally:
        try: os.killpg(process.pid,signal.SIGTERM)
        except ProcessLookupError: pass
        if process.returncode is None:
            try: await asyncio.wait_for(process.wait(),2)
            except asyncio.TimeoutError:
                try: os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError: pass
                await process.wait()

async def execute(provider, tool, args):
    validate(provider,tool,args)
    if not installed(provider): return {'status':'unavailable','platform':provider,'error':'此平台 MCP 尚未安装'}
    # Login is a user action in the local Tools panel, never a model-created control.
    if not credential_present(provider) and not (provider=='bilibili' or tool in {'auth_status','check_login_status'}):
        return {'status':'needs_login','platform':provider,'error':'请打开“工具与连接 → 平台 MCP”完成登录或授权，再继续原问题。'}
    from .platform_mcp_registry import login_state
    login=login_state(provider)
    if login.get('state') in {'starting','waiting'}:
        return {'status':'needs_login','error':'正在等待你在独立登录窗口完成登录。'}
    result=await worker(provider,'call',tool,args)
    result.update(platform=provider,tool=tool,scope='read-only',checked_at=datetime.now(timezone.utc).isoformat())
    write_private(private_path(provider+'-last-read.json'),{k:result[k] for k in ('status','tool','checked_at')})
    return result
