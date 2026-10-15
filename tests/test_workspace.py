"""Workspace activity and explicit member consultations stay read-only."""
import asyncio
import json
from pathlib import Path
import tempfile
import time
import unittest
from fastapi.testclient import TestClient
from federation.app import create_app
from federation.hotspots import SOURCES, HotspotMonitor, parse_feed


class HotspotTest(unittest.IsolatedAsyncioTestCase):
    async def test_partial_failure_cache_and_cooldown(self):
        calls = []
        fail = set()
        def fetcher(source):
            calls.append(source['id'])
            if source['id'] in fail:
                raise ValueError('来源拒绝读取')
            return [{'id': source['id'], 'title': '真实来源 fixture', 'url': source['url'], 'group': source['group']}]
        monitor = HotspotMonitor(fetcher)
        first = await monitor.refresh()
        self.assertTrue(all(source['status'] == 'ready' for source in first['sources']))
        await monitor.refresh()
        self.assertEqual(len(calls), len(SOURCES))
        fail.update({'openai', 'baidu'})
        second = await monitor.refresh(force=True)
        self.assertEqual({source['id']:source['status'] for source in second['sources']},
                         {source['id']: 'stale' if source['id'] in fail else 'ready' for source in SOURCES})
        self.assertEqual(second['sources'][0]['items'], first['sources'][0]['items'])
        self.assertEqual(second['sources'][0]['fetched_at'], first['sources'][0]['fetched_at'])
        empty = HotspotMonitor(lambda source: (_ for _ in ()).throw(ValueError('无数据')))
        self.assertTrue(all(source['status'] == 'unavailable' and not source['items'] for source in (await empty.refresh())['sources']))

    def test_actual_formats_and_invalid_source_data(self):
        rss = b'<rss><channel><item><title>AI news</title><link>https://openai.com/news/one</link><pubDate>Mon, 05 Oct 2026 10:00:00 GMT</pubDate></item><item><title>bad link</title><link>javascript:alert(1)</link></item></channel></rss>'
        items = parse_feed(rss, SOURCES[0])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['published_at'], '2026-10-05T10:00:00+00:00')
        baidu = '<!DOCTYPE html><!--s-data:' + json.dumps({'data': {'cards': [{'content': [{'word': '热榜', 'url': 'https://www.baidu.com/s?wd=x', 'hotScore': '123'}]}]}}) + '-->'
        self.assertEqual(parse_feed(baidu.encode(), SOURCES[2])[0]['score'], '123')
        bili = {'code': 0, 'data': {'list': [{'title': '榜单', 'bvid': 'BV1UGa961Ejt', 'stat': {'view': 123}}]}}
        self.assertEqual(parse_feed(json.dumps(bili).encode(), SOURCES[3])[0]['score'], 123)
        for body in [b'<!DOCTYPE rss><rss/>', b'<html>Visitor System</html>', b'<rss><channel/></rss>']:
            with self.assertRaises(ValueError):
                parse_feed(body, SOURCES[0])
        with self.assertRaises(ValueError):
            parse_feed(b'{"code":-412,"message":"restricted"}', SOURCES[3])


class WorkspaceTest(unittest.TestCase):
    def test_new_human_lesson_excludes_unrelated_old_project_context(self):
        with tempfile.TemporaryDirectory() as root:
            turns = []
            async def runner(turn, store):
                turns.append(dict(turn))
                turn['answer'] = '用户完成具体任务，才说明产品有价值。'
            app = create_app(base=Path(root) / 'data', runner=runner)
            with TestClient(app) as client:
                room = client.post('/api/chat/primary', json={}).json()
                route = '/api/chat/rooms/' + room['id'] + '/messages'
                for content in ['解释下 GPT 代充的产品价值', '教我 AI 产品思维，我不想读文档，只想聊天学', '举个例子']:
                    response = client.post(route, json={'content': content}).json()
                    for _ in range(100):
                        if client.get('/api/jobs/' + response['job']['id']).json()['status'] not in {'running', 'queued'}:
                            break
                        time.sleep(.01)
                self.assertNotIn('GPT 代充', turns[1]['question'])
                self.assertNotIn('GPT 代充', turns[2]['question'])
                context = turns[2]['question'] + json.dumps(turns[2].get('context_memory', {}), ensure_ascii=False)
                self.assertNotIn('GPT 代充', context)
                self.assertIn('教我 AI 产品思维', context)
                self.assertTrue(turns[2]['teaching'])
                self.assertEqual(client.get('/api/chat/rooms/' + room['id']).json()['messages'][0]['content'], '解释下 GPT 代充的产品价值')

    def test_real_member_order_actor_receipts_and_no_knowledge_writes(self):
        with tempfile.TemporaryDirectory() as root:
            turns = []
            async def runner(turn, store):
                turns.append(dict(turn))
                live = app.state.reply_streams.snapshot(turn['room_id'], turn['parent_job_id'])
                self.assertEqual(live['agent_id'], turn['space'])
                self.assertEqual(live['turn_id'], turn['id'])
                app.state.reply_streams.append(turn['room_id'], turn['parent_job_id'], '正在回答')
                await asyncio.sleep(.1)
                turn['answer'] = '明确用户需要完成的事情。' if turn['space'] != 'central' else '先验证你是不是学会了，再谈功能。'
                turn['wiki_reads'] = [{'path': '/index.md', 'sha256': 'fixture'}]
            app = create_app(base=Path(root) / 'data', runner=runner)
            with TestClient(app) as client:
                agents = client.get('/api/agents').json()['agents']
                expert = next(member for member in agents if member['id'] != 'central' and member['depth'] == 2)
                room = client.post('/api/chat/primary', json={}).json()
                before = {member['id']: app.state.store.pages(member['id']) for member in agents}
                url = '/api/chat/rooms/' + room['id'] + '/messages'
                self.assertEqual(client.post(url, json={'content': '教我 AI 产品思维', 'requested_agents': [expert['id']]}).status_code, 400)
                response = client.post(url, json={'content': '@' + expert['name'] + ' 教我 AI 产品思维'}).json()
                job_id = response['job']['id']
                with client.stream('GET', '/api/chat/rooms/' + room['id'] + '/events?job_id=' + job_id) as stream:
                    lines = list(stream.iter_lines())
                previews = [json.loads(lines[index + 1][6:]) for index, line in enumerate(lines) if line == 'event: reply']
                self.assertEqual({value['agent_id'] for value in previews}, {expert['id']})
                self.assertEqual([turn['space'] for turn in turns], [expert['id']])
                self.assertNotIn('<main_agent_handoff>', turns[0]['question'])
                final = client.get('/api/chat/rooms/' + room['id']).json()
                self.assertEqual([message['agent_id'] for message in final['messages'] if message['role'] == 'assistant'], [expert['id']])
                self.assertEqual(final['messages'][1]['wiki_reads'][0]['path'], '/index.md')
                self.assertEqual(final.get('task_groups', []), [])
                self.assertEqual(final.get('proposals', []), [])
                self.assertEqual(final['status'], 'idle')
                self.assertEqual(before, {member['id']: app.state.store.pages(member['id']) for member in agents})
                workspace = client.get('/api/workspace').json()
                self.assertEqual(workspace['running'], 0)
                parent = next(job for job in workspace['jobs'] if job['id'] == job_id)
                self.assertEqual(parent['requested_agents'], [expert['id']])
                self.assertFalse(any('question' in job or 'output' in job for job in workspace['jobs']))
                page = client.get('/')
                self.assertIn('ws-chat-host', page.text)
                self.assertNotIn('cdn.jsdelivr', page.headers['content-security-policy'])
                self.assertEqual(client.get('/workspace/workspace.js').status_code, 200)
                self.assertEqual(client.get('/workspace/secrets.json').status_code, 404)

    def test_hotspot_fetch_does_not_join_model_queue(self):
        with tempfile.TemporaryDirectory() as root:
            app = create_app(base=Path(root) / 'data')
            calls = []
            app.state.hotspots.fetcher = lambda source: calls.append(source['id']) or []
            with TestClient(app) as client:
                initial = client.get('/api/hotspots').json()
                self.assertTrue(all(source['status'] == 'loading' for source in initial['sources']))
                for _ in range(100):
                    time.sleep(.01)
                    data = client.get('/api/hotspots').json()
                    if data['checked_at']:
                        break
                self.assertEqual(len(calls), len(SOURCES))
                self.assertEqual(client.get('/api/workspace').json()['jobs'], [])
                self.assertEqual(app.state.store.space('central')['knowledge_count'], 0)
