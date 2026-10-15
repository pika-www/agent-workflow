"""Layered recipe routing, explicit exclusions and real local-file isolation."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from federation.agent_templates import refresh_local_pack, refresh_standard
from federation.core import FederationStore
from federation.frontend_template_selection import (match_frontend_templates, select_frontend_templates,
                                                     supports_frontend_recipes)
from federation.template_context import prepare_template_context, select_frameworks


class FrontendIntentTest(unittest.TestCase):
    def test_framework_style_and_component_are_independent_layers(self):
        cases = {
            '用 Vue + Less': ['vue-ts', 'frontend-less'],
            'anglar + SCSS': ['angular-ts', 'frontend-scss'],
            'React、Tailwind CSS 和 MUI': ['react-ts', 'frontend-tailwind', 'frontend-mui'],
            '比较 CSS / Less / Scss': ['frontend-css', 'frontend-less', 'frontend-scss'],
            '微信小程序使用 CSS': ['wechat-miniprogram', 'frontend-css'],
            'uni-app + Scss': ['uniapp-vue', 'frontend-scss'],
            'Taro React 配方': ['taro-react'],
            'React Native/Expo': ['expo-react-native'],
            'RN 示例': ['expo-react-native'],
            'Next.js React SSR': ['nextjs-app'],
            'Nuxt Vue 应用': ['nuxt-app'],
            'SvelteKit 与 Astro': ['svelte-component', 'astro-content'],
            'Bootstrap 和 Ant Design': ['frontend-bootstrap', 'frontend-ant-design'],
            'Vue3 + Less4': ['vue-ts', 'frontend-less'],
            'Angular v20 + SCSS': ['angular-ts', 'frontend-scss'],
            'reactive VueModel cssLoader lessThan': [],
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(match_frontend_templates(text), expected)

    def test_negative_mentions_do_not_resurrect_from_history(self):
        cases = {
            '不用 React，使用 Vue，不要 Less': ['vue-ts'],
            '不要用 Vue 和 React': [],
            '不要 Vue 改用 Angular': ['angular-ts'],
            'do not use React, use Angular without Less': ['angular-ts'],
            'preact reactive lessThan JSX': [],
            '不用 React Native，只使用 React': ['react-ts'],
            'CSS 不是 SCSS': ['frontend-css'],
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(match_frontend_templates(text), expected)
        result = select_frontend_templates({'template_query': '不要 Less，改用 SCSS',
                                            'template_history': ['Vue 与 Less']})
        self.assertEqual([item['id'] for item in result['choices']], ['vue-ts', 'frontend-scss'])
        self.assertEqual(select_frameworks({'template_query': '不用 React',
                                           'template_history': ['React']} )[0], [])

    def test_native_wechat_aliases_preserve_platform_and_negation(self):
        for alias in ('微信原生小程序', '微信原生', '原生微信小程序', '微信 原生 小程序'):
            with self.subTest(alias=alias):
                self.assertEqual(match_frontend_templates(alias + '草稿输入页'), ['wechat-miniprogram'])
                self.assertEqual(match_frontend_templates('不用' + alias + '，改用 Taro'), ['taro-react'])
                result = select_frontend_templates({'template_query': '不要' + alias,
                                                     'template_history': ['微信小程序 + SCSS']})
                self.assertEqual([item['id'] for item in result['choices']], ['frontend-scss'])
                self.assertTrue(result['explicit'])
        self.assertEqual(match_frontend_templates('使用 uni-app，不用原生微信小程序'), ['uniapp-vue'])
        self.assertEqual(match_frontend_templates('原生 App、原生小程序、微信支付、微信聊天'), [])

    def test_current_task_and_each_layer_precede_fallback_and_history(self):
        result = select_frontend_templates({'template_query': 'Angular + SCSS',
            'template_fallback': '用 React 和 Less', 'template_history': ['Vue CSS']})
        self.assertEqual([item['id'] for item in result['choices']], ['angular-ts', 'frontend-scss'])
        result = select_frontend_templates({'template_query': '改用 Less',
            'template_history': ['Vue + CSS', 'Angular + SCSS']})
        self.assertEqual([item['id'] for item in result['choices']], ['angular-ts', 'frontend-less'])
        self.assertEqual([item['reason'] for item in result['choices']], ['recent-user-context', 'current-task'])


class FrontendIsolationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = FederationStore(base=Path(self.temp.name) / 'data')
        self.store.init()
        self.inventory = []

    def tearDown(self):
        self.temp.cleanup()

    def seed(self, space, recipes):
        self.inventory = [refresh_standard(self.store, space)]
        for identifier, framework in recipes:
            definition = {'id': identifier, 'framework': framework, 'kind': 'specialist',
                          'title': framework, 'source_version': 'controlled', 'upstream_commit': ''}
            documents = {'GUIDELINES.md': '# ' + space + ' / ' + framework,
                'template/example.txt': 'Actual source for ' + framework,
                'template/CHECKLIST.md': '# Verify', 'template/LEARNED_RULES.md': '# Current rules'}
            self.inventory.append(refresh_local_pack(self.store, space, definition, documents, {}))

    def prepare(self, space, query):
        target = self.store.base / 'ask-runs' / 'controlled' / 'wiki'
        target.mkdir(parents=True)
        job = {'space': space, 'template_query': query}
        with patch('federation.template_context.all_templates', return_value=self.inventory):
            selected, notice = prepare_template_context(self.store, job, target)
        return selected, notice, job, target

    def test_real_angular_scss_files_are_read_from_own_library_only(self):
        self.seed('software-frontend', [('angular-ts', 'angular'), ('frontend-scss', 'scss')])
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in self.store.base.rglob('*') if p.is_file()}
        selected, notice, job, target = self.prepare('software-frontend', 'anglar + SCSS')
        self.assertEqual([item['id'] for item in selected], ['agent-standard', 'angular-ts', 'frontend-scss'])
        self.assertIn('隔离副本', notice)
        self.assertEqual(job['template_notices'], [])
        for item in selected:
            copied = target / '_agent_templates' / item['id']
            self.assertTrue((copied / 'GUIDELINES.md').is_file())
            manifest = json.loads((copied / 'manifest.json').read_text())
            self.assertEqual(manifest['space_id'], 'software-frontend')
        self.assertTrue(all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == digest for p, digest in before.items()))

    def test_missing_framework_is_visible_and_is_not_replaced(self):
        self.seed('software-frontend', [('angular-ts', 'angular'), ('frontend-less', 'less')])
        selected, notice, job, target = self.prepare('software-frontend', 'Vue + Less')
        self.assertEqual([item['id'] for item in selected], ['agent-standard', 'frontend-less'])
        self.assertIn('vue-ts', notice)
        self.assertIn('尚未保存', notice)
        self.assertFalse((target / '_agent_templates/angular-ts').exists())

    def test_more_than_six_recipes_has_explicit_overflow_receipt(self):
        recipes = [('angular-ts', 'angular'), ('svelte-component', 'svelte'), ('astro-content', 'astro'),
                   ('frontend-css', 'css'), ('frontend-less', 'less'), ('frontend-scss', 'scss'),
                   ('frontend-bootstrap', 'bootstrap')]
        self.seed('software-frontend', recipes)
        selected, notice, job, target = self.prepare('software-frontend', 'Angular Svelte Astro CSS Less Scss Bootstrap')
        self.assertEqual(len(selected), 7)
        self.assertEqual(len(job['template_requested']), 8)
        self.assertIn('frontend-bootstrap', notice)
        self.assertIn('尚未读取', notice)
        self.assertFalse((target / '_agent_templates/frontend-bootstrap').exists())

    def test_app_recipes_remain_in_own_library_and_native_style_notice_is_visible(self):
        self.seed('software-app', [('expo-react-native', 'expo'), ('frontend-css', 'css')])
        selected, notice, job, target = self.prepare('software-app', 'React Native 和 CSS')
        self.assertEqual([item['id'] for item in selected], ['agent-standard', 'expo-react-native', 'frontend-css'])
        self.assertIn('不能把 CSS/Less/SCSS', notice)
        self.assertTrue(all('software-app' in (target / '_agent_templates' / item['id'] / 'GUIDELINES.md').read_text()
                            for item in selected[1:]))

    def test_native_wechat_app_task_does_not_fall_back_to_flutter(self):
        self.seed('software-app', [('flutter-stateful-screen', 'flutter'),
                                   ('wechat-miniprogram', 'wechat')])
        selected, notice, job, target = self.prepare('software-app', '微信原生小程序草稿输入页')
        self.assertEqual([item['id'] for item in selected], ['agent-standard', 'wechat-miniprogram'])
        self.assertEqual(job['template_selection_reason'], 'frontend-multilayer-task-match')
        self.assertEqual(job['template_notices'], [])
        self.assertFalse((target / '_agent_templates/flutter-stateful-screen').exists())
        manifest = json.loads((target / '_agent_templates/wechat-miniprogram/manifest.json').read_text())
        self.assertEqual(manifest['space_id'], 'software-app')

    def test_only_frontend_app_and_their_descendants_are_supported(self):
        self.assertTrue(supports_frontend_recipes(self.store, 'software-frontend'))
        self.assertTrue(supports_frontend_recipes(self.store, 'software-app'))
        self.assertFalse(supports_frontend_recipes(self.store, 'software-backend'))
        branch = self.store.add_branch('前端细分', '组件', 'software-frontend')
        self.assertTrue(supports_frontend_recipes(self.store, branch['id']))


if __name__ == '__main__':
    unittest.main()
