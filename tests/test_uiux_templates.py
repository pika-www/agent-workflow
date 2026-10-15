"""UI/UX artifact contracts and locally checkable evidence, without design-tool claims."""
import csv
from html.parser import HTMLParser
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
import unittest

from federation.agent_templates import all_templates, refresh_agent_library, validate_any_template
from federation.core import FederationStore
from federation.specialist_catalog import ROLE_PACKS, _pack
from federation.uiux_templates import build_uiux_templates


class Markup(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.tags = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def luminance(value):
    channels = [int(value[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    rgb = [part / 12.92 if part <= .04045 else ((part + .055) / 1.055) ** 2.4 for part in channels]
    return sum(channel * weight for channel, weight in zip(rgb, (.2126, .7152, .0722)))


class UiuxTemplateTest(unittest.TestCase):
    def setUp(self):
        self.packs = {pack['id']: pack for pack in build_uiux_templates(_pack)}

    def test_catalog_has_distinct_recipes_and_independent_copies(self):
        self.assertEqual(set(self.packs), {'uiux-screen-handoff', 'uiux-design-system'})
        self.assertEqual([p['id'] for p in ROLE_PACKS['software-uiux']], list(self.packs))
        for query, expected in [('页面设计和交互原型', 'uiux-screen-handoff'), ('设计系统 token 深色主题', 'uiux-design-system')]:
            scores = [(sum(word.casefold() in query.casefold() for word in pack['keywords']), pack['id']) for pack in self.packs.values()]
            self.assertEqual(max(scores)[1], expected)
        self.packs['uiux-screen-handoff']['documents']['GUIDELINES.md'] = 'local edit'
        self.assertNotEqual(ROLE_PACKS['software-uiux'][0]['documents']['GUIDELINES.md'], 'local edit')

    def test_assets_and_learned_rules_fit_native_read_budget(self):
        for pack in self.packs.values():
            documents = {**pack['documents'], 'template/LEARNED_RULES.md': '# 本库学习规则\n'}
            self.assertLessEqual(len(documents), 9, 'All files including learned rules fit native prefetch')
            for filename, text in documents.items():
                self.assertFalse(PurePosixPath(filename).is_absolute())
                self.assertNotIn('..', PurePosixPath(filename).parts)
                self.assertTrue(text.endswith('\n'))
                if filename.endswith('.json'):
                    parsed = json.loads(text)
                    self.assertTrue(parsed['example_only'])
            self.assertEqual(pack['source_url'], 'local-policy://specialist/' + pack['id'])
            self.assertIn('原创适配', documents['GUIDELINES.md'])
            self.assertIn('不代表已经运行', documents['template/EXAMPLE.md'])

    def test_screen_states_handoff_and_element_references_are_consistent(self):
        files = self.packs['uiux-screen-handoff']['documents']
        screen = json.loads(files['template/screen-spec.json'])
        rows = list(csv.DictReader(io.StringIO(files['template/state-matrix.csv'])))
        states = {row['state_id'] for row in rows}
        self.assertEqual(set(screen['states']), states)
        self.assertEqual(states, {'initial', 'editing', 'validation_error', 'loading', 'success', 'empty', 'server_error', 'offline', 'forbidden'})
        self.assertEqual(len(rows), len(states))
        self.assertTrue(all(all(row.values()) for row in rows))
        elements = {element['element_id']: element for element in screen['elements']}
        self.assertEqual(set(screen['reading_order']), set(elements))
        self.assertEqual(set(screen['keyboard_order']), {key for key, item in elements.items() if item['role'] in ('textbox', 'button')})
        self.assertFalse(screen['design_artifact_created'])
        self.assertIsNone(screen['design_artifact_url'])
        self.assertTrue(all(item['status'] == 'not_run' for item in screen['acceptance']))
        self.assertIn('后端', files['template/HANDOFF.md'])
        for platform in ('Web', 'iOS', 'Android', '微信小程序', 'Flutter', 'React Native', 'Dynamic Type', '安全区'):
            self.assertIn(platform, files['template/RESPONSIVE_PLATFORM.md'])

    def test_tokens_css_mapping_and_component_references_resolve(self):
        files = self.packs['uiux-design-system']['documents']
        data = json.loads(files['template/tokens.json'])
        css = files['template/tokens.css']
        for theme, colors in data['themes'].items():
            selector = ':root' if theme == 'light' else '[data-theme="dark"]'
            body = re.search(re.escape(selector) + r'\s*\{([^}]+)\}', css).group(1)
            for name, value in colors.items():
                self.assertIn('--demo-color-' + name + ': ' + value + ';', body)
        for category in ('space', 'radius', 'type', 'layout', 'motion'):
            for name, value in data[category].items():
                self.assertIn('--demo-' + category + '-' + name + ': ' + value + ';', css)
        definitions = set(re.findall(r'(--demo-[\w-]+)\s*:', css))
        self.assertTrue(set(re.findall(r'var\((--demo-[\w-]+)\)', css)).issubset(definitions))
        components = json.loads(files['template/components.json'])['components']
        for component in components:
            self.assertTrue(set(component['tokens']).issubset(data['themes']['light']))
            self.assertTrue({'default', 'focus', 'disabled'}.issubset(component['states']))
            self.assertEqual(component['implementation_status'], 'not_integrated')

    def test_contrast_pairs_meet_the_stated_local_thresholds(self):
        data = json.loads(self.packs['uiux-design-system']['documents']['template/tokens.json'])
        for theme, colors in data['themes'].items():
            for pair in data['contrast_pairs']:
                values = sorted([luminance(colors[pair['foreground']]), luminance(colors[pair['background']])])
                ratio = (values[1] + .05) / (values[0] + .05)
                self.assertGreaterEqual(ratio, pair['minimum'], f'{theme} {pair}: {ratio}')

    def test_static_demo_has_accessible_associations_and_no_remote_requests(self):
        files = self.packs['uiux-design-system']['documents']
        html, css = files['template/demo.html'], files['template/tokens.css']
        markup = Markup(html)
        ids = [attrs['id'] for _, attrs in markup.tags if 'id' in attrs]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertFalse(any(tag in ('script', 'form', 'iframe') for tag, _ in markup.tags))
        self.assertNotRegex(html, r'https?://')
        for tag, attrs in markup.tags:
            for reference in ('for', 'aria-describedby', 'aria-labelledby'):
                self.assertTrue(set(attrs.get(reference, '').split()).issubset(ids))
            if tag == 'link':
                self.assertIn('template/' + attrs['href'], files)
            if tag == 'a':
                self.assertIn(attrs['href'][1:], ids)
            for classname in attrs.get('class', '').split():
                self.assertIn('.' + classname, css)
        self.assertIn(':focus-visible', css)
        self.assertIn('prefers-reduced-motion: reduce', css)
        self.assertIn('forced-colors: active', css)
        self.assertNotIn('outline: none', css)

    def test_css_parses_using_existing_esbuild_without_dependency_install(self):
        root = Path(__file__).resolve().parents[1]
        esbuild = root / 'openwiki-tools/node_modules/esbuild/lib/main.js'
        node = shutil.which('node') or '/Users/winfield/.nvm/versions/node/v24.18.0/bin/node'
        if not esbuild.is_file() or not Path(node).is_file():
            self.skipTest('Existing Node/esbuild unavailable')
        source = self.packs['uiux-design-system']['documents']['template/tokens.css']
        script = "const esbuild = await import(process.argv[1]); let source=''; for await(const c of process.stdin) source+=c; const result=await esbuild.transform(source,{loader:'css'}); if(result.warnings.length) throw new Error(JSON.stringify(result.warnings)); process.stdout.write('parsed');"
        result = subprocess.run([node, '--input-type=module', '-e', script, esbuild.as_uri()], input=source, text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'parsed')

    def test_existing_library_adds_learned_rules_with_valid_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = FederationStore(root / 'data', project_root=root / 'project')
            store.init()
            refresh_agent_library(store, 'software-uiux')
            self.assertEqual({item['id'] for item in all_templates(store, 'software-uiux')}, {'agent-standard', *self.packs})
            for template_id in self.packs:
                verified = validate_any_template(store, 'software-uiux', template_id)
                self.assertEqual(verified['id'], template_id)
                self.assertIn('template/LEARNED_RULES.md', verified['files'])


if __name__ == '__main__':
    unittest.main()
