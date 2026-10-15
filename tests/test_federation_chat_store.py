"""Exercise durable room state, membership boundaries and shared prompt context."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from federation.chat import ChatStore, HISTORY_CHAR_LIMIT, HISTORY_MESSAGE_LIMIT
from federation.core import FederationStore


class FederationChatStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = FederationStore(self.root / "data", project_root=self.root / "project")
        self.store.init()
        self.chat = ChatStore(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def test_room_validation_does_not_scan_knowledge_and_keeps_membership_checks(self):
        from unittest.mock import patch
        room = self.chat.create_room('group', ['software-frontend'])
        self.chat.append_message(room, 'user', '保存后读取原消息')
        before = (self.chat.root / (room['id'] + '.json')).read_bytes()
        with patch.object(self.store, 'spaces', side_effect=AssertionError('room polling scanned Wiki')):
            self.assertEqual(self.chat.get_room(room['id']), room)
            self.assertEqual(self.chat.list_rooms()[0]['id'], room['id'])
            invalid = copy.deepcopy(room)
            invalid['participants'][0] = 'unknown-agent'
            with self.assertRaisesRegex(ValueError, '未知 Agent'):
                self.chat.save_room(invalid)
            invalid = copy.deepcopy(room)
            invalid['current_agent'] = '不属于本会话的 Agent'
            with self.assertRaisesRegex(ValueError, '不属于本聊天'):
                self.chat.save_room(invalid)
        self.assertEqual((self.chat.root / (room['id'] + '.json')).read_bytes(), before)

    def test_agents_follow_existing_and_new_knowledge_spaces(self):
        agents = self.chat.agents()
        self.assertEqual(len(agents), 26)
        self.assertTrue(all(agent["id"] == agent["space_id"] for agent in agents))
        self.assertTrue(all(agent["knowledge_count"] == 0 for agent in agents))
        self.assertNotIn(str(self.root), json.dumps(agents, ensure_ascii=False))
        added = self.store.add_branch("制造业", "制造知识")
        self.assertIn(added["id"], {agent["id"] for agent in self.chat.agents()})

    def test_group_and_direct_membership_have_separate_semantics(self):
        group = self.chat.create_room("group", ["central", "commerce", "software"])
        self.assertEqual(group["participants"], ["commerce", "software", "central"])
        self.assertEqual(group["status"], "idle")
        direct = self.chat.create_room("direct", ["software"])
        self.assertEqual(direct["participants"], ["software"])
        self.assertEqual(self.chat.create_room("direct", ["central"])["participants"], ["central"])
        cases = [("group", []), ("group", ["central"]), ("direct", []),
                 ("direct", ["central", "software"]), ("group", ["software", "software"]),
                 ("group", ["software", "missing"]), ("direct", ["../central"]),
                 ("group", "software"), ("invalid", ["software"]), ({}, ["software"])]
        for mode, participants in cases:
            with self.subTest(mode=mode, participants=participants):
                with self.assertRaises(ValueError):
                    self.chat.create_room(mode, participants)
        too_many = [self.store.add_branch("额外行业" + str(index))["id"] for index in range(9)]
        with self.assertRaises(ValueError):
            self.chat.create_room("group", too_many)
        self.assertEqual(len(self.chat.create_room("group", too_many[:8])["participants"]), 9)
        with self.assertRaises(ValueError):
            self.chat.create_room("direct", ["central"], "长" * 81)

    def test_records_survive_new_store_and_are_private_atomic_json(self):
        room = self.chat.create_room("group", ["software", "commerce"], "跨行业问题")
        message = self.chat.append_message(room, "user", "请一起讨论验收流程")
        self.chat.append_message(room, "assistant", "软件视角的建议。", "software", phase="discussion")
        self.assertEqual(self.chat.get_room(room["id"])["messages"][0], message)
        file = self.chat.root / (room["id"] + ".json")
        self.assertEqual(file.stat().st_mode & 0o777, 0o600)
        restored = ChatStore(self.store).get_room(room["id"])
        self.assertEqual(restored, room)
        summaries = self.chat.list_rooms()
        self.assertNotIn("messages", summaries[0])
        self.assertEqual(summaries[0]["message_count"], 2)
        self.assertEqual(summaries[0]["last_message"], "软件视角的建议。")
        other = self.chat.create_room("direct", ["central"])
        self.assertEqual(self.chat.list_rooms()[0]["id"], other["id"])
        self.chat.append_message(room, "user", "继续")
        self.assertEqual(self.chat.list_rooms()[0]["id"], room["id"])
        self.assertFalse(list(self.chat.root.glob(".metadata-*")))

    def test_restart_marks_incomplete_turns_failed_and_keeps_messages(self):
        for state in ("queued", "running"):
            room = self.chat.create_room("group", ["software"])
            self.chat.append_message(room, "user", "中断前的问题")
            self.chat.append_message(room, "assistant", "已完成的内容", "software")
            self.chat.append_message(room, "assistant", "", "central", status="running")
            room.update(status=state, active_job_id=uuid.uuid4().hex, current_agent="中央 Agent")
            self.chat.save_room(room)
            restarted = ChatStore(self.store)
            loaded = restarted.get_room(room["id"])
            self.assertEqual(loaded["status"], "failed")
            self.assertIsNone(loaded["current_agent"])
            self.assertIsNone(loaded["active_job_id"])
            self.assertEqual(loaded["messages"][1]["content"], "已完成的内容")
            self.assertEqual(loaded["messages"][2]["status"], "failed")
            self.assertEqual(loaded["messages"][-1]["role"], "system")
            restarted_again = ChatStore(self.store)
            self.assertEqual(len(restarted_again.get_room(room["id"])["messages"]), 4)
            self.chat.append_message(loaded, "user", "重试问题")
            self.assertEqual(self.chat.get_room(room["id"])["messages"][-1]["content"], "重试问题")

    def test_invalid_identifiers_and_symlinks_never_escape_chat_root(self):
        room = self.chat.create_room("direct", ["software"])
        for identifier in ("../outside", str(uuid.uuid4()), room["id"].upper(), "/tmp/anything", {}, "x" * 32):
            with self.subTest(identifier=identifier):
                with self.assertRaises(ValueError):
                    self.chat.get_room(identifier)
        outside = self.root / "private.json"
        outside.write_text('{"private":true}')
        identifier = uuid.uuid4().hex
        (self.chat.root / (identifier + ".json")).symlink_to(outside)
        with self.assertRaises(ValueError):
            self.chat.get_room(identifier)
        bad_room = copy.deepcopy(room)
        bad_room["id"] = identifier
        with self.assertRaises(ValueError):
            self.chat.save_room(bad_room)
        self.assertEqual(outside.read_text(), '{"private":true}')
        with self.assertRaises(ValueError):
            self.chat.list_rooms()

    def test_symlinked_parent_and_tampered_room_rejected(self):
        room = self.chat.create_room("group", ["software"])
        path = self.chat.root / (room["id"] + ".json")
        tampered = copy.deepcopy(room)
        tampered["id"] = uuid.uuid4().hex
        path.write_text(json.dumps(tampered))
        with self.assertRaises(ValueError):
            self.chat.get_room(room["id"])
        path.write_text("broken JSON")
        with self.assertRaises(ValueError):
            self.chat.get_room(room["id"])
        separate = self.root / "symlink-data"
        separate.mkdir()
        (separate / "chat").symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            ChatStore(FederationStore(separate, project_root=self.root / "project"))

    def test_speakers_cannot_spoof_uninvited_agents_or_invalid_messages(self):
        room = self.chat.create_room("direct", ["software"])
        cases = [("assistant", "x", "commerce", "completed"),
                 ("assistant", "x", None, "completed"),
                 ("user", "x", "software", "completed"),
                 ("assistant", "x", "software", "invented"),
                 ("unknown", "x", None, "completed"),
                 ("user", "", None, "completed"),
                 ("user", "长" * 6001, None, "completed")]
        for role, content, agent_id, status in cases:
            with self.assertRaises(ValueError):
                self.chat.append_message(room, role, content, agent_id, status)
        self.assertEqual(room["messages"], [])
        self.assertEqual(self.chat.get_room(room["id"])["messages"], [])

    def test_prompts_keep_current_question_and_recent_cross_agent_answers_bounded(self):
        room = self.chat.create_room("group", ["software", "commerce"])
        for index in range(35):
            self.chat.append_message(room, "user", f"较早的问题 {index}")
            self.chat.append_message(room, "assistant", f"较早的回复 {index} " + "长" * 2_000, "software")
        latest = "这是本轮最新问题：" + "保持完整" * 1_000
        self.chat.append_message(room, "user", latest)
        self.chat.append_message(room, "assistant", "软件行业已经给出本轮观点", "software")
        self.chat.append_message(room, "assistant", "电商连接失败，未能回答", "commerce", status="failed")
        self.chat.append_message(room, "assistant", "电商尚未完成，不该进入上下文", "commerce", status="running")
        prompt = self.chat.turn_prompt(room, "central", "synthesis")
        transcript = prompt.split("<conversation_history>\n")[1].split("\n</conversation_history>")[0]
        history = json.loads(transcript)
        self.assertLessEqual(len(transcript), HISTORY_CHAR_LIMIT)
        self.assertLessEqual(len(history), HISTORY_MESSAGE_LIMIT)
        self.assertEqual([item["content"] for item in history if item["role"] == "user"][-1], latest)
        self.assertIn("软件行业已经给出本轮观点", transcript)
        failed = [item for item in history if item["status"] == "failed"]
        self.assertEqual(failed[0]["content"], "电商连接失败，未能回答")
        self.assertNotIn("电商尚未完成", transcript)
        self.assertNotIn("较早的问题 0", transcript)
        self.assertNotIn(str(self.root), prompt)
        self.assertIn("不是已审核知识", prompt)
        self.assertIn("不更新模型权重", prompt)
        self.assertIn("尚无已整理的专业知识页", prompt)
        self.assertIn("不得尝试越过当前知识库", prompt)
        with self.assertRaises(ValueError):
            self.chat.turn_prompt(room, "content", "discussion")

    def test_direct_context_and_knowledge_availability_are_truthful(self):
        room = self.chat.create_room("direct", ["software"])
        with self.assertRaises(ValueError):
            self.chat.turn_prompt(room, "software", "direct")
        self.chat.append_message(room, "user", "介绍软件知识")
        prompt = self.chat.turn_prompt(room, "software", "direct")
        self.assertIn("单独聊天", prompt)
        self.assertIn("只能给出标注为一般建议", prompt)
        page = Path(self.store.space("software")["wiki_dir"]) / "topic.md"
        page.write_text("# 真实存在的知识页\n这是隔离测试。")
        prompt = self.chat.turn_prompt(room, "software", "direct")
        self.assertIn("本库有专业知识页", prompt)
        self.assertNotIn("尚无已整理的专业知识页", prompt)


if __name__ == "__main__":
    unittest.main()
