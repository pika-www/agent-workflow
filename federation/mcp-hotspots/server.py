"""Local stdio host for the pinned, MIT-licensed hot-trending-mcp provider."""
from pathlib import Path
import ssl
import sys
import urllib.request

import certifi

sys.path.insert(0, str(Path(__file__).parent / 'vendor'))
import hot_mcp_server as upstream
from mcp.types import ToolAnnotations

# The upstream copy stays byte-for-byte intact. Enable TLS verification and
# bound retries in our host; upstream disables certificate checking by default.
upstream._SSL_CTX = ssl.create_default_context(cafile=certifi.where())
def bounded_get(url, headers=None, timeout=3):
    request = urllib.request.Request(url, headers={'User-Agent': upstream.UA,
        'Accept': 'application/json, text/plain, */*', **(headers or {})})
    with urllib.request.urlopen(request, timeout=min(timeout, 3), context=upstream._SSL_CTX) as response:
        raw = response.read(1500001)
        if len(raw) > 1500000:
            raise ValueError('Platform response exceeds the size limit')
        return raw.decode(response.headers.get_content_charset() or 'utf-8', errors='replace')


upstream._http_get = bounded_get
upstream.mcp.remove_tool('query_hot_trending')


@upstream.mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
def query_hot_trending(platform: str, limit: int = 12) -> dict:
    """Read a public Baidu, Bilibili or Douyin hot list; no account access."""
    if platform not in {'baidu', 'bilibili', 'douyin'}:
        raise ValueError('Unsupported hotspot platform')
    if not 1 <= limit <= 12:
        raise ValueError('Limit must be between 1 and 12')
    return upstream.query_hot_trending_raw(platform, limit)


if __name__ == '__main__':
    upstream.mcp.run(transport='stdio')
