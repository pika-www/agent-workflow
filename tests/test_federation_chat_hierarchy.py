"""Real hierarchy metadata, bounded team selection and native graph topology."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from federation.chat import ChatStore
from federation.core import FederationStore, ROOT
from federation import core


class FederationChatHierarchyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = FederationStore(self.root / "data", project_root=self.root / "project")
        self.store.init()
        self.chat = ChatStore(self.store)

    def tearDown(self):
        self.temporary.cleanup()

    def test_catalog_matches_knowledge_hierarchy_without_exposing_storage(self):
        agents = {agent["id"]: agent for agent in self.chat.agents()}
        self.assertEqual(len(agents), 26)
        self.assertIsNone(agents["central"]["parent_id"])
        self.assertEqual(agents["central"]["child_count"], 4)
        self.assertEqual(agents["software"]["child_count"], 6)
        frontend = agents["software-frontend"]
        self.assertEqual(frontend["parent_id"], "software")
        self.assertEqual(frontend["depth"], 2)
        self.assertEqual(frontend["ancestor_ids"], ["central", "software"])
        self.assertEqual(frontend["breadcrumb"], ["中央智能体知识库", "互联网与软件", "前端"])
        self.assertNotIn(str(self.root), json.dumps(agents, ensure_ascii=False))

    def test_specialists_speak_before_parents_and_central_once(self):
        room = self.chat.create_room("group", ["software-frontend", "software-app"])
        self.assertEqual(room["participants"], ["software-frontend", "software-app", "software", "central"])
        explicit = self.chat.create_room("group", ["central", "software", "software-frontend", "software-app"])
        self.assertEqual(explicit["participants"], room["participants"])
        self.assertEqual(self.chat.create_room("direct", ["software-app"])["participants"], ["software-app"])

    def test_same_depth_selection_order_survives_cross_industry_expansion(self):
        room = self.chat.create_room("group", ["commerce-growth", "software-frontend", "commerce-service"])
        self.assertEqual(room["participants"], ["commerce-growth", "software-frontend", "commerce-service",
                                               "commerce", "software", "central"])

    def test_deeper_specialty_invites_its_full_ancestor_chain(self):
        ios = self.store.add_branch("iOS", "Apple 移动应用", parent_id="software-app")
        swift = self.store.add_branch("Swift", "Swift 语言与 SwiftUI", parent_id=ios["id"])
        room = self.chat.create_room("group", ["software-frontend", swift["id"]])
        self.assertEqual(room["participants"], [swift["id"], ios["id"], "software-frontend",
                                               "software-app", "software", "central"])
        self.assertEqual(self.chat.create_room("direct", [swift["id"]])["participants"], [swift["id"]])

    def test_existing_rooms_keep_members_and_order_when_reopened(self):
        room = self.chat.create_room("group", ["software-frontend"])
        # A room from before automatic hierarchy expansion is a valid durable
        # conversation, even though creating this selection today adds software.
        room["participants"] = ["software-frontend", "central"]
        self.chat.append_message(room, "user", "保留原来的对话成员。")
        restored = ChatStore(self.store).get_room(room["id"])
        self.assertEqual(restored["participants"], ["software-frontend", "central"])
        self.assertEqual(restored["messages"], room["messages"])
        room["participants"] = ["software", "software-frontend", "central"]
        self.chat.save_room(room)
        self.assertEqual(ChatStore(self.store).get_room(room["id"])["participants"], room["participants"])
        self.chat.append_message(room, "assistant", "可以继续讨论。", "software-frontend")

    def test_manual_selection_limit_is_separate_from_expanded_size(self):
        selected = [agent["id"] for agent in self.chat.agents() if agent["depth"] == 2][:8]
        room = self.chat.create_room("group", selected)
        self.assertEqual(len(room["participants"]), 11)
        self.assertEqual(ChatStore(self.store).get_room(room["id"])["participants"], room["participants"])
        with self.assertRaisesRegex(ValueError, "1 至 8"):
            self.chat.create_room("group", selected + ["business-strategy"])

    def test_adding_uiux_does_not_invite_it_to_existing_five_specialist_room(self):
        old_specialties = {parent: [item for item in children if parent != "software" or item[0] != "uiux"]
                           for parent, children in core.SPECIALTIES.items()}
        base = self.root / "before-uiux"
        members = ["software-frontend", "software-app", "software-backend",
                   "software-devops", "software-testing"]
        with patch.object(core, "SPECIALTIES", old_specialties):
            legacy_store = FederationStore(base, project_root=self.root / "project")
            legacy_store.init()
            legacy_chat = ChatStore(legacy_store)
            self.assertNotIn("software-uiux", {agent["id"] for agent in legacy_chat.agents()})
            room = legacy_chat.create_room("group", members)
            legacy_chat.append_message(room, "user", "沿用五位软件专业成员。")
            room_path = legacy_chat.root / (room["id"] + ".json")
            original_bytes = room_path.read_bytes()
        upgraded = FederationStore(base, project_root=self.root / "project")
        upgraded.init()
        chat = ChatStore(upgraded)
        self.assertIn("software-uiux", {agent["id"] for agent in chat.agents()})
        self.assertEqual(chat.get_room(room["id"])["participants"], members + ["software", "central"])
        self.assertEqual(room_path.read_bytes(), original_bytes)
        new_room = chat.create_room("group", ["software-uiux", "software-frontend"])
        self.assertEqual(new_room["participants"], ["software-uiux", "software-frontend", "software", "central"])

    def test_expanded_member_limit_bounds_long_ancestor_chains(self):
        leaves = []
        for starter in ["software-frontend", "content-design", "commerce-growth", "business-strategy"]:
            parent = starter
            for level in range(3, 7):
                parent = self.store.add_branch("细分" + str(level), parent_id=parent)["id"]
            leaves.append(parent)
        with self.assertRaisesRegex(ValueError, "总数不能超过 24"):
            self.chat.create_room("group", leaves)

    def test_specialty_prompt_names_its_exact_scope_and_parent(self):
        room = self.chat.create_room("direct", ["software-frontend"])
        self.chat.append_message(room, "user", "你在团队负责什么？")
        prompt = self.chat.turn_prompt(room, "software-frontend", "direct")
        self.assertIn("中央智能体知识库 → 互联网与软件 → 前端", prompt)
        self.assertIn("直属上级为互联网与软件 Agent", prompt)
        self.assertIn("Web 前端、交互界面、浏览器性能与前端工程化", prompt)
        self.assertIn("唯一知识库标识为 software-frontend", prompt)
        self.assertIn("不得尝试越过当前知识库访问其他 Agent 的文件", prompt)
        self.assertIn("尚无已整理的专业知识页", prompt)

    def test_parent_summary_uses_shared_messages_without_claiming_publication(self):
        room = self.chat.create_room("group", ["software-frontend", "software-app", "commerce-growth"])
        self.chat.append_message(room, "user", "一起讨论新产品上线。")
        self.chat.append_message(room, "assistant", "前端建议先确认浏览器兼容。", "software-frontend")
        self.chat.append_message(room, "assistant", "App 建议核对商店审核。", "software-app")
        prompt = self.chat.turn_prompt(room, "software", "summary")
        self.assertIn("本行业或本专业分支的阶段汇总", prompt)
        self.assertIn("所属分支本轮参与者：前端 Agent、App Agent。", prompt)
        self.assertIn("前端建议先确认浏览器兼容", prompt)
        self.assertIn("不能声称已读过它们的知识库或已将讨论发布入库", prompt)
        self.assertIn("不是已审核知识", prompt)
        self.assertIn("只输出自己的这一次汇总", prompt)

    def test_graph_has_direct_parent_edges_and_namespaced_pages(self):
        frontend_wiki = Path(self.store.space("software-frontend")["wiki_dir"])
        app_wiki = Path(self.store.space("software-app")["wiki_dir"])
        central_wiki = Path(self.store.space("central")["wiki_dir"])
        (frontend_wiki / "handoff.md").write_text("# 前端交接\n", encoding="utf-8")
        (app_wiki / "handoff.md").write_text("# App 交接\n", encoding="utf-8")
        (central_wiki / "overview.md").write_text("# 中央综述\n", encoding="utf-8")
        result = subprocess.run([self.store.node, str(ROOT / "federation/visualizer.mjs"), "--graph"],
                                input=json.dumps({"spaces": self.store.spaces()}), text=True,
                                capture_output=True, check=True)
        graph = json.loads(result.stdout)
        nodes = {node["id"]: node for node in graph["nodes"]}
        edges = {(edge["source"], edge["target"]) for edge in graph["edges"]}
        self.assertEqual(len([node for node in graph["nodes"] if node["isFederationHub"]]), 26)
        self.assertEqual(len([target for source, target in edges if source == "central/index"
                              and nodes[target]["isFederationHub"]]), 4)
        self.assertIn(("software/index", "software-frontend/index"), edges)
        self.assertIn(("software/index", "software-uiux/index"), edges)
        self.assertNotIn(("content/index", "software-uiux/index"), edges)
        self.assertNotIn(("central/index", "software-frontend/index"), edges)
        self.assertIn(("software-frontend/index", "software-frontend/handoff"), edges)
        self.assertIn(("software-app/index", "software-app/handoff"), edges)
        self.assertIn(("central/index", "central/overview"), edges)
        page = nodes["software-frontend/handoff"]
        self.assertEqual(page["parentSpaceId"], "software")
        self.assertEqual(page["spaceDepth"], 2)
        self.assertEqual(page["breadcrumb"], ["中央智能体知识库", "互联网与软件", "前端"])
        self.assertIn("../software-frontend/index.md", nodes["software/index"]["body"])
        self.assertNotIn("software-frontend/index.md", nodes["central/index"]["body"])
        self.assertNotIn("software-app/handoff.md", nodes["software-frontend/index"]["body"])

    def test_graph_preserves_original_page_and_supports_legacy_flat_input(self):
        result = subprocess.run([self.store.node, str(ROOT / "federation/visualizer.mjs"), "--verify"],
                                text=True, capture_output=True, check=True)
        evidence = json.loads(result.stdout)
        self.assertTrue(evidence["originalPagePreserved"])
        self.assertTrue(evidence["nestedParentLinks"])
        self.assertTrue(evidence["cyclicHierarchyRejected"])
        self.assertEqual(evidence["centralHubEdges"], 4)


if __name__ == "__main__":
    unittest.main()
