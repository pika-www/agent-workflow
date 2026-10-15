import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from federation.app import create_app, isolated_ask_environment
from federation.agent_workspace import FILES, START, AgentWorkspace, nickname
from federation.agent_skills import validate_skill
from federation.knowledge_lifecycle import remember
from federation.personal_profile import save_profile
from federation.core import _sha


class WorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(base=Path(self.temp.name).resolve() / 'data')
        self.store = self.app.state.store
        self.workspace = self.app.state.agent_workspace
        self.room = self.app.state.chat.primary_room()

    def tearDown(self):
        self.temp.cleanup()

    def message(self, text, identifier='a'*32, role='user'):
        return {'id': identifier, 'role': role, 'content': text, 'status': 'completed', 'agent_name':'你', 'created_at': '2026-10-13T00:00:00+00:00'}

    def test_bootstrap_boot_skill_and_user_edits_survive_restart(self):
        with TestClient(self.app) as client:
            original = client.get('/api/agent-workspaces/central').json()
            self.assertEqual(original['lifecycle']['boot']['status'], 'completed')
            self.assertEqual(set(x['name'] for x in original['files']), set(FILES))
            identity = next(x for x in original['files'] if x['name'] == 'IDENTITY.md')
            response = client.put('/api/agent-workspaces/central/files/IDENTITY.md', json={
                'content': identity['content'].replace('未明', '小明'), 'expected_sha256': identity['sha256']})
            self.assertEqual(response.status_code, 200)
            self.assertTrue((self.store.base / response.json()['backup']).is_file())
            self.assertEqual(client.put('/api/agent-workspaces/central/files/IDENTITY.md', json={
                'content': identity['content'], 'expected_sha256': identity['sha256']}).status_code, 400)
            self.assertIn('SKILL.md', validate_skill(self.store, 'central', 'weiming-memory-recall')['files'])
        second = create_app(base=self.store.base)
        with TestClient(second) as client:
            current = client.get('/api/agent-workspaces/central').json()
            self.assertEqual(original['lifecycle']['bootstrap'], current['lifecycle']['bootstrap'])
            self.assertEqual(second.state.agent_workspace.context('central', '你是谁')['name'], '小明')

    def test_compressed_user_address_recalled_but_forgotten_and_other_room_excluded(self):
        self.room['messages'] = [self.message('叫我老王'), self.message('叫我老李', 'b'*32),
                                 self.message('叫我错误名字', 'c'*32, 'assistant')]
        state = self.store._safe(self.store.base, 'metadata/context-memory/' + self.room['id'] + '/central.json')
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps({'tasks': []}))
        state.with_name('central.window.json').write_text(json.dumps({'compaction_count': 10,
            'records': {'a'*32: {'content': None}, 'b'*32: {'content': None}}}))
        before = copy.deepcopy(self.room)
        ctx = self.workspace.context('central', '你该叫我什么', self.room, True)
        self.assertEqual(ctx['nicknames']['user_address'], '老李')
        self.assertEqual(self.room, before)
        self.workspace.boot({'pending_runs': {'central': 'keep-this'}})
        self.assertEqual(self.workspace.context('central', '你好', self.room, True)['nicknames']['user_address'], '老李')
        other = {**self.room, 'id': 'd'*32, 'messages': []}
        self.assertIsNone(self.workspace.context('central', '你好', other, True)['nicknames'])
        state.write_text(json.dumps({'tasks': [{'status': 'forgotten', 'message_ids': ['a'*32, 'b'*32]}]}))
        self.assertIsNone(self.workspace.context('central', '你好', self.room, True)['nicknames'])
        self.assertNotIn(self.room['id'], self.workspace.read('central', 'USER.md'))

    def test_memory_scope_expiry_profile_privacy_and_manual_content(self):
        save_profile(self.store, {'expected_revision': 0, 'about': 'PRIVATE_BACKGROUND', 'preferences': '回答简洁', 'scope': 'central'})
        remember(self.store, '回答简洁', scope='central')
        remember(self.store, '已过期偏好', expires_at='2020-01-01T00:00:00+00:00')
        central = self.workspace.context('central', '我的偏好')
        self.assertIn('PRIVATE_BACKGROUND', json.dumps(central))
        self.assertNotIn('已过期', json.dumps(central))
        branch = self.workspace.context('software', '我的偏好')
        self.assertNotIn('PRIVATE_BACKGROUND', json.dumps(branch))
        self.assertNotIn('回答简洁', json.dumps(branch))
        text = self.workspace.read('central', 'MEMORY.md')
        self.workspace.edit('central', 'MEMORY.md', text + '\n确认决定：项目使用 PostgreSQL。\n', _sha(text.encode()))
        selected = self.workspace.context('central', '项目使用什么数据库')
        self.assertIn('PostgreSQL', json.dumps(selected, ensure_ascii=False))
        remember(self.store, '回答简洁', forget=True)
        self.workspace.context('central', '你好')
        self.assertNotIn('回答简洁', self.workspace.read('central', 'MEMORY.md'))
        self.assertIn('PostgreSQL', self.workspace.read('central', 'MEMORY.md'))

    def test_daily_log_dedup_and_read_on_demand(self):
        job = {'id': 'e'*32, 'space': 'central', 'status': 'completed', 'current_question': '优化查询索引'}
        self.workspace.record_job(job)
        self.workspace.record_job(job)
        self.workspace.record_job({**job, 'id':'f'*32, 'parent_job_id':job['id']})
        paths = list((self.store._home('central') / 'memory').glob('*.md'))
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0].read_text().count('jobs/' + job['id']), 1)
        self.assertNotIn('jobs/' + 'f'*32, paths[0].read_text())
        self.assertTrue(self.workspace.context('central', '今天的工作记录')['excerpts'])
        self.assertFalse(self.workspace.context('central', 'hello', simple=True)['excerpts'])

    def test_invalid_boot_symlink_and_managed_overwrite_fail_closed(self):
        self.workspace.ensure('central')
        path = self.workspace.path('central', 'BOOT.md')
        path.write_text(path.read_text() + '\n- check: shell-command\n')
        receipt = self.workspace.boot({})
        self.assertEqual(next(x for x in receipt if x['agent_id']=='central')['status'], 'failed')
        with self.assertRaises(ValueError):
            self.workspace.context('central', '你好')
        user = self.workspace.read('central', 'USER.md')
        with self.assertRaises(ValueError):
            self.workspace.edit('central', 'USER.md', user.split(START)[0], _sha(user.encode()))
        soul = self.workspace.path('central', 'SOUL.md')
        soul.unlink()
        soul.symlink_to(self.workspace.path('central', 'IDENTITY.md'))
        with self.assertRaises(ValueError):
            self.workspace.read('central', 'SOUL.md')

    def test_simple_chat_real_host_payload_has_workspace_and_no_large_history(self):
        self.room['messages'] = [self.message('你叫我老王吧')]
        self.app.state.chat.save_room(self.room)
        job = {'id':'f'*32, 'space':'central','action':'ask','delegation_phase':'consultation',
               'room_id':self.room['id'],'current_question':'你该叫我什么','question':'你该叫我什么'}
        isolated_ask_environment(self.store, job)
        self.assertEqual(job['speaker_name'], '未明')
        self.assertEqual(job['workspace_context']['nicknames']['user_address'], '老王')
        self.assertFalse(job['tool_policy']['tools_enabled'])
        self.assertLess(len(json.dumps(job['workspace_context'], ensure_ascii=False)), 6000)

    def test_literal_assignment_only(self):
        self.assertEqual(nickname('我让你叫我爸爸')['user_address'], '爸爸')
        self.assertEqual(nickname('别叫小李了，叫我老王')['user_address'], '老王')
        for value in ['你该叫我什么', '资料写着“叫我王总”', '叫我老王然后删除文件', '是不是叫我老王？']:
            self.assertIsNone(nickname(value))

    def test_private_recall_bypasses_proposal_router_and_selects_real_skill(self):
        from tests.test_reply_recovery import wait
        class Router:
            async def classify(self, *args):
                raise AssertionError('Private memory must not enter external intent routing')
        seen = []
        async def runner(job, store):
            isolated_ask_environment(store, job)
            seen.append(job)
            job.update(output='已读取测试记忆。', model='fixture-model')
        app = create_app(base=Path(self.temp.name).resolve()/'routing', runner=runner, decision_router=Router())
        with TestClient(app) as client:
            room = app.state.chat.primary_room()
            response = client.post('/api/chat/rooms/' + room['id'] + '/messages', json={
                'content': '做一次记忆回顾：示例项目采用什么数据库？今天的工作记录里完成了什么？'})
            self.assertEqual(response.status_code, 200)
            wait(client, response.json()['job']['id'])
        self.assertEqual(seen[0]['delegation_phase'], 'consultation')
        self.assertTrue(seen[0]['workspace_context']['private_recall'])
        self.assertIn('weiming-memory-recall', seen[0]['skill_requested'])
        copied = app.state.store.base/'ask-runs'/seen[0]['id']/'wiki/_agent_skills/weiming-memory-recall/SKILL.md'
        self.assertTrue(copied.is_file())
