"""Launch reviewed upstream code without modifying the pinned source snapshots."""
import sys
import types
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from federation.platform_mcp_registry import PROVIDERS, RUNTIME, load_json, private_path

provider = sys.argv[1]
spec = PROVIDERS[provider]
source = RUNTIME / 'sources' / spec['source']
sys.path.insert(0, str(source))
if provider == 'bilibili':
    import os
    credentials = load_json(private_path('bilibili.json'))
    for key in ('sessdata', 'bili_jct', 'buvid3', 'dedeuserid'):
        if credentials.get(key): os.environ[key] = credentials[key]
    import server
    for name in ('send_comment', 'get_media_subtitle'): server.mcp.remove_tool(name)
    server.mcp.run(transport='stdio')
elif provider == 'douyin':
    # Reading metadata/comments does not require downloading ffmpeg at import.
    module = types.ModuleType('static_ffmpeg')
    module.add_paths = lambda: None
    sys.modules['static_ffmpeg'] = module
    from src.server import mcp
    import asyncio
    async def restrict():
        for name in await mcp.get_tools():
            if name not in spec['tools']: mcp.remove_tool(name)
    asyncio.run(restrict())
    mcp.run(transport='stdio', show_banner=False)
elif provider == 'tieba':
    from dsh_mediacrawler.server import main
    main()
else:
    raise ValueError('Unsupported provider')
