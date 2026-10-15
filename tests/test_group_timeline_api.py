"""Real API/worker/orchestration timeline checks using a controlled model.

Every room and job is temporary. Thread-safe gates expose intermediate durable
state without replacing run_orchestration or the timeline synchronizer. These
checks prove local routing/persistence, not a live model's response quality.
"""
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from fastapi.testclient import TestClient

from federation.app import create_app
from federation.chat import ChatStore
from federation.group_timeline import sync_group_timeline


def plan(*assignments):
    return json.dumps({"action": "delegate", "tasks": [
        {"agent_id": agent_id, "task": instruction}
        for agent_id, instruction in assignments]}, ensure_ascii=False)


class GroupTimelineAPITest(unittest.TestCase):
    FRONTEND_RESULT = "前端受控结果：表单需要加载、成功与错误状态。"
    BACKEND_RESULT = "后端受控结果：接口使用明确的业务错误码。"
    MODULE_RESULT = "软件模块受控汇总：页面状态与接口错误码已经形成交接方案。"
    CENTRAL_RESULT = "中央受控最终答复：采用软件模块提交的前后端交接方案。"
    PARTIAL_MODULE = "软件模块部分汇总：前端结果已保留，后端执行失败，接口设计未完成。"
    PARTIAL_CENTRAL = "中央部分汇总：软件模块仅有前端结果，后端执行失败，整体尚未完成。"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name) / "data"
        self.turns = []
        self.block_at = None
        self.entered = threading.Event()
        self.release = threading.Event()
        self.fail_backend = False
        self.direct_answer = False
        self.branch = "software"
        self.client = None
        self.open_client()

    def tearDown(self):
        self.close_client()
        self.temp.cleanup()

    async def runner(self, job, store):
        self.turns.append(copy.deepcopy(job))
        key = (job["space"], job["delegation_phase"])
        if key == self.block_at:
            self.entered.set()
            # Cancellation must propagate through the real app lifespan.
            while not self.release.is_set():
                await asyncio.sleep(0.01)
        await asyncio.sleep(0)
        if self.direct_answer:
            if key == ("central", "plan"):
                job["answer"] = json.dumps({"action": "answer", "answer": "未执行的规划草稿"}, ensure_ascii=False)
            elif key == ("central", "execute"):
                job["answer"] = "你好，我是中央 Agent，本次直接回答。"
            else:
                raise AssertionError("Unexpected direct invocation: " + repr(key))
            return
        if self.branch == "content":
            answers = {
                ("central", "plan"): plan(("content", "安排内容策划模块完成短片大纲。")),
                ("content", "plan"): plan(("content-planning", "整理短片故事结构。")),
                ("content-planning", "execute"): "策划受控结果：短片采用三幕式故事结构。",
                ("content", "summary"): "内容模块受控汇总：故事结构已整理，等待剧本扩写。",
                ("central", "summary"): "中央受控最终答复：采用内容模块提交的短片故事大纲。",
            }
            if key not in answers:
                raise AssertionError("Unexpected content invocation: " + repr(key))
            job["answer"] = answers[key]
            return
        answers = {
            ("central", "plan"): plan(("software", "协调前端和后端交接方案。")),
            ("software", "plan"): plan(("software-frontend", "整理页面状态。"),
                                        ("software-backend", "整理接口错误码。")),
            ("software-frontend", "execute"): self.FRONTEND_RESULT,
            ("software-backend", "execute"): self.BACKEND_RESULT,
            ("software", "summary"): self.PARTIAL_MODULE if self.fail_backend else self.MODULE_RESULT,
            ("central", "summary"): self.PARTIAL_CENTRAL if self.fail_backend else self.CENTRAL_RESULT,
        }
        if key == ("software-backend", "execute") and self.fail_backend:
            raise RuntimeError("受控后端故障，未生成接口结果")
        if key not in answers:
            raise AssertionError("Unexpected invocation: " + repr(key))
        if key == ("software-frontend", "execute"):
            # These are fixture receipts, not real native evidence. The API must
            # retain them on the actual member response, attributed to its task.
            job["wiki_reads"] = [{"path": "/fixture-states.md", "sha256": "f" * 64,
                                  "knowledge_status": "untracked"}]
            job["wiki_citation_check"] = {"scope": "fixture-only", "valid": True}
            job["template_reads"] = [{"template_id": "agent-standard", "path": "/_agent_templates/agent-standard/GUIDELINES.md",
                                      "sha256": "a" * 64}]
        job["answer"] = answers[key]

    def open_client(self):
        self.app = create_app(base=self.base, runner=self.runner)
        self.client = TestClient(self.app)
        self.client.__enter__()

    def close_client(self):
        if self.client is not None:
            client, self.client = self.client, None
            client.__exit__(None, None, None)

    def room(self):
        # Legacy explicit rooms retain the immediate-execution protocol. Primary
        # consultation/approval is exercised in test_primary_consultation_api.py.
        response = self.client.post("/api/chat/rooms", json={
            "mode": "orchestrated", "participants": ["central"], "title": "旧群聊编排兼容测试"})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def primary_room(self):
        response = self.client.post("/api/chat/primary", json={})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def send(self, room, text="请让软件模块协调前端和后端方案。"):
        response = self.client.post("/api/chat/rooms/" + room["id"] + "/messages", json={"content": text})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["job"]

    def read(self, room):
        response = self.client.get("/api/chat/rooms/" + room["id"])
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def finish(self, job):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            response = self.client.get("/api/jobs/" + job["id"])
            self.assertEqual(response.status_code, 200, response.text)
            current = response.json()
            if current["status"] not in {"queued", "running"}:
                return current
            time.sleep(0.01)
        self.fail("Controlled timeline round did not finish")

    def wait_for_gate(self):
        self.assertTrue(self.entered.wait(8), "Controlled Agent did not reach gate")

    @staticmethod
    def replies(room):
        return [message for message in room["messages"] if message["role"] == "assistant"]

    def assert_exactly_once(self, room):
        events = [message for message in room["messages"] if message.get("event_key")]
        keys = [message["event_key"] for message in events]
        self.assertTrue(keys)
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(len(room["messages"]), len({message["id"] for message in room["messages"]}))
        for message in events:
            self.assertIn(message["event_kind"], {"group_started", "member_joined", "delegation", "work_started", "result", "error"})
            if message["event_kind"] == "result":
                self.assertEqual(message["role"], "assistant")
                self.assertEqual(message["event_origin"], "agent")
                self.assertEqual(message["agent_id"], message["actor_agent_id"])
            else:
                self.assertEqual(message["role"], "system")
                self.assertEqual(message["event_origin"], "host")
                self.assertIsNone(message["agent_id"])
        return events

    def assert_repeat_sync_unchanged(self, room, round_id):
        chat = self.app.state.chat
        current = chat.get_room(room["id"])
        before = copy.deepcopy(current["messages"])
        for _ in range(2):
            self.assertEqual(sync_group_timeline(chat, current, round_id), [])
        self.assertEqual(self.read(room)["messages"], before)
        self.assert_exactly_once(current)

    def assert_group_members_and_event_order(self, room, round_id, expected_members):
        groups = [group for group in room["task_groups"] if group["round_id"] == round_id]
        self.assertEqual(len(groups), 1)
        group = groups[0]
        self.assertEqual(group["id"], round_id)
        self.assertEqual(group["members"], expected_members)
        self.assertTrue(group["title"].strip())
        messages = [m for m in room["messages"] if m.get("round_id") == round_id]
        starts = [m for m in messages if m.get("event_kind") == "group_started"]
        self.assertEqual(len(starts), 1)
        self.assertEqual((starts[0]["actor_agent_id"], starts[0]["recipient_agent_id"]), ("central", "central"))
        joins = [m for m in messages if m.get("event_kind") == "member_joined"]
        self.assertEqual([m["recipient_agent_id"] for m in joins], expected_members[1:])
        self.assertEqual(len(joins), len({m["recipient_agent_id"] for m in joins}))
        positions = {m["id"]: index for index, m in enumerate(messages)}
        tasks = {task["id"]: task for task in room["delegations"] if task["round_id"] == round_id}
        for join in joins:
            member = join["recipient_agent_id"]
            member_task = next(task for task in tasks.values() if task["agent_id"] == member)
            parent = tasks[member_task["parent_task_id"]]["agent_id"]
            self.assertEqual(join["actor_agent_id"], parent)
            handoffs = [m for m in messages if m.get("event_kind") == "delegation"
                        and m["recipient_agent_id"] == member]
            self.assertEqual(len(handoffs), 1)
            self.assertLess(positions[starts[0]["id"]], positions[join["id"]])
            self.assertLess(positions[join["id"]], positions[handoffs[0]["id"]])
            for result in messages:
                if result.get("event_kind") == "result" and result["agent_id"] == member:
                    self.assertLess(positions[handoffs[0]["id"]], positions[result["id"]])
        return group

    def test_primary_entry_is_idempotent_and_keeps_eighteen_legacy_rooms_byte_identical(self):
        chat = self.app.state.chat
        legacy_paths = []
        for index in range(18):
            response = self.client.post("/api/chat/rooms", json={
                "mode": "orchestrated", "participants": ["central"], "title": "历史会话 " + str(index + 1)})
            self.assertEqual(response.status_code, 200, response.text)
            legacy = response.json()
            chat.append_message(legacy, "user", "历史用户问题 " + str(index + 1))
            chat.append_message(legacy, "assistant", "历史中央答复 " + str(index + 1), "central")
            legacy_paths.append(chat._path(legacy["id"]))
        before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in legacy_paths}
        self.assertEqual(len(self.client.get("/api/chat/rooms").json()["rooms"]), 18)
        primary = self.primary_room()
        self.assertEqual(primary["purpose"], "primary")
        self.assertEqual(primary["mode"], "orchestrated")
        self.assertEqual(primary["participants"], ["central"])
        self.assertNotIn(chat._path(primary["id"]), legacy_paths)
        for _ in range(3):
            self.assertEqual(self.primary_room(), primary)
        self.assertEqual(len(self.client.get("/api/chat/rooms").json()["rooms"]), 19)
        self.close_client()
        self.open_client()
        self.assertEqual(self.primary_room(), primary)
        self.assertEqual({path: hashlib.sha256(path.read_bytes()).hexdigest() for path in legacy_paths}, before)
        self.assertEqual(len(self.client.get("/api/chat/rooms").json()["rooms"]), 19)
        self.assertEqual(self.turns, [])

    def test_legacy_room_tasks_form_distinct_groups_from_actual_plans(self):
        primary = self.room()
        first = self.send(primary)
        self.assertEqual(self.finish(first)["status"], "completed")
        first_state = self.read(primary)
        first_group = copy.deepcopy(self.assert_group_members_and_event_order(
            first_state, first["id"], ["central", "software", "software-frontend", "software-backend"]))
        self.assertEqual(first_group["status"], "completed")
        self.assertEqual(self.read(primary)["id"], primary["id"])
        self.branch = "content"
        second = self.send(primary, "请内容模块安排编剧策划整理短片大纲。")
        self.assertEqual(self.finish(second)["status"], "completed")
        current = self.read(primary)
        self.assertEqual(current["id"], primary["id"])
        self.assertEqual(current["current_task_group_id"], second["id"])
        self.assertEqual(len(current["task_groups"]), 2)
        self.assertEqual(current["task_groups"][0], first_group)
        second_group = self.assert_group_members_and_event_order(
            current, second["id"], ["central", "content", "content-planning"])
        self.assertEqual(second_group["status"], "completed")
        self.assertNotEqual(first_group["id"], second_group["id"])
        self.assertEqual(current["messages"][:len(first_state["messages"])], first_state["messages"])
        second_tasks = [t for t in current["delegations"] if t["round_id"] == second["id"]]
        self.assertEqual([t["agent_id"] for t in second_tasks], second_group["members"])
        second_messages = [m for m in current["messages"] if m.get("round_id") == second["id"]]
        self.assertEqual([m["agent_id"] for m in second_messages if m["role"] == "assistant"],
                         ["content-planning", "content", "central"])
        second_turns = [turn for turn in self.turns if turn["parent_job_id"] == second["id"]]
        self.assertEqual([(turn["space"], turn["delegation_phase"]) for turn in second_turns],
                         [("central", "plan"), ("content", "plan"), ("content-planning", "execute"),
                          ("content", "summary"), ("central", "summary")])
        self.assertTrue(all(not member.startswith("software") for member in second_group["members"]))
        self.assertEqual(len(self.client.get("/api/chat/rooms").json()["rooms"]), 1)
        self.assert_repeat_sync_unchanged(primary, second["id"])

    def test_live_results_precede_central_summary_and_keep_speakers_order_and_receipts(self):
        self.block_at = ("central", "summary")
        room = self.room()
        job = self.send(room)
        self.wait_for_gate()
        pending = self.read(room)
        self.assertEqual(self.client.get("/api/jobs/" + job["id"]).json()["status"], "running")
        self.assertEqual(pending["status"], "running")
        self.assertEqual(pending["active_job_id"], job["id"])
        self.assertEqual(self.read(room)["id"], room["id"])
        pending_group = self.assert_group_members_and_event_order(
            pending, job["id"], ["central", "software", "software-frontend", "software-backend"])
        self.assertEqual(pending_group["status"], "running")
        replies = self.replies(pending)
        self.assertEqual([m["agent_id"] for m in replies], ["software-frontend", "software-backend", "software"])
        self.assertEqual([m["content"] for m in replies], [self.FRONTEND_RESULT, self.BACKEND_RESULT, self.MODULE_RESULT])
        self.assertEqual(replies[0]["wiki_reads"][0]["path"], "/fixture-states.md")
        self.assertEqual(replies[0]["wiki_citation_check"]["scope"], "fixture-only")
        self.assertEqual(replies[0]["template_reads"][0]["template_id"], "agent-standard")
        self.assertNotIn("本轮实际读取", replies[0]["content"])
        self.assertTrue(all(m["round_id"] == job["id"] for m in pending["messages"]))
        self.assert_exactly_once(pending)
        dispatch = [m for m in pending["messages"] if m.get("event_kind") == "delegation"]
        self.assertEqual([(m["actor_agent_id"], m["recipient_agent_id"]) for m in dispatch],
                         [("central", "software"), ("software", "software-frontend"), ("software", "software-backend")])
        positions = {m["id"]: index for index, m in enumerate(pending["messages"])}
        self.assertLess(positions[dispatch[0]["id"]], positions[dispatch[1]["id"]])
        for handoff, reply in ((dispatch[1], replies[0]), (dispatch[2], replies[1])):
            self.assertLess(positions[handoff["id"]], positions[reply["id"]])
        self.assertLess(positions[replies[1]["id"]], positions[replies[2]["id"]])
        # The next API poll cannot append duplicates while no state changes.
        self.assertEqual(self.read(room)["messages"], pending["messages"])
        self.release.set()
        self.assertEqual(self.finish(job)["status"], "completed")
        current = self.read(room)
        self.assertEqual(current["messages"][:len(pending["messages"])], pending["messages"])
        self.assertEqual([m["agent_id"] for m in self.replies(current)],
                         ["software-frontend", "software-backend", "software", "central"])
        final = current["messages"][-1]
        self.assertEqual((final["agent_id"], final["phase"], final["content"]),
                         ("central", "summary", self.CENTRAL_RESULT))
        self.assertNotIn("event_kind", final)
        self.assertEqual(current["task_groups"][0]["status"], "completed")
        self.assert_repeat_sync_unchanged(room, job["id"])

    def test_partial_failure_keeps_member_results_and_marks_module_summary_partial_once(self):
        self.fail_backend = True
        room = self.room()
        job = self.send(room)
        self.assertEqual(self.finish(job)["status"], "failed")
        current = self.read(room)
        self.assertEqual(current["status"], "failed")
        self.assertEqual(current["task_groups"][0]["status"], "failed")
        replies = self.replies(current)
        self.assertEqual([m["agent_id"] for m in replies], ["software-frontend", "software", "central"])
        self.assertEqual([m["status"] for m in replies], ["completed", "failed", "failed"])
        self.assertEqual(replies[0]["content"], self.FRONTEND_RESULT)
        self.assertEqual(replies[1]["content"], self.PARTIAL_MODULE)
        self.assertEqual(replies[1]["result_scope"], "partial")
        self.assertEqual(replies[2]["content"], self.PARTIAL_CENTRAL)
        errors = [m for m in current["messages"] if m.get("event_kind") == "error"]
        self.assertEqual({m["actor_agent_id"] for m in errors}, {"software-backend", "software", "central"})
        self.assertTrue(any("受控后端故障" in m["content"] for m in errors))
        self.assert_repeat_sync_unchanged(room, job["id"])

    def test_shutdown_cancellation_retains_completed_child_and_one_final_error(self):
        self.block_at = ("software-backend", "execute")
        room = self.room()
        job = self.send(room)
        self.wait_for_gate()
        pending = self.read(room)
        self.assertEqual([m["agent_id"] for m in self.replies(pending)], ["software-frontend"])
        self.close_client()  # Real lifespan cancellation propagates to orchestration.
        self.open_client()
        current = self.read(room)
        self.assertEqual(current["messages"][:len(pending["messages"])], pending["messages"])
        self.assertEqual(current["status"], "failed")
        self.assertEqual(current["task_groups"][0]["status"], "failed")
        self.assertIsNone(current["active_job_id"])
        self.assertIsNone(current["current_agent"])
        statuses = {task["agent_id"]: task["status"] for task in current["delegations"]}
        self.assertEqual(statuses, {"central": "failed", "software": "failed", "software-frontend": "completed",
                                    "software-backend": "failed"})
        replies = self.replies(current)
        self.assertEqual([m["agent_id"] for m in replies], ["software-frontend", "central"])
        self.assertEqual(replies[0]["content"], self.FRONTEND_RESULT)
        self.assertEqual(replies[1]["status"], "failed")
        self.assertIn("未完成", replies[1]["content"])
        self.assert_repeat_sync_unchanged(room, job["id"])
        self.assertEqual(ChatStore(self.app.state.store).get_room(room["id"])["messages"], current["messages"])

    def test_restart_recovers_live_snapshot_without_replaying_finished_member(self):
        self.block_at = ("software-backend", "execute")
        room = self.room()
        job = self.send(room)
        self.wait_for_gate()
        snapshot = self.read(room)
        completed_child = copy.deepcopy(next(t for t in snapshot["delegations"] if t["agent_id"] == "software-frontend"))
        self.close_client()
        # Restore the actual API-produced running snapshot to simulate a crash
        # before graceful cancellation persisted. No fabricated task/result data.
        self.app.state.chat.save_room(copy.deepcopy(snapshot))
        turn_count = len(self.turns)
        self.open_client()  # ChatStore's real startup recovery reads the snapshot.
        recovered = self.read(room)
        self.assertEqual(len(self.turns), turn_count)
        self.assertEqual(recovered["status"], "failed")
        self.assertEqual(recovered["task_groups"][0]["status"], "failed")
        self.assertIsNone(recovered["active_job_id"])
        self.assertIsNone(recovered["current_agent"])
        self.assertEqual(recovered["messages"][:len(snapshot["messages"])], snapshot["messages"])
        self.assertEqual(next(t for t in recovered["delegations"] if t["agent_id"] == "software-frontend"), completed_child)
        self.assertFalse(any(t["status"] in {"queued", "running"} for t in recovered["delegations"]))
        self.assertEqual([m["agent_id"] for m in self.replies(recovered)], ["software-frontend"])
        errors = [m for m in recovered["messages"] if m.get("event_kind") == "error"]
        self.assertEqual({m["actor_agent_id"] for m in errors}, {"central", "software", "software-backend"})
        self.assertTrue(all("服务重启" in m["content"] for m in errors))
        self.assert_repeat_sync_unchanged(room, job["id"])
        self.assertEqual(ChatStore(self.app.state.store).get_room(room["id"])["messages"], recovered["messages"])

    def test_legacy_round_is_not_backfilled_and_followup_only_adds_new_round(self):
        room = self.room()
        first = self.send(room)
        self.assertEqual(self.finish(first)["status"], "completed")
        legacy = self.read(room)
        # Model an existing room from before timeline support: real old tasks and
        # user/final messages are retained, but no event marker has ever existed.
        legacy["messages"] = [m for m in legacy["messages"] if not m.get("event_kind")]
        legacy.pop("group_timeline")
        legacy.pop("task_groups", None)
        legacy.pop("current_task_group_id", None)
        self.app.state.chat.save_room(legacy)
        old_messages, old_tasks = copy.deepcopy(legacy["messages"]), copy.deepcopy(legacy["delegations"])
        self.assertEqual(sync_group_timeline(self.app.state.chat, legacy, first["id"]), [])
        self.assertEqual(self.read(room), legacy)
        second = self.send(room, "沿用此前方案，补充错误提示。")
        self.assertEqual(self.finish(second)["status"], "completed")
        current = self.read(room)
        self.assertEqual(current["messages"][:len(old_messages)], old_messages)
        self.assertEqual(current["delegations"][:len(old_tasks)], old_tasks)
        self.assertEqual({m["round_id"] for m in current["messages"][len(old_messages):]}, {second["id"]})
        events = self.assert_exactly_once(current)
        self.assertEqual({m["round_id"] for m in events}, {second["id"]})
        self.assertNotIn(first["id"], current["group_timeline"]["rounds"])
        self.assert_repeat_sync_unchanged(room, second["id"])

    def test_direct_answer_in_orchestrated_room_has_one_central_final_and_no_handoffs(self):
        self.direct_answer = True
        room = self.room()
        job = self.send(room, "你好，介绍一下自己。")
        self.assertEqual(self.finish(job)["status"], "completed")
        current = self.read(room)
        self.assertEqual([(j["space"], j["delegation_phase"]) for j in self.turns],
                         [("central", "plan"), ("central", "execute")])
        self.assertEqual(len(current["delegations"]), 1)
        replies = self.replies(current)
        self.assertEqual(len(replies), 1)
        self.assertEqual((replies[0]["agent_id"], replies[0]["phase"], replies[0]["content"]),
                         ("central", "summary", "你好，我是中央 Agent，本次直接回答。"))
        self.assertNotIn("event_kind", replies[0])
        events = self.assert_exactly_once(current)
        self.assertFalse(any(m["event_kind"] in {"delegation", "result", "error"} for m in events))
        group = self.assert_group_members_and_event_order(current, job["id"], ["central"])
        self.assertEqual(group["status"], "completed")
        self.assertFalse(any("未执行的规划草稿" in m["content"] for m in current["messages"]))
        self.assert_repeat_sync_unchanged(room, job["id"])


if __name__ == "__main__":
    unittest.main()
