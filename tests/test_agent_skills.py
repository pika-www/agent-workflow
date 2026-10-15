"""Skill import boundary, deduplication, preservation and agent-scope checks."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from federation.agent_skills import (inventory_local_skills, list_skills, skill_root,
                                     sync_local_skills, validate_skill)
from federation.core import FederationStore
from federation.skill_assignments import ALL_ROLES, ASSIGNMENTS, KEYWORDS


class AgentSkillsTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.store = FederationStore(self.root / 'data', project_root=self.root / 'project')
        self.store.init()
        self.source = self.root / 'sources'
        self.source.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def source_skill(self, name='java-server-framework-development', root=None, body='规范正文', display='Java 服务端框架开发'):
        folder = (root or self.source) / name.lower()
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'SKILL.md').write_text('---\nname: ' + name + '\ndescription: |\n  Java/Spring 接口开发与事务规范。\n  保留测试和迁移证据。\n---\n\n# 技能\n' + body + '\n')
        (folder / 'agents').mkdir(exist_ok=True)
        (folder / 'agents/openai.yaml').write_text('interface:\n  display_name: "' + display + '"\n')
        return folder

    def test_inventory_deduplicates_sources_and_retains_differences_and_machine_name(self):
        installed = self.source_skill('Spreadsheets', self.root / '.codex/skills', display='电子表格处理')
        delivery = self.source_skill('Spreadsheets', self.root / 'Documents/projects/skill', body='另一个副本', display='交付副本')
        report = inventory_local_skills([installed.parent, delivery.parent])
        self.assertEqual(report['scanned_skill_files'], 2)
        self.assertEqual(report['unique_skills'], 1)
        item = report['catalog'][0]
        self.assertEqual(item['id'], 'spreadsheets')
        self.assertEqual(item['name'], 'Spreadsheets')
        self.assertEqual(item['display_name'], '电子表格处理')
        self.assertEqual(item['source_path'], str(installed))
        self.assertEqual(item['source_kind'], 'local_installed')
        self.assertIn('事务规范。\n保留', item['description'])
        self.assertFalse(item['source_duplicates'][0]['same_content'])
        self.assertIn('SKILL.md', item['source_duplicates'][0]['different_files'])
        self.assertEqual(len(report['source_hashes']), 4)

    def test_plugin_cache_prefers_latest_numeric_version_without_loaded_claim(self):
        old = self.source_skill('documents', self.root / '.codex/plugins/cache/example/documents/2.0.0/skills', body='old')
        latest = self.source_skill('documents', self.root / '.codex/plugins/cache/example/documents/10.0.0/skills', body='new')
        report = inventory_local_skills([self.root / '.codex/plugins/cache'])
        item = report['catalog'][0]
        self.assertEqual(item['source_path'], str(latest))
        self.assertEqual(item['upstream_version'], '10.0.0')
        self.assertIn('不等于当前已加载', item['selection_reason'])
        self.assertEqual(item['source_duplicates'][0]['source_path'], str(old))

    def test_complete_resources_are_copied_without_execution_and_sources_unchanged(self):
        source = self.source_skill()
        (source / 'scripts').mkdir()
        (source / 'scripts/helper.py').write_text('raise RuntimeError("never execute this imported script")\n')
        (source / 'LICENSE').write_text('Fixture license\n')
        (source / 'assets').mkdir()
        (source / 'assets/reference.bin').write_bytes(b'\x00\xff\x01')
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()}
        report = sync_local_skills(self.store, [self.source])
        self.assertEqual(report['status_counts']['imported'], 2)
        manifest = validate_skill(self.store, 'software-backend', source.name)
        target = skill_root(self.store, 'software-backend', source.name)
        self.assertEqual(set(manifest['files']), {'SKILL.md', 'agents/openai.yaml', 'scripts/helper.py', 'LICENSE', 'assets/reference.bin'})
        self.assertEqual((target / 'assets/reference.bin').read_bytes(), b'\x00\xff\x01')
        self.assertEqual((target / 'scripts/helper.py').stat().st_mode & 0o777, 0o600)
        self.assertEqual(manifest['execution_status'], 'reference_only')
        self.assertEqual(manifest['dependency_status'], 'not_connected')
        self.assertTrue(any('脚本' in dependency for dependency in manifest['dependencies']))
        self.assertEqual(list_skills(self.store, 'content-design'), [])
        with self.assertRaises(ValueError):
            validate_skill(self.store, 'content-design', source.name)
        after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_idempotence_source_update_archive_and_local_conflict_preservation(self):
        source = self.source_skill()
        first = sync_local_skills(self.store, [self.source])
        before = validate_skill(self.store, 'software-backend', source.name)
        same = sync_local_skills(self.store, [self.source])
        self.assertEqual(same['status_counts']['unchanged'], 2)
        self.assertEqual(before, validate_skill(self.store, 'software-backend', source.name))
        original = (source / 'SKILL.md').read_bytes()
        (source / 'SKILL.md').write_bytes(original + b'\nUpdated source\n')
        update = sync_local_skills(self.store, [self.source])
        self.assertEqual(update['status_counts']['updated'], 2)
        self.assertEqual(validate_skill(self.store, 'software-backend', source.name)['revision'], 2)
        archive = next(item['archive_path'] for item in update['results'] if item['space_id'] == 'software-backend')
        self.assertEqual((Path(archive) / 'SKILL.md').read_bytes(), original)
        target = skill_root(self.store, 'software-backend', source.name)
        (target / 'SKILL.md').write_text('用户本地修改\n')
        conflict = sync_local_skills(self.store, [self.source])
        self.assertEqual(conflict['status_counts']['conflict'], 1)
        self.assertEqual((target / 'SKILL.md').read_text(), '用户本地修改\n')
        item = list_skills(self.store, 'software-backend')[0]
        self.assertEqual(item['status'], 'conflict')
        self.assertIn('接口开发', item['keywords'])
        self.assertEqual(item['display_name'], 'Java 服务端框架开发')

    def test_manual_extra_files_empty_directories_and_missing_target_are_not_overwritten(self):
        source = self.source_skill()
        sync_local_skills(self.store, [self.source])
        target = skill_root(self.store, 'software-backend', source.name)
        (target / 'manual').mkdir()
        with self.assertRaisesRegex(ValueError, '人工修改'):
            validate_skill(self.store, 'software-backend', source.name)
        (target / 'manual').rmdir()
        (target / 'notes.md').write_text('用户笔记')
        self.assertEqual(sync_local_skills(self.store, [self.source])['status_counts']['conflict'], 1)
        self.assertEqual((target / 'notes.md').read_text(), '用户笔记')
        shutil.rmtree(target)
        item = list_skills(self.store, 'software-backend')[0]
        self.assertEqual(item['status'], 'conflict')
        self.assertIn('接口开发', item['keywords'])
        self.assertEqual(sync_local_skills(self.store, [self.source])['status_counts']['conflict'], 1)
        self.assertFalse(target.exists())

    def test_source_symlinks_are_rejected_and_secrets_and_caches_excluded(self):
        source = self.source_skill()
        outside = self.root / 'outside.txt'
        outside.write_text('private fixture')
        (source / 'escape.txt').symlink_to(outside)
        report = inventory_local_skills([self.source])
        self.assertEqual(report['unique_skills'], 0)
        self.assertIn('符号链接', report['source_errors'][0]['error'])
        (source / 'escape.txt').unlink()
        for filename in ('.env', 'credentials.json', 'private.key', 'cookies.json', '.env.production'):
            (source / filename).write_text('private fixture')
        (source / '__pycache__').mkdir()
        (source / '__pycache__/compiled.pyc').write_bytes(b'cache')
        (source / '.env.example').write_text('EXAMPLE_TOKEN=\n')
        report = sync_local_skills(self.store, [self.source])
        item = report['catalog'][0]
        self.assertIn('.env', item['excluded_files'])
        self.assertIn('__pycache__/', item['excluded_files'])
        self.assertIn('.env.example', item['files'])
        target = skill_root(self.store, 'software-backend', source.name)
        self.assertFalse((target / 'credentials.json').exists())
        self.assertNotIn(str(outside), report['source_hashes'])

    def test_imported_symlink_manifest_tampering_and_traversal_are_rejected(self):
        source = self.source_skill()
        sync_local_skills(self.store, [self.source])
        target = skill_root(self.store, 'software-backend', source.name)
        original = (target / 'SKILL.md').read_bytes()
        (target / 'SKILL.md').unlink()
        (target / 'SKILL.md').symlink_to(source / 'SKILL.md')
        with self.assertRaises(ValueError):
            validate_skill(self.store, 'software-backend', source.name)
        (target / 'SKILL.md').unlink()
        (target / 'SKILL.md').write_bytes(original)
        manifest = target / 'manifest.json'
        manifest.write_text(manifest.read_text().replace('reference_only', 'unrestricted'))
        with self.assertRaisesRegex(ValueError, '修改'):
            validate_skill(self.store, 'software-backend', source.name)
        with self.assertRaises(ValueError):
            validate_skill(self.store, 'software-backend', '../software')

    def test_oversized_skill_source_rejected_without_partial_import(self):
        self.source_skill(body='X' * 300)
        with patch('federation.agent_skills.MAX_SKILL_BYTES', 200):
            report = sync_local_skills(self.store, [self.source])
        self.assertEqual(report['assignment_count'], 0)
        self.assertEqual(len(report['source_errors']), 1)
        self.assertEqual(list_skills(self.store, 'software-backend'), [])

    def test_unknown_skills_remain_unassigned_and_all_known_roles_have_deliberate_mapping(self):
        self.source_skill('my-unknown-skill')
        report = sync_local_skills(self.store, [self.source])
        self.assertEqual(report['unassigned'], ['my-unknown-skill'])
        self.assertEqual(report['assignment_count'], 0)
        self.assertEqual(set(agent for agents in ASSIGNMENTS.values() for agent in agents), set(ALL_ROLES))
        self.assertIn('software-uiux', ASSIGNMENTS['figma-generate-library'])
        self.assertNotIn('software-backend', ASSIGNMENTS['figma-generate-library'])
        self.assertIn('business-finance', ASSIGNMENTS['artifact-template-financial-budget'])
        self.assertIn('content-postproduction', ASSIGNMENTS['ai-video-directing'])
        self.assertEqual(set(ASSIGNMENTS), set(KEYWORDS))
        self.assertNotIn('方案', KEYWORDS['documents'])
        self.assertNotIn('Figma', KEYWORDS['figma-generate-library'])


if __name__ == '__main__':
    unittest.main()
