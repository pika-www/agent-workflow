"""Local data lifecycle and real filesystem isolation for all-Agent templates."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from federation.core import FederationStore
from federation.agent_templates import (all_templates, initialize_standards, refresh_agent_library,
                                       validate_any_template, validate_standard)
from federation.template_context import prepare_template_context, select_frameworks


class AgentTemplateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = FederationStore(base=Path(self.temp.name) / 'data')
        self.store.init()

    def tearDown(self):
        self.temp.cleanup()

    def test_every_agent_has_distinct_specialist_and_default_standards(self):
        results = initialize_standards(self.store)
        self.assertFalse(any(x['status'] == 'conflict' for x in results))
        task_files = set()
        for agent in self.store.spaces():
            templates = all_templates(self.store, agent['id'])
            self.assertGreaterEqual(len(templates), 2, agent['id'])
            self.assertEqual(templates[0]['id'], 'agent-standard')
            self.assertTrue(any(x['kind'] == 'specialist' for x in templates))
            task_files.add(tuple(sorted(templates[1]['files'])))
        self.assertGreater(len(task_files), 15, 'Distinct specialties need distinct practical deliverables')

    def test_learning_updates_rules_and_preserves_old_version(self):
        before = refresh_agent_library(self.store, 'software-backend')
        page = self.store._wiki('software-backend') / 'api-standards.md'
        page.write_text('---\ntitle: 接口规范\n---\n# 接口规范\n受控示例：任务契约使用 X-Request-ID。')
        after = refresh_agent_library(self.store, 'software-backend')
        self.assertTrue(all(x['status'] == 'updated' for x in after))
        self.assertEqual(after[0]['revision'], before[0]['revision'] + 1)
        for item in after:
            folder = self.store._home('software-backend') / 'templates' / item['id']
            self.assertIn('X-Request-ID', (folder / 'template/LEARNED_RULES.md').read_text())
            self.assertTrue((self.store.base / item['archive_path'] / 'manifest.json').is_file())
        self.assertTrue(all(x['status'] == 'unchanged' for x in refresh_agent_library(self.store, 'software-backend')))

    def test_preserves_user_modified_standard_and_added_files(self):
        refresh_agent_library(self.store, 'software-testing')
        root = self.store._home('software-testing') / 'templates/agent-standard'
        (root / 'GUIDELINES.md').write_text('user custom policy')
        with self.assertRaisesRegex(ValueError, '人工修改'):
            refresh_agent_library(self.store, 'software-testing')
        self.assertEqual((root / 'GUIDELINES.md').read_text(), 'user custom policy')

    def test_manifest_tampering_and_symlink_are_rejected(self):
        refresh_agent_library(self.store, 'business-finance')
        root = self.store._home('business-finance') / 'templates/agent-standard'
        manifest = root / 'manifest.json'
        manifest.write_text(manifest.read_text() + ' ')
        with self.assertRaisesRegex(ValueError, '版本记录'):
            validate_standard(self.store, 'business-finance')
        refresh_agent_library(self.store, 'commerce-service')
        root = self.store._home('commerce-service') / 'templates/agent-standard'
        (root / 'GUIDELINES.md').unlink()
        (root / 'GUIDELINES.md').symlink_to(manifest)
        with self.assertRaisesRegex(ValueError, '符号链接'):
            validate_standard(self.store, 'commerce-service')

    def test_archive_failure_does_not_move_current_template(self):
        refresh_agent_library(self.store, 'software-backend')
        root = self.store._home('software-backend') / 'templates/agent-standard'
        manifest = (root / 'manifest.json').read_bytes()
        (self.store._wiki('software-backend') / 'new.md').write_text('# 新规范\n受控变化')
        import os
        original = os.replace
        def fail_archive(source, destination):
            if Path(source) == root:
                raise OSError('controlled archive failure')
            return original(source, destination)
        with patch('federation.agent_templates.os.replace', side_effect=fail_archive):
            with self.assertRaisesRegex(OSError, 'archive failure'):
                refresh_agent_library(self.store, 'software-backend')
        self.assertEqual((root / 'manifest.json').read_bytes(), manifest)
        validate_standard(self.store, 'software-backend')

    def test_specialist_selection_copies_actual_files_only_to_own_snapshot(self):
        initialize_standards(self.store)
        original = {str(p):hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in self.store._home('software-backend').rglob('*') if p.is_file()}
        target = self.store.base / 'ask-runs/test/wiki'; target.mkdir(parents=True)
        job = {'space':'software-backend', 'question':'设计 OpenAPI 接口契约', 'template_query':'设计 OpenAPI 接口契约'}
        selected, notice = prepare_template_context(self.store, job, target)
        self.assertEqual(selected[0]['id'], 'agent-standard')
        self.assertEqual(len(selected), 2)
        self.assertTrue(any(p.suffix in {'.yaml','.yml','.json'} for p in target.rglob('*') if p.is_file()))
        self.assertTrue(notice)
        for path, digest in original.items():
            self.assertEqual(hashlib.sha256(Path(path).read_bytes()).hexdigest(), digest)
        self.assertFalse(any('vue' in str(p) or 'react' in str(p) for p in target.rglob('*')))

    def test_explicit_framework_wins_and_exclusion_does_not_revive_history(self):
        self.assertEqual(select_frameworks({'template_query':'改用 Vue 实现', 'template_history':['React 登录页']})[0], ['vue'])
        self.assertEqual(select_frameworks({'template_query':'继续实现该组件', 'template_history':['React 登录页']})[0], ['react'])
        self.assertEqual(select_frameworks({'template_query':'不用 Vue', 'template_history':['Vue 登录页']})[0], [])

    def test_ordinary_dialogue_omits_unrelated_templates_but_explicit_request_reads_them(self):
        refresh_agent_library(self.store, 'central')
        for index, question in enumerate(('收藏了一堆文章都没看，怎么办？', '你的任务模板和检查表是什么？')):
            target = self.store.base / 'ask-runs' / str(index) / 'wiki'
            target.mkdir(parents=True)
            job = {'space': 'central', 'delegation_phase': 'consultation',
                   'current_question': question, 'template_query': question}
            selected, notice = prepare_template_context(self.store, job, target)
            self.assertTrue(job['template_inventory'])
            if index == 0:
                self.assertEqual(selected, [])
                self.assertEqual(notice, '')
                self.assertFalse((target / '_agent_templates').exists())
            else:
                self.assertIn('agent-standard', [item['id'] for item in selected])
                self.assertTrue((target / '_agent_templates/agent-standard/GUIDELINES.md').is_file())

    def test_generic_branch_owns_its_own_inherited_specialist_templates(self):
        branch = self.store.add_branch('性能专项', '性能与容量', 'software-testing')
        refresh_agent_library(self.store, branch['id'])
        templates = all_templates(self.store, branch['id'])
        self.assertGreaterEqual(len(templates), 2)
        for item in templates:
            self.assertEqual(item['space_id'], branch['id'])
            validate_any_template(self.store, branch['id'], item['id'])

    def test_explicit_missing_framework_is_reported_with_generic_context(self):
        refresh_agent_library(self.store, 'software-frontend')
        target = self.store.base / 'ask-runs/missing/wiki'; target.mkdir(parents=True)
        job = {'space': 'software-frontend', 'template_query': '用 Vue 和 React 比较实现'}
        selected, notice = prepare_template_context(self.store, job, target)
        self.assertEqual([x['id'] for x in selected], ['agent-standard'])
        self.assertIn('vue-ts', notice)
        self.assertIn('react-ts', notice)
        self.assertIn('尚未保存', notice)
        self.assertFalse((target / '_agent_templates/frontend-accessible-form').exists())

    def test_framework_mentions_do_not_escape_agent_ownership(self):
        refresh_agent_library(self.store, 'software-backend')
        target = self.store.base / 'ask-runs/backend/wiki'; target.mkdir(parents=True)
        selected, notice = prepare_template_context(self.store,
            {'space': 'software-backend', 'template_query': '给 Vue 前端设计 OpenAPI'}, target)
        self.assertEqual([x['id'] for x in selected], ['agent-standard', 'openapi-service-contract'])
        self.assertNotIn('尚未保存', notice)


if __name__ == '__main__':
    unittest.main()
