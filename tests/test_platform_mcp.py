"""MCP data quality, per-source failover and stale provenance."""
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

from federation.hotspots import HotspotMonitor, normalize
from federation.platform_mcp import parse_result, read_hotlist, PROVIDER


def response(platform='baidu', url='https://www.baidu.com/s?wd=test'):
    return {'tool': 'query_hot_trending', 'data': {'platform': platform,
        'items': [{'title': 'Real platform title', 'url': url, 'hot': 12345, 'rank': 4}]}}


class ParseTest(unittest.TestCase):
    def test_only_valid_platform_links_counts_and_rank_survive(self):
        result = response()
        result['data']['items'] += [
            {'title': 'Injected', 'url': url, 'hot': 8} for url in [
                'http://www.baidu.com/s', 'https://www.baidu.com.evil.test/',
                'https://user:secret@www.baidu.com/', 'https://127.0.0.1/',
                'https://www.baidu.com:18732/', 'javascript:alert(1)']]
        rows = parse_result(result, 'baidu')
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['rank'], rows[0]['score']), (4, 12345))
        self.assertNotIn('published_at', rows[0])
        bili = parse_result(response('bilibili', 'https://b23.tv/BV1PTHS6MEC5'), 'bilibili')[0]
        self.assertEqual(bili['url'], 'https://www.bilibili.com/video/BV1PTHS6MEC5')
        for value in [None, {}, {'tool': 'publish'}, response('douyin'),
                      {'tool': 'query_hot_trending', 'data': {'platform': 'baidu', 'error': 'blocked'}},
                      response(url='https://example.com/')]:
            with self.assertRaises(ValueError):
                parse_result(value, 'baidu')

    def test_vendored_provider_matches_reviewed_commit(self):
        folder = Path(__file__).parents[1] / 'federation/mcp-hotspots/vendor'
        manifest = json.loads((folder / 'upstream.json').read_text())
        self.assertEqual(manifest['commit'], PROVIDER['commit'])
        for name, sha in manifest['files'].items():
            self.assertEqual(hashlib.sha256((folder / name).read_bytes()).hexdigest(), sha)


class MonitorTest(unittest.IsolatedAsyncioTestCase):
    async def test_mcp_preferred_per_source_then_direct_then_existing_cache(self):
        failed_mcp, failed_direct, direct_calls = set(), set(), []
        async def mcp(platform):
            if platform in failed_mcp:
                raise ValueError('MCP unavailable')
            return parse_result(response(platform, {
                'baidu':'https://www.baidu.com/s?wd=test',
                'bilibili':'https://www.bilibili.com/video/BV1PTHS6MEC5',
                'douyin':'https://www.douyin.com/search/test'}[platform]), platform)
        def direct(source):
            direct_calls.append(source['id'])
            if source['id'] in failed_direct or source['kind'] == 'pending':
                raise ValueError('Platform unavailable')
            return normalize([{'title':'Direct title', 'url':'https://example.com/'+source['id']}], source)
        monitor = HotspotMonitor(direct, mcp_fetcher=mcp)
        await monitor.refresh()
        for name in ('baidu', 'bilibili', 'douyin'):
            self.assertNotIn(name, direct_calls)
            self.assertEqual(monitor.sources[name]['data_route']['method'], 'mcp')
            self.assertEqual(monitor.sources[name]['mcp']['status'], 'connected')
        first = copy.deepcopy(monitor.sources['bilibili'])
        context = await monitor.context()
        self.assertEqual(next(s for s in context['sources'] if s['id']=='bilibili')['data_route']['board'], '热门视频')
        failed_mcp.update({'baidu', 'bilibili'})
        failed_direct.add('bilibili')
        await monitor.refresh(force=True)
        self.assertEqual(monitor.sources['baidu']['status'], 'ready')
        self.assertEqual(monitor.sources['baidu']['mcp']['status'], 'failed')
        self.assertEqual(monitor.sources['baidu']['data_route']['fallback_from'], 'mcp')
        self.assertEqual(monitor.sources['bilibili']['status'], 'stale')
        self.assertEqual(monitor.sources['bilibili']['items'], first['items'])
        self.assertEqual(monitor.sources['bilibili']['fetched_at'], first['fetched_at'])
        self.assertEqual(monitor.sources['bilibili']['data_route'], first['data_route'])
        self.assertEqual(monitor.sources['douyin']['mcp']['status'], 'connected')
        self.assertEqual(monitor.sources['xiaohongshu']['items'], [])

    async def test_cancellation_terminates_and_reaps_mcp_process_group(self):
        process = AsyncMock()
        process.pid = 123456
        process.returncode = None
        async def communicate():
            raise asyncio.CancelledError()
        process.communicate.side_effect = communicate
        with patch('federation.platform_mcp.asyncio.create_subprocess_exec', return_value=process), \
                patch('federation.platform_mcp.os.killpg') as kill, \
                patch('federation.platform_mcp.Path.is_file', return_value=True):
            with self.assertRaises(asyncio.CancelledError):
                await read_hotlist('baidu')
            kill.assert_called_once()
            self.assertEqual(kill.call_args.args[0], 123456)
            process.wait.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
