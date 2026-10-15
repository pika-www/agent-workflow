"""Structural and local-code checks; these are not SDK or device build tests."""
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

import pytest

from federation.specialist_catalog import _pack
from federation.web_ecosystem_templates import build_web_ecosystem_templates


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def packs():
    return {pack["id"]: pack for pack in build_web_ecosystem_templates(_pack)}


def node_binary():
    binary = shutil.which("node")
    if not binary:
        binary = next(iter(sorted((Path.home() / ".nvm/versions/node").glob("*/bin/node"))), None)
    if not binary:
        pytest.skip("Node.js unavailable; JavaScript behavior not tested")
    return str(binary)


def run_node(script, payload):
    result = subprocess.run([node_binary(), "-e", script], input=json.dumps(payload),
                            text=True, capture_output=True, check=False, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_catalog_outputs_are_independent_and_safe_document_sets(packs):
    assert len(packs) == 8
    for pack in packs.values():
        assert pack["kind"] == "specialist"
        assert pack["upstream_commit"] == ""
        assert pack["source_url"].startswith("local-policy://specialist/")
        docs = pack["documents"]
        for required in ("GUIDELINES.md", "template/SCAFFOLD.md", "template/EXAMPLE.md", "template/CHECKLIST.md"):
            assert docs[required].strip()
        for relative_path, body in docs.items():
            path = PurePosixPath(relative_path)
            assert not path.is_absolute() and ".." not in path.parts
            assert body.endswith("\n")
            if path.suffix == ".json":
                json.loads(body)
        assert "本项目原创适配" in docs["GUIDELINES.md"]
        assert "未构建完整工程" in docs["GUIDELINES.md"]
    packs["nextjs-app"]["documents"]["template/app/page.tsx"] = "local change"
    fresh = {p["id"]: p for p in build_web_ecosystem_templates(_pack)}
    assert fresh["nextjs-app"]["documents"]["template/app/page.tsx"] != "local change"


def test_wechat_route_and_event_bindings_resolve_to_actual_page(packs):
    docs = packs["wechat-miniprogram"]["documents"]
    config = json.loads(docs["template/app.json"])
    assert config["pages"]
    for page in config["pages"]:
        for extension in ("js", "json", "wxml", "wxss"):
            assert "template/" + page + "." + extension in docs
    markup = ET.fromstring(docs["template/pages/draft/index.wxml"])
    events = [value for element in markup.iter() for name, value in element.attrib.items() if name.startswith("bind")]
    assert events
    run_node("""
      const fs = require('node:fs');
      const vm = require('node:vm');
      const assert = require('node:assert/strict');
      const input = JSON.parse(fs.readFileSync(0, 'utf8'));
      let page;
      vm.runInNewContext(input.code, { Page: (value) => { page = value; } }, { timeout: 1000 });
      for (const event of input.events) assert.equal(typeof page[event], 'function', event);
    """, {"code": docs["template/pages/draft/index.js"], "events": events})


def test_wechat_local_page_handles_empty_normal_and_long_values_without_network(packs):
    docs = packs["wechat-miniprogram"]["documents"]
    run_node("""
      const fs = require('node:fs');
      const vm = require('node:vm');
      const assert = require('node:assert/strict');
      const input = JSON.parse(fs.readFileSync(0, 'utf8'));
      let definition;
      vm.runInNewContext(input.code, { Page: (value) => { definition = value; } }, { timeout: 1000 });
      const page = { ...definition, data: { ...definition.data }, setData(update) { Object.assign(this.data, update); } };
      assert.equal(page.data.ready, false);
      page.onTitleInput({ detail: { value: '   ' } });
      page.previewDraft();
      assert.equal(page.data.ready, false);
      assert.equal(page.data.message, '请输入非空白标题');
      page.onTitleInput({ detail: { value: '  New draft  ' } });
      page.previewDraft();
      assert.equal(page.data.ready, true);
      assert.equal(page.data.message, 'DEMO 本地草稿：New draft');
      page.onTitleInput({ detail: { value: 'changed' } });
      assert.equal(page.data.message, '内容已更改，尚未生成草稿');
      page.onTitleInput({ detail: { value: 'a'.repeat(81) } });
      assert.equal(page.data.title.length, 80);
      page.previewDraft();
      assert.equal(page.data.message, 'DEMO 本地草稿：' + 'a'.repeat(80));
    """, {"code": docs["template/pages/draft/index.js"]})


def test_uni_pages_resolve_and_platform_recipe_retains_real_scaffold(packs):
    docs = packs["uniapp-vue"]["documents"]
    config = json.loads(docs["template/src/pages.json"])
    for page in config["pages"]:
        assert "template/src/" + page["path"] + ".vue" in docs
    manifest = json.loads(docs["template/src/manifest.example.json"])
    assert manifest["appid"] == manifest["mp-weixin"]["appid"] == ""
    assert "template/src/manifest.json" not in docs  # Intentionally not a complete application manifest.
    assert "createSSRApp" in docs["template/src/main.ts"]
    assert "build:mp-weixin" in docs["template/SCAFFOLD.md"]


def test_taro_build_time_configs_register_an_existing_page(packs):
    docs = packs["taro-react"]["documents"]
    config = docs["template/src/app.config.ts"]
    result = run_node("""
      const fs = require('node:fs');
      const vm = require('node:vm');
      const input = JSON.parse(fs.readFileSync(0, 'utf8'));
      const code = input.code.replace('export default ', 'result = ');
      const context = { defineAppConfig: (value) => value };
      vm.runInNewContext(code, context, { timeout: 1000 });
      process.stdout.write(JSON.stringify(context.result));
    """, {"code": config})
    for page in json.loads(result)["pages"]:
        assert "template/src/" + page + ".tsx" in docs
        assert "template/src/" + page + ".config.ts" in docs
    assert "event.detail.value" in docs["template/src/pages/draft/index.tsx"]
    assert "event.target.value" not in docs["template/src/pages/draft/index.tsx"]


def test_next_server_client_boundary_and_local_imports(packs):
    docs = packs["nextjs-app"]["documents"]
    page = docs["template/app/page.tsx"]
    form = docs["template/app/ui/draft-form.tsx"]
    assert "use client" not in page
    assert form.startswith("'use client';")
    imported = re.search(r"import DraftForm from '([^']+)'", page).group(1)
    assert "template/app/" + imported.removeprefix("./") + ".tsx" in docs
    layout = docs["template/app/layout.tsx"]
    assert "<html" in layout and "<body>" in layout


def test_native_web_and_svelte_scopes_are_not_silently_interchangeable(packs):
    expo = packs["expo-react-native"]["documents"]
    platforms = json.loads(expo["template/PLATFORMS.json"])
    assert platforms["entry_variant"] == "blank-typescript"
    assert set(platforms["targets_to_validate"]) == {"android", "ios", "web"}
    assert platforms["sdk_build_status"] == platforms["device_test_status"] == "not-run"
    assert "template/" + platforms["entry"] in expo
    assert "<div" not in expo["template/App.tsx"] and "react-native" in expo["template/App.tsx"]
    svelte = packs["svelte-component"]["documents"]
    assert "$state(" in svelte["template/src/routes/+page.svelte"]
    assert "$derived(" in svelte["template/src/routes/+page.svelte"]
    assert "SvelteKit" in svelte["template/SCAFFOLD.md"]


def test_typescript_and_tsx_parse_with_available_local_typescript_compiler(packs):
    # Parsing is useful without SDK installation but deliberately does not claim type/build success.
    candidates = sorted((ROOT / "openwiki-upstream/node_modules/.pnpm").glob("typescript@*/node_modules/typescript/lib/typescript.js"))
    if not candidates:
        pytest.skip("No local TypeScript compiler; syntax check not performed")
    files = {}
    for pack in packs.values():
        for path, body in pack["documents"].items():
            if path.endswith((".ts", ".tsx")):
                files[pack["id"] + "/" + path] = body
            elif path.endswith((".vue", ".svelte")):
                match = re.search(r'<script[^>]*lang="ts"[^>]*>(.*?)</script>', body, re.S)
                if match:
                    files[pack["id"] + "/" + path + ".ts"] = match.group(1)
    assert len(files) >= 13
    run_node("""
      const fs = require('node:fs');
      const assert = require('node:assert/strict');
      const input = JSON.parse(fs.readFileSync(0, 'utf8'));
      const ts = require(input.compiler);
      for (const [name, source] of Object.entries(input.files)) {
        const kind = name.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
        const tree = ts.createSourceFile(name, source, ts.ScriptTarget.Latest, true, kind);
        assert.equal(tree.parseDiagnostics.length, 0, name + ': ' + tree.parseDiagnostics.map(d => d.messageText).join('; '));
      }
    """, {"compiler": str(candidates[-1]), "files": files})
