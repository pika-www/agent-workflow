"""Read-only platform MCP bridge, isolated from chat/profile/Wiki credentials."""
import asyncio
from contextlib import suppress
import json
import os
from pathlib import Path
import re
import signal
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
PLATFORMS = frozenset({'baidu', 'bilibili', 'douyin'})
PROVIDER = {'name': 'hot-trending-mcp', 'type': 'community', 'transport': 'stdio',
            'repository': 'https://github.com/boy-373/hot-trending-mcp',
            'commit': '2e1dea10ded20c502e3bec4fedf52b81c40dd055', 'tool': 'query_hot_trending'}
HOSTS = {'baidu': {'top.baidu.com', 'www.baidu.com', 'm.baidu.com'},
         'bilibili': {'www.bilibili.com', 'b23.tv'},
         'douyin': {'www.douyin.com', 'www.iesdouyin.com'}}


def parse_result(result, platform):
    if platform not in PLATFORMS:
        raise ValueError('不支持的 MCP 热榜平台')
    if not isinstance(result, dict) or result.get('tool') != PROVIDER['tool']:
        raise ValueError('MCP 返回格式无效')
    data = result.get('data')
    if not isinstance(data, dict) or data.get('error') or data.get('platform') != platform:
        raise ValueError('MCP 未返回该平台的有效榜单')
    rows = data.get('items')
    if not isinstance(rows, list) or not rows:
        raise ValueError('MCP 没有返回榜单条目')
    items = []
    for row in rows[:50]:
        if not isinstance(row, dict):
            continue
        try:
            url = urlsplit(row.get('url', ''))
            valid = (url.scheme == 'https' and url.hostname in HOSTS[platform]
                     and not url.username and not url.password and url.port in (None, 443))
        except (TypeError, ValueError, AttributeError):
            valid = False
        score = row.get('hot')
        if not valid or not isinstance(row.get('title'), str) or not row['title'].strip():
            continue
        link = row['url']
        if platform == 'bilibili' and url.hostname == 'b23.tv' and re.fullmatch(r'/BV[A-Za-z0-9]{10}', url.path):
            link = 'https://www.bilibili.com/video' + url.path
        items.append({'title': row['title'], 'url': link, 'rank': row.get('rank'),
                      'score': score if type(score) is int and score >= 0 else None})
    if not items:
        raise ValueError('MCP 没有返回有效的平台链接')
    return items


async def read_hotlist(platform):
    if platform not in PLATFORMS:
        raise ValueError('不支持的 MCP 热榜平台')
    python = ROOT / '.venv-mcp-hotspots/bin/python'
    if not python.is_file():
        raise ValueError('本机热榜 MCP 尚未安装')
    # Only the platform slug is sent. No model prompt, personal profile, OAuth
    # token or Wiki directory is passed into this separately reviewed provider.
    process = await asyncio.create_subprocess_exec(str(python),
        str(ROOT / 'federation/mcp-hotspots/client.py'), platform,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        env={key: os.environ[key] for key in ('PATH', 'LANG', 'TZ') if key in os.environ},
        cwd=str(ROOT / 'federation/mcp-hotspots'), start_new_session=True)
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=13)
        if process.returncode or len(stdout) > 150000:
            raise ValueError('本机热榜 MCP 读取失败')
        return parse_result(json.loads(stdout), platform)
    except asyncio.TimeoutError:
        raise ValueError('本机热榜 MCP 读取超时') from None
    finally:
        # Cancellation must also reap the stdio server, not leave children
        # behind during shutdown or a failed MCP session.
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        if process.returncode is None:
            try:
                await asyncio.wait_for(process.wait(), timeout=2)
            except asyncio.TimeoutError:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                await process.wait()
