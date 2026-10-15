"""Render a public page in the application's own ephemeral browser.

Never connects to a user's Chrome, profile, cookies or desktop tabs. All network
requests are fulfilled by the existing DNS-pinned public-address transport.
Only GET/HEAD are allowed; downloads, service workers and sockets are disabled.
"""
import asyncio
import base64
from contextlib import suppress
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import sys
from urllib.parse import urlsplit

from .web_learning import CollectionError, canonical_url


def needs_browser(response, document=None):
    if 'html' not in response.get('headers', {}).get('content-type', ''):
        return False
    text = (document or {}).get('text', '')
    raw = response['body'].decode('utf-8', errors='replace')
    return len(text.strip()) < 600 or bool(re.search(
        r'id=["\'](?:__next|__nuxt|app|root)["\']', raw, re.I))


class PublicBrowserReader:
    def __init__(self, fetcher, isolated=False):
        self.fetcher = fetcher
        self.isolated = isolated
        self.manager = self.browser = None

    async def close(self):
        try:
            if self.browser:
                await self.browser.close()
        finally:
            if self.manager:
                await self.manager.stop()
            self.manager = self.browser = None

    async def render(self, response, screenshot_path=None):
        if self.isolated:
            return await render_worker(response, screenshot_path, getattr(self.fetcher, 'cache_dir', None))
        # response has already passed robots.txt and public URL checks.
        from playwright.async_api import async_playwright
        if not self.browser:
            self.manager = await async_playwright().start()
            from .browser_runtime import launch_options
            self.browser = await self.manager.chromium.launch(**launch_options())
        context = await self.browser.new_context(
            viewport={'width': 1440, 'height': 1000}, accept_downloads=False,
            service_workers='block', permissions=[])
        budget = {'requests': 0, 'bytes': 0, 'blocked': 0}
        navigations = []
        semaphore = asyncio.Semaphore(6)
        original_url = canonical_url(response['url'])

        async def route_request(route):
            request = route.request
            try:
                if request.method not in {'GET', 'HEAD'} or request.resource_type in {'image', 'media', 'font'}:
                    budget['blocked'] += 1
                    await route.abort()
                    return
                url = canonical_url(request.url)
                budget['requests'] += 1
                if budget['requests'] > 100 or budget['bytes'] > 24_000_000:
                    raise CollectionError('浏览器本轮公开资源读取达到上限')
                if request.is_navigation_request():
                    navigations.append(url)
                    # Redirected documents must also pass robots; scripts/assets
                    # are read through the same public-IP-pinned transport.
                    value = response if url == original_url else await asyncio.to_thread(self.fetcher.fetch, url)
                else:
                    async with semaphore:
                        value = await asyncio.to_thread(self.fetcher._request, url, 6_000_000)
                budget['bytes'] += len(value['body'])
                headers = {key: val for key, val in value['headers'].items()
                           if key not in {'content-length', 'content-encoding', 'transfer-encoding', 'set-cookie'}}
                await route.fulfill(status=value['status'], headers=headers, body=value['body'])
            except asyncio.CancelledError:
                raise
            except Exception:
                budget['blocked'] += 1
                await route.abort()

        page = await context.new_page()
        await context.route('**/*', route_request)
        await context.route_web_socket('**/*', lambda socket: socket.close())
        try:
            await page.goto(original_url, wait_until='domcontentloaded', timeout=40_000)
            try:
                await page.wait_for_load_state('networkidle', timeout=12_000)
            except Exception:
                pass
            observed = await page.evaluate('''() => ({
              title: document.title,
              text: document.body?.innerText || '',
              links: Array.from(document.querySelectorAll('a[href]')).slice(0,600)
                .map(a => ({url:a.href, label:(a.innerText || a.title || '').slice(0,200)}))
            })''')
            text = observed['text'].strip()
            if len(text) < 160:
                raise CollectionError('浏览器没有读到足够的可见公开正文')
            links = []
            for link in observed['links']:
                try:
                    url = canonical_url(link['url'])
                    if urlsplit(url).hostname == urlsplit(original_url).hostname and url != original_url:
                        links.append({'url': url, 'label': link['label']})
                except ValueError:
                    continue
            screenshot = None
            if screenshot_path:
                await page.screenshot(path=str(screenshot_path), full_page=False)
                screenshot_path.chmod(0o600)
                screenshot = str(screenshot_path)
            # SPA menus often expose read-only documentation without href.
            # Only named help/tutorial actions are followed; creation, account,
            # payment and application-run controls are never touched.
            if len(links) < 3:
                async def discover_help():
                    for label in (r'^使用教程\s*[>›]?$', r'^帮助中心$'):
                        target = page.get_by_text(re.compile(label)).first
                        if await target.count():
                            try:
                                await target.click(timeout=1200)
                                for opened in context.pages[:3]:
                                    try:
                                        await opened.wait_for_load_state('domcontentloaded', timeout=1000)
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                try:
                    await asyncio.wait_for(discover_help(), timeout=5)
                except asyncio.TimeoutError:
                    pass
                host = urlsplit(original_url).hostname
                for url in navigations:
                    destination = urlsplit(url).hostname or ''
                    if url != original_url and (destination == host or destination.endswith('.' + host)):
                        links.append({'url':url,'label':'页面帮助或教程入口'})
            return {'url': original_url, 'title': observed['title'], 'text': text,
                    'sha256': hashlib.sha256(text.encode()).hexdigest(), 'links': links,
                    'read_method': 'browser_dom', 'browser_inspected': True,
                    'viewport': {'width': 1440, 'height': 1000}, 'network': budget,
                    'screenshot_path': screenshot}
        finally:
            await context.close()


async def render_worker(response, screenshot_path=None, cache_dir=None):
    """Keep browser protocol/network callbacks off the UI server event loop."""
    payload = {'response':{**response,'body':base64.b64encode(response['body']).decode()},
               'screenshot_path':str(screenshot_path) if screenshot_path else None, 'cache_dir':str(cache_dir) if cache_dir else None}
    process = await asyncio.create_subprocess_exec(
        sys.executable, '-m', 'federation.public_browser',
        cwd=str(Path(__file__).resolve().parent.parent),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, start_new_session=True)
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(json.dumps(payload).encode()), timeout=55)
        if process.returncode:
            detail=stderr.decode(errors='replace').strip().splitlines()
            raise CollectionError('独立浏览器读取失败：' + (detail[-1][:300] if detail else '没有返回错误详情'))
        result = json.loads(stdout)
        if not isinstance(result.get('text'),str) or not result['text'].strip():
            raise CollectionError('独立浏览器没有返回公开正文')
        return result
    finally:
        if process.returncode is None:
            with suppress(ProcessLookupError):
                os.killpg(process.pid,signal.SIGTERM)
            try:
                await asyncio.wait_for(process.wait(),timeout=5)
            except asyncio.TimeoutError:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid,signal.SIGKILL)
                await process.wait()


async def worker_main():
    from .web_learning import SafeFetcher
    raw = sys.stdin.buffer.read(10_000_001)
    if len(raw)>10_000_000:
        raise ValueError('公开页面输入超过上限')
    payload=json.loads(raw)
    response=payload['response']
    response['body']=base64.b64decode(response['body'],validate=True)
    canonical_url(response['url'])
    reader=PublicBrowserReader(SafeFetcher(use_system_proxy=True, cache_dir=payload.get('cache_dir')))
    task=asyncio.current_task()
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM,task.cancel)
    try:
        result=await reader.render(response,Path(payload['screenshot_path']) if payload.get('screenshot_path') else None)
        print(json.dumps(result,ensure_ascii=False))
    finally:
        await reader.close()


if __name__ == '__main__':
    asyncio.run(worker_main())
