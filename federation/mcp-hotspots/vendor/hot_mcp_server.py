# -*- coding: utf-8 -*-
"""
China Hot Trending Aggregator - Remote MCP Server
--------------------------------------------------
Aggregates real-time hot-search / trending boards from major Chinese
platforms: Weibo, Zhihu, Bilibili, Baidu, Toutiao, Douyin, Tieba, Juejin.
All data comes from the platforms' own public web/API endpoints:
no API key, no login required. Results are cached in memory for 5 minutes;
a failed source degrades gracefully and never breaks the other platforms.

Author: liufuyang  2026-09-02
"""
import json
import os
import re
import ssl
import time
import datetime
import urllib.parse
import urllib.request
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings


BASE_DIR = Path(__file__).parent

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

CACHE_TTL = 300  # seconds
FETCH_TIMEOUT = 10  # seconds per attempt

# platform slug -> display names (Chinese names kept in UTF-8 JSON config
# so this code file stays pure-ASCII, safe for Windows default encoding)
with open(BASE_DIR / "platform_names.json", "r", encoding="utf-8") as _f:
    PLATFORM_NAMES = json.load(_f)

# order used by platform="all": the 5 mainstream ones first
ALL_ORDER = ["weibo", "zhihu", "bilibili", "baidu",
             "toutiao", "douyin", "tieba", "juejin"]
ALL_TOP_N = 10

# in-memory cache: slug -> (timestamp, result)
_cache = {}


# ---------------------------------------------------------------- HTTP utils
def _http_get(url, headers=None, timeout=FETCH_TIMEOUT):
    req = urllib.request.Request(url)
    req.add_header("User-Agent", UA)
    req.add_header("Accept", "application/json, text/plain, */*")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    resp = urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX)
    raw = resp.read()
    encoding = resp.headers.get_content_charset() or "utf-8"
    return raw.decode(encoding, errors="ignore")


def _http_json(url, headers=None, timeout=FETCH_TIMEOUT):
    return json.loads(_http_get(url, headers=headers, timeout=timeout))


def _retry(fn, *args, **kwargs):
    """Call fn once, retry exactly once on failure."""
    try:
        return fn(*args, **kwargs)
    except Exception:
        time.sleep(0.5)
        return fn(*args, **kwargs)


def _item(rank, title, hot, url):
    return {"rank": int(rank), "title": str(title or "").strip(),
            "hot": int(hot or 0), "url": url or ""}


# ------------------------------------------------------------------- sources
def fetch_weibo():
    url = "https://weibo.com/ajax/side/hotSearch"
    d = _retry(_http_json, url, headers={"Referer": "https://weibo.com/"})
    rows = ((d.get("data") or {}).get("realtime")) or []
    out = []
    for it in rows:
        title = it.get("word") or it.get("note") or ""
        if not title:
            continue
        q = urllib.parse.quote(title)
        out.append(_item(len(out) + 1, title, it.get("num"),
                         "https://s.weibo.com/weibo?q=" + q))
    return out


def fetch_zhihu():
    url = "https://api.zhihu.com/topstory/hot-lists/total?limit=50"
    d = _retry(_http_json, url, headers={"Referer": "https://www.zhihu.com/"})
    rows = d.get("data") or []
    out = []
    for it in rows:
        t = it.get("target") or {}
        title = t.get("title")
        if not title:
            continue
        hot = 0
        m = re.match(r"\s*([\d.]+)", str(it.get("detail_text") or ""))
        if m:
            try:
                hot = int(float(m.group(1)) * 10000)
            except ValueError:
                hot = 0
        # api.zhihu.com exposes API URLs; convert to browser-friendly link
        out.append(_item(len(out) + 1, title, hot,
                         "https://www.zhihu.com/question/" + str(t.get("id") or "")))
    return out


def fetch_bilibili():
    url = "https://api.bilibili.com/x/web-interface/popular?ps=20&pn=1"
    d = _retry(_http_json, url, headers={"Referer": "https://www.bilibili.com/"})
    rows = ((d.get("data") or {}).get("list")) or []
    out = []
    for it in rows:
        title = it.get("title")
        if not title:
            continue
        stat = it.get("stat") or {}
        link = it.get("short_link_v2") or it.get("short_link") or ""
        if not link:
            bvid = it.get("bvid") or ""
            link = ("https://www.bilibili.com/video/" + bvid) if bvid else ""
        out.append(_item(len(out) + 1, title, stat.get("view"), link))
    return out


def fetch_baidu():
    # PC endpoint returns hotScore directly; HTML page is fallback.
    url = "https://top.baidu.com/api/board?platform=pc&tab=realtime"
    try:
        d = _http_json(url, headers={"Referer": "https://top.baidu.com/board?tab=realtime"})
        rows = (((d.get("data") or {}).get("cards")) or [{}])[0].get("content") or []
    except Exception:
        rows = []
    if not rows:
        html = _retry(_http_get, "https://top.baidu.com/board?tab=realtime")
        m = re.search(r"<!--s-data:(.*?)-->", html, re.S)
        if m:
            sd = json.loads(m.group(1))
            cards = ((sd.get("data") or {}).get("cards")) or sd.get("cards") or []
            if cards:
                c0 = cards[0].get("content") or []
                rows = (c0[0].get("content") if c0 and isinstance(c0[0], dict)
                        and c0[0].get("content") else c0)
    out = []
    for it in rows:
        title = it.get("word") or it.get("title") or it.get("query") or ""
        if not title:
            continue
        link = it.get("url") or ("https://www.baidu.com/s?wd=" + urllib.parse.quote(title))
        out.append(_item(len(out) + 1, title, it.get("hotScore"), link))
    return out


def fetch_toutiao():
    url = "https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc"
    d = _retry(_http_json, url)
    rows = d.get("data") or []
    out = []
    for it in rows:
        title = it.get("Title")
        if not title:
            continue
        cid = it.get("ClusterId") or it.get("ClusterIdStr") or ""
        link = it.get("Url") or ("https://www.toutiao.com/trending/" + str(cid) + "/")
        out.append(_item(len(out) + 1, title, it.get("HotValue"), link))
    return out


def fetch_douyin():
    url = "https://www.iesdouyin.com/web/api/v2/hotsearch/billboard/word/"
    d = _retry(_http_json, url)
    rows = d.get("word_list") or []
    out = []
    for it in rows:
        title = it.get("word")
        if not title:
            continue
        out.append(_item(len(out) + 1, title, it.get("hot_value"),
                         "https://www.douyin.com/search/" + urllib.parse.quote(title)))
    return out


def fetch_tieba():
    url = "https://tieba.baidu.com/hottopic/browse/topicList"
    d = _retry(_http_json, url)
    rows = (((d.get("data") or {}).get("bang_topic") or {}).get("topic_list")) or []
    out = []
    for it in rows:
        title = it.get("topic_name")
        if not title:
            continue
        out.append(_item(len(out) + 1, title, it.get("discuss_num"),
                         it.get("topic_url") or ""))
    return out


def fetch_juejin():
    url = "https://api.juejin.cn/content_api/v1/content/article_rank?category_id=1&type=hot"
    d = _retry(_http_json, url)
    rows = d.get("data") or []
    out = []
    for it in rows:
        try:
            content = it.get("content") or {}
            counter = it.get("content_counter") or {}
            cid = content.get("content_id")
            title = content.get("title")
            if not title:
                continue
            out.append(_item(len(out) + 1, title, counter.get("hot_rank"),
                             "https://juejin.cn/post/" + str(cid)))
        except Exception:
            continue
    return out


FETCHERS = {
    "weibo": fetch_weibo,
    "zhihu": fetch_zhihu,
    "bilibili": fetch_bilibili,
    "baidu": fetch_baidu,
    "toutiao": fetch_toutiao,
    "douyin": fetch_douyin,
    "tieba": fetch_tieba,
    "juejin": fetch_juejin,
}


# -------------------------------------------------------------------- cache
def get_platform(slug, limit):
    """Return (ok, payload). payload is a list on success, error string on failure."""
    n = max(1, min(int(limit or 20), 50))
    now = time.time()
    cached = _cache.get(slug)
    if cached and now - cached[0] < CACHE_TTL:
        return True, cached[1][:n]
    try:
        items = FETCHERS[slug]()
        if not items:
            return False, "source returned an empty list"
    except Exception as e:
        return False, "%s: %s" % (type(e).__name__, e)
    _cache[slug] = (now, items)
    return True, items[:n]


def query_hot_trending_raw(platform, limit):
    platform = (platform or "all").strip().lower()
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(limit, 50))
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    if platform == "all":
        boards = {}
        errors = {}
        for slug in ALL_ORDER:
            ok, payload = get_platform(slug, ALL_TOP_N)
            if ok:
                boards[slug] = payload[:ALL_TOP_N]
            else:
                errors[slug] = payload
        return {
            "platforms": boards,
            "failed": errors,
            "note": ("per-platform top %d; aggregated at %s; "
                     "cache 5 minutes" % (ALL_TOP_N, stamp)),
        }

    if platform not in FETCHERS:
        return {"error": "unsupported platform '%s' (supported: %s, all)"
                         % (platform, ", ".join(ALL_ORDER))}
    ok, payload = get_platform(platform, limit)
    if not ok:
        return {"error": "failed to fetch %s hot list (%s). Please retry shortly."
                         % (platform, payload)}
    return {"platform": platform, "updated_at": stamp, "items": payload}


mcp = FastMCP(
    "hot-trending-query",
    host=os.environ.get("MCP_HOST", "127.0.0.1"),
    port=int(os.environ.get("MCP_PORT", "8007")),
    transport_security=TransportSecuritySettings(
        allowed_hosts=(os.environ.get("MCP_ALLOWED_HOSTS") or "127.0.0.1:*,localhost:*,[::1]:*,mcp.pianam.cn,mcp.pianam.cn:*").split(","),
        allowed_origins=(os.environ.get("MCP_ALLOWED_ORIGINS") or "https://mcp.pianam.cn,https://mcp.pianam.cn:*,http://127.0.0.1:*,http://localhost:*").split(","),
    ),
)


@mcp.tool()
def query_hot_trending(platform: str = "all", limit: int = 20) -> dict:
    """Query real-time hot-search / trending boards from major Chinese platforms.

    Args:
        platform: one of weibo / zhihu / bilibili / baidu / toutiao /
            douyin / tieba / juejin, or "all" (default). With "all" the
            tool returns the top 10 items of every platform.
        limit: max items per platform for single-platform queries (1-50,
            default 20). Ignored when platform="all" (top 10 each).
    Returns:
        Each item: rank, title, hot (popularity value, platform-specific
        metric), url (link to the original hot topic). For "all", a dict
        of platform -> items plus a "failed" map for degraded sources.
    Data: public web endpoints of the platforms themselves, no API key.
    Results cached 5 minutes server-side.
    """
    try:
        return query_hot_trending_raw(platform, limit)
    except Exception as e:
        return {"error": "query failed: %s: %s" % (type(e).__name__, e)}


@mcp.tool()
def list_platforms() -> dict:
    """List all supported platforms and their display names."""
    return {
        "platforms": [
            {"slug": s, "name": PLATFORM_NAMES[s]["zh"],
             "name_en": PLATFORM_NAMES[s]["en"]}
            for s in ALL_ORDER
        ],
        "note": "use query_hot_trending(platform=...) to fetch a board; "
                "platform='all' returns top 10 of every board",
    }


if __name__ == "__main__":
    # Rate-limit middleware: must run uvicorn with a custom app directly.
    # mcp.run() builds its own app instance and silently drops middleware.
    import sys
    import uvicorn
    sys.path.insert(0, str(BASE_DIR))
    from rate_limit import RateLimitMiddleware
    _app = mcp.streamable_http_app()
    _app.add_middleware(RateLimitMiddleware, limit_per_minute=60)
    uvicorn.run(_app, host=mcp.settings.host, port=mcp.settings.port,
                log_level=mcp.settings.log_level.lower())
