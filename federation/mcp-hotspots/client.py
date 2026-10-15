"""One bounded MCP initialize -> tools/list -> tools/call -> close session."""
import asyncio
from datetime import timedelta
import json
import os
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def query(platform):
    if platform not in {'baidu', 'bilibili', 'douyin'}:
        raise ValueError('Unsupported hotspot platform')
    server = StdioServerParameters(command=sys.executable,
        args=[str(Path(__file__).with_name('server.py'))],
        env={key: os.environ[key] for key in ('PATH', 'LANG', 'TZ') if key in os.environ})
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=12)) as session:
            initialized = await session.initialize()
            listing = await session.list_tools()
            if not any(tool.name == 'query_hot_trending' for tool in listing.tools):
                raise ValueError('MCP did not advertise query_hot_trending')
            result = await session.call_tool('query_hot_trending', {'platform': platform, 'limit': 12})
            if result.isError:
                raise ValueError('MCP tool returned an error')
            data = getattr(result, 'structuredContent', None)
            if not isinstance(data, dict):
                data = json.loads('\n'.join(block.text for block in result.content if block.type == 'text'))
            return {'server': initialized.serverInfo.model_dump(), 'tool': 'query_hot_trending', 'data': data}


if __name__ == '__main__':
    try:
        result = asyncio.run(query(sys.argv[1]))
        output = json.dumps(result, ensure_ascii=False)
        if len(output.encode()) > 150000:
            raise ValueError('MCP response exceeds the size limit')
        print(output)
    except Exception as exc:
        print(json.dumps({'error': type(exc).__name__ + ': MCP public feed read failed'}))
        sys.exit(1)
