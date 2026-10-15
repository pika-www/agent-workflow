"""Actual orchestration states become durable, attributed group messages."""
import copy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

from federation.chat import ChatStore, HISTORY_MESSAGE_LIMIT
from federation.core import FederationStore, _now
from federation.group_timeline import sync_group_timeline, RECEIPT_BYTE_LIMIT, RECEIPT_ITEM_LIMIT
from federation.orchestration import run_orchestration
from federation.skill_context import skill_receipt
from federation.template_context import template_receipt


def delegate(*members):
    return json.dumps({'action': 'delegate', 'tasks': [{'agent_id': name, 'task': '完成 ' + name + ' 的实际任务'} for name in members]})


class GroupTimelineTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.store = FederationStore(self.root / 'data', project_root=self.root / 'project')
        self.store.init()
        self.chat = ChatStore(self.store)
        self.room = self.chat.create_room('orchestrated', ['central'])
        self.round = uuid.uuid4().hex
        self.room.update(status='running', active_job_id=self.round)
        self.chat.append_message(self.room, 'user', '请让前端和后端共同给出实现方案', round_id=self.round)

    def tearDown(self):
        self.tmp.cleanup()

    def persist(self):
        return sync_group_timeline(self.chat, self.room, self.round)

    async def orchestration(self, replies, with_receipts=False, verify_results=False):
        async def invoke(agent, prompt, phase, task_id):
            # The start event must already be persisted before the model callback.
            loaded = self.chat.get_room(self.room['id'])
            self.assertTrue(any(item.get('event_kind') == 'work_started' and
                                item.get('delegation_task_id') == task_id and item['phase'] == phase
                                for item in loaded['messages']))
            value = replies[(agent, phase)]
            if isinstance(value, Exception):
                raise value
            if with_receipts and agent == 'software-frontend' and phase == 'execute':
                task = next(item for item in self.room['delegations'] if item['id'] == task_id)
                task.update(wiki_reads=[{'path': 'guide.md', 'sha256': 'a' * 64}],
                            wiki_citation_check={'status': 'verified', 'checked_count': 1},
                            template_reads=[{'template_id': 'vue-ts', 'path': 'src/App.vue', 'sha256': 'b' * 64}],
                            template_selection=[{'id': 'vue-ts', 'source_version': '3.0'}],
                            skill_reads=[{'skill_id': 'client-test', 'path': 'SKILL.md', 'sha256': 'c' * 64}],
                            skill_selection=[{'id': 'client-test', 'display_name': '客户端测试', 'version': 'v1'}],
                            skill_notices=['未执行外部工具'])
                value += template_receipt(task) + skill_receipt(task)
            return value
        return await run_orchestration(self.room, self.chat.agents(), '任务', self.chat._history(self.room),
                                       invoke, self.persist, self.round, verify_results=verify_results)

    async def test_result_review_persists_through_real_timeline_callback(self):
        result = await self.orchestration({
            ('central', 'plan'): delegate('software'),
            ('software', 'plan'): delegate('software-backend'),
            ('software-backend', 'execute'): '后端实际产物。',
            ('software', 'summary'): '模块保留后端产物。',
            ('central', 'summary'): '主 Agent 保留实际产物。',
            ('central', 'review'): '{"complete":true,"gaps":[],"tasks":[]}',
        }, verify_results=True)
        self.assertFalse(result['failed'])
        root = next(task for task in self.room['delegations'] if task['agent_id'] == 'central')
        self.assertEqual(root['quality'], 'coverage_checked')
        events = [message for message in self.chat.get_room(self.room['id'])['messages']
                  if message.get('event_kind') == 'work_started' and message['phase'] == 'review']
        self.assertEqual(len(events), 1)
        self.assertIn('检查结果完整性', events[0]['content'])
        self.assertEqual(self.persist(), [])

    async def test_nested_agents_report_in_same_room_before_central_final(self):
        result = await self.orchestration({
            ('central', 'plan'): delegate('software'),
            ('software', 'plan'): delegate('software-frontend', 'software-backend'),
            ('software-frontend', 'execute'): '前端实际结果。',
            ('software-backend', 'execute'): '后端实际结果。',
            ('software', 'summary'): '软件模块实际汇总。',
            ('central', 'summary'): '中央最终汇总。',
        }, with_receipts=True)
        self.assertFalse(result['failed'])
        messages = self.room['messages']
        actual = [message for message in messages if message.get('event_kind') == 'result']
        self.assertEqual([message['agent_id'] for message in actual], ['software-frontend', 'software-backend', 'software'])
        self.assertEqual([message['content'] for message in actual], ['前端实际结果。', '后端实际结果。', '软件模块实际汇总。'])
        self.assertNotIn('中央最终汇总。', [message['content'] for message in messages])
        self.assertFalse(any('"action"' in message['content'] for message in messages))
        frontend = actual[0]
        self.assertEqual(frontend['recipient_agent_id'], 'software')
        self.assertEqual(frontend['parent_agent_id'], 'software')
        self.assertEqual(frontend['event_origin'], 'agent')
        self.assertEqual(frontend['wiki_reads'][0]['sha256'], 'a' * 64)
        self.assertEqual(frontend['skill_reads'][0]['sha256'], 'c' * 64)
        self.assertEqual(frontend['wiki_citation_check']['status'], 'verified')
        dispatches = [message for message in messages if message.get('event_kind') == 'delegation']
        self.assertEqual([(message['actor_agent_id'], message['recipient_agent_id']) for message in dispatches],
                         [('central', 'software'), ('software', 'software-frontend'), ('software', 'software-backend')])
        self.assertTrue(all(message['role'] == 'system' and message['agent_id'] is None and message['event_origin'] == 'host'
                            for message in dispatches))
        task = next(item for item in self.room['delegations'] if item['agent_id'] == 'software-frontend')
        self.assertIn('【本轮实际读取的技能规范】', task['result'])
        task['wiki_reads'][0]['path'] = 'later-change.md'
        self.assertEqual(frontend['wiki_reads'][0]['path'], 'guide.md')
        self.assertEqual(self.persist(), [])
        loaded = self.chat.get_room(self.room['id'])
        self.assertEqual(loaded['messages'], messages)
        event_keys = [message['event_key'] for message in messages if 'event_key' in message]
        self.assertEqual(len(event_keys), len(set(event_keys)))
        self.assertNotIn('group_timeline', self.chat.list_rooms()[0])

    async def test_failures_and_partial_module_results_are_explicit(self):
        result = await self.orchestration({
            ('central', 'plan'): delegate('software'),
            ('software', 'plan'): delegate('software-frontend'),
            ('software-frontend', 'execute'): RuntimeError('模型连接失败'),
            ('software', 'summary'): '前端没有结果，当前只有部分分析。',
            ('central', 'summary'): '本轮缺少前端结果。',
        })
        self.assertTrue(result['failed'])
        messages = self.room['messages']
        results = [message for message in messages if message.get('event_kind') == 'result']
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['agent_id'], 'software')
        self.assertEqual(results[0]['status'], 'failed')
        self.assertEqual(results[0]['result_scope'], 'partial')
        errors = [message for message in messages if message.get('event_kind') == 'error']
        self.assertEqual({message['actor_agent_id'] for message in errors}, {'central', 'software', 'software-frontend'})
        self.assertTrue(all(message['event_origin'] == 'host' and message['role'] == 'system' for message in errors))
        self.assertTrue(any('模型连接失败' in message['content'] for message in errors))

    async def test_direct_central_answer_is_not_duplicated_by_timeline(self):
        await self.orchestration({('central', 'plan'): '{"action":"answer","answer":"planner internal text"}',
                                  ('central', 'execute'): '中央实际回答。'})
        self.assertEqual([message['role'] for message in self.room['messages']], ['user', 'system', 'system', 'system'])
        self.assertFalse(any(message.get('event_kind') == 'result' for message in self.room['messages']))
        self.assertNotIn('planner internal text', json.dumps(self.room['messages']))
        self.chat.append_message(self.room, 'assistant', '中央实际回答。', 'central', round_id=self.round)
        self.assertEqual(self.persist(), [])
        self.assertEqual(sum(message['content'] == '中央实际回答。' for message in self.room['messages']), 1)

    def task(self, agent, parent=None, instruction='具体任务'):
        info = next(item for item in self.chat.agents() if item['id'] == agent)
        task = {'id': uuid.uuid4().hex, 'round_id': self.round, 'parent_task_id': parent['id'] if parent else None,
                'agent_id': agent, 'agent_name': info['name'], 'depth': info['depth'], 'title': instruction[:100],
                'instruction': instruction, 'status': 'queued', 'phase': 'plan' if info['child_count'] else 'execute',
                'result': '', 'error': None, 'created_at': _now(), 'updated_at': _now()}
        self.room['delegations'].append(task)
        if agent not in self.room['participants']:
            self.room['participants'].append(agent)
        return task

    def enable(self):
        root = self.task('central')
        self.persist()
        return root

    def test_primary_room_is_dedicated_and_idempotent_without_promoting_old_history(self):
        self.room.update(status='idle', active_job_id=None)
        self.chat.save_room(self.room)
        self.chat.create_room('orchestrated', ['central'], '主 Agent')
        old_paths = {path: path.read_bytes() for path in self.chat.root.glob('*.json')}
        primary = self.chat.primary_room()
        self.assertEqual(primary['purpose'], 'primary')
        self.assertEqual(primary['title'], '主 Agent')
        self.assertEqual(primary['participants'], ['central'])
        self.assertEqual(primary['messages'], [])
        self.assertEqual(primary['task_groups'], [])
        self.assertNotIn(self.chat._path(primary['id']), old_paths)
        for _ in range(3):
            self.assertEqual(self.chat.primary_room()['id'], primary['id'])
        restarted = ChatStore(self.store)
        self.assertEqual(restarted.primary_room()['id'], primary['id'])
        self.assertEqual(len(list(self.chat.root.glob('*.json'))), len(old_paths) + 1)
        for path, before in old_paths.items():
            self.assertEqual(path.read_bytes(), before)
        index = json.loads((self.chat.root.parent / 'primary.json').read_text())
        self.assertEqual(index['room_id'], primary['id'])

    def test_primary_creation_recovers_index_write_interruption_without_duplicate(self):
        import federation.chat as chat_module
        original_write = chat_module._write_json
        def fail_index(path, value):
            if path.name == 'primary.json':
                raise OSError('interrupted index write')
            return original_write(path, value)
        with patch('federation.chat._write_json', side_effect=fail_index):
            with self.assertRaises(OSError):
                self.chat.primary_room()
        orphan = [self.chat.get_room(path.stem) for path in self.chat.root.glob('*.json')
                  if self.chat.get_room(path.stem).get('purpose') == 'primary']
        self.assertEqual(len(orphan), 1)
        before = self.chat._path(orphan[0]['id']).read_bytes()
        recovered = self.chat.primary_room()
        self.assertEqual(recovered['id'], orphan[0]['id'])
        self.assertEqual(self.chat._path(recovered['id']).read_bytes(), before)
        (self.chat.root.parent / 'primary.json').write_text('{invalid index')
        self.assertEqual(self.chat.primary_room()['id'], recovered['id'])
        self.assertEqual(len(list(self.chat.root.glob('*.json'))), 2)

    def test_concurrent_primary_requests_across_stores_create_only_one_room(self):
        self.room.update(status='idle', active_job_id=None)
        self.chat.save_room(self.room)
        instances = [ChatStore(self.store) for _ in range(4)]
        with ThreadPoolExecutor(max_workers=4) as executor:
            identifiers = list(executor.map(lambda chat: chat.primary_room()['id'], instances))
        self.assertEqual(len(set(identifiers)), 1)
        self.assertEqual(len(list(self.chat.root.glob('*.json'))), 2)

    def test_task_groups_are_per_round_with_only_actual_members(self):
        root = self.enable()
        self.assertEqual(self.room['task_groups'][0]['members'], ['central'])
        self.assertEqual(self.room['messages'][1]['event_kind'], 'group_started')
        module = self.task('software', root)
        joined = self.persist()
        self.assertEqual([message['event_kind'] for message in joined], ['member_joined', 'delegation'])
        self.assertEqual(joined[0]['actor_agent_id'], 'central')
        self.assertEqual(joined[0]['recipient_agent_id'], 'software')
        leaf = self.task('software-frontend', module)
        self.persist()
        self.assertEqual(self.room['task_groups'][0]['members'], ['central', 'software', 'software-frontend'])
        for task in (root, module, leaf):
            task.update(status='completed', result='本轮结果', phase='summary' if task is not leaf else 'execute')
        self.persist()
        previous_group = copy.deepcopy(self.room['task_groups'][0])
        previous_messages = copy.deepcopy(self.room['messages'])
        self.round = uuid.uuid4().hex
        self.room['active_job_id'] = self.round
        second_root = self.task('central', instruction='准备内容策划')
        self.persist()
        content = self.task('content', second_root)
        self.persist()
        self.assertEqual(self.room['task_groups'][0], previous_group)
        self.assertEqual(self.room['messages'][:len(previous_messages)], previous_messages)
        self.assertEqual(self.room['task_groups'][1]['members'], ['central', 'content'])
        self.assertEqual(self.room['current_task_group_id'], self.round)
        self.assertIn('software-frontend', self.room['participants'])
        self.assertNotIn('software-frontend', self.room['task_groups'][1]['members'])
        joins = [message for message in self.room['messages'] if message.get('event_kind') == 'member_joined' and message['round_id'] == self.round]
        self.assertEqual(len(joins), 1)
        self.assertEqual(self.persist(), [])
        self.assertEqual(len(self.room['task_groups']), 2)

    def test_previous_timeline_round_does_not_gain_new_task_group_metadata(self):
        root = self.task('central')
        self.room['group_timeline'] = {'schema_version': 1, 'rounds': {
            self.round: {'enabled_at': _now(), 'root_task_id': root['id'], 'event_keys': []}}}
        root['status'] = 'running'
        self.persist()
        self.assertNotIn('task_groups', self.room)
        self.assertFalse(any(message.get('event_kind') in {'group_started', 'member_joined'} for message in self.room['messages']))

    def test_old_rounds_do_not_backfill_or_rewrite_history(self):
        root = self.task('central')
        root.update(status='completed', phase='execute', result='旧的中央回答')
        child = self.task('software', root)
        child.update(status='completed', phase='summary', result='旧的模块回答')
        self.chat.save_room(self.room)
        before = self.chat._path(self.room['id']).read_bytes()
        self.assertEqual(self.persist(), [])
        self.assertNotIn('group_timeline', self.room)
        self.assertEqual(self.chat._path(self.room['id']).read_bytes(), before)

    def test_atomic_save_failure_rolls_back_messages_and_keys_then_retries_once(self):
        root = self.enable()
        child = self.task('software', root)
        before_messages = copy.deepcopy(self.room['messages'])
        before_timeline = copy.deepcopy(self.room['group_timeline'])
        before_groups = copy.deepcopy(self.room['task_groups'])
        before_file = self.chat._path(self.room['id']).read_bytes()
        with patch.object(self.chat, 'save_room', side_effect=OSError('disk failed')):
            with self.assertRaises(OSError):
                self.persist()
        self.assertEqual(self.room['messages'], before_messages)
        self.assertEqual(self.room['group_timeline'], before_timeline)
        self.assertEqual(self.room['task_groups'], before_groups)
        self.assertEqual(self.chat._path(self.room['id']).read_bytes(), before_file)
        added = self.persist()
        self.assertEqual([message['event_kind'] for message in added], ['member_joined', 'delegation'])
        self.assertEqual(added[0]['delegation_task_id'], child['id'])
        self.assertEqual(self.persist(), [])

    def test_empty_event_persist_saves_task_changes_and_restart_does_not_replay(self):
        root = self.enable()
        root.update(status='running', phase='plan')
        self.persist()
        root['error'] = '计划校验失败，准备重试'
        self.assertEqual(self.persist(), [])
        self.assertEqual(self.chat.get_room(self.room['id'])['delegations'][0]['error'], root['error'])
        child = self.task('software', root)
        self.persist()
        child.update(status='completed', phase='execute', result='成员已返回')
        root.update(status='completed', phase='summary', result='主Agent结果')
        self.persist()
        self.room.update(status='idle', active_job_id=None)
        self.chat.save_room(self.room)
        before_file = self.chat._path(self.room['id']).read_bytes()
        restarted = ChatStore(self.store)
        loaded = restarted.get_room(self.room['id'])
        self.assertEqual(sync_group_timeline(restarted, loaded, self.round), [])
        self.assertEqual(self.chat._path(self.room['id']).read_bytes(), before_file)
        self.assertEqual(sum(message.get('event_kind') == 'result' for message in loaded['messages']), 1)

    def test_host_events_do_not_evict_real_conversation_context(self):
        self.chat.append_message(self.room, 'assistant', '已有真实回答', 'central')
        for index in range(HISTORY_MESSAGE_LIMIT + 5):
            message = self.chat.append_message(self.room, 'system', '宿主状态 ' + str(index))
            message['event_origin'] = 'host'
        history = json.loads(self.chat._history(self.room))
        self.assertEqual([item['content'] for item in history], ['请让前端和后端共同给出实现方案', '已有真实回答'])

    def test_long_assignment_and_receipts_fit_limits_with_honest_omission(self):
        root = self.enable()
        child = self.task('software', root, instruction='任务' * 3000)
        dispatch = next(message for message in self.persist() if message['event_kind'] == 'delegation')
        self.assertLessEqual(len(dispatch['content']), 6000)
        self.assertIn('完整内容保留在任务详情中', dispatch['content'])
        child.update(status='completed', phase='execute', result='答' * 60000,
                     skill_reads=[{'path': 'p' * 1500, 'sha256': 'a' * 64} for _ in range(200)])
        reply = self.persist()[0]
        self.assertEqual(len(reply['content']), 60000)
        self.assertLessEqual(len(reply['skill_reads']), RECEIPT_ITEM_LIMIT)
        self.assertLessEqual(len(json.dumps({'skill_reads': reply['skill_reads']}, ensure_ascii=False, separators=(',', ':')).encode()), RECEIPT_BYTE_LIMIT)
        self.assertIn('receipt_truncation', reply)
        self.assertEqual(len(child['skill_reads']), 200)
        self.assertIn('任务详情', reply['receipt_notice'])


if __name__ == '__main__':
    unittest.main()
