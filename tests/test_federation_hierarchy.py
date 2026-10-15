"""Hierarchy migration, nested isolation and additive initialization checks."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from federation.core import BRANCHES, MAX_BRANCH_DEPTH, SPECIALTIES, FederationStore


class FederationHierarchyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = self.root / "project"
        (self.project / "openwiki-data").mkdir(parents=True)
        (self.project / "openwiki-data/.env").write_text("LOCAL_MODEL=preserve\n", encoding="utf-8")
        self.base = self.root / "federation"

    def tearDown(self):
        self.temporary.cleanup()

    def store(self):
        store = FederationStore(self.base, project_root=self.project)
        store.init()
        return store

    def registry(self, branches, version=2):
        self.base.mkdir(parents=True, exist_ok=True)
        path = self.base / "registry.json"
        path.write_text(json.dumps({"version": version, "branches": branches}, ensure_ascii=False), encoding="utf-8")
        return path

    def test_default_tree_has_isolated_empty_specialties(self):
        store = self.store()
        spaces = {space["id"]: space for space in store.spaces()}
        self.assertEqual(len(spaces), 26)
        central = spaces["central"]
        self.assertIsNone(central["parent_id"])
        self.assertEqual(central["depth"], 0)
        self.assertEqual(central["ancestor_ids"], [])
        self.assertEqual(set(central["children_ids"]), {key for key, _, _ in BRANCHES})
        self.assertEqual(central["child_count"], 4)
        self.assertEqual(len({space["source_dir"] for space in spaces.values()}), len(spaces))
        self.assertEqual(len({space["wiki_dir"] for space in spaces.values()}), len(spaces))
        for parent, name, _ in BRANCHES:
            self.assertEqual(spaces[parent]["depth"], 1)
            self.assertEqual(spaces[parent]["child_count"], len(SPECIALTIES[parent]))
            for suffix, specialty, _ in SPECIALTIES[parent]:
                identifier = parent + "-" + suffix
                space = spaces[identifier]
                self.assertEqual(space["name"], specialty)
                self.assertEqual(space["parent_id"], parent)
                self.assertEqual(space["ancestor_ids"], ["central", parent])
                self.assertEqual(space["breadcrumb"], [central["name"], name, specialty])
                self.assertEqual(space["depth"], 2)
                self.assertEqual(space["child_count"], 0)
                self.assertEqual(space["knowledge_count"], 0)
                self.assertEqual(space["source_count"], 0)
                self.assertEqual(space["pending_count"], 0)
                state = Path(space["state_dir"])
                connector = json.loads((state / "connectors/custom-mcp/config.json").read_text())
                self.assertEqual(connector["transport"]["args"][1:], [space["source_dir"]])
                self.assertIn(" / ".join(space["breadcrumb"]), (state / "INSTRUCTIONS.md").read_text())
                self.assertIn(" / ".join(space["breadcrumb"]), store.page(identifier, "index.md")["body"])

    def test_uiux_has_software_parent_and_independent_knowledge_from_visual_design(self):
        store = self.store()
        uiux = store.space("software-uiux")
        visual = store.space("content-design")
        self.assertEqual(uiux["name"], "UI/UX 设计师")
        self.assertEqual(uiux["parent_id"], "software")
        self.assertEqual(visual["parent_id"], "content")
        self.assertEqual(uiux["ancestor_ids"], ["central", "software"])
        for field in ("state_dir", "wiki_dir", "source_dir"):
            self.assertNotEqual(uiux[field], visual[field])
            self.assertTrue(Path(uiux[field]).is_dir())
        store.add_source("software-uiux", "界面交接.md", "DEMO：产品表单的空态和校验规范。")
        (Path(uiux["wiki_dir"]) / "component-states.md").write_text("# DEMO 组件状态规范\n", encoding="utf-8")
        self.assertEqual(store.space("software-uiux")["source_count"], 1)
        self.assertEqual(store.space("software-uiux")["knowledge_count"], 1)
        for other in ("content-design", "software-frontend", "software", "central"):
            self.assertEqual(store.sources(other), [])
            self.assertEqual(store.space(other)["knowledge_count"], 0)

    def test_v1_migrates_once_and_preserves_existing_files(self):
        identifier = "branch-012345abcdef"
        registry = self.registry([{"id": identifier, "name": "既有行业", "description": "用户旧职责"}], version=1)
        protected = {}
        for relative, content in {
            "branches/software/state/wiki/index.md": "# 原来的索引与人工链接\n",
            "branches/software/state/INSTRUCTIONS.md": "保留用户的行业指令\n",
            "branches/software/state/.env": "USER_MODEL=preserve\n",
            "branches/software/inbox/原文.md": "用户原文\n",
            f"branches/{identifier}/state/wiki/业务.md": "# 已有真实业务资料\n",
            "chat/rooms/existing.json": '{"messages":["原聊天保留"]}',
            "published/software/既有快照.md": "# 已审核版本\n",
        }.items():
            path = self.base / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            protected[path] = hashlib.sha256(path.read_bytes()).hexdigest()
        store = self.store()
        self.assertEqual(store.space(identifier)["parent_id"], "central")
        migrated = json.loads(registry.read_text())
        self.assertEqual(migrated["version"], 2)
        self.assertEqual(migrated["branches"][0]["parent_id"], "central")
        saved = registry.read_bytes()
        timestamp = registry.stat().st_mtime_ns
        self.store()
        self.assertEqual(registry.read_bytes(), saved)
        self.assertEqual(registry.stat().st_mtime_ns, timestamp)
        for path, digest in protected.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest, str(path))

    def test_nested_additions_survive_init_and_restart(self):
        store = self.store()
        first = store.add_branch("Web 框架", "前端框架实践", parent_id="software-frontend")
        second = store.add_branch("Vue", "Vue 工程知识", parent_id=first["id"])
        third = store.add_branch("React", "React 工程知识", parent_id=first["id"])
        store.init()
        restarted = self.store()
        self.assertEqual(restarted.space(second["id"])["parent_id"], first["id"])
        self.assertEqual(restarted.space(second["id"])["depth"], 4)
        self.assertEqual(restarted.space(first["id"])["children_ids"], [second["id"], third["id"]])
        self.assertEqual(restarted.space(second["id"])["ancestor_ids"], ["central", "software", "software-frontend", first["id"]])
        persisted = json.loads((self.base / "registry.json").read_text())
        self.assertEqual(len(persisted["branches"]), 3)
        self.assertTrue(all(item["parent_id"] for item in persisted["branches"]))

    def test_names_are_unique_only_among_siblings(self):
        store = self.store()
        one = store.add_branch("交付", parent_id="software-frontend")
        two = store.add_branch("交付", parent_id="software-backend")
        self.assertNotEqual(one["id"], two["id"])
        with self.assertRaisesRegex(ValueError, "同名"):
            store.add_branch(" 交付 ", parent_id="software-frontend")
        with self.assertRaisesRegex(ValueError, "同名"):
            store.add_branch("app", parent_id="software")
        self.assertEqual(self.store().space(two["id"])["parent_id"], "software-backend")

    def test_depth_limit_and_unknown_parent_do_not_mutate_registry(self):
        store = self.store()
        parent = "software-frontend"
        for depth in range(3, MAX_BRANCH_DEPTH + 1):
            child = store.add_branch(f"第{depth}层", parent_id=parent)
            self.assertEqual(child["depth"], depth)
            parent = child["id"]
        original = (self.base / "registry.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "最多"):
            store.add_branch("超过深度", parent_id=parent)
        for invalid in ("unknown", "../software", None, 123):
            with self.assertRaises(ValueError):
                store.add_branch("无效上级", parent_id=invalid)
        self.assertEqual((self.base / "registry.json").read_bytes(), original)

    def test_invalid_v2_graph_rejected_without_rewriting_registry(self):
        a, b = "branch-000000000001", "branch-000000000002"
        cases = [
            [{"id": a, "name": "缺父级"}],
            [{"id": a, "name": "空父级", "parent_id": None}],
            [{"id": a, "name": "不存在", "parent_id": "unknown"}],
            [{"id": a, "name": "自循环", "parent_id": a}],
            [{"id": a, "name": "循环甲", "parent_id": b}, {"id": b, "name": "循环乙", "parent_id": a}],
            [{"id": a, "name": "重复", "parent_id": "software"}, {"id": b, "name": "重复", "parent_id": "software"}],
            [{"id": a, "name": "App", "parent_id": "software"}],
            [{"id": "software-frontend", "name": "覆盖内置", "parent_id": "central"}],
        ]
        for branches in cases:
            with self.subTest(branches=branches):
                path = self.registry(branches)
                original = path.read_bytes()
                with self.assertRaisesRegex(ValueError, "注册表"):
                    self.store()
                self.assertEqual(path.read_bytes(), original)

    def test_v2_can_load_child_before_parent_without_reparenting(self):
        parent, child = "branch-000000000001", "branch-000000000002"
        self.registry([{"id": child, "name": "子分支", "parent_id": parent},
                       {"id": parent, "name": "父分支", "parent_id": "content-design"}])
        store = self.store()
        self.assertEqual(store.space(child)["ancestor_ids"], ["central", "content", "content-design", parent])
        store.add_branch("另一行业")
        self.assertEqual(self.store().space(child)["parent_id"], parent)

    def test_child_knowledge_is_not_merged_into_parent(self):
        store = self.store()
        store.add_source("software-frontend", "前端验收.md", "明确虚构的前端验收资料")
        child_wiki = Path(store.space("software-frontend")["wiki_dir"])
        (child_wiki / "知识.md").write_text("# 前端虚构事实\n来源：前端验收.md\n", encoding="utf-8")
        for other in ("software", "software-backend", "central"):
            self.assertEqual(store.space(other)["knowledge_count"], 0)
            self.assertEqual(store.sources(other), [])
        published = store.publish("software-frontend", store.review("software-frontend")["token"])
        self.assertEqual(published["parent_id"], "software")
        self.assertEqual(published["breadcrumb"][-2:], ["互联网与软件", "前端"])
        self.assertEqual(store.space("software")["knowledge_count"], 0)
        self.assertEqual(store.sources("software"), [])
        self.assertTrue(all(source["name"].startswith("software-frontend/") for source in store.sources("central")))
        self.assertIn("software-frontend", store.native_command("software-frontend", "ask", "说明来源")[-1])


if __name__ == "__main__":
    unittest.main()
