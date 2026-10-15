"""Per-industry discovery. Only successfully read page text is learning evidence."""
import asyncio
import hashlib
import re
from urllib.parse import urlsplit

from .core import _now, _write_json
from .public_search import search
from .web_learning import SafeFetcher, canonical_url, extract_document, official_sites, _related_links, CollectionError
from .autonomy_strategy import strategy


async def discover(store, agent, plan, directory, limit=2):
    seeds = official_sites(store, agent['id']) if agent['id'] != 'central' else []
    if not seeds:
        for page in store.pages(agent['id']):
            for raw in re.findall(r'https?://[^\s<>\)\]"；]+', page['body']):
                try:
                    url = canonical_url(raw)
                    if url not in seeds:
                        seeds.append(url)
                except ValueError:
                    pass
            if len(seeds) >= 8:
                break
    candidates, errors = [], []
    query = plan['query']
    try:
        result = await search(store, query)
        candidates = [s['url'] for s in result.get('sources', [])]
        _write_json(directory / 'search.json', result)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        errors.append({'stage': 'search', 'error': str(exc)[:300]})
    # Prefer a discovered primary source when the role has an official catalog.
    hosts = {urlsplit(u).hostname for u in seeds}
    # Planner suggestions are only fetch candidates. A successful public read
    # and quote/semantic verification remain required before they become evidence.
    proposals = plan.get('urls', [])
    if not isinstance(proposals, list):
        proposals = []
    else:
        proposals = list(proposals)
    proposals += ['https://' + part for part in re.findall(r'\bsite:([A-Za-z0-9.-]+/[^\s]+)', query)]
    verified_candidates = []
    for value in proposals[:3]:
        try:
            value = canonical_url(value)
            verified_candidates.append(value)
        except (TypeError, ValueError):
            pass
    candidates = list(dict.fromkeys(verified_candidates + candidates))
    requested_hosts = re.findall(r'\bsite:([A-Za-z0-9.-]+)', query)
    def matches(url, domains):
        host = urlsplit(url).hostname or ''
        return any(host == domain or host.endswith('.' + domain) for domain in domains)
    # Official catalogs influence ranking, but do not fence in industry research.
    # An explicit site: query still constrains this particular search.
    allowed_hosts = requested_hosts
    if allowed_hosts:
        rejected = [u for u in candidates if not matches(u, allowed_hosts)]
        candidates = [u for u in candidates if matches(u, allowed_hosts)]
        if rejected:
            errors.append({'stage': 'relevance', 'error': '搜索结果偏离指定行业来源，已排除', 'discarded_count': len(rejected)})
        matching_seeds = [u for u in seeds if matches(u, allowed_hosts)]
        seeds = matching_seeds
    ranked = await strategy(store, 'rankSources', candidates=candidates, hosts=list(hosts), query=query)
    if not isinstance(ranked, list) or set(ranked) != set(candidates) or any(not isinstance(u, str) for u in ranked):
        raise ValueError('行业学习策略返回了未发现的来源')
    candidates = ranked
    # A repair's concrete chapter/API candidates must survive general search
    # ranking, which can otherwise promote catalogs or contributor histories.
    proposed = [u for u in verified_candidates if u in candidates]
    queue = list(dict.fromkeys(proposed + candidates[:3] + seeds[:4]))
    fetcher = SafeFetcher(use_system_proxy=True)
    sources, seen, fallback, discovered = [], set(), [], []
    specific_query = re.sub(r'\bsite:\S+', '', query)
    generic = {'site', 'official', 'documentation', 'docs', 'www', 'com', 'org', 'dev'}
    generic.update(part for host in hosts for part in host.split('.'))
    specific_query = ' '.join(term for term in specific_query.split() if term.lower() not in generic)
    while queue and len(seen) < 10 and len(sources) < limit:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            url = canonical_url(url)
            response = await asyncio.wait_for(asyncio.to_thread(fetcher.fetch, url), 24)
            if allowed_hosts and not matches(response['url'], allowed_hosts):
                raise ValueError('跳转后的正文不属于指定来源')
            # Read links before extraction: a short table of contents can fail
            # the body reader while still linking to precisely the needed API.
            mime = response.get('headers', {}).get('content-type', '')
            related = _related_links(response, specific_query) if not mime or 'html' in mime else []
            links = [u for u in related
                     if not allowed_hosts or matches(u, allowed_hosts)]
            discovered = list(dict.fromkeys(discovered + links))
            queue = list(dict.fromkeys(queue + links[:4]))
            document = _read_document(response, specific_query)
            if len(document['text'].strip()) < 180:
                raise ValueError('页面正文不足，不能作为学习依据')
            navigation = (len(document['text']) < 2400 and re.search(
                r'\b(?:index|table of contents|overview)\b|文档首页|目录|总览', document['title'], re.I))
            if links and (url in seeds or navigation):
                queue = list(dict.fromkeys(links[:4] + queue))
                fallback.append((response, document))
                continue
            sources.append(_archive(directory, response, document, len(sources), specific_query))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            errors.append({'url': url, 'stage': 'read', 'error': str(exc)[:300]})
    for response, document in fallback:
        if len(sources) >= limit:
            break
        sources.append(_archive(directory, response, document, len(sources), specific_query))
    _write_json(directory / 'sources.json', {'sources': sources, 'errors': errors,
                                           'discovered_links': discovered[:40]})
    if not sources:
        raise ValueError('本行业未读到可用的公开原文；已保存发现与读取失败记录')
    return sources


def _read_document(response, query):
    # Quotes use visible text rather than generated Markdown link syntax.
    is_html = response.get('body') and 'html' in response.get('headers', {}).get('content-type', '')
    plain = _plain_document(response) if is_html else None
    try:
        document = extract_document(response)
    except CollectionError as exc:
        if not plain or '正文超过单份入库上限' not in str(exc):
            raise
        # Large standards need a focused passage, not rejection or a larger
        # model context. Keep the same download bound and record this scope.
        from trafilatura import extract_metadata
        metadata = extract_metadata(response['body'], default_url=response['url'])
        return {'title': metadata.title if metadata and metadata.title else response['url'],
                'text': _excerpt(plain, query), 'archive_scope': 'selected_passage',
                'full_text_sha256': hashlib.sha256(plain.encode()).hexdigest(),
                'full_text_bytes': len(plain.encode())}
    return {**document, 'text': plain} if plain else document


def _plain_document(response):
    from lxml import html
    from trafilatura import extract
    tree = html.fromstring(response['body'], parser=html.HTMLParser(no_network=True))
    for element in tree.xpath('//script | //style | //noscript | //template | //*[@hidden] | //*[@aria-hidden="true"]'):
        element.drop_tree()
    # Sphinx nests commands as td > p > code > span. The reader can discard
    # those cells as empty; preserve their actual text before readability cleanup.
    for cell in tree.xpath('//td | //th'):
        value = cell.text_content()
        for child in list(cell):
            cell.remove(child)
        cell.text = value
    return extract(tree, url=response['url'], output_format='txt', include_comments=False,
                   include_tables=True, include_links=False, include_formatting=False, favor_precision=True)


def _excerpt(text, query):
    """Choose one contiguous, verifiable passage near the requested concepts."""
    raw = text.encode('utf-8')
    if len(raw) <= 14000:
        return text
    words = set(re.findall(r'[a-z][a-z0-9_]{2,}', query.lower())) - {
        'the', 'and', 'for', 'with', 'how', 'from', 'official', 'documentation', 'docs'}
    lower = text.lower()
    positions = [m.start() for word in words for m in list(re.finditer(re.escape(word), lower))[:80]]
    starts = {max(0, p - 1200) for p in positions} | {0}
    def window(start):
        return text[start:].encode('utf-8')[:14000].decode('utf-8', errors='ignore')
    def score(start):
        passage = window(start).lower()
        return (sum(word in passage for word in words),
                sum(min(5, passage.count(word)) for word in words), -start)
    return window(max(starts, key=score))


def _archive(directory, response, document, index, query=''):
    text = document['text']
    excerpt = _excerpt(text, query)
    name = 'source-' + str(index + 1) + '.txt'
    path = directory / name
    path.write_text(text, encoding='utf-8')
    path.chmod(0o600)
    return {'id': str(index + 1), 'title': document['title'], 'url': response['url'],
            'sha256': hashlib.sha256(text.encode()).hexdigest(), 'file': name,
            'excerpt': excerpt, 'truncated': len(excerpt) < len(text) or document.get('archive_scope') == 'selected_passage',
            'archive_scope': document.get('archive_scope', 'page_text'),
            **{k: document[k] for k in ('full_text_sha256', 'full_text_bytes') if k in document},
            'checked_at': _now(), 'read_method': 'public_page_text'}
