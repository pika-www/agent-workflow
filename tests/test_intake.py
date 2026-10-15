"""Main conversation stays inert until the host approves a displayed plan."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

from federation.chat import ChatStore
from federation.core import FederationStore, _now
from federation.intake import (
    IntakeError, MAX_MODEL_CHARS, MAX_PROPOSAL_CHARS, MAX_RESEARCH_CHARS,
    add_proposal, approve_proposal, build_intake_prompt, capability_answer,
    classify_intake, classify_clarification_followup, is_learning_revocation,
    requests_research, resolve_research_goal, explicit_learning_request,
    is_project_cancellation, make_proposal, parse_intake_output, supersede_pending, validate_proposal,
    is_skill_capability_question, skill_capability_answer,
    is_teaching_request, teaching_context,
)
from federation.group_timeline import sync_group_timeline
from federation.product_analysis import analysis_only, analysis_goal


PLAN = '# 商城方案\n\n## 目标与范围\n商品浏览。\n## 调研事实与待核实信息\n支付资质待核实。\n## 建议方案\n先做浏览原型。\n## 建议分工\n必要时前端参与。\n## 验收标准\n用户可查看商品。\n## 待确认事项\n请确认平台。'


class IntakeParsingTest(unittest.TestCase):
    def test_product_analysis_never_becomes_a_development_proposal(self):
        question = 'https://cephalon.cloud/aigc 拆一下这个产品，关键功能怎么实现、怎么获客和收费。给我一套最小版本方案，最后生成可下载文档。'
        self.assertEqual(classify_intake(question), 'answer')
        room = {'messages': [{'role': 'user', 'content': question},
                             {'role': 'assistant', 'content': '开发另一个系统并写入知识库'}]}
        for text in ['暂时先不做开始做，先分析一下即可', '先不开发，只分析', '只分析，不做项目', '暂时不做，透彻分析并给文档']:
            self.assertTrue(analysis_only(text))
            self.assertEqual(classify_intake(text, previous_proposal={'id': 'pending'}), 'answer')
            goal = analysis_goal(text, room)
            self.assertIn('https://cephalon.cloud/aigc', goal)
            self.assertNotIn('另一个系统', goal)
        prompt = build_intake_prompt(question, analysis=True)
        self.assertIn('产品深度分析', prompt)
        self.assertNotIn('普通答复控制在400字以内', prompt)
        self.assertIsNone(analysis_goal('今天天气如何', room))
        self.assertIsNone(analysis_goal('分析我的性格', {'analysis_context': {'goal': question}}))
        self.assertFalse(analysis_only('请给我待确认的开发方案，先不执行'))
        self.assertTrue(analysis_only('不要给我待确认方案，先分析'))
        self.assertIsNone(analysis_goal('换个话题，如何下载手机应用', {'analysis_context': {'goal': question}}))
        self.assertNotIn('cephalon.cloud', analysis_goal('另一个产品，先分析盈利', {'analysis_context': {'goal': question}}))
        self.assertIsNone(analysis_goal('@AI 产品思维 Agent 请先用知识库补查单位贡献与收费成本，用两句话说明，只用本库，不联网。', {'analysis_context': {'goal': question}}))
        self.assertIn('cephalon.cloud',analysis_goal('继续分析上一份报告的收费，只用本库，不联网。', {'analysis_context': {'goal': question}}))
        personal_room = {'analysis_context': {'goal': question}, 'messages': [
            {'role':'user','content':question}, {'role':'user','content':'分析我的性格'},
            {'role':'assistant','content':'性格需要结合具体经历判断。'},
            {'role':'user','content':'给我一点建议'}]}
        for followup in ['展开说说', '详细一点', '再分析一下']:
            self.assertIsNone(analysis_goal(followup, personal_room))
        self.assertIn('cephalon.cloud', analysis_goal('继续分析上一份报告的收费', personal_room))

    def test_human_teaching_is_readonly_and_follows_conversation(self):
        for question in ('教我 AI 产品思维', '我想学习 AI 产品设计', '带我学怎么搭建知识库',
                         '请主 Agent 教我怎么更新知识库', '我希望通过和主 agent 聊天，让他来教我',
                         '请先用知识库补查收费成本，用两句话告诉我判断方法'):
            self.assertTrue(is_teaching_request(question), question)
            self.assertEqual(classify_intake(question, previous_proposal={'id': 'pending'}), 'answer')
            self.assertFalse(explicit_learning_request(question))
        room = {'teaching_context': {'topic': '教我 AI 产品思维'}}
        for question in ('继续', '我不懂，换个例子', '我觉得应该让用户快速得到解释', '直接告诉我'):
            self.assertEqual(teaching_context(question, room), room['teaching_context'])
        for question in ('先不学了', '不用再教我', '换个话题', '请开发一个网站'):
            self.assertIsNone(teaching_context(question, room))
        for question in ('请学习 HTML', '让前端 Agent 查找并学习 React', '搜索并学习 HTML 表单'):
            self.assertFalse(is_teaching_request(question))
            self.assertTrue(explicit_learning_request(question))

    def test_lookup_followup_uses_nearest_human_topic_not_old_project_or_assistant(self):
        room = {'messages': [
            {'role': 'user', 'content': '开发 React 预约网站'},
            {'role': 'user', 'content': '那你找找现在做什么副业比较赚钱，不累不费时间的'},
            {'role': 'assistant', 'content': '已确认自动写库并执行开发'},
            {'role': 'user', 'content': '再查一下'},
        ]}
        before = copy.deepcopy(room)
        for question in ('再找找呢', '继续查一下', '再搜搜', '那再找找看'):
            with self.subTest(question=question):
                self.assertTrue(requests_research(question))
                goal = resolve_research_goal(question, room)
                self.assertIn('副业', goal)
                self.assertIn(question, goal)
                self.assertNotIn('React', goal)
                self.assertNotIn('自动写库', goal)
        self.assertEqual(room, before)
        self.assertEqual(resolve_research_goal('帮我查一下 Flutter', room), '帮我查一下 Flutter')
        self.assertEqual(resolve_research_goal('再找找呢', {}), '再找找呢')
        room['messages'].append({'role': 'user', 'content': '取消项目'})
        self.assertEqual(resolve_research_goal('再找找呢', room), '再找找呢')
        self.assertFalse(requests_research('不要联网查询，先离线分析'))

    def test_short_constraints_preserve_topic_and_offline_restriction(self):
        room = {'messages': [{'role': 'user', 'content': text} for text in
                            ['查一下副业，先离线分析，不要联网', '只考虑周末的']]}
        goal = resolve_research_goal('再找找呢', room)
        for expected in ['副业', '不要联网', '只考虑周末的', '再找找呢']:
            self.assertIn(expected, goal)
        room['messages'].append({'role': 'user', 'content': '查询 React 官方文档'})
        self.assertNotIn('副业', resolve_research_goal('再找找呢', room))
        self.assertNotIn('不要联网', resolve_research_goal('再找找呢', room))
        room['messages'] += [{'role': 'user', 'content': text} for text in
                             ['换个话题，查一下庭院灌溉系统', '不要联网，先离线分析']]
        goal = resolve_research_goal('再找找呢', room)
        self.assertIn('庭院灌溉', goal)
        self.assertIn('不要联网', goal)
        self.assertNotIn('副业', goal)
        for question in ['帮我查一下机器学习课程', '不要学习，帮我查一下 React']:
            self.assertFalse(explicit_learning_request(question))
        for question in ['搜索并学习 HTML 表单', '让前端 Agent 查找并学习 React', '请学习 HTML']:
            self.assertTrue(explicit_learning_request(question))

    def test_clarification_followups_require_actual_project_constraints(self):
        context = {'goal': '开发预约网站', 'content': '请说明目标用户、预算和平台。'}
        before = copy.deepcopy(context)
        for question in ('预算5000，平台用微信小程序', 'React', '目标用户是单店顾客', '面向大学生',
                         '大学生', '5000', '两周', '工期两周', '技术栈用 Vue', '功能包括服务列表和提交预约'):
            with self.subTest(question=question):
                self.assertTrue(classify_clarification_followup(question, context))
        for question in ('React 是什么？', '为什么选择 React', '这个预算是多少', '确认', '今天天气很好',
                         '先不要执行', '不要联网学习了，只讨论方案', '你好',
                         '换个话题，我想做一个新的短片项目，预算5000元。',
                         '另外，我想做一个电商网站，面向企业客户。'):
            with self.subTest(question=question):
                self.assertFalse(classify_clarification_followup(question, context))
        self.assertFalse(classify_clarification_followup('5000', {'goal': '开发预约网站'}))
        self.assertFalse(classify_clarification_followup('React', None))
        self.assertFalse(classify_clarification_followup('React', {'goal': '网站', 'status': 'superseded'}))
        self.assertEqual(context, before)

    def test_permission_withdrawals_distinguish_learning_from_whole_project(self):
        pending = {'id': uuid.uuid4().hex, 'status': 'awaiting_confirmation'}
        for question in ('不要联网学习了，只讨论方案', '先不联网学习', '取消学习', '关闭自动学习',
                         '不要再更新知识库', '只做方案', '不学习了'):
            with self.subTest(question=question):
                self.assertTrue(is_learning_revocation(question))
                self.assertFalse(is_project_cancellation(question))
                self.assertEqual(classify_intake(question, previous_proposal=pending), 'revision')
        for question in ('先不要执行', '先别执行', '请先别执行这个方案', '暂时不做', '暂停执行', '取消项目', '请停止这个任务', '取消'):
            with self.subTest(question=question):
                self.assertTrue(is_project_cancellation(question))
                self.assertEqual(classify_intake(question, previous_proposal=pending), 'answer')
        for question in ('为什么不要联网学习？', '不是不要联网学习', '不要取消学习'):
            self.assertFalse(is_learning_revocation(question))
        for question in ('为什么取消项目？', '不要取消项目', '取消方案里的支付功能', '请解释如何暂停执行'):
            self.assertFalse(is_project_cancellation(question))

    def test_default_questions_and_capabilities_do_not_plan(self):
        for question in ('你好', 'Vue 和 React 有什么区别？', '如何搭建知识库？', '我想了解如何开发网站',
                         '帮我解释为什么要增加后端', '确认', '按这个做', '取消', '停止执行'):
            with self.subTest(question=question):
                self.assertEqual(classify_intake(question), 'answer')
        for question in ('现在我可以做什么？', '你能帮我做什么？', '可以直接接入电脑应用吗？'):
            self.assertEqual(classify_intake(question), 'capability')
        self.assertIn('2 位', capability_answer([{'id': 'central'}, {'id': 'software'}, {'id': 'software-frontend'}]))
        self.assertIn('不代表已经接入', capability_answer())

    def test_skill_capability_queries_are_not_execution_requests(self):
        for question in ['我的简历里有哪些开发技能？', '我有哪些技能？', '我会哪些技能', '我的专业技能有哪些']:
            self.assertFalse(is_skill_capability_question(question), question)
            self.assertEqual(classify_intake(question), 'answer', question)
        for question in ('你可以调用skill 的进程吗？', '你能读取 SKILL.md 吗？',
                         '当前接入了哪些 Skill？', '你可以运行技能脚本吗？'):
            self.assertTrue(is_skill_capability_question(question), question)
            self.assertEqual(classify_intake(question), 'capability')
        for question in ('请用 $documents 生成报告', '请使用技能创建一份方案',
                         '请调用 Skill 脚本处理文件', '这个进程占用了多少内存？',
                         '请依据 $pdf Skill 说明核验流程，不能把规范读取说成执行了渲染。'):
            self.assertFalse(is_skill_capability_question(question), question)
        answer = skill_capability_answer([
            {'id': 'documents', 'display_name': '文档编辑', 'status': 'ready', 'execution_status': 'reference_only'},
            {'id': 'broken', 'status': 'conflict', 'execution_status': 'reference_only'},
        ])
        self.assertIn('1 份', answer)
        self.assertIn('文档编辑', answer)
        self.assertIn('未预读', answer)
        self.assertIn('执行适配器尚未接入', answer)
        self.assertNotIn('broken', answer)

    def test_projects_and_real_constraint_changes_plan_but_discussion_does_not(self):
        for question in ('帮我开发一个商城网站', '我要做一个微信小程序', '请创建知识库', '帮我拉群做项目',
                         '我需要一个商城系统', '帮我写一部短剧剧本', '请策划品牌营销方案'):
            self.assertEqual(classify_intake(question), 'proposal')
        pending = {'id': uuid.uuid4().hex, 'status': 'awaiting_confirmation'}
        room = {'proposals': [pending], 'active_proposal_id': pending['id']}
        for question in ('改成 Vue', '预算5000元', '工期两周', '技术栈用React', '平台改为微信小程序', '需要支持离线'):
            self.assertEqual(classify_intake(question, room), 'revision')
        for question in ('为什么选择 React？', '为什么增加后端？', '增加后端有什么好处？', '是否需要增加后端？',
                         '预算是多少？', '确认', '同意方案'):
            self.assertEqual(classify_intake(question, room), 'answer')
        self.assertEqual(classify_intake('预算5000', previous_proposal=pending), 'revision')

    def test_plain_answers_envelopes_and_complete_markdown(self):
        self.assertEqual(parse_intake_output('可以，先从需求范围开始。'), {'type': 'answer', 'content': '可以，先从需求范围开始。'})
        self.assertEqual(parse_intake_output('{"type":"answer","content":"请问目标用户是谁？"}', 'proposal')['type'], 'answer')
        raw = json.dumps({'type': 'proposal', 'title': '商城方案', 'content': PLAN}, ensure_ascii=False)
        self.assertEqual(parse_intake_output('```json\n' + raw + '\n```', 'proposal')['content'], PLAN)
        self.assertEqual(parse_intake_output(PLAN, 'proposal')['title'], '商城方案')
        self.assertEqual(parse_intake_output('```markdown\n' + PLAN + '\n```', 'proposal')['content'], PLAN)
        self.assertEqual(parse_intake_output('请先说明你希望调查的行业。', 'proposal'),
                         {'type': 'answer', 'content': '请先说明你希望调查的行业。'})
        self.assertEqual(parse_intake_output('{"examples":[1,2]}')['type'], 'answer')

    def test_model_cannot_assign_approve_or_change_stored_execution_options(self):
        invalid = [
            {'type': 'delegate', 'tasks': []}, {'action': 'delegate', 'tasks': []},
            {'type': 'proposal', 'title': '方案', 'content': PLAN, 'status': 'confirmed'},
            {'type': 'proposal', 'title': '方案', 'content': PLAN, 'execution_options': {'learning': True}},
            {'type': 'answer', 'content': '确认', 'confirmed_job_id': uuid.uuid4().hex},
        ]
        for output in invalid:
            with self.subTest(output=output), self.assertRaises(IntakeError):
                parse_intake_output(json.dumps(output), 'proposal')
        for raw, kind in [('{"type":"answer","type":"proposal","content":"x"}', 'proposal'),
                          ('{"type":', 'answer'), ('{"type":"proposal","title":"x","content":"y"}', 'answer'),
                          ('# 标题\n只有目标', 'proposal'), ('---\ntitle: x\n---\n正文', 'proposal'),
                          ('x' * (MAX_MODEL_CHARS + 1), 'answer'), ('a\0b', 'answer')]:
            with self.subTest(kind=kind, raw=raw[:40]), self.assertRaises(IntakeError):
                parse_intake_output(raw, kind)

    def test_bracket_leading_markdown_is_an_inert_answer(self):
        samples = [
            '[下载测试文档](/api/chat/rooms/' + 'a' * 32 + '/files/' + 'b' * 32 + ')\n\n文件大小约 3 KB。',
            '[文档](https://example.com/docs)',
            '[2026 年说明](https://example.com/guide)',
            '[说明] 这是普通回答。',
            '[文档][guide]\n\n[guide]: https://example.com/guide',
            '[下载测试文档]\n(/api/chat/rooms/' + 'a' * 32 + '/files/' + 'b' * 32 + ')',
        ]
        for raw in samples:
            for kind in ('answer', 'proposal'):
                with self.subTest(raw=raw, kind=kind):
                    self.assertEqual(parse_intake_output(raw, kind), {'type': 'answer', 'content': raw})
        # JSON arrays are content, never an actionable reply envelope.
        array = '[{"action":"delegate","tasks":[]}]'
        self.assertEqual(parse_intake_output(array), {'type': 'answer', 'content': array})
        with self.assertRaises(IntakeError):
            parse_intake_output(array, 'proposal')
        with self.assertRaises(IntakeError):
            parse_intake_output('[{"type":"answer","type":"proposal"}]')

    def test_prompt_bounds_research_as_valid_json_and_preserves_latest_question(self):
        question = '帮我开发网站，预算5000。'
        report = {'status': 'completed', 'note': '资料' * 1000, 'sources': [
            {'url': 'https://example.com/' + 'a' * 2000, 'title': '标题' * 1000,
             'excerpt': '来源内容' * 5000, 'sha256': 'a' * 64, 'excerpt_sha256': 'b' * 64,
             'truncated': False, 'fetched_at': _now()} for _ in range(8)],
            'errors': [{'url': 'u' * 3000, 'error': '失败' * 4000}] * 8}
        original = copy.deepcopy(report)
        prompt = build_intake_prompt(question, [{'id': 'central', 'description': None}],
                                     history=[{'role': 'user', 'content': '旧问题'}],
                                     research_context=report, kind='proposal')
        history = json.loads(prompt.split('<conversation_history>\n')[1].split('\n</conversation_history>')[0])
        self.assertEqual(history, [{'role': 'user', 'content': question}])
        evidence = prompt.split('<read_only_research>')[1].split('</read_only_research>')[0]
        self.assertLessEqual(len(evidence), MAX_RESEARCH_CHARS)
        saved = json.loads(evidence)
        self.assertEqual(len(saved['sources']), 2)
        for source in saved['sources']:
            self.assertTrue(source['truncated'])
            self.assertEqual(source['excerpt_sha256'], hashlib.sha256(source['excerpt'].encode()).hexdigest())
        self.assertEqual(report, original)
        self.assertIn('1200字', prompt)
        self.assertIn('正常方案直接返回以“# 项目方案标题”开头', prompt)
        self.assertIn('不要输出JSON、YAML、代码围栏', prompt)
        self.assertNotIn('建议返回严格JSON', prompt)
        self.assertIn('最多3个', prompt)
        self.assertIn('常规表单字段、管理员设置、技术搭配和部署环境未知时', prompt)
        self.assertIn('不能重复询问用户已经说明', prompt)
        self.assertIn('实际URL', prompt)
        self.assertIn('不得生成[Wiki:/index.md]、run_inputs等伪造溯源标记', prompt)
        self.assertIn('不能将其视为结构化方案确认', build_intake_prompt('确认'))


class IntakeStorageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.store = FederationStore(self.root / 'data', project_root=self.root / 'project')
        self.store.init()
        self.chat = ChatStore(self.store)
        self.room = self.chat.primary_room()

    def tearDown(self):
        self.tmp.cleanup()

    def draft(self, previous=None, options=None):
        message = {'id': uuid.uuid4().hex, 'role': 'assistant', 'agent_id': 'central', 'agent_name': '主 Agent',
                   'content': PLAN, 'status': 'completed', 'created_at': _now(), 'phase': 'proposal'}
        proposal = make_proposal('开发商城网站', PLAN, '商城方案', message['id'], previous=previous,
                                 execution_options=options)
        self.room['messages'].append(message)
        add_proposal(self.room, proposal)
        return proposal

    def test_reply_and_proposal_are_one_commit_and_restart_keeps_pending(self):
        legacy = self.chat.create_room('direct', ['software'])
        self.chat.append_message(legacy, 'user', '保留旧记录')
        old_path = self.chat.root / (legacy['id'] + '.json')
        old_bytes = old_path.read_bytes()
        path = self.chat.root / (self.room['id'] + '.json')
        before = path.read_bytes()
        proposal = self.draft()
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.room['task_groups'], [])
        with patch('federation.chat._write_json', wraps=__import__('federation.core', fromlist=['_write_json'])._write_json) as writer:
            self.chat.save_room(self.room)
            self.assertEqual(writer.call_count, 1)
        restored = ChatStore(self.store).primary_room()
        self.assertEqual(restored['active_proposal_id'], proposal['id'])
        self.assertEqual(restored['proposals'][0]['status'], 'awaiting_confirmation')
        self.assertEqual(old_path.read_bytes(), old_bytes)

    def test_only_displayed_content_can_be_attached_and_invalid_save_preserves_file(self):
        before = (self.chat.root / (self.room['id'] + '.json')).read_bytes()
        unknown = make_proposal('目标', PLAN, '方案', uuid.uuid4().hex)
        with self.assertRaises(IntakeError):
            add_proposal(self.room, unknown)
        proposal = self.draft()
        for mutate in (lambda room: room['messages'][0].update(content='不同的未展示方案'),
                       lambda room: room['messages'][0].update(status='failed'),
                       lambda room: room.update(active_proposal_id=uuid.uuid4().hex),
                       lambda room: room['proposals'].append(copy.deepcopy(proposal)),
                       lambda room: room['proposals'][0].pop('created_at')):
            bad = copy.deepcopy(self.room)
            mutate(bad)
            with self.assertRaises(ValueError):
                self.chat.save_room(bad)
            self.assertEqual((self.chat.root / (self.room['id'] + '.json')).read_bytes(), before)

    def test_revision_invalidates_old_button_and_preserves_history(self):
        old = self.draft()
        self.chat.save_room(self.room)
        old_message = copy.deepcopy(self.room['messages'][0])
        previous = supersede_pending(self.room)
        self.assertEqual(previous, old)
        self.assertIsNone(self.room['active_proposal_id'])
        self.assertEqual(self.room['proposals'][0]['status'], 'superseded')
        with self.assertRaises(IntakeError):
            approve_proposal(self.room, old['id'], uuid.uuid4().hex)
        new = self.draft(previous=previous)
        self.assertEqual(new['revision'], 2)
        self.assertEqual(new['supersedes_proposal_id'], old['id'])
        self.assertNotEqual(new['id'], old['id'])
        self.chat.save_room(self.room)
        self.assertEqual(self.room['messages'][0], old_message)

    def test_structured_approval_is_idempotent_and_keeps_saved_options(self):
        options = {'learning': True, 'urls': ['https://example.com/docs'], 'max_pages': 2}
        proposal = self.draft(options=options)
        options['urls'].append('https://not-in-approved-plan.example/')
        self.assertEqual(self.room['proposals'][0]['execution_options']['urls'], ['https://example.com/docs'])
        job_id = uuid.uuid4().hex
        approved = approve_proposal(self.room, proposal['id'], job_id)
        self.assertEqual(approved['status'], 'confirmed')
        self.assertEqual(approved['confirmed_job_id'], job_id)
        self.assertEqual(approve_proposal(self.room, proposal['id'], job_id), approved)
        approved['execution_options']['urls'].clear()
        self.assertEqual(self.room['proposals'][0]['execution_options']['urls'], ['https://example.com/docs'])
        with self.assertRaises(IntakeError):
            approve_proposal(self.room, proposal['id'], uuid.uuid4().hex)
        self.chat.save_room(self.room)
        self.assertEqual(self.chat.get_room(self.room['id'])['proposals'][0]['confirmed_job_id'], job_id)

    def test_bounded_fields_and_options_reject_malformed_metadata(self):
        proposal = self.draft()
        for updates in ({'created_at': None}, {'updated_at': 'yesterday'}, {'revision': True},
                        {'revision': 0}, {'status': 'executing'}, {'confirmed_job_id': uuid.uuid4().hex},
                        {'content': 'x' * (MAX_PROPOSAL_CHARS + 1)},
                        {'execution_options': {'learning': False, 'urls': ['https://example.com']}},
                        {'execution_options': {'learning': True, 'max_pages': 6}},
                        {'execution_options': {'learning': True, 'tool': 'shell'}}):
            with self.subTest(updates=tuple(updates)), self.assertRaises(IntakeError):
                validate_proposal({**proposal, **updates})

    def test_task_group_links_only_a_matching_confirmed_plan(self):
        proposal = self.draft()
        round_id = uuid.uuid4().hex
        approve_proposal(self.room, proposal['id'], round_id)
        self.room.update(status='running', active_job_id=round_id)
        stamp = _now()
        self.room['delegations'] = [{'id': uuid.uuid4().hex, 'round_id': round_id, 'parent_task_id': None,
                                    'agent_id': 'central', 'agent_name': '主 Agent', 'depth': 0,
                                    'title': '执行方案', 'instruction': '开发商城', 'status': 'queued', 'phase': 'plan',
                                    'result': '', 'created_at': stamp, 'updated_at': stamp}]
        sync_group_timeline(self.chat, self.room, round_id)
        self.assertEqual(self.room['task_groups'][0]['proposal_id'], proposal['id'])
        malformed = copy.deepcopy(self.room)
        malformed['task_groups'][0]['proposal_id'] = uuid.uuid4().hex
        with self.assertRaises(ValueError):
            self.chat.save_room(malformed)


if __name__ == '__main__':
    unittest.main()
