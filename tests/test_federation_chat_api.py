"""Multi-agent routing and durable conversation checks with a controlled runner."""
import asyncio
from pathlib import Path
from unittest.mock import patch
import tempfile
import time
import unittest

from fastapi.testclient import TestClient

from federation.app import create_app
from federation.chat import ChatStore


class ChatAPITest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.turns = []
        self.fail_agent = None

        async def runner(job, store):
            self.turns.append(dict(job))
            await asyncio.sleep(0.06)
            if job['space'] == self.fail_agent:
                raise RuntimeError('受控测试的模型错误')
            job['answer'] = job['space'] + ' 的独立回答，第 ' + str(len(self.turns)) + ' 次。'

        self.app = create_app(base=Path(self.temp.name) / 'data', runner=runner)
        self.client = TestClient(self.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def room(self, mode='group', participants=None):
        response = self.client.post('/api/chat/rooms', json={
            'mode': mode, 'participants': participants or ['software', 'commerce'], 'title': '隔离测试'})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def send(self, room, content='请两个行业一起讨论这个问题。'):
        response = self.client.post('/api/chat/rooms/' + room['id'] + '/messages', json={'content': content})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def finish(self, job):
        for _ in range(200):
            value = self.client.get('/api/jobs/' + job['id']).json()
            if value['status'] not in {'queued', 'running'}:
                return value
            time.sleep(0.01)
        self.fail('Test queue did not finish')

    def test_group_calls_each_scoped_agent_then_central_and_remembers_followup(self):
        room = self.room()
        result = self.send(room)
        completed = self.finish(result['job'])
        self.assertEqual(completed['status'], 'completed')
        for turn in completed['turns']:
            detail = self.client.get('/api/jobs/' + turn['id'])
            self.assertEqual(detail.status_code, 200)
            self.assertEqual(detail.json()['status'], 'completed')
        self.assertEqual([j['space'] for j in self.turns], ['software', 'commerce', 'central'])
        self.assertTrue(all(j['structured_chat'] for j in self.turns))
        self.assertIn('software 的独立回答', self.turns[1]['question'])
        self.assertIn('commerce 的独立回答', self.turns[2]['question'])
        current = self.client.get('/api/chat/rooms/' + room['id']).json()
        self.assertEqual(current['status'], 'idle')
        self.assertEqual([m.get('agent_id') for m in current['messages']], [None, 'software', 'commerce', 'central'])
        followup = self.send(room, '根据上轮讨论，补充执行步骤。')
        self.assertEqual(self.finish(followup['job'])['status'], 'completed')
        self.assertIn('central 的独立回答', self.turns[3]['question'])
        self.assertIn('根据上轮讨论', self.turns[3]['question'])
        recovered = ChatStore(self.app.state.store).get_room(room['id'])
        self.assertEqual(len(recovered['messages']), 8)
        self.assertIsNone(recovered['active_job_id'])

    def test_direct_central_can_chat_without_pretending_to_have_published_knowledge(self):
        room = self.room('direct', ['central'])
        self.assertEqual(self.finish(self.send(room, '我们先讨论知识库规划。')['job'])['status'], 'completed')
        self.assertEqual([j['space'] for j in self.turns], ['central'])
        self.assertEqual(self.app.state.store.space('central')['knowledge_count'], 0)
        self.assertEqual(self.app.state.store.space('central')['published_count'], 0)

    def test_agent_catalog_tracks_new_industry_and_individual_chat(self):
        branch = self.client.post('/api/branches', json={'name': '制造业', 'description': '测试'}).json()
        agents = self.client.get('/api/agents').json()['agents']
        self.assertEqual(len(agents), 27)
        self.assertIn(branch['id'], [a['id'] for a in agents])
        room = self.room('direct', [branch['id']])
        self.assertEqual(self.finish(self.send(room)['job'])['status'], 'completed')
        self.assertEqual([j['space'] for j in self.turns], [branch['id']])

    def test_same_room_cannot_queue_two_rounds_and_sources_are_locked_during_chat(self):
        room = self.room()
        result = self.send(room)
        duplicate = self.client.post('/api/chat/rooms/' + room['id'] + '/messages', json={'content': '重复发送'})
        self.assertEqual(duplicate.status_code, 409)
        source = self.client.post('/api/spaces/software/sources', json={'filename': 'busy.md', 'text': 'x'})
        self.assertEqual(source.status_code, 409)
        self.assertEqual(self.finish(result['job'])['status'], 'completed')
        self.assertEqual(len(self.app.state.chat.get_room(room['id'])['messages']), 4)

    def test_failed_agent_is_labeled_other_agents_continue_and_room_accepts_followup(self):
        self.fail_agent = 'software'
        room = self.room()
        self.assertEqual(self.finish(self.send(room)['job'])['status'], 'failed')
        current = self.app.state.chat.get_room(room['id'])
        self.assertEqual(current['status'], 'failed')
        self.assertEqual(current['messages'][1]['status'], 'failed')
        self.assertEqual(current['messages'][2]['status'], 'completed')
        self.assertEqual(current['messages'][3]['agent_id'], 'central')
        self.assertIsNone(current['active_job_id'])
        self.fail_agent = None
        self.assertEqual(self.finish(self.send(room, '重试讨论。')['job'])['status'], 'completed')

    def test_input_and_cross_origin_checks_apply_to_chat(self):
        invalid = self.client.post('/api/chat/rooms', json={'mode': 'group', 'participants': ['unknown']})
        self.assertEqual(invalid.status_code, 400)
        room = self.room()
        blank = self.client.post('/api/chat/rooms/' + room['id'] + '/messages', json={'content': '   '})
        self.assertEqual(blank.status_code, 400)
        bad_origin = self.client.post('/api/chat/rooms/' + room['id'] + '/messages',
                                     json={'content': 'test'}, headers={'Origin': 'https://unrelated.example'})
        self.assertEqual(bad_origin.status_code, 403)
        self.assertEqual(self.app.state.chat.get_room(room['id'])['messages'], [])

    def test_shutdown_retains_completed_speaker_and_marks_interrupted_speaker(self):
        async def interrupted_runner(job, store):
            if job['space'] == 'software':
                job['answer'] = '本条已完成。'
            else:
                await asyncio.Event().wait()

        app = create_app(base=Path(self.temp.name) / 'interrupted', runner=interrupted_runner)
        with TestClient(app) as client:
            room = client.post('/api/chat/rooms', json={
                'mode': 'group', 'participants': ['software', 'commerce']}).json()
            client.post('/api/chat/rooms/' + room['id'] + '/messages', json={'content': '测试停止时保存状态。'})
            for _ in range(100):
                current = client.get('/api/chat/rooms/' + room['id']).json()
                if current['current_agent'] == '电商与零售 Agent':
                    break
                time.sleep(0.01)
            self.assertEqual(current['current_agent'], '电商与零售 Agent')
        restored = ChatStore(app.state.store).get_room(room['id'])
        self.assertEqual(restored['status'], 'failed')
        self.assertEqual(restored['messages'][1]['content'], '本条已完成。')
        self.assertEqual(restored['messages'][2]['status'], 'failed')
        self.assertEqual(restored['messages'][2]['agent_id'], 'commerce')
        self.assertIsNone(restored['active_job_id'])
        self.assertFalse(any(m['agent_id'] == 'central' for m in restored['messages']))

    def test_job_disk_failure_does_not_leave_room_queued(self):
        room = self.room()
        original = Path.write_text

        def fail_job_write(path, *args, **kwargs):
            if path.parent.name == 'jobs' and path.suffix == '.tmp':
                raise OSError('Controlled disk failure')
            return original(path, *args, **kwargs)

        with patch.object(Path, 'write_text', fail_job_write):
            with self.assertRaises(Exception):
                self.client.post('/api/chat/rooms/' + room['id'] + '/messages', json={'content': '不得卡住会话'})
        restored = self.app.state.chat.get_room(room['id'])
        self.assertEqual(restored['status'], 'idle')
        self.assertEqual(restored['messages'], [])
        self.assertIsNone(restored['active_job_id'])
        self.assertEqual(self.turns, [])

    def test_specialists_speak_before_their_parent_and_central(self):
        room = self.room('group', ['software-frontend', 'software-backend'])
        self.assertEqual(room['participants'], ['software-frontend', 'software-backend', 'software', 'central'])
        final = self.finish(self.send(room, '前端和后端讨论接口配合，再由上级汇总。')['job'])
        self.assertEqual(final['status'], 'completed')
        self.assertEqual([turn['space'] for turn in self.turns], room['participants'])
        messages = self.app.state.chat.get_room(room['id'])['messages'][1:]
        self.assertEqual([m['phase'] for m in messages], ['reply', 'reply', 'summary', 'summary'])
        self.assertIn('software-frontend 的独立回答', self.turns[2]['question'])
        self.assertIn('software-backend 的独立回答', self.turns[2]['question'])
        self.assertIn('software 的独立回答', self.turns[3]['question'])

    def test_specialist_direct_chat_and_nested_branch_creation(self):
        response = self.client.post('/api/branches', json={
            'name': 'iOS', 'description': '移动端开发子方向', 'parent_id': 'software-app'})
        self.assertEqual(response.status_code, 200, response.text)
        branch = response.json()
        self.assertEqual(branch['ancestor_ids'], ['central', 'software', 'software-app'])
        graph = self.client.get('/api/graph').json()
        self.assertIn({'source': 'software-app/index', 'target': branch['id'] + '/index'}, graph['edges'])
        self.assertNotIn({'source': 'central/index', 'target': branch['id'] + '/index'}, graph['edges'])
        room = self.room('direct', [branch['id']])
        final = self.finish(self.send(room, '只需要 iOS Agent 回答。')['job'])
        self.assertEqual(final['status'], 'completed')
        self.assertEqual([turn['space'] for turn in self.turns], [branch['id']])


if __name__ == '__main__':
    unittest.main()
