"""Read-only research boundaries with a real store and controlled HTTP/search.

Search configuration/results and SafeFetcher.fetch are replaced. Scope selection, URL policy, extraction,
evidence hashes, filesystem writes and report persistence use production code.
No public-network or model requests are made by this suite.
"""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from federation.agent_templates import refresh_agent_library
from federation.core import FederationStore
from federation.project_research import research_project
from federation.web_learning import CollectionError, SafeFetcher


LONG_TEXT = '# 官方资料受控样例\n\n' + '\n'.join(
    f'第 {index} 项：页面需要明确输入标签、错误状态和键盘操作；这些只是测试正文，不代表真实联网证据。'
    for index in range(110)
)
SHORT_TEXT = '# 第二份受控资料\n\n' + (
    '在定义页面方案时，先核对用户目标与交互边界，再记录验证方法。'
    '本文用于检验真实正文保存及散列值，不是产品实施结果。\n' * 4
).rstrip()


def response(url, text=LONG_TEXT):
    return {'url': url, 'status': 200,
            'headers': {'content-type': 'text/markdown; charset=utf-8'},
            'body': text.encode('utf-8')}


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode('utf-8')).hexdigest()


class ProjectResearchTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='project-research-boundary-')
        self.root = Path(self.temporary.name).resolve()
        self.store = FederationStore(self.root / 'data', project_root=self.root / 'project')
        self.store.init()
        refresh_agent_library(self.store, 'software-frontend')
        # Existing human work exists in each protected area, including a changed
        # real template. Read-only research must neither normalize nor upgrade it.
        originals = {
            self.store._source('software-frontend') / 'manual-source.md': '# 手工来源\n不要被调研覆盖。\n',
            self.store._wiki('software-frontend') / 'existing-page.md': '# 已有知识草稿\n原结论与原引用保持原样。\n',
            self.store._home('software-frontend') / 'templates/agent-standard/GUIDELINES.md': '# 用户调整的工作规范\n保留人工修改和格式。\n',
            self.store.base / 'published/software-frontend/existing-snapshot.md': '# 已审核快照\n调研不得自行发布或改变快照。\n',
            self.store._source('software-backend') / 'separate-branch.md': '# 其他分支\n隔离的原始资料。\n',
        }
        for path, text in originals.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf-8')
        self.agents = self.store.spaces()
        self.original_files = self.nonresearch_files()
        self.run_id = uuid.uuid4().hex
        # Never use a developer's actual credential or invoke a paid provider.
        key_patch = patch('federation.project_research._search_key', return_value='')
        self.search_key = key_patch.start()
        self.addCleanup(key_patch.stop)
        search_patch = patch('federation.project_research._tavily_urls', new_callable=AsyncMock, return_value=[])
        self.search = search_patch.start()
        self.addCleanup(search_patch.stop)

    def tearDown(self):
        self.temporary.cleanup()

    def nonresearch_files(self):
        """Compare all actual files and mtimes, not a mocked write helper."""
        return {
            path.relative_to(self.store.base).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in self.store.base.rglob('*')
            if path.is_file() and path.relative_to(self.store.base).parts[0] != 'research-runs'
        }

    def assert_protected_unchanged(self, before=None):
        self.assertEqual(self.nonresearch_files(), self.original_files if before is None else before,
                         'Research must not add, delete, touch or rewrite any non-research file')

    async def test_dynamic_page_uses_app_browser_and_discovers_observed_document_link(self):
        url='https://example.com/app'
        shell={'url':url,'status':200,'headers':{'content-type':'text/html'},'body':b'<html><body><div id="app"></div></body></html>'}
        text=SHORT_TEXT
        rendered={'url':url,'title':'真实渲染受控样例','text':text,'sha256':digest(text),
                  'read_method':'browser_dom','links':[{'url':'https://example.com/help','label':'帮助'}]}
        with patch.object(SafeFetcher,'fetch',side_effect=lambda target:shell if target==url else response(target)), \
             patch('federation.project_research.PublicBrowserReader.render',new_callable=AsyncMock,return_value=rendered) as browser:
            report=await research_project(self.store,'深度分析 '+url,self.run_id,self.agents,profile='product-analysis')
        browser.assert_awaited_once()
        self.assertTrue(report['browser_inspected'])
        self.assertEqual([s['url'] for s in report['sources']],[url,'https://example.com/help'])
        self.assertEqual(report['sources'][0]['read_method'],'browser_dom')
        self.assertEqual((self.store.base/report['sources'][0]['path']).read_text(),text)
        self.assert_protected_unchanged()

    async def test_rejected_public_fetch_cannot_be_bypassed_by_browser(self):
        with patch.object(SafeFetcher,'fetch',side_effect=CollectionError('robots 不允许访问')), \
             patch('federation.project_research.PublicBrowserReader.render',new_callable=AsyncMock) as browser:
            report=await research_project(self.store,'深度分析 https://example.com/private',self.run_id,self.agents,profile='product-analysis')
        browser.assert_not_awaited()
        self.assertEqual(report['status'],'unavailable')
        self.assert_protected_unchanged()

    def assert_saved_report(self, report):
        directory = self.store.base / 'research-runs' / report['run_id']
        self.assertTrue(directory.is_dir())
        persisted = json.loads((directory / 'report.json').read_text(encoding='utf-8'))
        self.assertEqual(persisted, report)
        self.assertEqual({file.name for file in directory.iterdir()},
                         {'report.json'} | {f'{index + 1}.md' for index in range(len(report['sources']))})
        return directory

    async def test_only_two_sources_are_saved_with_full_text_and_independent_hashes(self):
        urls = ['https://example.com/one', 'https://example.com/two', 'https://example.com/ignored-third']
        with patch.object(SafeFetcher, 'fetch', side_effect=[response(urls[0]), response(urls[1], SHORT_TEXT)]) as fetch:
            report = await research_project(self.store, '前端项目调研 ' + ' '.join(urls), self.run_id, self.agents)
        self.assertEqual([call.args[0] for call in fetch.call_args_list], urls[:2])
        self.assertEqual(report['scope'], 'proposal-only')
        self.assertEqual(report['status'], 'completed')
        self.assertEqual(report['errors'], [])
        self.assertEqual(report['mode'], 'provided-urls')
        self.assertEqual(report['search_status'], 'not_requested')

        self.search_key.assert_not_called()
        self.search.assert_not_awaited()
        self.assertEqual(len(report['sources']), 2)
        directory = self.assert_saved_report(report)
        for source, url, expected in zip(report['sources'], urls, [LONG_TEXT, SHORT_TEXT]):
            with self.subTest(url=url):
                file = self.store.base / source['path']
                self.assertEqual(file.parent, directory)
                self.assertEqual(file.read_bytes(), expected.encode('utf-8'))
                self.assertEqual(source['url'], url)
                self.assertEqual(source['sha256'], digest(expected))
                self.assertEqual(source['excerpt'], expected[:3500])
                self.assertEqual(source['excerpt_sha256'], digest(source['excerpt']))
                self.assertEqual(source['truncated'], len(expected) > 3500)
                self.assertTrue(source['fetched_at'])
        self.assertNotEqual(report['sources'][0]['sha256'], report['sources'][0]['excerpt_sha256'])
        self.assertEqual(report['sources'][1]['sha256'], report['sources'][1]['excerpt_sha256'])
        self.assertIn('不代表', report['note'])
        self.assertFalse((self.store.base / 'web-learning').exists())
        self.assert_protected_unchanged()

    async def test_product_analysis_follows_public_detail_pages_with_an_eight_page_limit(self):
        base = 'https://example.com/'
        links = ''.join(f'<a href="/docs/{index}">Documentation {index}</a>' for index in range(12))
        def page(url):
            if url == base:
                return {'url': url, 'status': 200, 'headers': {'content-type': 'text/html'},
                        'body': ('<html><body>' + links + '<p>' + SHORT_TEXT * 5 + '</p></body></html>').encode()}
            return response(url, SHORT_TEXT)
        with patch.object(SafeFetcher, 'fetch', side_effect=page) as fetch:
            report = await research_project(self.store, '深度分析产品 ' + base, self.run_id, self.agents, profile='product-analysis')
        self.assertEqual(fetch.call_count, 8)
        self.assertEqual(len(report['sources']), 8)
        self.assertEqual(report['scope'], 'read-only-product-analysis')
        self.assertFalse(report['browser_inspected'])
        self.assertIn('浏览器正文不等于完整功能体验', report['note'])
        self.assert_saved_report(report)
        self.assert_protected_unchanged()

    async def test_official_discovery_keeps_existing_learning_index_and_all_branch_content(self):
        index = self.store.base / 'web-learning/index.json'
        index.parent.mkdir(parents=True, exist_ok=True)
        index.write_text('{"existing-capture":{"version":"human-kept"}}\n', encoding='utf-8')
        before = self.nonresearch_files()
        with patch.object(SafeFetcher, 'fetch', side_effect=lambda url: response(url)) as fetch:
            report = await research_project(self.store, '为前端 HTML 页面制定方案', self.run_id, self.agents)
        self.assertEqual(report['source_catalog'], 'software-frontend')
        self.assertEqual(report['mode'], 'official-sites')
        self.assertEqual(report['search_status'], 'not_configured')
        self.assertIn('未执行全网搜索', report['note'])
        self.assertGreaterEqual(fetch.call_count, 1)
        self.assertLessEqual(fetch.call_count, 2)
        self.assertEqual(len(report['sources']), fetch.call_count)
        self.assertEqual(report['status'], 'completed')
        self.assertTrue(all(source['url'].startswith('https://') for source in report['sources']))
        self.assert_saved_report(report)
        self.assert_protected_unchanged(before)

    async def test_private_urls_are_rejected_before_the_fetcher_is_called(self):
        for url in ['http://127.0.0.1/docs', 'http://10.0.0.8/docs', 'http://169.254.169.254/latest',
                    'http://localhost/docs', 'http://[::1]/docs', 'http://wiki.internal/docs']:
            with self.subTest(url=url), patch.object(SafeFetcher, 'fetch') as fetch:
                report = await research_project(self.store, '项目调研 ' + url, uuid.uuid4().hex, self.agents)
                fetch.assert_not_called()
                self.assertEqual(report['status'], 'unavailable')
                self.assertEqual(report['sources'], [])
                self.assertEqual(len(report['errors']), 1)
                self.assertEqual(report['errors'][0]['url'], url)
                self.assertTrue(report['errors'][0]['error'])
                self.assert_saved_report(report)
        self.assert_protected_unchanged()

    async def test_no_network_request_leaves_all_files_untouched_even_with_a_supplied_url(self):
        for restriction in ['不要联网', '不联网', '离线', '不要上网', 'no internet', 'no network']:
            with self.subTest(restriction=restriction), patch.object(SafeFetcher, 'fetch') as fetch:
                report = await research_project(self.store, f'前端项目，{restriction} https://example.com/guide', uuid.uuid4().hex, self.agents)
                fetch.assert_not_called()
                self.assertEqual(report['status'], 'not_researched')
                self.assertEqual(report['sources'], [])
                self.assertEqual(report['errors'], [])
                self.assertIn('不联网', report['note'])
                self.assertEqual(report['mode'], 'offline')
        self.search_key.assert_not_called()
        self.search.assert_not_awaited()
        self.assertFalse((self.store.base / 'research-runs').exists())
        self.assertFalse((self.store.base / 'web-learning').exists())
        self.assert_protected_unchanged()

    async def test_unmatched_scope_does_not_invent_research_or_use_an_unrelated_catalog(self):
        for goal, agents in [('研究庭院灌溉方案', self.agents), ('前端页面方案', [{'id': 'central'}])]:
            with self.subTest(goal=goal), patch.object(SafeFetcher, 'fetch') as fetch:
                report = await research_project(self.store, goal, uuid.uuid4().hex, agents)
                fetch.assert_not_called()
                self.assertEqual(report['status'], 'not_researched')
                self.assertIsNone(report['source_catalog'])
                self.assertEqual(report['sources'], [])
                self.assertIn('仍需核实', report['note'])
                self.assertIn('未配置可用的联网搜索服务', report['note'])
                self.assertEqual(report['query'], goal)
                self.assertEqual(report['search_status'], 'not_configured')
                self.assertEqual(report['mode'], 'none')
        self.assertFalse((self.store.base / 'research-runs').exists())
        self.assert_protected_unchanged()

    async def test_income_topics_have_official_entry_points_without_requiring_a_matching_agent(self):
        for topic in ['普通人在家做副业', '如何开始自由职业接单', '探索创收机会', '用 React 开发做副业', 'freelance work', 'side income']:
            with self.subTest(topic=topic), patch.object(SafeFetcher, 'fetch', side_effect=lambda url: response(url)) as fetch:
                report = await research_project(self.store, topic, uuid.uuid4().hex, [{'id': 'central'}])
                self.assertEqual(report['source_catalog'], 'freelance-income')
                self.assertEqual(report['status'], 'completed')
                self.assertEqual(report['query'], topic)
                self.assertEqual(report['mode'], 'official-sites')
                self.assertEqual(report['search_status'], 'not_configured')
                self.assertEqual(fetch.call_count, 2)
                self.assertEqual([source['url'] for source in report['sources']], [
                    'https://support.proginn.com/qa/',
                    'https://support.proginn.com/outsource/coder-sign/',
                ])
                self.assertIn('未执行全网搜索', report['note'])
                self.assertIn('当前目录仅覆盖技术接单示例，不能代表全部副业或当前收益排名', report['note'])
                self.assertIn('不据此推断用户已有技术技能', report['note'])
                self.assertIn('不构成收益承诺', report['note'])
                self.assert_saved_report(report)
        self.search.assert_not_awaited()
        self.assert_protected_unchanged()

    async def test_unknown_topic_search_uses_full_goal_and_saves_only_two_distinct_public_sources(self):
        goal = '研究庭院灌溉方案；承接原约束：只读，预算有限且不能改造现有供水'
        urls = ['https://example.com/irrigation', 'https://example.org/water', 'https://example.net/unused']
        self.search_key.return_value = 'controlled-test-key'
        self.search.return_value = [urls[0], urls[0], urls[1], urls[2]]
        with patch.object(SafeFetcher, 'fetch', side_effect=lambda url: response(url, SHORT_TEXT)) as fetch:
            report = await research_project(self.store, goal, self.run_id, self.agents)
        self.search_key.assert_called_once_with(self.store)
        self.search.assert_awaited_once_with(self.store, goal, [], 'controlled-test-key')
        self.assertEqual([call.args[0] for call in fetch.call_args_list], urls[:2])
        self.assertEqual(report['query'], goal)
        self.assertIsNone(report['source_catalog'])
        self.assertEqual(report['mode'], 'tavily')
        self.assertEqual(report['search_status'], 'completed')
        self.assertEqual(report['status'], 'completed')
        self.assertEqual(len(report['sources']), 2)
        directory = self.assert_saved_report(report)
        self.assertNotIn('controlled-test-key', (directory / 'report.json').read_text('utf-8'))
        self.assert_protected_unchanged()

    async def test_catalog_search_uses_goal_and_official_domains_instead_of_fetching_fixed_seeds(self):
        goal = '查询副业接单的平台规则与费用限制'
        self.search_key.return_value = 'controlled-test-key'
        found = 'https://support.proginn.com/controlled-fees/'
        self.search.return_value = [found]
        with patch.object(SafeFetcher, 'fetch', side_effect=lambda url: response(url)) as fetch:
            report = await research_project(self.store, goal, self.run_id, self.agents)
        self.search.assert_awaited_once_with(self.store, goal, ['support.proginn.com'], 'controlled-test-key')
        fetch.assert_called_once_with(found)
        self.assertEqual(report['mode'], 'tavily')
        self.assertEqual(report['search_status'], 'completed')
        self.assertEqual(report['status'], 'completed')
        self.assertIn('不构成收益承诺', report['note'])
        self.assert_saved_report(report)
        self.assert_protected_unchanged()

    async def test_search_failure_falls_back_to_catalog_and_records_partial_evidence(self):
        self.search_key.return_value = 'controlled-test-key'
        self.search.side_effect = CollectionError('controlled-test-key provider failed')
        with patch.object(SafeFetcher, 'fetch', side_effect=lambda url: response(url)) as fetch:
            report = await research_project(self.store, '副业调研', self.run_id, self.agents)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(report['mode'], 'official-sites')
        self.assertEqual(report['search_status'], 'failed')
        self.assertEqual(report['errors'][0]['stage'], 'search')
        self.assertIn('搜索服务调用失败', report['note'])
        self.assertIn('已回退到官方资料入口', report['note'])
        directory = self.assert_saved_report(report)
        self.assertNotIn('controlled-test-key', (directory / 'report.json').read_text('utf-8'))
        self.assert_protected_unchanged()

    async def test_empty_search_falls_back_to_catalog_without_claiming_search_evidence(self):
        self.search_key.return_value = 'controlled-test-key'
        with patch.object(SafeFetcher, 'fetch', side_effect=lambda url: response(url)) as fetch:
            report = await research_project(self.store, '副业调研', self.run_id, self.agents)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(report['status'], 'completed')
        self.assertEqual(report['mode'], 'official-sites')
        self.assertEqual(report['search_status'], 'no_results')
        self.assertIn('搜索服务未返回可用网页', report['note'])
        self.assert_saved_report(report)
        self.assert_protected_unchanged()

    async def test_unknown_topic_retains_failed_or_empty_search_without_inventing_sources(self):
        self.search_key.return_value = 'controlled-test-key'
        for error, expected_status in [(CollectionError('controlled search failure'), 'failed'), (None, 'no_results')]:
            with self.subTest(status=expected_status), patch.object(SafeFetcher, 'fetch') as fetch:
                self.search.side_effect = error
                report = await research_project(self.store, '研究庭院灌溉方案', uuid.uuid4().hex, self.agents)
                fetch.assert_not_called()
                self.assertEqual(report['status'], 'unavailable')
                self.assertEqual(report['mode'], 'none')
                self.assertEqual(report['search_status'], expected_status)
                self.assertEqual(report['sources'], [])
                self.assertIn('不能称为已完成调研', report['note'])
                self.assert_saved_report(report)
        self.assert_protected_unchanged()

    async def test_search_results_still_pass_public_url_validation_before_fetch(self):
        self.search_key.return_value = 'controlled-test-key'
        self.search.return_value = ['http://127.0.0.1/private', 'https://example.com/public']
        with patch.object(SafeFetcher, 'fetch', side_effect=lambda url: response(url)) as fetch:
            report = await research_project(self.store, '研究庭院灌溉方案', self.run_id, self.agents)
        fetch.assert_called_once_with('https://example.com/public')
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(len(report['sources']), 1)
        self.assertEqual(report['errors'][0]['url'], 'http://127.0.0.1/private')
        self.assert_saved_report(report)
        self.assert_protected_unchanged()

    async def test_partial_fetch_failure_preserves_only_actual_evidence_and_honest_status(self):
        urls = ['https://example.com/readable', 'https://example.com/blocked']
        with patch.object(SafeFetcher, 'fetch', side_effect=[response(urls[0], SHORT_TEXT), CollectionError('robots policy unavailable')]) as fetch:
            report = await research_project(self.store, '后端项目调研 ' + ' '.join(urls), self.run_id, self.agents)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(len(report['sources']), 1)
        self.assertEqual(report['sources'][0]['sha256'], digest(SHORT_TEXT))
        self.assertEqual(report['errors'], [{'url': urls[1], 'error': 'robots policy unavailable'}])
        self.assertIn('仅核验本轮列出的', report['note'])
        self.assert_saved_report(report)
        self.assert_protected_unchanged()

    async def test_all_failed_fetches_leave_an_unavailable_report_without_fake_source_files(self):
        with patch.object(SafeFetcher, 'fetch', side_effect=CollectionError('controlled fetch failure')) as fetch:
            report = await research_project(self.store, '调研 https://example.com/one https://example.com/two', self.run_id, self.agents)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(report['status'], 'unavailable')
        self.assertEqual(report['sources'], [])
        self.assertEqual(len(report['errors']), 2)
        self.assertIn('不能称为已完成调研', report['note'])
        self.assert_saved_report(report)
        self.assert_protected_unchanged()

    async def test_invalid_run_identifiers_cannot_write_outside_the_research_directory(self):
        with patch.object(SafeFetcher, 'fetch') as fetch:
            for identifier in ['../escape', '/tmp/escape', 'a' * 31, 'A' * 32]:
                with self.subTest(identifier=identifier), self.assertRaisesRegex(ValueError, '调研编号无效'):
                    await research_project(self.store, '前端网页方案', identifier, self.agents)
            fetch.assert_not_called()
        self.assertFalse((self.store.base / 'research-runs').exists())
        self.assert_protected_unchanged()


if __name__ == '__main__':
    unittest.main()
