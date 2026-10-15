"""Live public search with fallback, query filtering and source receipts."""
from datetime import datetime, timezone
import hashlib
import re
from urllib.parse import urlsplit, parse_qs, urljoin
from urllib.request import getproxies
from xml.etree import ElementTree

import httpx
from lxml import html
from .web_learning import canonical_url

PROVIDERS = ('auto', 'duckduckgo', 'bing-rss', 'tavily')
STOP = {'site', 'official', 'documentation', 'docs', 'the', 'and', 'for', 'with',
        'what', 'how', 'does', 'this', 'that', 'from', 'search', 'please', 'www', 'com', 'org'}


async def _fetch(url, query, **params):
    async with httpx.AsyncClient(timeout=18, follow_redirects=False,
                                 proxy=getproxies().get('https')) as client:
        async with client.stream('GET', url, params={'q': query, **params},
                                 headers={'User-Agent': 'Mozilla/5.0 (compatible; OpenWikiSearch/1.0)'}) as response:
            if response.status_code != 200:
                raise ValueError('搜索入口 HTTP ' + str(response.status_code))
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                raw.extend(chunk)
                if len(raw) > 500000:
                    raise ValueError('搜索响应超过大小上限')
            return bytes(raw)


async def _entries(provider, query, store, key):
    if provider == 'tavily':
        from .web_learning import _tavily_urls
        if not key:
            raise ValueError('Tavily 密钥尚未配置')
        urls = await _tavily_urls(store, query, [], key)
        return [{'url': u, 'title': u, 'description': '', 'provider_ranked': True} for u in urls]
    if provider == 'bing-rss':
        raw = await _fetch('https://www.bing.com/search', query, format='rss')
        try:
            feed = ElementTree.fromstring(raw)
        except ElementTree.ParseError:
            raise ValueError('Bing 未返回 RSS 搜索结果') from None
        return [{'url': i.findtext('link', ''), 'title': i.findtext('title', ''),
                 'description': i.findtext('description', '')} for i in feed.findall('./channel/item')]
    raw = await _fetch('https://html.duckduckgo.com/html/', query)
    tree = html.fromstring(raw, parser=html.HTMLParser(no_network=True))
    if tree.xpath('//form[contains(@action,"anomaly")]'):
        raise ValueError('搜索入口要求人工验证，未绕过验证')
    entries = []
    for block in tree.xpath('//*[contains(concat(" ",normalize-space(@class)," ")," result ")]')[:20]:
        anchors = block.xpath('.//a[contains(@class,"result__a")]')
        if not anchors:
            continue
        anchor = anchors[0]
        raw_url = urljoin('https://duckduckgo.com', anchor.get('href', ''))
        parts = urlsplit(raw_url)
        if parts.hostname in {'duckduckgo.com', 'www.duckduckgo.com'}:
            raw_url = parse_qs(parts.query).get('uddg', [''])[0]
        snippets = block.xpath('.//*[contains(@class,"result__snippet")]')
        entries.append({'url': raw_url, 'title': anchor.text_content().strip(),
                        'description': ' '.join(n.text_content().strip() for n in snippets)})
    return entries


def _terms(query):
    query = re.sub(r'\bsite:\S+', '', query.lower())
    terms = set(re.findall(r'[a-z0-9][a-z0-9_.+-]{1,}', query)) - STOP
    for text in re.findall(r'[\u4e00-\u9fff]+', query):
        terms.update(text[i:i+2] for i in range(len(text)-1)
                     if text[i:i+2] not in {'搜索', '联网', '一下', '帮我', '请问', '如何', '什么'})
    return terms


def _sources(entries, query, target_host):
    restrictions = [urlsplit('https://' + s) for s in re.findall(r'(?:^|\s)site:([^\s"\']+)', query)]
    terms = _terms(query)
    sources, seen, discarded = [], set(), 0
    for entry in entries[:20]:
        try:
            url = canonical_url(entry['url'])
        except (ValueError, TypeError):
            continue
        parts = urlsplit(url)
        text = (url + ' ' + entry['title'] + ' ' + entry.get('description', '')).lower()
        matches = [term for term in terms if term in text]
        if target_host:
            related = (parts.hostname == target_host or parts.hostname.endswith('.' + target_host)
                       or target_host in text)
        elif restrictions:
            related = any((parts.hostname == r.hostname or parts.hostname.endswith('.' + (r.hostname or '')))
                          and (not r.path.strip('/') or parts.path.startswith(r.path)) for r in restrictions)
        else:
            related = entry.get('provider_ranked') or not terms or len(matches) >= min(2, len(terms))
        if not related:
            discarded += 1
            continue
        if url in seen:
            continue
        seen.add(url)
        snippet = entry.get('description') or entry['title']
        sources.append({'url': url, 'title': entry['title'][:300], 'excerpt': snippet[:1500],
                        'sha256': hashlib.sha256(snippet.encode()).hexdigest(),
                        'read_method': 'search_result_snippet', 'truncated': True})
        if len(sources) >= 6:
            break
    return sources, discarded


async def search(store, query):
    from .tool_services import configuration
    from .web_learning import _search_key
    if not isinstance(query, str) or not query.strip() or len(query) > 1000 or '\0' in query:
        raise ValueError('搜索词无效')
    config = configuration(store).get('search', {})
    if config.get('enabled') is False:
        return {'status': 'unavailable', 'sources': [], 'note': '搜索服务已关闭'}
    key = config.get('api_key') or _search_key(store)
    selected = config.get('provider', 'auto')
    if selected not in PROVIDERS:
        return {'status': 'unavailable', 'sources': [], 'note': '搜索服务配置无效'}
    original_query, target_host = query, None
    if query.strip().startswith(('http://', 'https://')) and not any(c.isspace() for c in query.strip()):
        target_host = urlsplit(canonical_url(query.strip())).hostname
        query = f'site:{target_host} "{target_host}"'
    providers = ([*(['tavily'] if key else []), 'duckduckgo', 'bing-rss'] if selected == 'auto' else [selected])
    attempts, discarded, sources = [], 0, []
    provider = providers[0]
    for provider in providers:
        try:
            entries = await _entries(provider, query, store, key)
            sources, count = _sources(entries, query, target_host)
            discarded += count
            attempts.append({'provider': provider, 'status': 'completed' if sources else 'no_related_results' if count else 'no_results',
                             'returned_count': len(sources), 'discarded_count': count})
            if sources:
                break
        except (httpx.HTTPError, ValueError, ElementTree.ParseError, html.etree.ParserError) as exc:
            attempts.append({'provider': provider, 'status': 'blocked',
                             'error': str(exc)[:200] if isinstance(exc, ValueError) else type(exc).__name__})
    return {'status': 'completed' if sources else 'no_related_results' if discarded else 'blocked' if all(a['status']=='blocked' for a in attempts) else 'no_results',
            'provider': provider, 'configured_provider': selected, 'query': original_query, 'effective_query': query,
            'target_host': target_host, 'discarded_unrelated_count': discarded, 'attempts': attempts,
            'checked_at': datetime.now(timezone.utc).isoformat(), 'sources': sources,
            'note': '实时搜索结果摘要，尚未读取网页正文；需要正文时继续调用 web_read。匹配筛选不等于事实核验。'}
