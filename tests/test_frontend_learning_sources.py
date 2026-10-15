"""Official discovery selection and source ownership for mainstream recipes."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from federation.core import FederationStore
from federation.frontend_sources import FRONTEND_SOURCES, documentation_seeds, matched_documentation
from federation import web_learning as web


class FrontendSourceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = FederationStore(Path(self.temp.name) / 'data')
        self.store.init()

    def tearDown(self):
        self.temp.cleanup()

    def test_composed_topics_use_each_official_source(self):
        cases = {
            'Angular + SCSS': ['angular-ts', 'frontend-scss'],
            'Vue + Less': ['vue-ts', 'frontend-less'],
            'CSS Less Scss': ['frontend-css', 'frontend-less', 'frontend-scss'],
            'Next.js + Tailwind CSS': ['nextjs-app', 'frontend-tailwind'],
            'React Native / Expo': ['expo-react-native'],
            '微信小程序': ['wechat-miniprogram'],
            'uni-app Vue 3': ['uniapp-vue'],
            'Taro React': ['taro-react'],
            '不要 React，使用 anglar': ['angular-ts'],
        }
        for goal, ids in cases.items():
            with self.subTest(goal=goal):
                self.assertEqual(matched_documentation(documentation_seeds(), goal), list(documentation_seeds(ids)))

    def test_app_sources_and_custom_children_inherit_only_their_profile(self):
        app = web.official_sites(self.store, 'software-app')
        self.assertEqual(matched_documentation(app, '微信小程序 SCSS'), list(documentation_seeds(['wechat-miniprogram', 'frontend-scss'])))
        self.assertEqual(matched_documentation(app, 'Angular'), [])
        child = self.store.add_branch('小程序专员', '微信与跨平台', 'software-app')
        self.assertEqual(web.official_sites(self.store, child['id']), app)
        backend = web.official_sites(self.store, 'software-backend')
        self.assertEqual(matched_documentation(backend, 'Angular + Less'), [])

    async def test_user_technology_goal_beats_off_topic_research_query(self):
        calls = []
        text = 'Angular standalone components have templates and scoped styles. ' * 8
        def fetch(url):
            calls.append(url)
            return {'url': url, 'status': 200, 'headers': {'content-type': 'text/plain'}, 'body': text.encode()}
        with patch.object(web, '_search_key', return_value=''), patch.object(web.SafeFetcher, 'fetch', side_effect=fetch):
            report = await web.collect_sources(self.store, 'software-frontend', '学习 Angular 组件',
                                               queries=['React component tutorial'], max_pages=1)
        self.assertEqual(report['sources'][0]['url'], FRONTEND_SOURCES['angular-ts'][0])
        self.assertEqual(calls, list(FRONTEND_SOURCES['angular-ts']))
        self.assertEqual(report['errors'], [])
        self.assertEqual(self.store.sources('software-app'), [])

    async def test_failed_wechat_fetch_does_not_learn_react_instead(self):
        with patch.object(web, '_search_key', return_value=''), patch.object(web.SafeFetcher, 'fetch', side_effect=web.CollectionError('robots unavailable')) as fetch:
            report = await web.collect_sources(self.store, 'software-frontend', '微信小程序', max_pages=1)
        self.assertEqual(report['sources'], [])
        self.assertTrue(report['errors'])
        self.assertEqual([call.args[0] for call in fetch.call_args_list], list(FRONTEND_SOURCES['wechat-miniprogram']))
        self.assertEqual(self.store.sources('software-frontend'), [])

    async def test_explicit_rejection_survives_off_topic_model_query(self):
        calls = []
        def fetch(url):
            calls.append(url)
            return {'url': url, 'status': 200, 'headers': {'content-type': 'text/plain'},
                    'body': ('HTML forms should use labels and validation. ' * 10).encode()}
        with patch.object(web, '_search_key', return_value=''), patch.object(web.SafeFetcher, 'fetch', side_effect=fetch):
            report = await web.collect_sources(self.store, 'software-frontend', '学习前端表单，不用 React',
                queries=['React forms official documentation'], max_pages=1)
        self.assertEqual(calls, ['https://developer.mozilla.org/en-US/docs/Web/HTML'])
        self.assertNotIn('react', report['discovery']['effective_search_goal'].lower())
        self.assertEqual(report['sources'][0]['url'], calls[0])

    async def test_unsupported_app_framework_reports_gap_without_fetch_or_search(self):
        with patch.object(web, '_search_key', return_value='controlled-key'), patch.object(web, '_tavily_urls') as search, patch.object(web.SafeFetcher, 'fetch') as fetch:
            report = await web.collect_sources(self.store, 'software-app', '学习 Angular',
                queries=['Angular components official documentation'], max_pages=1)
        self.assertEqual(report['sources'], [])
        self.assertEqual(report['discovery']['seeds'], [])
        self.assertEqual(report['errors'][0]['code'], 'unsupported_technology_source')
        fetch.assert_not_called(); search.assert_not_called()
        self.assertEqual(self.store.sources('software-app'), [])


if __name__ == '__main__':
    unittest.main()
