"""Reply previews cannot authorize work, become final messages, or leak across jobs."""
import asyncio
import json
from pathlib import Path
import tempfile
import time
import unittest
from datetime import datetime, timezone, timedelta

from fastapi.testclient import TestClient
from federation.app import create_app
from federation.chat_stream import ReplyStreams, sse_event


class ReplyStreamTest(unittest.TestCase):
    def test_progress_survives_snapshot_and_persistence_without_draft_text(self):
        with tempfile.TemporaryDirectory() as root:
            streams = ReplyStreams(Path(root))
            job = 'a' * 32
            streams.start('b' * 32, job)
            streams.progress('b' * 32, job, 'checking_evidence', '正在核对依据')
            preview = streams.snapshot('b' * 32, job)
            self.assertGreater(preview['revision'], 0)
            self.assertEqual(streams.load_saved(job)['preview']['text'], '')
            self.assertEqual(preview['text'], '')
            self.assertEqual(preview['processing_stage']['stage'], 'checking_evidence')
            preview['processing_stage']['stage'] = 'mutated'
            self.assertEqual(streams.snapshot('b' * 32, job)['processing_stage']['stage'], 'checking_evidence')

    def test_acceptance_receipt_survives_native_start_without_becoming_model_text(self):
        streams=ReplyStreams()
        ack={'text':'前面还有一个任务。','queue_ahead':1}
        streams.start('room','job',acknowledgement=ack)
        streams.start('room','job',turn_id='native')
        preview=streams.snapshot('room','job')
        self.assertEqual(preview['acknowledgement']['queue_ahead'],1)
        self.assertEqual(preview['text'],'')
        self.assertIsNone(preview['first_text_ms'])
        streams.start('room','another')
        self.assertNotIn('acknowledgement',streams.snapshot('room','another'))

    def test_waiting_job_gets_real_queue_receipt_before_model_starts(self):
        import threading
        gate=threading.Event()
        with tempfile.TemporaryDirectory() as root:
            async def runner(job,store):
                while not gate.is_set():await asyncio.sleep(.01)
                job['answer']='完成这轮解释。'
            app=create_app(base=Path(root)/'data',runner=runner)
            try:
                with TestClient(app) as client:
                    first=client.post('/api/chat/primary',json={}).json()
                    one=client.post('/api/chat/rooms/'+first['id']+'/messages',json={'content':'解释产品任务'}).json()
                    second=client.post('/api/chat/rooms',json={'mode':'orchestrated','participants':['central']}).json()
                    # This is a separate primary fixture, not an authorization to create specialists.
                    second['purpose']='primary';app.state.chat.save_room(second)
                    two=client.post('/api/chat/rooms/'+second['id']+'/messages',json={'content':'解释资料引用'}).json()
                    self.assertEqual(two['job']['status'],'queued')
                    self.assertGreaterEqual(two['job']['acceptance_reply']['queue_ahead'],1)
                    self.assertEqual(two['room']['live_reply']['text'],'')
                    self.assertIn('另有',two['room']['live_reply']['acknowledgement']['text'])
                    gate.set()
                    for _ in range(100):
                        job=client.get('/api/jobs/'+two['job']['id']).json()
                        if job['status']=='completed':break
                        time.sleep(.01)
                    self.assertEqual(job['status'],'completed')
                    final=client.get('/api/chat/rooms/'+second['id']).json()['messages'][-1]
                    self.assertGreaterEqual(final['acceptance_reply']['queue_ahead'],1)
            finally:gate.set()

    def test_request_clock_includes_work_before_stream_start(self):
        streams = ReplyStreams()
        received = (datetime.now(timezone.utc)-timedelta(seconds=2)).isoformat()
        streams.start('room','job',received_at=received)
        streams.append('room','job','首段回复')
        preview = streams.snapshot('room','job')
        self.assertGreaterEqual(preview['request_first_text_ms'], 2000)
        self.assertLess(preview['first_text_ms'], 1000)

    def test_answer_receipts_and_initial_version_survive_api_persistence(self):
        with tempfile.TemporaryDirectory() as root:
            async def runner(job, store):
                job['answer']='校对补充：先前结论已撤回，现有资料不足。'
                job['wiki_input']={'scope':'answer_model_supplied_materials','inputs':[],'omitted_paths':['/omitted.md']}
                job['answer_check']={'status':'corrected_with_limits','human_review':'unchanged','repair_count':1,'checks':[]}
                app.state.reply_streams.append(job['room_id'],job['parent_job_id'],'先前未核对的结论。')
                app.state.reply_streams.update(job['room_id'],job['parent_job_id'],
                  {'id':'before-check','title':'先前回答（校对前）','text':'先前未核对的结论。','status':'completed'})
            app=create_app(base=Path(root)/'data',runner=runner)
            with TestClient(app) as client:
                room=client.post('/api/chat/primary',json={}).json()
                sent=client.post('/api/chat/rooms/'+room['id']+'/messages',json={'content':'请解释证据'}).json()
                for _ in range(100):
                    job=client.get('/api/jobs/'+sent['job']['id']).json()
                    if job['status']=='completed': break
                    time.sleep(.01)
                message=client.get('/api/chat/rooms/'+room['id']).json()['messages'][-1]
                self.assertEqual(message['wiki_input']['omitted_paths'], ['/omitted.md'])
                self.assertEqual(message['answer_check']['human_review'],'unchanged')
                self.assertEqual(message['interim_replies'][0]['text'],'先前未核对的结论。')
                self.assertEqual(message['content'], '校对补充：先前结论已撤回，现有资料不足。')
                self.assertGreaterEqual(job['timing']['request_total_ms'], 0)
                self.assertEqual(app.state.store.space('central')['knowledge_count'],0)

    def test_interim_updates_are_bounded_and_isolated_from_the_final_answer(self):
        streams = ReplyStreams()
        streams.start('room', 'job')
        event = {'id': 'first-answer', 'title': '先回应你', 'text': '初步判断，尚待校对。', 'status': 'streaming'}
        self.assertTrue(streams.accept_line('room', 'job', 'OPENWIKI_UPDATE ' + json.dumps(event)))
        preview = streams.snapshot('room', 'job')
        self.assertEqual(preview['text'], '')
        self.assertEqual(preview['updates'][0]['text'], event['text'])
        preview['updates'][0]['text'] = 'cannot mutate the stream'
        streams.update('room', 'job', {**event, 'text': '', 'status': 'completed'})
        streams.append('room', 'job', '最终校对结果')
        self.assertEqual(streams.snapshot('room', 'job')['text'], '最终校对结果')
        self.assertEqual(streams.snapshot('room', 'job')['updates'][0]['text'], event['text'])
        with self.assertRaises(ValueError):
            streams.update('room', 'job', event)
        with self.assertRaises(ValueError):
            streams.update('room', 'job', {**event, 'id': 'second', 'text': 'x' * 40000})
        streams.start('room', 'next')
        streams.update('room', 'job', event)
        self.assertEqual(streams.snapshot('room', 'next')['updates'], [])

    def test_ack_and_interim_answer_arrive_before_processing_finishes(self):
        with tempfile.TemporaryDirectory() as root:
            async def researcher(*args):
                await asyncio.sleep(.2)
                return {'status': 'completed', 'sources': [{'url': 'https://example.com/app', 'title': '示例来源',
                        'sha256': 'a' * 64, 'excerpt': '页面提供应用目录。'}], 'errors': []}
            async def runner(job, store):
                app.state.reply_streams.update(job['room_id'], job['parent_job_id'],
                    {'id': 'first-answer', 'title': '先回应你', 'text': '页面展示了应用目录，内部实现尚不能确认。', 'status': 'completed'})
                await asyncio.sleep(.3)
                app.state.reply_streams.append(job['room_id'], job['parent_job_id'], '校对后的完整回复。')
                job['answer'] = '校对后的完整回复。'
            app = create_app(base=Path(root) / 'data', runner=runner, researcher=researcher)
            with TestClient(app) as client:
                room = client.post('/api/chat/primary', json={}).json()
                sent = client.post('/api/chat/rooms/' + room['id'] + '/messages',
                    json={'content': '只查询 https://example.com/app，不开发、不学习。', 'research': True}).json()
                ack = sent['room']['messages'][-1]
                self.assertEqual(ack['phase'], 'acknowledgement')
                self.assertEqual(ack['response_origin'], 'host_execution_ack')
                self.assertEqual(sent['job']['decision']['status'], 'bypassed')
                with client.stream('GET', '/api/chat/rooms/' + room['id'] + '/events?job_id=' + sent['job']['id']) as stream:
                    lines = list(stream.iter_lines())
                previews = [json.loads(lines[i + 1][6:]) for i, line in enumerate(lines) if line == 'event: reply']
                self.assertTrue(any(p['updates'] and not p['text'] for p in previews), 'An interim response must precede the final answer')
                final = client.get('/api/chat/rooms/' + room['id']).json()
                self.assertEqual(final['messages'][-1]['interim_replies'][0]['text'], '页面展示了应用目录，内部实现尚不能确认。')
                self.assertEqual(final['messages'][-1]['content'], '校对后的完整回复。')
                self.assertEqual(final['task_groups'], [])
                self.assertEqual(app.state.store.space('central')['knowledge_count'], 0)
    def test_bounds_unicode_and_old_jobs(self):
        streams = ReplyStreams()
        streams.start('room', 'job')
        streams.accept_line('room', 'job', 'OPENWIKI_REPLY ' + json.dumps({'text': '中文\n<script>x</script>'}))
        self.assertEqual(streams.snapshot('room', 'job')['text'], '中文\n<script>x</script>')
        self.assertIsNone(streams.snapshot('room', 'other'))
        self.assertFalse(streams.accept_line('room', 'job', 'diagnostic'))
        with self.assertRaises(ValueError):
            streams.append('room', 'job', 'x' * 64000)
        with self.assertRaises(ValueError):
            streams.append('room', 'job', '\0')
        streams.start('room', 'next')
        streams.append('room', 'job', 'stale')
        streams.clear('room', 'job')
        self.assertEqual(streams.snapshot('room', 'next')['text'], '')
        event = sse_event('reply', {'text': 'a\nevent: done\n'})
        self.assertEqual(event.count('\ndata: '), 1)
        self.assertEqual(event.count('\nevent: '), 0)

    def test_sse_previews_complete_and_followup_teaching_remains_readonly(self):
        with tempfile.TemporaryDirectory() as root:
            turns = []
            async def runner(job, store):
                turns.append(dict(job))
                for piece in ['先明确用户任务。', '比如用户想直接听你解释。', '你觉得什么算学会？']:
                    app.state.reply_streams.append(job['room_id'], job['parent_job_id'], piece)
                    self.assertEqual(app.state.chat.get_room(job['room_id'])['messages'][-1]['role'], 'user')
                    await asyncio.sleep(0.11)
                job['answer'] = '先明确用户任务。比如用户想直接听你解释。你觉得什么算学会？'
            app = create_app(base=Path(root) / 'data', runner=runner)
            with TestClient(app) as client:
                room = client.post('/api/chat/primary', json={}).json()
                before = app.state.store.pages('central')
                response = client.post('/api/chat/rooms/' + room['id'] + '/messages',
                                       json={'content': '教我 AI 产品思维', 'learning': True}).json()
                job_id = response['job']['id']
                with client.stream('GET', '/api/chat/rooms/' + room['id'] + '/events?job_id=' + job_id) as stream:
                    self.assertEqual(stream.headers['content-type'], 'text/event-stream; charset=utf-8')
                    self.assertEqual(stream.headers['x-accel-buffering'], 'no')
                    events = list(stream.iter_lines())
                previews = [json.loads(events[i + 1][6:]) for i, line in enumerate(events) if line == 'event: reply']
                self.assertGreaterEqual(len(previews), 2)
                self.assertTrue(next(p['text'] for p in previews if p['text']).startswith('先明确'))
                self.assertIn('event: done', events)
                current = client.get('/api/chat/rooms/' + room['id']).json()
                self.assertEqual(current['status'], 'idle')
                self.assertEqual(current['messages'][-1]['status'], 'completed')
                self.assertNotIn('live_reply', current)
                self.assertEqual(current['task_groups'], [])
                self.assertEqual(current.get('proposals', []), [])
                self.assertEqual(app.state.store.pages('central'), before)
                self.assertEqual(turns[0]['delegation_phase'], 'consultation')
                self.assertTrue(turns[0]['teaching'])
                followup = client.post('/api/chat/rooms/' + room['id'] + '/messages', json={'content': '举个例子'}).json()
                for _ in range(100):
                    if client.get('/api/jobs/' + followup['job']['id']).json()['status'] == 'completed':
                        break
                    time.sleep(0.01)
                self.assertTrue(turns[-1]['teaching'])
                self.assertIn('教我 AI 产品思维', turns[-1]['retrieval_query'])
                self.assertEqual(client.get('/api/chat/rooms/' + room['id'] + '/events?job_id=' + '0' * 32).status_code, 404)

    def test_failed_generation_preserves_partial_as_failed_not_as_knowledge(self):
        with tempfile.TemporaryDirectory() as root:
            async def runner(job, store):
                app.state.reply_streams.append(job['room_id'], job['parent_job_id'], '部分答复')
                raise RuntimeError('连接中断')
            app = create_app(base=Path(root) / 'data', runner=runner)
            with TestClient(app) as client:
                room = client.post('/api/chat/primary', json={}).json()
                response = client.post('/api/chat/rooms/' + room['id'] + '/messages', json={'content': '教我 AI 产品思维'}).json()
                for _ in range(100):
                    if client.get('/api/jobs/' + response['job']['id']).json()['status'] == 'failed':
                        break
                    time.sleep(0.01)
                message = client.get('/api/chat/rooms/' + room['id']).json()['messages'][-1]
                self.assertEqual(message['status'], 'failed')
                self.assertIn('部分答复', message['content'])
                self.assertIn('连接中断', message['content'])
                self.assertEqual(app.state.store.space('central')['knowledge_count'], 0)
