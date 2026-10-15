"""Explicit mentions answer directly; unmentioned turns return to central."""
import asyncio
import json
from pathlib import Path
import tempfile
import time
import unittest

from fastapi.testclient import TestClient
from federation.app import create_app
from federation.intake import member_conversation_history


class MemberMentionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.turns = []
        self.fail_agent = None

        async def runner(turn, store):
            self.turns.append(dict(turn))
            if turn.get('speaker_name'):
                room = self.app.state.chat.get_room(turn['room_id'])
                self.assertFalse(any(m['role'] == 'assistant' and m.get('round_id') == turn['parent_job_id'] and
                                     m.get('agent_id') == 'central' and m.get('phase') != 'acknowledgement' for m in room['messages']))
                self.assertNotIn('handoff_message_id', turn)
                self.assertNotIn('<main_agent_handoff>', turn['question'])
                self.assertEqual(room['current_agent'], turn['speaker_name'])
                self.app.state.reply_streams.append(turn['room_id'], turn['parent_job_id'], '可见的成员回复')
            await asyncio.sleep(.12)
            if turn['space'] == self.fail_agent:
                raise RuntimeError('受控连接中断')
            turn['answer'] = turn['speaker_name'] + '：接着刚才的场景说。' if turn.get('speaker_name') else '记住你不想看文档，只想聊天学。'
            turn['wiki_reads'] = [{'path': '/index.md', 'sha256': 'fixture'}]

        async def researcher(store, goal, job_id, catalog):
            return {'status': 'ready', 'sources': [{'url': 'https://example.com/verified', 'title': '受控来源', 'text': '来源数据'}]}

        self.app = create_app(base=Path(self.temp.name) / 'data', runner=runner, researcher=researcher)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.room = self.client.post('/api/chat/primary', json={}).json()
        self.members = [a for a in self.client.get('/api/agents').json()['agents'] if a['id'] in {'software-frontend', 'software-backend'}]
        self.route = '/api/chat/rooms/' + self.room['id'] + '/messages'

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def send(self, content, **options):
        response = self.client.post(self.route, json={'content': content, **options})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['job']

    def finish(self, job):
        for _ in range(300):
            result = self.client.get('/api/jobs/' + job['id']).json()
            if result['status'] not in {'queued', 'running'}:
                return result
            time.sleep(.01)
        self.fail('成员咨询没有结束')

    def test_direct_member_preserves_named_context_and_sse_without_main_message(self):
        member = self.members[0]
        self.finish(self.send('教我 AI 产品思维，我不想看文档，只想聊天学'))
        before = {a['id']: self.app.state.store.pages(a['id']) for a in self.app.state.chat.agents()}
        job = self.send('@' + member['name'] + ' 结合刚才那个场景，举个例子')
        with self.client.stream('GET', '/api/chat/rooms/' + self.room['id'] + '/events?job_id=' + job['id']) as stream:
            lines = list(stream.iter_lines())
        rooms = [json.loads(lines[i + 1][6:]) for i, line in enumerate(lines) if line == 'event: room']
        self.assertTrue(rooms)
        self.assertFalse(any(any(m.get('agent_id') == 'central' and m.get('round_id') == job['id'] for m in room['messages']) for room in rooms))
        previews = [json.loads(lines[i + 1][6:]) for i, line in enumerate(lines) if line == 'event: reply']
        self.assertTrue(any(p['text'] == '可见的成员回复' and p['agent_id'] == member['id'] for p in previews))
        self.assertEqual(self.finish(job)['status'], 'completed')
        self.assertEqual([t['space'] for t in self.turns], ['central', member['id']])
        turn = self.turns[-1]
        self.assertIn('记住你不想看文档', turn['question'])
        self.assertIn('agent_name', turn['question'])
        self.assertIn('你是' + member['name'], turn['question'])
        self.assertNotIn('你是主 Agent，当前', turn['question'])
        self.assertIn('教我 AI 产品思维', turn['retrieval_query'])
        final = self.client.get('/api/chat/rooms/' + self.room['id']).json()
        current = [m for m in final['messages'] if m.get('round_id') == job['id']]
        self.assertEqual([m.get('agent_id') for m in current], [None, member['id']])
        self.assertEqual(current[1]['wiki_reads'][0]['path'], '/index.md')
        self.assertEqual(final['status'], 'idle')
        self.assertEqual(final.get('task_groups', []), [])
        self.assertEqual(final.get('proposals', []), [])
        self.assertEqual(before, {a['id']: self.app.state.store.pages(a['id']) for a in self.app.state.chat.agents()})

    def test_multiple_members_read_previous_member_without_central_echo(self):
        names = ' '.join('@' + a['name'] for a in self.members)
        job = self.send(names + ' 聊聊怎么减少页面里多余的点击', requested_agents=[a['id'] for a in self.members])
        self.assertEqual(self.finish(job)['status'], 'completed')
        self.assertEqual([t['space'] for t in self.turns], [a['id'] for a in self.members])
        self.assertIn(self.members[0]['name'] + '：接着刚才的场景说。', self.turns[1]['question'])
        current = self.client.get('/api/chat/rooms/' + self.room['id']).json()
        self.assertEqual([m.get('agent_id') for m in current['messages']], [None, *[a['id'] for a in self.members]])

    def test_failed_member_keeps_partial_and_other_member_continues_then_followup_works(self):
        self.fail_agent = self.members[0]['id']
        job = self.send(' '.join('@' + a['name'] for a in self.members) + ' 讨论这个交互')
        self.assertEqual(self.finish(job)['status'], 'failed')
        current = self.client.get('/api/chat/rooms/' + self.room['id']).json()
        replies = [m for m in current['messages'] if m['role'] == 'assistant']
        self.assertEqual(len(replies), 2)
        self.assertEqual(replies[0]['status'], 'failed')
        self.assertIn('可见的成员回复', replies[0]['content'])
        self.assertIn('受控连接中断', replies[0]['content'])
        self.assertEqual(replies[1]['status'], 'completed')
        self.assertIsNone(current['active_job_id'])
        self.fail_agent = None
        followup = self.send('@' + self.members[0]['name'] + ' 再试一次')
        self.assertEqual(self.finish(followup)['status'], 'completed')
        self.assertNotIn('受控连接中断', self.turns[-1]['question'])

    def test_mentioned_member_receives_real_research_context(self):
        job = self.send('@' + self.members[0]['name'] + ' 搜索一下这个交互的资料', research=True)
        self.assertEqual(self.finish(job)['status'], 'completed')
        self.assertIn('https://example.com/verified', self.turns[0]['question'])
        final = self.client.get('/api/chat/rooms/' + self.room['id']).json()
        self.assertTrue(final['messages'][-1]['research_only'])
        self.assertEqual(final['messages'][-1]['research']['status'], 'ready')

    def test_main_can_continue_after_member_without_losing_its_answer(self):
        member = self.members[0]
        self.finish(self.send('@' + member['name'] + ' 给我一个例子'))
        self.assertEqual(self.finish(self.send('你觉得他这个例子怎么样？'))['status'], 'completed')
        self.assertEqual([t['space'] for t in self.turns], [member['id'], 'central'])
        self.assertIn(member['name'] + '：接着刚才的场景说。', self.turns[-1]['question'])
        current = self.client.get('/api/chat/rooms/' + self.room['id']).json()
        self.assertEqual([m.get('agent_id') for m in current['messages']], [None, member['id'], None, 'central'])

    def test_shutdown_marks_actual_member_interrupted_without_main_message(self):
        async def interrupted(turn, store):
            app.state.reply_streams.append(turn['room_id'], turn['parent_job_id'], '成员已经说出的部分')
            await asyncio.Event().wait()
        app = create_app(base=Path(self.temp.name) / 'interrupted', runner=interrupted)
        with TestClient(app) as client:
            room = client.post('/api/chat/primary', json={}).json()
            result = client.post('/api/chat/rooms/' + room['id'] + '/messages',
                                json={'content': '@software-frontend 在吗'}).json()
            for _ in range(100):
                current = client.get('/api/chat/rooms/' + room['id']).json()
                if current.get('live_reply', {}).get('text'):
                    break
                time.sleep(.01)
            self.assertTrue(current['live_reply']['text'])
        current = app.state.chat.get_room(room['id'])
        self.assertEqual([m.get('agent_id') for m in current['messages']], [None, 'software-frontend'])
        self.assertEqual(current['messages'][1]['status'], 'failed')
        self.assertIn('成员已经说出的部分', current['messages'][1]['content'])
        self.assertEqual(current['status'], 'failed')
        self.assertIsNone(current['active_job_id'])
        self.assertIsNone(current['current_agent'])

    def test_history_bound_preserves_only_readonly_identities(self):
        messages = [{'role': 'assistant', 'status': 'completed', 'phase': 'consultation', 'round_id': 'older',
                     'agent_name': '成员' + str(i), 'content': '中' * 1000} for i in range(12)]
        messages += [{'role': 'assistant', 'status': 'failed', 'phase': 'consultation', 'content': '失败不能当上下文'},
                     {'role': 'assistant', 'status': 'completed', 'phase': 'execute', 'content': '项目执行内容'},
                     {'role': 'user', 'round_id': 'current', 'content': '本轮问题单独提供'}]
        history = member_conversation_history({'messages': messages}, {'id': 'current'})
        self.assertEqual(len(history), 8)
        self.assertEqual(history[0]['agent_name'], '成员4')
        self.assertLess(len(json.dumps(history, ensure_ascii=False)), 6000)
        self.assertNotIn('失败不能当上下文', str(history))
        self.assertNotIn('项目执行内容', str(history))

    def test_id_mention_does_not_call_prefix_or_allow_hidden_extra_member(self):
        blocked = self.client.post(self.route, json={'content': '@software-frontend 在吗', 'requested_agents': ['software']})
        self.assertEqual(blocked.status_code, 400)
        self.assertEqual(self.turns, [])
        job = self.send('@software-frontend 在吗')
        self.assertEqual(self.finish(job)['status'], 'completed')
        self.assertEqual([t['space'] for t in self.turns], ['software-frontend'])

    def test_greeting_skips_old_lesson_but_real_question_keeps_context(self):
        self.finish(self.send('教我 AI 产品思维，只想聊天学'))
        greeting = self.send('@software-frontend 你在吗？')
        self.assertEqual(self.finish(greeting)['status'], 'completed')
        self.assertFalse(self.turns[-1]['teaching'])
        self.assertNotIn('<earlier_conversation>', self.turns[-1]['question'])
        self.assertEqual(self.turns[-1]['retrieval_query'], '你在吗？')
        question = self.send('@software-frontend 在吗？顺便举个刚才场景的例子')
        self.assertEqual(self.finish(question)['status'], 'completed')
        self.assertTrue(self.turns[-1]['teaching'])
        self.assertIn('<earlier_conversation>', self.turns[-1]['question'])

    def test_member_capability_question_uses_its_identity(self):
        job = self.send('@software-frontend 你能做什么？')
        self.assertEqual(self.finish(job)['status'], 'completed')
        self.assertEqual([t['space'] for t in self.turns], ['software-frontend'])
        self.assertIn('<consulted_member>', self.turns[0]['question'])
        self.assertIn('Web 前端', self.turns[0]['question'])

    def test_room_reference_does_not_revive_explicitly_forgotten_task(self):
        self.finish(self.send('教我 AI 产品思维，我不想看文档，只想聊天学'))
        memory=self.app.state.context_memory;state=memory.inspect(self.room['id'],'central')
        memory.edit(self.room['id'],'central',state['active_task'],state['revision'],'forget')
        job=self.send('@'+self.members[0]['name']+' 结合刚才那个场景，举个例子')
        self.assertEqual(self.finish(job)['status'],'completed')
        self.assertNotIn('记住你不想看文档',self.turns[-1]['question'])
        self.assertNotIn('教我 AI 产品思维',json.dumps((self.turns[-1].get('context_memory') or {}).get('room_context'),ensure_ascii=False))
