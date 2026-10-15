"""Public headline feeds. This cache never writes Wiki knowledge or invokes AI."""
import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
from html import unescape
import json
import re
import time
import urllib.request
from urllib.parse import urljoin, urlsplit
import xml.etree.ElementTree as ET
from lxml import html as lxml_html
from .platform_mcp import PLATFORMS as MCP_PLATFORMS, PROVIDER as MCP_PROVIDER, read_hotlist

SOURCES = (
    {'id': 'openai', 'name': 'OpenAI', 'group': 'ai', 'kind': 'rss', 'url': 'https://openai.com/news/rss.xml'},
    {'id': 'google-ai', 'name': 'Google AI', 'group': 'ai', 'kind': 'rss', 'url': 'https://blog.google/technology/ai/rss/'},
    {'id': 'baidu', 'name': '百度热搜', 'group': 'general', 'kind': 'baidu', 'url': 'https://top.baidu.com/board?tab=realtime'},
    {'id': 'bilibili', 'name': '哔哩哔哩', 'group': 'general', 'kind': 'bilibili', 'url': 'https://api.bilibili.com/x/web-interface/ranking/v2?rid=0&type=all'},
    {'id': 'douyin', 'name': '抖音热榜', 'group': 'general', 'kind': 'douyin',
     'url': 'https://aweme.snssdk.com/aweme/v1/hot/search/list/',
     'description': '抖音热点榜 · 平台公开数据', 'score_label': '抖音热度'},
    {'id': 'github', 'name': 'GitHub', 'group': 'tech', 'kind': 'github',
     'url': 'https://github.com/trending?since=daily',
     'description': 'GitHub Trending · 今日趋势', 'score_label': '今日新增 Star'},
    {'id': 'xiaohongshu', 'name': '小红书', 'group': 'general', 'kind': 'pending',
     'url': 'https://www.xiaohongshu.com/explore', 'description': '小红书热点 · 待接入',
     'unavailable_reason': '公开榜单接口实测返回 HTTP 406；尚未接入可用的榜单数据源。'},
)
MAX_BYTES = 1500000


def stamp():
    return datetime.now(timezone.utc).isoformat()


def public_link(url, base):
    if not isinstance(url, str) or not url.strip() or len(url) > 2000:
        return None
    value = urljoin(base, str(url or ''))
    parsed = urlsplit(value)
    if parsed.scheme not in {'https', 'http'} or not parsed.hostname or parsed.username or parsed.password:
        return None
    if parsed.hostname.lower() in {'localhost', '127.0.0.1', '::1'}:
        return None
    return value[:2000]


def date(value):
    try:
        result = parsedate_to_datetime(value)
        return (result if result.tzinfo else result.replace(tzinfo=timezone.utc)).isoformat()
    except (TypeError, ValueError, OverflowError):
        try:
            result = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return (result if result.tzinfo else result.replace(tzinfo=timezone.utc)).isoformat()
        except (TypeError, ValueError, AttributeError):
            return None


def normalize(items, source):
    result, seen = [], set()
    for item in items:
        title = re.sub(r'\s+', ' ', str(item.get('title') or '')).strip()[:240]
        url = public_link(item.get('url'), source['url'])
        if not title or not url or url in seen:
            continue
        seen.add(url)
        result.append({'id': hashlib.sha256((source['id'] + url).encode()).hexdigest()[:20],
                       'title': title, 'url': url, 'rank': item.get('rank') if type(item.get('rank')) is int and item['rank'] > 0 else len(result) + 1,
                       'published_at': item.get('published_at'), 'score': item.get('score'),
                       'score_label': source.get('score_label', '播放量' if source['id'] == 'bilibili' else '平台热度'),
                       'summary': re.sub(r'\s+', ' ', unescape(re.sub(r'<[^>]*>', ' ', str(item.get('summary') or '')))).strip()[:1600],
                       'source_id': source['id'], 'source': source['name'], 'group': source['group']})
        if len(result) >= 12:
            break
    if not result:
        raise ValueError('没有读到可展示的榜单或新闻，未生成示例数据。')
    return result


def parse_feed(body, source):
    if len(body) > MAX_BYTES or (source['kind'] == 'rss' and (b'<!DOCTYPE' in body.upper() or b'<!ENTITY' in body.upper())):
        raise ValueError('订阅正文无效或超过上限。')
    items = []
    if source['kind'] == 'rss':
        root = ET.fromstring(body)
        for node in root.findall('.//item'):
            items.append({'title': node.findtext('title'), 'url': node.findtext('link'),
                          'summary': node.findtext('description'),
                          'published_at': date(node.findtext('pubDate'))})
        if not items:
            ns = {'a': 'http://www.w3.org/2005/Atom'}
            for node in root.findall('a:entry', ns):
                link = node.find('a:link', ns)
                items.append({'title': node.findtext('a:title', namespaces=ns),
                              'summary': node.findtext('a:summary', namespaces=ns),
                              'url': link.get('href') if link is not None else None,
                              'published_at': date(node.findtext('a:published', namespaces=ns) or node.findtext('a:updated', namespaces=ns))})
    elif source['kind'] == 'baidu':
        match = re.search(r'<!--s-data:(.*?)-->', body.decode('utf-8'), re.S)
        if not match:
            raise ValueError('百度页面没有返回榜单数据。')
        value = json.loads(match.group(1))
        cards = value.get('data', {}).get('cards', [])
        for card in cards:
            for node in card.get('content', []):
                items.append({'title': node.get('word') or node.get('query'), 'url': node.get('url'),
                              'score': node.get('hotScore')})
    elif source['kind'] == 'bilibili':
        value = json.loads(body)
        if value.get('code') != 0:
            raise ValueError('平台暂未提供榜单：' + str(value.get('message', value.get('code'))))
        for node in value.get('data', {}).get('list', []):
            if not re.fullmatch(r'BV[A-Za-z0-9]{10}', str(node.get('bvid', ''))):
                continue
            items.append({'title': node.get('title'), 'url': 'https://www.bilibili.com/video/' + str(node.get('bvid', '')),
                          'score': node.get('stat', {}).get('view')})
    elif source['kind'] == 'douyin':
        value = json.loads(body)
        if value.get('status_code') != 0:
            raise ValueError('抖音暂未提供热榜：' + str(value.get('status_code')))
        words = value.get('data', {}).get('word_list', [])
        for node in words:
            identifier = str(node.get('sentence_id', ''))
            if not re.fullmatch(r'\d{1,30}', identifier):
                continue
            # event_time is the topic's event time, not an article publication.
            items.append({'title': node.get('word'), 'url': 'https://www.douyin.com/hot/' + identifier,
                          'score': node.get('hot_value'), 'rank': node.get('position')})
    elif source['kind'] == 'github':
        root = lxml_html.fromstring(body, parser=lxml_html.HTMLParser(no_network=True))
        for node in root.xpath('//article[contains(concat(" ", normalize-space(@class), " "), " Box-row ")]'):
            links = node.xpath('./h2/a[@href]')
            if not links:
                continue
            relative = links[0].get('href')
            if not re.fullmatch(r'/[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}', relative):
                continue
            description = ' '.join(p.text_content() for p in node.xpath('./p'))
            # Daily gain is distinct from the repository's total stars.
            gain = re.search(r'([0-9][0-9,]*)\s+stars?\s+today', node.text_content(), re.I)
            items.append({'title': relative[1:], 'url': 'https://github.com' + relative,
                          'summary': description, 'score': int(gain[1].replace(',', '')) if gain else None})
    return normalize(items, source)


def fetch(source):
    if source['kind'] == 'pending':
        raise ValueError(source['unavailable_reason'])
    request = urllib.request.Request(source['url'], headers={'User-Agent': 'Mozilla/5.0', 'Accept': '*/*'})
    with urllib.request.urlopen(request, timeout=9) as response:
        body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise ValueError('来源正文超过上限。')
    return parse_feed(body, source)


class HotspotMonitor:
    def __init__(self, fetcher=fetch, article_fetcher=None, mcp_fetcher=None):
        self.fetcher, self.lock = fetcher, None
        self.mcp_fetcher = mcp_fetcher or read_hotlist
        self.explicit_mcp_fetcher = mcp_fetcher is not None
        self.article_fetcher = article_fetcher or fetch_article
        self.known_items, self.articles, self.article_locks = {}, {}, {}
        self.reader_slots = None
        self.sources = {source['id']: {**source, 'status': 'loading', 'items': [], 'fetched_at': None} for source in SOURCES}
        self.checked_at = None
        self.last_attempt = 0

    def snapshot(self):
        return {'checked_at': self.checked_at, 'refresh_seconds': 300,
                'sources': list(self.sources.values()),
                'items': [item for source in self.sources.values() for item in source['items']]}

    def item(self, identifier):
        for source in self.sources.values():
            for item in source['items']:
                if item['id'] == identifier:
                    return {**item, 'fetched_at': source['fetched_at'], 'source_status': source['status']}
        return self.known_items.get(identifier)

    def resolve(self, question):
        """Only resolve an exact visible headline or an explicit source/rank."""
        for item in self.snapshot()['items']:
            if len(item['title']) > 8 and item['title'].lower() in question.lower():
                return item['id']
        aliases = {'openai': r'openai', 'google-ai': r'google|谷歌',
                   'baidu': r'百度', 'bilibili': r'哔哩|b站', 'douyin': r'抖音|douyin',
                   'github': r'github|git\s*hub', 'xiaohongshu': r'小红书|xiaohongshu|rednote'}
        rank = re.search(r'第?([一二三四五六七八九十]|\d{1,2})(?:条|名)', question)
        if rank:
            value = rank[1]
            number = int(value) if value.isdigit() else '一二三四五六七八九十'.index(value) + 1
            for source_id, pattern in aliases.items():
                if re.search(pattern, question, re.I):
                    return next((item['id'] for item in self.sources[source_id]['items'] if item['rank'] == number), None)
        return None

    async def read(self, identifier):
        item = self.item(identifier)
        if item is None:
            raise KeyError(identifier)
        if self.reader_slots is None:
            self.reader_slots = asyncio.Semaphore(3)
        cached = self.articles.get(identifier)
        if cached and time.monotonic() - cached[0] < (1800 if cached[1]['status'] == 'ready' else 90):
            return cached[1]
        lock = self.article_locks.setdefault(identifier, asyncio.Lock())
        async with lock:
            cached = self.articles.get(identifier)
            if cached and time.monotonic() - cached[0] < (1800 if cached[1]['status'] == 'ready' else 90):
                return cached[1]
            result = {**item, 'status': 'unavailable', 'text': '', 'read_at': stamp(), 'truncated': False}
            try:
                async with self.reader_slots:
                    document = await asyncio.wait_for(asyncio.to_thread(self.article_fetcher, item), timeout=22)
                text = document['text'][:60000]
                result.update(status='ready', text=text, document_title=document['title'],
                              document_url=document.get('url', item['url']),
                              sha256=hashlib.sha256(text.encode()).hexdigest(),
                              truncated=len(document['text']) > len(text))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                result['error'] = str(exc)[:300] or '正文读取超时。'
            self.articles[identifier] = (time.monotonic(), result)
            if len(self.articles) > 64:
                oldest = next(iter(self.articles))
                self.articles.pop(oldest)
                self.article_locks.pop(oldest, None)
            return result

    async def context(self, identifier=None):
        snapshot = self.snapshot()
        result = {'checked_at': snapshot['checked_at'], 'sources': []}
        for source in snapshot['sources']:
            result['sources'].append({'id': source['id'], 'name': source['name'], 'status': source['status'],
                'description': source.get('description'), 'error': source.get('error'),
                'data_route': source.get('data_route'), 'mcp': source.get('mcp'),
                'fetched_at': source['fetched_at'], 'items': [
                    {key: item.get(key) for key in ('id', 'title', 'url', 'rank', 'score', 'score_label', 'published_at')}
                    for item in source['items']]})
        if identifier:
            article = await self.read(identifier)
            excerpt = article['text'][:3500]
            result['selected'] = {key: article.get(key) for key in
                ('id', 'title', 'url', 'source', 'published_at', 'score', 'fetched_at', 'source_status', 'status', 'read_at', 'summary', 'error')}
            result['selected'].update(excerpt=excerpt, excerpt_sha256=hashlib.sha256(excerpt.encode()).hexdigest(),
                truncated=article['truncated'] or len(article['text']) > len(excerpt))
        return result

    async def refresh(self, force=False):
        if self.lock is None:
            self.lock = asyncio.Lock()
        if self.lock.locked() or (self.last_attempt and not force and time.monotonic() - self.last_attempt < 300):
            return self.snapshot()
        async with self.lock:
            self.last_attempt = time.monotonic()
            async def one(source):
                previous = self.sources[source['id']]
                mcp = None
                route = {'method': 'rss' if source['kind'] == 'rss' else 'direct',
                         'label': '官方 RSS' if source['kind'] == 'rss' else '平台公开来源'}
                try:
                    if source['id'] in MCP_PLATFORMS and (self.fetcher is fetch or self.explicit_mcp_fetcher):
                        mcp = {**MCP_PROVIDER, 'status': 'connected'}
                        try:
                            rows = await asyncio.wait_for(self.mcp_fetcher(source['id']), timeout=14)
                            items = normalize(rows, source)
                            route = {'method': 'mcp', 'label': '开源 MCP · 本机',
                                     'board': '热门视频' if source['id'] == 'bilibili' else '热搜榜'}
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            mcp.update(status='failed', error=str(exc)[:160] or 'MCP 读取超时')
                            items = await asyncio.wait_for(asyncio.to_thread(self.fetcher, source), timeout=10)
                            route.update(label='平台公开来源 · MCP 暂不可用，已回退', fallback_from='mcp')
                    else:
                        items = await asyncio.wait_for(asyncio.to_thread(self.fetcher, source), timeout=18)
                    self.sources[source['id']] = {**source, 'status': 'ready', 'items': items,
                        'fetched_at': stamp(), 'error': None, 'data_route': route, 'mcp': mcp}
                    for item in items:
                        self.known_items.pop(item['id'], None)
                        self.known_items[item['id']] = {**item, 'fetched_at': self.sources[source['id']]['fetched_at'], 'source_status': 'ready'}
                    while len(self.known_items) > 144:
                        self.known_items.pop(next(iter(self.known_items)))
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.sources[source['id']] = {**source, 'status': 'stale' if previous['items'] else 'unavailable',
                        'items': previous['items'], 'fetched_at': previous['fetched_at'], 'error': str(exc)[:240],
                        'mcp': mcp, 'data_route': previous.get('data_route') if previous['items'] else None}
            await asyncio.gather(*(one(source) for source in SOURCES))
            self.checked_at = stamp()
        return self.snapshot()


def fetch_article(item):
    """Read only an actual feed item through the existing public-address reader."""
    from .web_learning import SafeFetcher, extract_document
    response = SafeFetcher(use_system_proxy=True).fetch(item['url'])
    return {**extract_document(response), 'url': response['url']}
