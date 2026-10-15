"""Isolated tests for actual industry boundaries and reviewed publication."""
import json
import os
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch

from federation.core import BRANCHES, SPECIALTIES, BUILTIN_CONNECTOR_IDS, FederationStore, SNAPSHOT_NOTE
from federation import core


class FederationCoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = self.root / "project"
        (self.project / "openwiki-data").mkdir(parents=True)
        (self.project / "openwiki-data/.env").write_text("OPENWIKI_PROVIDER=openai-compatible\nOPENAI_COMPATIBLE_API_KEY=ollama\n", encoding="utf-8")
        self.store = FederationStore(self.root / "federation", project_root=self.project)
        self.store.init()

    def tearDown(self):
        self.temporary.cleanup()

    def add_page(self, branch="software", relative="topics/验收.md", body="# 示例事实\n\n来源：虚构验收.md\n负责人：陈知。\n"):
        target = Path(self.store.space(branch)["wiki_dir"]) / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        return target

    def test_isolated_state_and_mcp_roots(self):
        spaces = self.store.spaces()
        expected = {"central", *(key for key, _, _ in BRANCHES)}
        expected.update(parent + '-' + suffix for parent, specs in SPECIALTIES.items() for suffix, _, _ in specs)
        self.assertEqual({item["id"] for item in spaces}, expected)
        self.assertEqual(len({item["state_dir"] for item in spaces}), len(expected))
        for item in spaces:
            state = Path(item["state_dir"])
            config = json.loads((state / "connectors/custom-mcp/config.json").read_text())
            expected = self.store.base / "published" if item["id"] == "central" else self.store.base / "branches" / item["id"] / "inbox"
            self.assertEqual(config["transport"]["args"][1:], [str(expected)])
            self.assertEqual(item["knowledge_count"], 0)
            self.assertEqual(item["pending_count"], 0)
            self.assertEqual((state / ".env").stat().st_mode & 0o777, 0o600)
        self.assertNotIn("state", json.dumps(json.loads((Path(self.store.space("central")["state_dir"]) / "connectors/custom-mcp/config.json").read_text())["transport"]["args"][1:]))

    def test_init_preserves_edits_and_sources(self):
        state = Path(self.store.space("software")["state_dir"])
        (state / "INSTRUCTIONS.md").write_text("用户的职责调整", encoding="utf-8")
        (state / ".env").write_text("USER_CONFIG=retained\n", encoding="utf-8")
        self.store.add_source("software", "原文.md", "# 用户资料\n保留原文")
        self.store.init()
        self.assertEqual((state / "INSTRUCTIONS.md").read_text(), "用户的职责调整")
        self.assertEqual((state / ".env").read_text(), "USER_CONFIG=retained\n")
        self.assertEqual(self.store.sources("software")[0]["name"], "原文.md")
        self.assertEqual(self.store.sources("commerce"), [])

    def test_traversal_and_symlink_rejected(self):
        self.add_page()
        for relative in ("../.env", "/etc/passwd.md", "topics/../../.env", "topics\\escape.md"):
            with self.assertRaises(ValueError):
                self.store.page("software", relative)
        external = self.root / "external.md"
        external.write_text("private", encoding="utf-8")
        wiki = Path(self.store.space("software")["wiki_dir"])
        (wiki / "escape.md").symlink_to(external)
        (wiki / "outside").symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.store.page("software", "escape.md")
        with self.assertRaises(ValueError):
            self.store.page("software", "outside/external.md")
        self.assertNotIn("escape.md", {item["path"] for item in self.store.pages("software")})
        with self.assertRaises(ValueError):
            self.store.space("../central")

    def test_upload_size_and_no_overwrite(self):
        original = "原始文件不会被覆盖"
        self.store.add_source("software", "事实.txt", original)
        with self.assertRaises(ValueError):
            self.store.add_source("software", "事实.txt", "替换")
        for filename in ("../outside.md", ".hidden.md", "directory/name.md", "invalid.pdf"):
            with self.assertRaises(ValueError):
                self.store.add_source("software", filename, "test")
        with self.assertRaises(ValueError):
            self.store.add_source("central", "原文.md", "不允许直接上传中央")
        with self.assertRaises(ValueError):
            self.store.add_source("software", "large.md", "中" * 27_000)
        self.assertEqual((self.store.base / "branches/software/inbox/事实.txt").read_text(), original)

    def test_template_cannot_be_published(self):
        review = self.store.review("software")
        with self.assertRaisesRegex(ValueError, "模板"):
            self.store.publish("software", review["token"])
        self.assertFalse((self.store.base / "published/software").exists())

    def test_other_connectors_explicitly_disabled_without_overwriting_user_config(self):
        for space in self.store.spaces():
            state = Path(space["state_dir"])
            for identifier in BUILTIN_CONNECTOR_IDS:
                if identifier == "custom-mcp":
                    continue
                config = json.loads((state / "connectors" / identifier / "config.json").read_text())
                self.assertIs(config["enabled"], False)
                if identifier == "git-repo":
                    self.assertEqual(config["repos"], [])
                if identifier == "google":
                    self.assertNotIn("readOnlyOperations", config)
                    self.assertNotIn("transport", config)
        config_path = Path(self.store.space("software")["state_dir"]) / "connectors/hackernews/config.json"
        user_config = '{"enabled": true, "queries": ["user-preserved"]}'
        config_path.write_text(user_config)
        with self.assertRaisesRegex(ValueError, "hackernews"):
            self.store.init()
        self.assertEqual(config_path.read_text(), user_config)

    def test_git_repo_and_legacy_gmail_cannot_bypass_disabled_flag(self):
        state = Path(self.store.space("software")["state_dir"])
        git_config = state / "connectors/git-repo/config.json"
        git_config.write_text('{"enabled": false, "repos": [{"id":"outside","path":"/tmp"}]}')
        with self.assertRaisesRegex(ValueError, "git-repo"):
            self.store.init()
        git_config.write_text('{"enabled": false, "repos": []}')
        google_config = state / "connectors/google/config.json"
        google_config.write_text('{"enabled": false, "readOnlyOperations": []}')
        with self.assertRaisesRegex(ValueError, "google"):
            self.store.init()

    def test_new_connector_in_upstream_registry_gets_disabled(self):
        registry = self.project / "openwiki-upstream/src/connectors/registry.ts"
        registry.parent.mkdir(parents=True)
        registry.write_text('export const CONNECTOR_IDS = ["custom-mcp", "future-source"] as const;')
        self.store.init()
        for space in self.store.spaces():
            config = Path(space["state_dir"]) / "connectors/future-source/config.json"
            self.assertIs(json.loads(config.read_text())["enabled"], False)

    def test_new_industry_is_isolated_and_survives_restart(self):
        branch = self.store.add_branch("医疗健康", "医疗行业知识与流程资料")
        self.assertRegex(branch["id"], r"^branch-[a-f0-9]{12}$")
        self.assertEqual(branch["knowledge_count"], 0)
        self.assertEqual(branch["pending_count"], 0)
        self.store.add_source(branch["id"], "示例.md", "明确标注的虚构验收资料")
        restarted = FederationStore(self.store.base, project_root=self.project)
        restarted.init()
        self.assertEqual(restarted.space(branch["id"])["name"], "医疗健康")
        self.assertEqual(restarted.space(branch["id"])["source_count"], 1)
        self.assertEqual(len(restarted.spaces()), 27)
        config = json.loads((Path(branch["state_dir"]) / "connectors/custom-mcp/config.json").read_text())
        self.assertEqual(config["transport"]["args"][1:], [branch["source_dir"]])
        self.assertTrue((self.store.base / "registry.json").is_file())
        self.assertFalse((self.store.base / "published/registry.json").exists())
        self.assertEqual(restarted.sources("central"), [])

    def test_new_industry_validates_name_scope_and_registry_ids(self):
        for name, description in (("", ""), ("空\n行", ""), ("名" * 41, ""), ("新行业", "责" * 301)):
            with self.assertRaises(ValueError):
                self.store.add_branch(name, description)
        with self.assertRaises(ValueError):
            self.store.add_branch("互联网与软件")
        self.store.add_branch("Analytics")
        with self.assertRaises(ValueError):
            self.store.add_branch(" analytics ")
        (self.store.base / "registry.json").write_text(json.dumps({"version": 1, "branches": [{"id": "../../outside", "name": "越界", "description": ""}]}))
        with self.assertRaisesRegex(ValueError, "注册表"):
            FederationStore(self.store.base, project_root=self.project)

    def test_stale_review_cannot_publish_changed_added_or_removed_pages(self):
        file = self.add_page()
        token = self.store.review("software")["token"]
        file.write_text("# 已变更", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "变化"):
            self.store.publish("software", token)
        token = self.store.review("software")["token"]
        second = self.add_page(relative="新增.md")
        with self.assertRaises(ValueError):
            self.store.publish("software", token)
        token = self.store.review("software")["token"]
        second.unlink()
        with self.assertRaises(ValueError):
            self.store.publish("software", token)
        self.assertFalse((self.store.base / "published/software").exists())

    def test_publication_preserves_original_provenance_and_old_snapshot(self):
        self.store.add_source("software", "虚构验收.md", "示例来源原文，不应改变")
        draft = self.add_page()
        initial_body = draft.read_text()
        self.assertFalse((self.store.base / "published/software/topics/验收.md").exists())
        review = self.store.review("software")
        result = self.store.publish("software", review["token"])
        destination = self.store.base / "published/software"
        self.assertEqual((destination / "topics/验收.md").read_text(), initial_body)
        provenance = (destination / SNAPSHOT_NOTE).read_text()
        self.assertIn(result["version"], provenance)
        self.assertIn(str(draft.parent.parent), provenance)
        self.assertIn("software", provenance)
        self.assertFalse((destination / "manifest.json").exists())
        self.assertEqual(self.store.space("software")["pending_count"], 0)
        self.assertEqual(self.store.space("software")["published_count"], 2)
        self.assertEqual(self.store.space("software")["knowledge_count"], 1)
        draft.write_text("# 示例事实\n第二版", encoding="utf-8")
        self.assertEqual(self.store.space("software")["pending_count"], 1)
        next_review = self.store.review("software")
        second = self.store.publish("software", next_review["token"])
        self.assertNotEqual(result["version"], second["version"])
        backup = self.store.base / "backups/software" / second["version"]
        self.assertEqual((backup / "topics/验收.md").read_text(), initial_body)
        self.assertEqual((destination / "topics/验收.md").read_text(), draft.read_text())
        self.assertEqual((self.store.base / "branches/software/inbox/虚构验收.md").read_text(), "示例来源原文，不应改变")
        self.assertEqual(self.store.space("commerce")["published_count"], 0)
        self.assertTrue(any(source["name"] == "software/" + SNAPSHOT_NOTE for source in self.store.sources("central")))

    def test_native_invocation_and_secret_isolation(self):
        with patch.dict(os.environ, {"OPENWIKI_CONFIG_DIR": "/wrong", "OPENWIKI_PROVIDER": "wrong",
                                     "OPENAI_API_KEY": "not-inherited", "ANTHROPIC_API_KEY": "not-inherited",
                                     "LANGSMITH_TRACING": "true", "SOME_SECRET": "not-inherited"}):
            environment = self.store.env_native("software")
        self.assertEqual(environment["OPENWIKI_CONFIG_DIR"], self.store.space("software")["state_dir"])
        for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENWIKI_PROVIDER", "SOME_SECRET"):
            self.assertNotIn(key, environment)
        self.assertEqual(environment["LANGSMITH_TRACING"], "false")
        self.add_page()
        self.store.publish("software", self.store.review("software")["token"])
        command = self.store.native_command("central", "sync")
        self.assertEqual(command[1:3], ["--input-type=module", "-e"])
        payload = json.loads(command[-1])
        self.assertEqual(payload["expectedReads"], 3)
        self.assertTrue(all(path.startswith(str(self.store.base / "published") + "/") for path in payload["sourceFiles"]))
        self.assertIn("未发布", payload["prompt"])
        self.assertIn("'--language', 'zh-CN'", command[3])
        with self.assertRaises(ValueError):
            self.store.native_command("software", "sync")
        with self.assertRaises(ValueError):
            self.store.native_command("central", "learn")
        ask = self.store.native_command("software", "ask", "实际问题")
        self.assertNotIn("--update", ask)
        self.assertIn("实际问题", ask[-1])

    def test_deterministic_native_preparation_uses_real_safe_files(self):
        with self.assertRaises(ValueError):
            self.store.native_command("software", "learn")
        self.store.add_source("software", "实际资料.md", "# 虚构示例\n确实存在的中文正文")
        self.store.add_source("commerce", "其他行业.md", "不应读取")
        source = Path(self.store.space("software")["source_dir"])
        (source / "escape.md").symlink_to(self.root / "missing.md")
        command = self.store.native_command("software", "learn")
        payload = json.loads(command[-1])
        self.assertEqual(payload["sourceFiles"], [str(source / "实际资料.md")])
        self.assertEqual(payload["expectedReads"], 1)
        state = Path(self.store.space("software")["state_dir"])
        config = json.loads((state / "connectors/custom-mcp/config.json").read_text())
        self.assertEqual(config["readOnlyOperations"], [{"type": "tool", "name": "read_text_file", "args": {"path": str(source / "实际资料.md")}}])
        instance = json.loads((state / "onboarding.json").read_text())["sourceInstances"][0]
        self.assertEqual(instance["connectorConfig"], config)
        self.assertIn("isError === true", command[3])
        self.assertIn("openwiki_read_raw_item", command[3])
        self.assertIn("仍应整理成独立示例", payload["prompt"])

    def fake_upstream_prefetch(self, fail=False):
        upstream = self.project / "openwiki-upstream"
        (upstream / "dist/connectors").mkdir(parents=True)
        (upstream / "dist/cli").mkdir(parents=True)
        (upstream / "package.json").write_text('{"type":"module"}')
        registry = '''
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
export function createConnectorRegistry() { return {'custom-mcp': {ingest: async () => {
  const root = path.join(process.env.OPENWIKI_CONFIG_DIR, 'connectors/custom-mcp');
  const config = JSON.parse(await readFile(path.join(root, 'config.json'), 'utf8'));
  const operations = [];
  for (const op of config.readOnlyOperations) operations.push({name: op.name, type: op.type,
    result: {isError: FAIL_FLAG, content: [{type: 'text', text: await readFile(op.args.path, 'utf8')}]}});
  const raw = path.join(root, 'raw/test-run/mcp-results.json');
  await mkdir(path.dirname(raw), {recursive:true});
  await writeFile(raw, JSON.stringify({operations, readOnlyOperations:config.readOnlyOperations}));
  return {status:'success', rawFiles:[raw]};
}}};}
'''.replace('FAIL_FLAG', 'true' if fail else 'false')
        (upstream / "dist/connectors/registry.js").write_text(registry)
        marker = self.project / "updater-called.json"
        (upstream / "dist/cli/cli.js").write_text("import {writeFile} from 'node:fs/promises';\nawait writeFile(" + json.dumps(str(marker)) + ", JSON.stringify(process.argv.slice(2)));\n")
        return marker

    def test_prefetch_error_prevents_model_updater(self):
        marker = self.fake_upstream_prefetch(fail=True)
        self.store.add_source("software", "source.md", "# Actual source")
        result = subprocess.run(self.store.native_command("software", "learn"), env=self.store.env_native("software"),
                                capture_output=True, text=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("正文读取失败", result.stderr)
        self.assertFalse(marker.exists())

    def test_prefetch_success_gives_raw_path_to_chinese_native_updater(self):
        marker = self.fake_upstream_prefetch()
        self.store.add_source("software", "source.md", "# 实际中文正文\n明确虚构示例")
        result = subprocess.run(self.store.native_command("software", "learn"), env=self.store.env_native("software"),
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        arguments = json.loads(marker.read_text())
        self.assertEqual(arguments[:5], ["personal", "--language", "zh-CN", "--update", "--print"])
        self.assertIn("test-run/mcp-results.json", arguments[-1])
        receipt = json.loads((Path(self.store.space("software")["state_dir"]) / "last-prefetch.json").read_text())
        self.assertEqual(receipt["operationCount"], 1)
        self.assertEqual(receipt["rawItems"], ["test-run/mcp-results.json"])

    def test_failed_publication_restores_previous_snapshot(self):
        draft = self.add_page()
        first = self.store.publish("software", self.store.review("software")["token"])
        original = draft.read_text()
        draft.write_text("# 第二版\n待发布", encoding="utf-8")
        real_write = core._write_json

        def fail_current_metadata(path, value):
            if path == self.store.base / "metadata/software.json":
                raise OSError("injected metadata failure")
            return real_write(path, value)

        with patch.object(core, "_write_json", side_effect=fail_current_metadata):
            with self.assertRaises(OSError):
                self.store.publish("software", self.store.review("software")["token"])
        self.assertEqual((self.store.base / "published/software/topics/验收.md").read_text(), original)
        self.assertEqual(self.store.space("software")["published_version"], first["version"])
        self.assertEqual(self.store.space("software")["pending_count"], 1)


if __name__ == "__main__":
    unittest.main()
