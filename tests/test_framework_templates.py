"""Controlled official-source transport and atomic framework snapshot tests."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

from federation.core import FederationStore
from federation import framework_templates as templates


class FakeOfficial:
    def __init__(self):
        self.version = "1.0.0"
        self.commit = "a" * 40
        self.calls = []
        self.fail_path = None
        self.corrupt_blob = False
        self.truncated = False
        self.special_mode = None
        self.missing_tag = False
        self.files = {}
        for identifier in templates.CATALOG:
            framework = identifier.split('-')[0]
            package = {"name": "fixture-" + identifier, "scripts": {"dev": "vite", "build": "tsc -b && vite build"},
                       "dependencies": {framework: "^1.0.0"}, "devDependencies": {"vite": "^1.0.0"}}
            files = {"package.json": json.dumps(package).encode(), "_gitignore": b"node_modules\ndist\n",
                     "vite.config.ts": b"export default {};\n", "index.html": b'<div id="root"></div>\n',
                     "README.md": b"# Official fixture\n", "public/icon.svg": b'<svg xmlns="http://www.w3.org/2000/svg"/>',
                     "src/assets/hero.png": b"\x89PNG\r\n\x1a\nfixture"}
            if identifier == "vue-ts":
                files.update({"src/main.ts": b"import App from './App.vue';\n", "src/App.vue": b'<script setup lang="ts"></script><template>Hi</template>',
                              ".vscode/extensions.json": b'{"recommendations": []}'})
            else:
                files.update({"src/main.tsx": b"import App from './App';\n", "src/App.tsx": b"export default function App() {return <div/>}",
                              "_oxlintrc.json": b'{}'})
            self.files[identifier] = files

    def json(self, url):
        self.calls.append(url)
        if url == "https://registry.npmjs.org/create-vite/latest":
            return {"name": "create-vite", "version": self.version, "license": "MIT",
                    "repository": {"url": "git+https://github.com/vitejs/vite.git", "directory": "packages/create-vite"}}
        path = unquote(urlsplit(url).path)
        if "/commits/" in path:
            if self.missing_tag:
                raise templates.TemplateError("Tag unavailable")
            assert path.endswith("create-vite@" + self.version), path
            return {"sha": self.commit}
        if path.endswith("/contents/packages/create-vite"):
            assert urlsplit(url).query == "ref=" + self.commit
            return [{"path": config["path"], "type": "dir", "sha": ("1" if identifier == "vue-ts" else "2") * 40}
                    for identifier, config in templates.CATALOG.items()]
        if "/git/trees/" in path:
            identifier = "vue-ts" if path.endswith("1" * 40) else "react-ts"
            tree = [{"path": name, "mode": "100644", "type": "blob", "size": len(body), "sha": templates._git_blob(body)}
                    for name, body in self.files[identifier].items()]
            if self.special_mode:
                tree[0]["mode"] = self.special_mode
            return {"truncated": self.truncated, "tree": tree}
        raise AssertionError(url)

    def artifact(self, url, allowed_types):
        self.calls.append(url)
        path = unquote(urlsplit(url).path)
        prefix = "/vitejs/vite/" + self.commit + "/"
        assert path.startswith(prefix), path
        path = path[len(prefix):]
        if self.fail_path and self.fail_path in path:
            raise templates.TemplateError("Controlled download failure")
        if path == "LICENSE":
            return b"MIT License\nFixture copyright retained.\n"
        if path == "packages/create-vite/package.json":
            return json.dumps({"name": "create-vite", "version": self.version, "engines": {"node": ">=22.12.0"}}).encode()
        for identifier, config in templates.CATALOG.items():
            if path.startswith(config["path"] + "/"):
                name = path[len(config["path"]) + 1:]
                result = self.files[identifier][name]
                return result + b"tampered" if self.corrupt_blob else result
        raise AssertionError(path)


class FrameworkRoutingTests(unittest.TestCase):
    def test_explicit_aliases_negations_and_native_boundaries(self):
        self.assertEqual(templates.match_frameworks("请维护Vue3和React.js模板"), ["vue", "react"])
        self.assertEqual(templates.match_frameworks("reactive state and preview"), [])
        self.assertEqual(templates.match_frameworks("不要Vue，使用React"), ["react"])
        self.assertEqual(templates.match_frameworks("不是Vue，React可以"), ["react"])
        self.assertEqual(templates.match_frameworks("不用React，使用Vue.js"), ["vue"])
        self.assertEqual(templates.match_frameworks("React Native and Vue"), ["vue"])
        self.assertEqual(templates.match_frameworks("React-Native 和 React 网页"), ["react"])
        self.assertEqual(templates.match_frameworks("without React, Vue please"), ["vue"])
        self.assertEqual(templates.match_frameworks("Svelte Angular"), [])

    def test_official_redirect_cannot_escape_trusted_hosts(self):
        client = templates._OfficialFetcher()
        with patch.object(client, "_robots"), patch.object(client, "_request", return_value={"status": 302, "headers": {"location": "https://example.com/code"}}) as request:
            with self.assertRaises(templates.TemplateError):
                client.artifact("https://api.github.com/repos/vitejs/vite/commits/x", templates.JSON_TYPES)
            self.assertEqual(request.call_count, 1)

    def test_json_requests_keep_pinned_transport_and_use_json_accept(self):
        client = templates._OfficialFetcher()
        with patch.object(templates, "_resolve_public", return_value=(2, "93.184.216.34")), patch.object(templates, "_PinnedHTTPSConnection") as connection:
            response = connection.return_value.getresponse.return_value
            response.status = 200
            response.getheaders.return_value = [("Content-Type", "application/json")]
            response.read.side_effect = [b'{}', b'']
            result = client._request("https://api.github.com/repos/vitejs/vite/commits/x")
            connection.assert_called_once_with("api.github.com", 443, "93.184.216.34", 2, templates.FETCH_TIMEOUT)
            self.assertEqual(connection.return_value.request.call_args.kwargs["headers"]["Accept"], "application/vnd.github+json")
            self.assertEqual(result["body"], b'{}')


class TemplateSyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = FederationStore(Path(self.temp.name) / "data", project_root=Path(self.temp.name) / "project")
        self.store.init()
        self.remote = FakeOfficial()
        self.patch = patch.object(templates, "_OfficialFetcher", return_value=self.remote)
        self.patch.start()
        self.space = "software-frontend"

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def root(self):
        return self.store._home(self.space) / "templates"

    async def sync(self, frameworks=None):
        return await templates.sync_templates(self.store, self.space, frameworks)

    async def test_initial_real_file_snapshot_manifest_and_readonly_listing(self):
        before = {space['id']: self.store.pages(space['id']) for space in self.store.spaces()}
        result = await self.sync()
        self.assertEqual(result['errors'], [])
        self.assertEqual([item['status'] for item in result['templates']], ['new', 'new'])
        count = len(self.remote.calls)
        records = templates.list_templates(self.store, self.space)
        self.assertEqual(len(records), 2)
        self.assertEqual(len(self.remote.calls), count)
        self.assertTrue((self.root() / '.framework-registry.json').is_file())
        for record in records:
            root = self.root() / record['id']
            self.assertEqual(record['source_version'], '1.0.0')
            self.assertEqual(record['upstream_commit'], 'a' * 40)
            self.assertEqual(record['upstream_ref'], 'create-vite@1.0.0')
            self.assertEqual(record['execution_status'], 'not-run')
            self.assertEqual(record['upstream_license'], 'MIT')
            self.assertIn('GUIDELINES.md', record['files'])
            self.assertIn('template/LICENSE', record['files'])
            self.assertNotIn('manifest.json', record['files'])
            self.assertEqual(record, templates.validate_template(self.store, self.space, record['id']))
            for path, checksum in record['files'].items():
                self.assertEqual(hashlib.sha256((root / path).read_bytes()).hexdigest(), checksum)
            self.assertEqual((root/'template/src/assets/hero.png').read_bytes(), b'\x89PNG\r\n\x1a\nfixture')
            self.assertTrue((root/'template/.gitignore').exists())
        self.assertTrue((self.root()/'react-ts/template/.oxlintrc.json').exists())
        self.assertEqual(before, {space['id']: self.store.pages(space['id']) for space in self.store.spaces()})
        self.assertTrue(all('/main/' not in url and '/commits/main' not in url for url in self.remote.calls))

    async def test_repeat_is_unchanged_without_rewriting_files_or_manifest(self):
        await self.sync(['vue'])
        root = self.root() / 'vue-ts'
        before = {p.relative_to(root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}
        result = await self.sync(['vue'])
        self.assertEqual(result['templates'][0]['status'], 'unchanged')
        after = {p.relative_to(root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        self.assertFalse((self.root()/'.archives').exists())

    async def test_update_archives_complete_old_version_and_updates_guidelines(self):
        await self.sync(['react'])
        original = (self.root()/'react-ts/template/src/App.tsx').read_bytes()
        self.remote.version = '1.1.0'
        self.remote.commit = 'b' * 40
        self.remote.files['react-ts']['src/App.tsx'] = b'export default function App(){ return <main/>; }'
        result = await self.sync(['react'])
        record = result['templates'][0]
        self.assertEqual(record['status'], 'updated')
        archive = self.store.base / record['archive_path']
        self.assertEqual((archive/'template/src/App.tsx').read_bytes(), original)
        self.assertEqual(json.loads((archive/'manifest.json').read_text())['source_version'], '1.0.0')
        self.assertIn('1.1.0', (self.root()/'react-ts/GUIDELINES.md').read_text())
        self.assertIn('template/src/App.tsx', [item['path'] for item in record['changed_files']])
        templates.validate_template(self.store, self.space, 'react-ts')

    async def test_modified_deleted_extra_symlink_and_manifest_edits_block_without_network(self):
        for kind in ['modified', 'deleted', 'extra', 'extra_dir', 'symlink', 'manifest']:
            with self.subTest(kind=kind):
                await self.sync(['vue'])
                root = self.root()/'vue-ts'
                target = root/'template/src/App.vue'
                original = target.read_bytes()
                manifest = (root/'manifest.json').read_bytes()
                if kind == 'modified': target.write_bytes(b'my manual content')
                elif kind == 'deleted': target.unlink()
                elif kind == 'extra': (root/'my-notes.txt').write_text('keep me')
                elif kind == 'extra_dir': (root/'my-empty-dir').mkdir()
                elif kind == 'symlink':
                    target.unlink(); target.symlink_to(self.store.base/'outside')
                else: (root/'manifest.json').write_bytes(manifest + b' ')
                call_count = len(self.remote.calls)
                result = await self.sync(['vue'])
                self.assertEqual(result['templates'][0]['status'], 'conflict')
                self.assertEqual(len(self.remote.calls), call_count)
                with self.assertRaises(ValueError): templates.validate_template(self.store, self.space, 'vue-ts')
                if target.is_symlink(): target.unlink()
                target.write_bytes(original)
                (root/'manifest.json').write_bytes(manifest)
                if (root/'my-notes.txt').exists(): (root/'my-notes.txt').unlink()
                if (root/'my-empty-dir').exists(): (root/'my-empty-dir').rmdir()

    async def test_existing_unmanaged_directory_not_adopted_and_generic_template_untouched(self):
        root=self.root(); (root/'agent-standard').mkdir(parents=True)
        (root/'agent-standard/GUIDELINES.md').write_text('generic contract')
        self.assertEqual(templates.list_templates(self.store, self.space), [])
        (root/'vue-ts').mkdir(); (root/'vue-ts/notes.txt').write_text('manual')
        result=await self.sync(['vue'])
        self.assertEqual(result['templates'][0]['status'], 'conflict')
        self.assertEqual(self.remote.calls, [])
        self.assertEqual((root/'vue-ts/notes.txt').read_text(), 'manual')
        self.assertEqual((root/'agent-standard/GUIDELINES.md').read_text(), 'generic contract')

    async def test_failed_download_never_promotes_partial_initial_or_update(self):
        self.remote.fail_path='src/App.vue'
        result=await self.sync(['vue'])
        self.assertTrue(result['errors'])
        self.assertFalse((self.root()/'vue-ts').exists())
        self.remote.fail_path=None
        await self.sync(['vue'])
        before=(self.root()/'vue-ts/manifest.json').read_bytes()
        self.remote.version='1.1.0'; self.remote.commit='b'*40
        self.remote.fail_path='src/App.vue'
        result=await self.sync(['vue'])
        self.assertTrue(result['errors'])
        self.assertEqual((self.root()/'vue-ts/manifest.json').read_bytes(),before)
        self.assertFalse((self.root()/'.archives').exists())
        templates.validate_template(self.store,self.space,'vue-ts')

    async def test_truncated_tree_blob_mismatch_and_upstream_symlink_are_rejected(self):
        for kind in ['truncated','blob','symlink','submodule']:
            with self.subTest(kind=kind):
                self.remote.truncated=kind=='truncated'
                self.remote.corrupt_blob=kind=='blob'
                self.remote.special_mode='120000' if kind=='symlink' else '160000' if kind=='submodule' else None
                result=await self.sync(['vue'])
                self.assertTrue(result['errors'])
                self.assertFalse((self.root()/'vue-ts').exists())

    async def test_missing_stable_tag_never_falls_back_to_main(self):
        self.remote.missing_tag=True
        result=await self.sync(['react'])
        self.assertTrue(result['errors'])
        self.assertFalse(any('main' in url for url in self.remote.calls))
        self.assertFalse((self.root()/'react-ts').exists())

    async def test_registry_write_failure_rolls_back_complete_current_version(self):
        await self.sync(['vue'])
        old=(self.root()/'vue-ts/manifest.json').read_bytes()
        self.remote.version='1.1.0';self.remote.commit='b'*40
        write=templates._write_json
        def broken(path,value):
            if path.name=='.framework-registry.json': raise OSError('disk full fixture')
            return write(path,value)
        with patch.object(templates,'_write_json',side_effect=broken):
            result=await self.sync(['vue'])
        self.assertTrue(result['errors'])
        self.assertEqual((self.root()/'vue-ts/manifest.json').read_bytes(),old)
        templates.validate_template(self.store,self.space,'vue-ts')
        self.assertEqual(len(list(self.root().glob('.failed-vue-ts-*'))),1)

    async def test_scope_and_invalid_ids_are_rejected(self):
        for space in ['central','software','software-backend','content-design']:
            self.assertFalse(templates.supports_templates(self.store,space))
            with self.assertRaises(ValueError): await templates.sync_templates(self.store,space,['vue'])
        self.assertTrue(templates.supports_templates(self.store,self.space))
        with self.assertRaises(ValueError): await self.sync(['../../outside'])
        self.assertEqual(self.remote.calls,[])
        child=self.store.add_branch('Vue团队','Vue implementation',parent_id=self.space)
        self.assertTrue(templates.supports_templates(self.store,child['id']))

    async def test_same_version_retag_is_not_silently_accepted(self):
        await self.sync(['vue'])
        before=(self.root()/'vue-ts/manifest.json').read_bytes()
        self.remote.commit='b'*40
        result=await self.sync(['vue'])
        self.assertTrue(result['errors'])
        self.assertEqual((self.root()/'vue-ts/manifest.json').read_bytes(),before)


if __name__ == '__main__':
    unittest.main()
