"""Bounded public research for a consultation, without importing or learning it.

Uses the existing public-address/robots-aware reader. Evidence is saved only in
the research run, never in a branch inbox, Wiki, template or published snapshot.
"""
import asyncio
import hashlib
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

from .core import _now, _write_json
from .public_browser import PublicBrowserReader, needs_browser
from .web_learning import (SafeFetcher, canonical_url, extract_document, official_sites,
                           _search_key, _select_seeds, _tavily_urls, _related_links, public_read_error)


# These explain platform entry requirements and workflows; they are not evidence
# of likely demand, an income forecast, or a recommendation to join a platform.
GENERAL_CATALOGS = {
    'freelance-income': (
        'https://support.proginn.com/qa/',
        'https://support.proginn.com/outsource/coder-sign/',
    ),
}


def research_scope(goal, agents):
    if re.search(r'副业|自由职业|接单|创收|增收|赚钱|挣钱|兼职|变现|\bfreelanc\w*\b|\bside\s+(?:hustle|income)\b', goal, re.I):
        return 'freelance-income'
    available = {agent['id'] for agent in agents}
    categories = [
        ('software-app', r'小程序|移动应用|手机应用|\bapp\b|flutter|android|ios|taro|uni-app'),
        ('software-frontend', r'前端|网站|网页|商城|react|vue|angular|css|html|web'),
        ('software-backend', r'后端|接口|数据库|java|spring|python|api'),
        ('software-devops', r'运维|部署|docker|kubernetes'),
        ('content-production', r'拍摄|摄影'),
        ('content-postproduction', r'剪辑|后期|视频'),
        ('content-planning', r'剧本|影视|短剧|故事'),
        ('commerce-operations', r'电商|店铺|零售|商品'),
        ('business', r'企业|经营|公司|组织|流程'),
    ]
    return next((identifier for identifier, pattern in categories
                 if identifier in available and re.search(pattern, goal, re.I)), None)


async def research_project(store, goal, run_id, agents, profile=None, on_progress=None, excerpt_query=None):
    if not re.fullmatch(r'[a-f0-9]{32}', run_id):
        raise ValueError('调研编号无效')
    report = {'run_id': run_id, 'scope': 'proposal-only', 'status': 'not_researched',
              'sources': [], 'errors': [], 'note': '', 'started_at': _now(),
              'mode': 'none', 'query': goal, 'search_status': 'not_requested'}
    detailed = profile == 'product-analysis'
    if detailed:
        report.update(profile=profile, scope='read-only-product-analysis', page_budget=8, browser_inspected=False)
    if re.search(r'不(?:要)?联网|离线|不要上网|no\s+(?:internet|network)', goal, re.I):
        report['mode'] = 'offline'
        report['note'] = '本轮按要求不联网；方案仅依据现有资料与明确标注的一般建议。'
        return report
    scope = research_scope(goal, agents)
    report['source_catalog'] = scope
    page_budget = 8 if detailed else 2
    supplied = re.findall(r'https?://[^\s<>"\u3000-\u303f\uff00-\uffef]+', goal)[:page_budget]
    seeds = (list(GENERAL_CATALOGS[scope]) if scope in GENERAL_CATALOGS
             else _select_seeds(official_sites(store, scope), goal) if scope else [])
    candidates = supplied or seeds
    discovery_note = ''
    if supplied:
        report['mode'] = 'provided-urls'
    else:
        report['mode'] = 'official-sites' if seeds else 'none'
        key = _search_key(store)
        if key:
            try:
                domains = list(dict.fromkeys(urlsplit(url).hostname for url in seeds))
                found = await asyncio.wait_for(_tavily_urls(store, goal, domains, key), timeout=35)
                report['search_status'] = 'completed' if found else 'no_results'
                if found:
                    candidates, report['mode'] = found, 'tavily'
                else:
                    discovery_note = '搜索服务未返回可用网页；' + ('已回退到官方资料入口。' if seeds else '相关需求与数据仍需核实。')
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                report['search_status'] = 'failed'
                report['errors'].append({'url': '', 'stage': 'search',
                    'error': (str(exc).replace(key, '[REDACTED]') or '公开资料搜索超时')[:400]})
                discovery_note = '搜索服务调用失败；' + ('已回退到官方资料入口。' if seeds else '没有可用的官方资料入口，相关需求与数据仍需核实。')
        else:
            report['search_status'] = 'not_configured'
            discovery_note = '未配置可用的联网搜索服务，未执行全网搜索；' + ('本轮只读取匹配的官方资料入口。' if seeds else '也未找到匹配的官方资料入口，相关需求与数据仍需核实。')
    if not candidates:
        report['note'] = discovery_note
        # A missing configuration did not execute any research. An attempted
        # search is retained as a run even if it returned no readable evidence.
        if report['search_status'] == 'not_configured':
            return report
    run_dir = store._safe(store.base, 'research-runs/' + run_id)
    run_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    # Use the same existing network route as search and visual browsing. A
    # failed direct connection must not force an expensive browser fallback.
    # SafeFetcher still pins public DNS, verifies TLS and respects robots.txt.
    fetcher = SafeFetcher(use_system_proxy=True, cache_dir=store.base / '.cache/robots')
    browser = PublicBrowserReader(fetcher, isolated=True) if detailed else None
    pending = list(dict.fromkeys(candidates))[:page_budget]
    seen = set()
    started = time.monotonic()
    try:
        while pending and len(seen) < page_budget:
            candidate = pending.pop(0)
            if candidate in seen:
                continue
            seen.add(candidate)
            if detailed and time.monotonic() - started > 110:
                report['errors'].append({'url': str(candidate), 'error': '本轮页面读取达到时间预算，未继续读取'})
                break
            try:
                url = canonical_url(candidate.rstrip('.,);'))
                if on_progress:
                    on_progress({'stage': 'researching', 'detail': '读取公开页面 ' + url, 'sources': len(report['sources'])})
                response = await asyncio.wait_for(asyncio.to_thread(fetcher.fetch, url), timeout=65)
                document = None
                try:
                    document = extract_document(response)
                except ValueError:
                    if not detailed:
                        raise
                links = []
                if detailed:
                    try:
                        links = _related_links(response, goal + ' pricing price plans documentation docs help features about contact 价格 教程 帮助 功能')
                    except ValueError:
                        pass
                    if needs_browser(response, document):
                        if on_progress:
                            on_progress({'stage': 'reading_page', 'detail': '渲染并读取动态页面 ' + url})
                        try:
                            rendered = await asyncio.wait_for(browser.render(response, run_dir / (str(len(report['sources']) + 1) + '.png')), timeout=60)
                            document = rendered
                            report['browser_inspected'] = True
                            ranked = sorted(rendered['links'], key=lambda item: -sum(
                                token in (item['url'] + ' ' + item['label']).lower() for token in
                                ('intro', 'price', 'pricing', 'docs', 'help', '教程', '介绍', '价格', '说明')))
                            links = [item['url'] for item in ranked] + links
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            report['errors'].append({'url': url, 'stage': 'browser', 'error': str(exc)[:300] or '动态页面读取超时'})
                    pending.extend(link for link in links if link not in seen and link not in pending)
                if not document:
                    raise ValueError('没有读到公开正文，动态页面也未能取得可见内容')
                filename = str(len(report['sources']) + 1) + '.md'
                target = run_dir / filename
                target.write_text(document['text'], encoding='utf-8')
                target.chmod(0o600)
                from .public_passages import relevant_excerpt
                excerpt = relevant_excerpt(document['text'],9000 if detailed else 3500,excerpt_query or '')
                source = {'url': document.get('url', response['url']), 'title': document['title'],
                    'sha256': document['sha256'], 'excerpt': excerpt,
                    'excerpt_sha256': hashlib.sha256(excerpt.encode()).hexdigest(),
                    'truncated': len(excerpt) < len(document['text']), 'fetched_at': _now(),
                    'read_method': document.get('read_method', 'http_text'),
                    'path': str(target.relative_to(store.base))}
                if document.get('screenshot_path'):
                    source['screenshot_path'] = str(Path(document['screenshot_path']).relative_to(store.base))
                report['sources'].append(source)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                report['errors'].append({'url': str(candidate)[:2000], **public_read_error(exc)})
    finally:
        if browser:
            await browser.close()
    report['read_diagnostics'] = fetcher.diagnostics[-60:]
    report['status'] = 'partial' if report['sources'] and report['errors'] else 'completed' if report['sources'] else 'unavailable'
    report['note'] = discovery_note + ('仅核验本轮列出的公开资料，不代表完成用户访谈、竞品覆盖或市场规模调研。'
                      if report['sources'] else '本轮未成功读取公开资料；需调研事项保持待核实，不能称为已完成调研。')
    if detailed:
        report['note'] += '本轮读取公开正文、必要时渲染动态页面并跟随页面实际链接；没有登录、启动算力或核验成交与盈利。浏览器正文不等于完整功能体验，移动端和登录后流程仍未验证。'
    if scope == 'freelance-income':
        report['note'] += '当前目录仅覆盖技术接单示例，不能代表全部副业或当前收益排名；不据此推断用户已有技术技能。'
        report['note'] += '平台资料仅说明规则与工作流程，不构成收益承诺；实际需求、成本、适用地区与接单结果仍需核实。'
    report['finished_at'] = _now()
    _write_json(run_dir / 'report.json', report)
    return report
