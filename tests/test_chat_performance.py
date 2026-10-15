"""Bound UI work without losing history, fresh validation or stream delivery."""
import asyncio
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

import httpx
from fastapi.testclient import TestClient
from federation.app import create_app, UICompression
from federation.intake import build_intake_prompt


def seed(chat, count=180):
    room = chat.primary_room()
    stamp = room['created_at']
    room['messages'] = [{'id': uuid.uuid4().hex, 'role': 'user',
        'content': f'历史消息 {i} ' + '保留原始内容。' * 100, 'status': 'completed', 'agent_name': '你',
        'created_at': stamp} for i in range(count)]
    chat.save_room(room)
    return room


class ChatPerformanceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(base=Path(self.temp.name) / 'data')
        self.chat = self.app.state.chat

    def tearDown(self):
        self.temp.cleanup()

    def test_cache_is_detached_and_invalidates_on_file_or_registry_change(self):
        room = seed(self.chat)
        with patch.object(self.chat, '_validate', wraps=self.chat._validate) as validate:
            first = self.chat.get_room(room['id'])
            self.chat.get_room(room['id'])
            self.assertEqual(validate.call_count, 1)
            first['messages'][0]['content'] = 'unsaved change'
            self.assertEqual(self.chat.get_room(room['id']), room)
            path = self.chat._path(room['id'])
            changed = copy.deepcopy(room)
            changed['messages'][-1]['content'] = 'external edit'
            path.write_text(json.dumps(changed))
            self.assertEqual(self.chat.get_room(room['id']), changed)
            self.assertEqual(validate.call_count, 2)
            self.chat.store._definitions['central']['name'] = '新名称'
            self.chat.get_room(room['id'])
            self.assertEqual(validate.call_count, 3)
            changed['messages'][-1]['role'] = 'invalid'
            path.write_text(json.dumps(changed))
            with self.assertRaises(ValueError):
                self.chat.get_room(room['id'])

    def test_window_compression_and_cache_leave_saved_history_complete(self):
        room = seed(self.chat)
        path = self.chat._path(room['id'])
        before = path.read_bytes()
        with TestClient(self.app) as client:
            route = '/api/chat/rooms/' + room['id']
            response = client.get(route + '?message_limit=60')
            self.assertEqual(response.headers['content-encoding'], 'gzip')
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertEqual(response.json()['messages'], room['messages'][-60:])
            self.assertEqual(response.json()['message_offset'], 120)
            self.assertEqual(client.get(route + '?message_limit=120').json()['messages'], room['messages'][-120:])
            self.assertEqual(client.get(route).json()['messages'], room['messages'])
            self.assertEqual(len(client.post('/api/chat/primary?message_limit=60', json={}).json()['messages']), 60)
            asset = client.get('/agent-chat.js')
            cached = client.get('/agent-chat.js', headers={'If-None-Match': asset.headers['etag']})
            self.assertEqual(cached.status_code, 304)
            self.assertEqual(cached.content, b'')
            self.assertEqual(client.get(route + '?message_limit=-1').status_code, 422)
        self.assertEqual(path.read_bytes(), before)

    def test_autonomy_status_needs_no_knowledge_inventory(self):
        with patch.object(self.chat.store, 'spaces', side_effect=AssertionError('inventory scan')):
            self.assertEqual(len(self.app.state.autonomy.snapshot()['agents']), len(self.chat.store._definitions))

    def test_focused_article_keeps_evidence_and_broad_questions_keep_board(self):
        context = {'checked_at': '2026-10-13', 'sources': [{'name': 'source', 'items': [
            {'title': 'unrelated headline', 'url': 'https://example.com/other'}]}],
            'selected': {'id': 'article', 'url': 'https://example.com/article',
                         'excerpt': 'exact evidence', 'excerpt_sha256': 'digest', 'status': 'ready'}}
        before = copy.deepcopy(context)
        focused = build_intake_prompt('这个热点讲什么内容', hotspot_context=context, history='UNRELATED_OLD_TASK', proposal={'content':'OLD_PROPOSAL'})
        self.assertNotIn('UNRELATED_OLD_TASK', focused)
        self.assertNotIn('OLD_PROPOSAL', focused)
        self.assertNotIn('unrelated headline', focused)
        self.assertNotIn('<available_roles>', focused)
        for value in ['exact evidence', 'digest', 'https://example.com/article']:
            self.assertIn(value, focused)
        for question in ['还有哪些热点', '这个重点是什么，顺便比较其他新闻', '今天有哪些热点']:
            self.assertIn('unrelated headline', build_intake_prompt(question, hotspot_context=context))
        self.assertEqual(context, before)


class AsyncPerformanceTest(unittest.IsolatedAsyncioTestCase):
    async def test_library_listeners_share_nonblocking_inventory_check(self):
        with tempfile.TemporaryDirectory() as root:
            app = create_app(base=Path(root) / 'data')
            entered, release = threading.Event(), threading.Event()
            calls = []
            def hashes(identifier):
                calls.append(identifier)
                entered.set()
                release.wait(3)
                return {}
            class Request:
                async def is_disconnected(self): return False
            endpoint = next(route.endpoint for route in app.routes if route.path == '/events')
            streams = [(await endpoint(Request())).body_iterator for _ in range(3)]
            with patch.object(app.state.store, '_page_hashes', side_effect=hashes):
                pending = [asyncio.create_task(stream.__anext__()) for stream in streams]
                try:
                    self.assertTrue(await asyncio.to_thread(entered.wait, 1))
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
                        self.assertEqual((await asyncio.wait_for(client.get('/'), .5)).status_code, 200)
                finally:
                    release.set()
                    self.assertEqual(await asyncio.gather(*pending), ['retry: 2000\n\n'] * 3)
                    for stream in streams: await stream.aclose()
                self.assertEqual(len(calls), len(app.state.store._definitions))

    async def test_inventory_requests_share_scan_without_blocking_page(self):
        with tempfile.TemporaryDirectory() as root:
            app = create_app(base=Path(root) / 'data')
            entered, release = threading.Event(), threading.Event()
            calls = []
            def scan():
                calls.append(1)
                entered.set()
                release.wait(3)
                return []
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
                with patch.object(app.state.chat, 'agents', side_effect=scan):
                    requests = [asyncio.create_task(client.get('/api/agents')) for _ in range(3)]
                    try:
                        self.assertTrue(await asyncio.to_thread(entered.wait, 1))
                        response = await asyncio.wait_for(client.get('/'), .5)
                        self.assertEqual(response.status_code, 200)
                    finally:
                        release.set()
                        await asyncio.gather(*requests)
                    self.assertEqual(len(calls), 1)

    async def test_compression_never_buffers_event_stream(self):
        sent = []
        async def source(scope, receive, send):
            await send({'type': 'http.response.start', 'status': 200, 'headers': [(b'content-type', b'text/event-stream')]})
            await send({'type': 'http.response.body', 'body': b'event: reply\ndata: first\n\n', 'more_body': True})
            self.assertEqual(len(sent), 2)
            await send({'type': 'http.response.body', 'body': b'', 'more_body': False})
        async def send(message): sent.append(message)
        async def receive(): return {'type': 'http.disconnect'}
        await UICompression(source)({'type': 'http', 'path': '/api/chat/rooms/id/events',
                                     'headers': [(b'accept-encoding', b'gzip')]}, receive, send)
        self.assertNotIn((b'content-encoding', b'gzip'), sent[0]['headers'])
