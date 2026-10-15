"""Frozen upstream formats and truthful availability of added platforms."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from federation.hotspots import SOURCES, HotspotMonitor, fetch, normalize, parse_feed


FIXTURES = Path(__file__).parent / 'fixtures' / 'hotspots'
BY_ID = {source['id']: source for source in SOURCES}


class PlatformFormatsTest(unittest.TestCase):
    def test_douyin_public_response_keeps_platform_rank_and_heat(self):
        items = parse_feed((FIXTURES / 'douyin-hot.json').read_bytes(), BY_ID['douyin'])
        self.assertEqual(items[0]['title'], '国足vs塔吉克斯坦')
        self.assertEqual(items[0]['url'], 'https://www.douyin.com/hot/2682945')
        self.assertEqual(items[0]['score'], 12104106)
        self.assertEqual(items[0]['score_label'], '抖音热度')
        self.assertEqual(items[1]['rank'], 2)
        self.assertIsNone(items[0]['published_at'], 'Event time must not become publication time')
        data = json.loads((FIXTURES / 'douyin-hot.json').read_bytes())
        data['data']['word_list'].insert(0, {'word': 'bad', 'sentence_id': '../unsafe'})
        data['data']['word_list'][1]['position'] = 3
        result = parse_feed(json.dumps(data).encode(), BY_ID['douyin'])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['rank'], 3)
        for body in [b'', b'{"status_code":1}', b'{"status_code":0,"data":{"word_list":[]}}']:
            with self.assertRaises(ValueError):
                parse_feed(body, BY_ID['douyin'])

    def test_github_trending_uses_daily_gain_not_total_stars(self):
        body = (FIXTURES / 'github-trending.html').read_bytes()
        item = parse_feed(body, BY_ID['github'])[0]
        self.assertEqual(item['title'], 'tester-army/e2e')
        self.assertEqual(item['url'], 'https://github.com/tester-army/e2e')
        self.assertEqual(item['score'], 1720)
        self.assertNotEqual(item['score'], 5495)
        self.assertEqual(item['score_label'], '今日新增 Star')
        self.assertIn('e2e testing framework', item['summary'])
        self.assertEqual(item['group'], 'tech')
        no_gain = body.replace(b'1,720 stars today', b'')
        self.assertIsNone(parse_feed(no_gain, BY_ID['github'])[0]['score'])
        for invalid in [b'<html>Login required</html>', b'<article class="Box-row"><h2><a href="javascript:bad">bad</a></h2></article>']:
            with self.assertRaises(ValueError):
                parse_feed(invalid, BY_ID['github'])

    def test_pending_xiaohongshu_does_not_generate_a_fake_list(self):
        with patch('federation.hotspots.urllib.request.urlopen') as request:
            with self.assertRaisesRegex(ValueError, '尚未接入'):
                fetch(BY_ID['xiaohongshu'])
            request.assert_not_called()


class PlatformMonitorTest(unittest.IsolatedAsyncioTestCase):
    async def test_added_source_resolution_context_and_independent_cache(self):
        failed = set()
        def reader(source):
            if source['id'] in failed or source['kind'] == 'pending':
                raise ValueError(source.get('unavailable_reason', '暂时失败'))
            fixture = {'douyin': 'douyin-hot.json', 'github': 'github-trending.html'}.get(source['id'])
            return parse_feed((FIXTURES / fixture).read_bytes(), source) if fixture else normalize([
                {'title': 'Fixture headline', 'url': 'https://example.com/' + source['id']}], source)
        monitor = HotspotMonitor(reader, article_fetcher=lambda item: {'title': item['title'], 'text': 'Read-only body.'})
        first = await monitor.refresh()
        xhs = next(source for source in first['sources'] if source['id'] == 'xiaohongshu')
        self.assertEqual(xhs['status'], 'unavailable')
        self.assertEqual(xhs['items'], [])
        self.assertIsNone(xhs['fetched_at'])
        self.assertIn('HTTP 406', xhs['error'])
        gh = monitor.sources['github']['items'][0]
        dy = monitor.sources['douyin']['items'][1]
        self.assertEqual(monitor.resolve('GitHub 第一条是什么？'), gh['id'])
        self.assertEqual(monitor.resolve('抖音第二条热点'), dy['id'])
        self.assertIsNone(monitor.resolve('小红书第一条'))
        context = await monitor.context(gh['id'])
        gh_source = next(source for source in context['sources'] if source['id'] == 'github')
        self.assertEqual(gh_source['items'][0]['score_label'], '今日新增 Star')
        self.assertEqual(gh_source['items'][0]['url'], gh['url'])
        self.assertIn('尚未接入', next(source for source in context['sources'] if source['id'] == 'xiaohongshu')['error'])
        self.assertEqual(context['selected']['url'], gh['url'])
        failed.add('github')
        second = await monitor.refresh(force=True)
        self.assertEqual(monitor.sources['github']['status'], 'stale')
        self.assertEqual(monitor.sources['github']['items'][0], gh)
        self.assertEqual(monitor.sources['douyin']['status'], 'ready')
        self.assertEqual(len(second['sources']), 7)


if __name__ == '__main__':
    unittest.main()
