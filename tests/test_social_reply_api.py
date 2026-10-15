import asyncio
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from fastapi.testclient import TestClient
from federation.app import create_app, isolated_ask_environment


class SocialReplyApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name) / 'data'
        self.calls = []
        self.output = {'reply': '谢谢你呀！', 'needs_human': False, 'reason': ''}
        async def runner(job, store):
            self.calls.append(dict(job))
            job['answer'] = json.dumps(self.output, ensure_ascii=False)
            job['model'] = 'controlled-test-model'
        self.app = create_app(base=self.base, runner=runner)

    def tearDown(self):
        self.temp.cleanup()

    def data(self, **extra):
        return dict(channel='comment', account_label='测试账号', sender='测试访客', content='拍得真好', is_test=True, **extra)

    def wait_job(self, client, job):
        for _ in range(300):
            value = client.get('/api/jobs/' + job['id']).json()
            if value['status'] in {'completed', 'failed'}:
                return value
            time.sleep(.01)
        self.fail('job did not finish')

    def test_import_automatically_generates_but_never_claims_delivery(self):
        with TestClient(self.app) as client:
            data = self.data()
            created = client.post('/api/social/replies/messages', json=data).json()
            job = self.wait_job(client, created['job'])
            self.assertEqual(job['status'], 'completed')
            message = client.get('/api/social/replies').json()['messages'][0]
            self.assertEqual(message['status'], 'test_completed')
            self.assertEqual(message['delivery_status'], 'not_sent')
            self.assertEqual(message['reply'], '谢谢你呀！')
            self.assertEqual(len(self.calls), 1)
            repeated = client.post('/api/social/replies/messages', json=data).json()
            self.assertFalse(repeated['created'])
            self.assertEqual(len(self.calls), 1)
            self.assertEqual(client.get('/api/chat/rooms').json()['rooms'], [])
            self.assertFalse(client.get('/api/social/replies').json()['transport']['ready'])
            self.assertEqual(self.calls[0]['delegation_phase'], 'social_reply')

    def test_real_import_is_blocked_and_manual_handoff_preserved(self):
        with TestClient(self.app) as client:
            data = self.data(); data.update(is_test=False, channel='private')
            created = client.post('/api/social/replies/messages', json=data).json()
            self.wait_job(client, created['job'])
            self.assertEqual(client.get('/api/social/replies').json()['messages'][0]['status'], 'blocked')
            self.output = {'reply': '', 'needs_human': True, 'reason': '没有本人报价资料'}
            job = client.post('/api/social/replies/messages/' + created['message']['id'] + '/generate', json={}).json()['job']
            self.wait_job(client, job)
            self.assertEqual(client.get('/api/social/replies').json()['messages'][0]['status'], 'handoff')

    def test_paused_import_resumes_without_per_message_approval(self):
        with TestClient(self.app) as client:
            client.patch('/api/social/replies/settings', json={'enabled':False})
            result = client.post('/api/social/replies/messages', json=self.data()).json()
            self.assertNotIn('job', result)
            self.assertEqual(self.calls, [])
            state = client.patch('/api/social/replies/settings', json={'enabled':True}).json()
            identifier = state['messages'][0]['generation_job_id']
            self.wait_job(client, {'id':identifier})
            self.assertEqual(len(self.calls), 1)

    def test_queued_pause_is_resumable_and_running_result_is_not_sent(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        async def runner(job, store):
            calls.append(job['id'])
            if len(calls) == 2:
                entered.set()
            while not release.is_set():
                await asyncio.sleep(.01)
            job['answer'] = json.dumps(self.output, ensure_ascii=False)
        app = create_app(base=Path(self.temp.name)/'paused', runner=runner)
        with TestClient(app) as client:
            first = client.post('/api/social/replies/messages', json=self.data(external_id='first')).json()
            second = client.post('/api/social/replies/messages', json=self.data(external_id='second')).json()
            self.assertTrue(entered.wait(2))
            # Both general lanes are occupied. A third automatic reply must
            # remain queued and obey a pause before its model starts.
            third = client.post('/api/social/replies/messages', json=self.data(external_id='third')).json()
            self.assertEqual(client.get('/api/jobs/'+third['job']['id']).json()['status'], 'queued')
            client.patch('/api/social/replies/settings', json={'enabled':False})
            release.set()
            for item in (first,second,third): self.wait_job(client,item['job'])
            state = client.get('/api/social/replies').json()
            self.assertEqual([m['status'] for m in state['messages']], ['blocked','blocked','paused'])
            self.assertEqual(len(calls), 2)
            state = client.patch('/api/social/replies/settings', json={'enabled':True}).json()
            self.wait_job(client, {'id':state['messages'][2]['generation_job_id']})
            self.assertEqual(len(calls), 3)

    def test_invalid_model_response_and_forged_state_are_not_sent(self):
        self.output = {'sent':True}
        with TestClient(self.app) as client:
            result = client.post('/api/social/replies/messages', json=self.data()).json()
            self.assertEqual(self.wait_job(client, result['job'])['status'], 'failed')
            self.assertEqual(client.get('/api/social/replies').json()['messages'][0]['status'], 'error')
            self.assertEqual(client.post('/api/social/replies/messages', json={**self.data(), 'access_token':'secret'}).status_code, 400)
            self.assertEqual(client.patch('/api/social/replies/settings', json={'connected':True}).status_code, 400)
            self.assertEqual(client.post('/api/social/replies/messages', json=self.data(), headers={'Origin':'https://evil.example'}).status_code, 403)
            self.assertEqual(client.post('/api/social/replies/send', json={}).status_code, 404)

    def test_reply_model_copy_has_no_wiki_or_connector_context(self):
        job = {'id':'a'*32, 'space':'central', 'action':'ask', 'question':'测试消息', 'delegation_phase':'social_reply'}
        environment = isolated_ask_environment(self.app.state.store, job)
        directory = Path(environment['OPENWIKI_CONFIG_DIR'])
        self.assertEqual(list((directory/'wiki').iterdir()), [])
        self.assertFalse((directory/'connectors').exists())
        self.assertFalse((directory/'INSTRUCTIONS.md').exists())
        self.assertEqual(json.loads(environment['FEDERATION_TEMPLATE_SELECTION']), [])


if __name__ == '__main__': unittest.main()
