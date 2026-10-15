"""Version provenance, freshness and isolation without rewriting knowledge."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from federation.core import FederationStore, _write_json
from federation.knowledge import knowledge_health, page_id, record_learning, source_snapshot

NOW = datetime(2026, 10, 3, tzinfo=timezone.utc)
OLD = '2026-08-01T00:00:00+00:00'
RECENT = '2026-10-01T00:00:00+00:00'


def sha(value):
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


class KnowledgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.store = FederationStore(self.root / 'data', project_root=self.root / 'project')
        self.store.init()
        self.space = 'software-frontend'

    def tearDown(self):
        self.tmp.cleanup()

    def page(self, path='guide.md', body='# Guide\n真实输入整理的说明。\n', space=None):
        file = self.store._safe(self.store._wiki(space or self.space), path)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(body)
        return file

    def web(self, text='source-v1', name='web-a.md', stamp=RECENT, url='https://example.org/docs', space=None, history=None):
        space = space or self.space
        source = self.store._safe(self.store._source(space), name)
        source.write_text('# Captured\n\n' + text)
        record = {'space_id': space, 'filename': name, 'url': url, 'title': 'Docs', 'sha256': sha(text),
                  'inbox_sha256': sha(source.read_bytes()), 'fetched_at': stamp,
                  'versions': history or {sha(text): {'filename': name, 'inbox_sha256': sha(source.read_bytes()), 'first_seen': stamp}}}
        index_file = self.store._safe(self.store.base, 'web-learning/index.json')
        index = json.loads(index_file.read_text()) if index_file.exists() else {}
        index[space + ':' + sha(url)] = record
        _write_json(index_file, index)
        return source, record

    def health_page(self, space=None):
        return knowledge_health(self.store, space or self.space, now=NOW)['pages'][0]

    def test_old_unrecorded_pages_remain_untracked_and_empty_paths_write_nothing(self):
        file = self.page()
        before = file.read_bytes()
        result = record_learning(self.store, self.space, 'empty', paths=[])
        self.assertEqual(result['recorded_count'], 0)
        self.assertFalse((self.store.base / 'metadata/knowledge').exists())
        self.assertEqual(self.health_page()['status'], 'untracked')
        self.assertEqual(self.health_page()['reasons'], ['no_learning_record'])
        self.assertEqual(file.read_bytes(), before)
        navigation = record_learning(self.store, self.space, 'navigation-only', paths=['index.md'])
        self.assertEqual(navigation['status'], 'no_pages')
        self.assertEqual(navigation['skipped_paths'], ['index.md'])
        self.assertFalse((self.store.base / 'metadata/knowledge').exists())
        self.assertEqual(knowledge_health(self.store, 'software-app', now=NOW)['summary']['total'], 0)

    def test_web_source_and_page_stable_ids_content_versions_and_current_receipts(self):
        file = self.page()
        source, _ = self.web(url='HTTPS://Example.org:443/docs?utm_source=test#top')
        initial = source_snapshot(self.store, self.space)[0]
        self.assertEqual(initial['url'], 'https://example.org/docs')
        self.assertEqual(initial['version'], sha('source-v1'))
        self.assertEqual(initial['input_sha256'], sha(source.read_bytes()))
        before = {file: file.read_bytes(), source: source.read_bytes()}
        result = record_learning(self.store, self.space, 'run-a', source_versions=[initial], paths=['guide.md', 'index.md'], now=NOW)
        self.assertEqual(result['recorded_count'], 1)
        self.assertEqual(result['skipped_paths'], ['index.md'])
        page = self.health_page()
        self.assertEqual(page['status'], 'current')
        self.assertEqual(page['page_id'], page_id(self.space, 'guide.md'))
        self.assertEqual(page['evidence'][0]['relation'], 'run_inputs')
        self.assertEqual(page['evidence_scope'], 'run_inputs')
        for path, value in before.items():
            self.assertEqual(path.read_bytes(), value)
        with self.assertRaisesRegex(ValueError, '已经登记'):
            record_learning(self.store, self.space, 'run-a', paths=['guide.md'], now=NOW)

    def test_source_update_deletion_and_local_change_make_page_stale(self):
        self.page()
        file, _ = self.web()
        record_learning(self.store, self.space, 'r1', paths=['guide.md'], now=NOW)
        original_id = source_snapshot(self.store, self.space)[0]['source_id']
        self.web(text='source-v2')
        self.assertEqual(source_snapshot(self.store, self.space)[0]['source_id'], original_id)
        page = self.health_page()
        self.assertEqual(page['status'], 'stale')
        self.assertIn('source_version_changed', page['reasons'])
        file.unlink()
        self.assertEqual(self.health_page()['status'], 'stale')
        self.assertIn('source_missing', self.health_page()['reasons'])
        self.web(text='source-v1')
        file.write_text('Manual source change')
        snapshot = source_snapshot(self.store, self.space)[0]
        self.assertEqual(snapshot['status'], 'conflict')
        self.assertEqual(self.health_page()['status'], 'stale')
        self.assertIn('web_index_hash_conflict', self.health_page()['reasons'])

    def test_page_manual_edit_and_rollback_do_not_inherit_latest_receipt(self):
        file = self.page(body='# First\n')
        self.web()
        first_hash = sha(file.read_bytes())
        record_learning(self.store, self.space, 'r1', paths=['guide.md'], now=NOW)
        file.write_text('# Second\n')
        self.assertEqual(self.health_page()['status'], 'untracked')
        record_learning(self.store, self.space, 'r2', paths=['guide.md'], now=NOW)
        self.assertEqual(self.health_page()['status'], 'current')
        file.write_text('# First\n')
        page = self.health_page()
        self.assertEqual(page['version'], first_hash)
        self.assertEqual(page['status'], 'untracked')
        self.assertIn('page_changed_after_learning', page['reasons'])
        sidecar = json.loads((self.store.base / 'metadata/knowledge' / (self.space + '.json')).read_text())
        self.assertEqual(len(sidecar['pages']['guide.md']), 2)

    def test_learning_older_input_or_source_rollback_preserves_version_difference(self):
        self.page()
        self.web(text='first')
        older_inputs = source_snapshot(self.store, self.space)
        self.web(text='second')
        record_learning(self.store, self.space, 'r-old-input', source_versions=older_inputs, paths=['guide.md'], now=NOW)
        self.assertEqual(self.health_page()['status'], 'stale')
        record_learning(self.store, self.space, 'r-second', paths=['guide.md'], now=NOW)
        self.web(text='first')
        self.assertEqual(self.health_page()['status'], 'stale')
        self.assertEqual(self.health_page()['evidence'][0]['recorded_version'], sha('second'))
        self.assertEqual(self.health_page()['evidence'][0]['current_version'], sha('first'))

    def test_stale_check_dates_and_unknown_dates_require_review(self):
        self.page()
        self.web(stamp=OLD)
        record_learning(self.store, self.space, 'r1', paths=['guide.md'], now=NOW)
        page = self.health_page()
        self.assertEqual(page['status'], 'review_due')
        self.assertIn('source_review_due', page['reasons'])
        self.web(stamp=None)
        self.assertEqual(self.health_page()['status'], 'review_due')
        self.assertIn('source_check_time_unknown', self.health_page()['reasons'])
        self.web(stamp='2030-01-01T00:00:00Z')
        self.assertIn('source_check_time_unknown', self.health_page()['reasons'])

    def test_local_identity_is_scoped_and_mtime_is_not_a_freshness_certificate(self):
        self.page()
        self.store.add_source(self.space, 'notes.md', 'local notes')
        self.store.add_source('software-app', 'notes.md', 'local notes')
        first = source_snapshot(self.store, self.space)[0]
        second = source_snapshot(self.store, 'software-app')[0]
        self.assertNotEqual(first['source_id'], second['source_id'])
        self.assertEqual(first['version'], second['version'])
        self.assertIsNone(first['checked_at'])
        record_learning(self.store, self.space, 'r1', paths=['guide.md'], now=NOW)
        self.assertEqual(self.health_page()['status'], 'review_due')
        (self.store._source(self.space) / 'notes.md').write_text('updated local notes')
        self.assertEqual(self.health_page()['status'], 'stale')

    def test_historical_web_file_still_in_inbox_is_a_conflict(self):
        self.page()
        old, old_record = self.web(name='web-old.md', text='old')
        history = {sha('old'): {'filename': old.name, 'inbox_sha256': old_record['inbox_sha256']}}
        self.web(name='web-new.md', text='new', history=history)
        snapshot = source_snapshot(self.store, self.space)
        self.assertEqual(len(snapshot), 1)
        self.assertEqual(snapshot[0]['status'], 'conflict')
        self.assertIn('superseded_source_still_in_inputs', snapshot[0]['reasons'])
        record_learning(self.store, self.space, 'r1', paths=['guide.md'], now=NOW)
        self.assertEqual(self.health_page()['status'], 'stale')

    def test_paths_scope_and_symlinks_are_rejected_without_partial_records(self):
        file = self.page()
        self.web()
        for paths in (['../escape.md'], ['/absolute.md'], ['guide.md', 'missing.md']):
            with self.assertRaises((ValueError, FileNotFoundError)):
                record_learning(self.store, self.space, 'unsafe', paths=paths, now=NOW)
        other = source_snapshot(self.store, self.space)
        other[0]['space_id'] = 'software-app'
        with self.assertRaises(ValueError):
            record_learning(self.store, self.space, 'wrong-source', source_versions=other, paths=['guide.md'])
        outside = self.root / 'outside.md'
        outside.write_text('protected')
        link = self.store._wiki(self.space) / 'escape.md'
        link.symlink_to(outside)
        with self.assertRaises(ValueError):
            record_learning(self.store, self.space, 'unsafe-link', paths=['escape.md'])
        self.assertEqual(outside.read_text(), 'protected')
        self.assertFalse((self.store.base / 'metadata/knowledge').exists())
        self.assertEqual(file.read_text(), '# Guide\n真实输入整理的说明。\n')

    def test_published_source_uses_frozen_upstream_version_and_detects_tampering(self):
        self.page()
        self.web()
        record_learning(self.store, self.space, 'branch-run', paths=['guide.md'], now=NOW)
        reviewed = self.store.review(self.space)
        self.store.publish(self.space, reviewed['token'])
        manifest_file = self.store.base / 'metadata' / (self.space + '.json')
        manifest = json.loads(manifest_file.read_text())
        manifest['knowledge'] = knowledge_health(self.store, self.space, now=NOW)
        _write_json(manifest_file, manifest)
        published = next(item for item in source_snapshot(self.store, 'central') if item['name'].endswith('/guide.md'))
        self.assertEqual(published['upstream_page_id'], page_id(self.space, 'guide.md'))
        self.assertEqual(published['upstream_version'], manifest['files']['guide.md'])
        self.assertEqual(published['upstream_run_id'], 'branch-run')
        self.assertEqual(published['provenance_basis'], 'publication_manifest')
        self.page(body='# Later draft\n')
        again = next(item for item in source_snapshot(self.store, 'central') if item['name'].endswith('/guide.md'))
        self.assertEqual(again['version'], published['version'])
        self.assertEqual(again['upstream_version'], published['upstream_version'])
        (self.store._source('central') / self.space / 'guide.md').write_text('tampered snapshot')
        tampered = next(item for item in source_snapshot(self.store, 'central') if item['name'].endswith('/guide.md'))
        self.assertEqual(tampered['status'], 'conflict')
        self.assertIn('published_snapshot_hash_conflict', tampered['reasons'])

    def test_upstream_source_changes_propagate_without_publishing_new_draft(self):
        self.page()
        self.web()
        record_learning(self.store, self.space, 'branch-run', paths=['guide.md'], now=NOW)
        reviewed = self.store.review(self.space)
        self.store.publish(self.space, reviewed['token'])
        manifest_file = self.store.base / 'metadata' / (self.space + '.json')
        manifest = json.loads(manifest_file.read_text())
        manifest['knowledge'] = knowledge_health(self.store, self.space, now=NOW)
        manifest['published_at'] = RECENT
        _write_json(manifest_file, manifest)
        self.page(space='central', body='# Central synthesis\n')
        record_learning(self.store, 'central', 'central-run', paths=['guide.md'], now=NOW)
        self.assertEqual(self.health_page('central')['status'], 'current')
        published_file = self.store._source('central') / self.space / 'guide.md'
        original_bytes = published_file.read_bytes()
        original_version = manifest['version']
        self.web(text='updated source after publication')
        source = next(item for item in source_snapshot(self.store, 'central') if item['name'].endswith('/guide.md'))
        self.assertEqual(source['status'], 'stale')
        self.assertIn('upstream_source_changed_after_publication', source['reasons'])
        page = self.health_page('central')
        self.assertEqual(page['status'], 'stale')
        self.assertIn('upstream_source_changed_after_publication', page['reasons'])
        self.assertEqual(published_file.read_bytes(), original_bytes)
        self.assertEqual(json.loads(manifest_file.read_text())['version'], original_version)
        # Same source bytes with an overdue check still propagates review age.
        self.web(text='source-v1', stamp=OLD)
        current = next(item for item in knowledge_health(self.store, 'central', now=NOW)['sources'] if item['name'].endswith('/guide.md'))
        self.assertEqual(current['status'], 'available')
        self.assertEqual(current['freshness'], 'review_due')

    def test_published_old_or_stale_provenance_never_becomes_current(self):
        self.page()
        self.web()
        record_learning(self.store, self.space, 'branch-run', paths=['guide.md'], now=NOW)
        reviewed = self.store.review(self.space)
        self.store.publish(self.space, reviewed['token'])
        manifest_file = self.store.base / 'metadata' / (self.space + '.json')
        manifest = json.loads(manifest_file.read_text())
        frozen = knowledge_health(self.store, self.space, now=NOW)
        manifest['knowledge'] = frozen
        frozen['pages'][0]['status'] = 'stale'
        _write_json(manifest_file, manifest)
        published = next(item for item in source_snapshot(self.store, 'central') if item['name'].endswith('/guide.md'))
        self.assertEqual(published['status'], 'stale')
        self.page(space='central', body='# Central synthesis\n')
        record_learning(self.store, 'central', 'central-run', paths=['guide.md'], now=NOW)
        self.assertEqual(self.health_page('central')['status'], 'stale')
        frozen['pages'][0]['status'] = 'untracked'
        _write_json(manifest_file, manifest)
        unknown = next(item for item in source_snapshot(self.store, 'central') if item['name'].endswith('/guide.md'))
        self.assertEqual(unknown['freshness'], 'unknown')
        del manifest['knowledge']
        _write_json(manifest_file, manifest)
        legacy = next(item for item in source_snapshot(self.store, 'central') if item['name'].endswith('/guide.md'))
        self.assertEqual(legacy['provenance_basis'], 'snapshot_manifest_only')
        self.assertEqual(legacy['freshness'], 'unknown')

    def test_corrupt_sidecar_is_not_silently_replaced_or_treated_as_current(self):
        self.page()
        self.web()
        record_learning(self.store, self.space, 'r1', paths=['guide.md'], now=NOW)
        file = self.store.base / 'metadata/knowledge' / (self.space + '.json')
        file.write_text('{invalid')
        self.assertEqual(self.health_page()['status'], 'untracked')
        self.assertIn('metadata_unreadable', self.health_page()['reasons'])
        with self.assertRaises(ValueError):
            record_learning(self.store, self.space, 'r2', paths=['guide.md'])
        self.assertEqual(file.read_text(), '{invalid')


if __name__ == '__main__':
    unittest.main()
