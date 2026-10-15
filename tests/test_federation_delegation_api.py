"""Exercise hierarchical delegation through the real API with a controlled model.

All data and model answers are temporary fixtures. These checks establish
routing, durable state and scope boundaries, not the quality of a live model.
"""
import asyncio
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
import uuid

from fastapi.testclient import TestClient

from federation.app import create_app, isolated_ask_environment
from federation.chat import ChatStore
from federation.core import _now


def plan(*assignments):
    return json.dumps({"action": "delegate", "tasks": [
        {"agent_id": agent_id, "task": instruction}
        for agent_id, instruction in assignments]}, ensure_ascii=False)


class DelegationAPITest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.turns = []
        self.answer = self.software_answer
        self.exercise_isolation = False
        self.scopes = []

        async def runner(job, store):
            self.turns.append(copy.deepcopy(job))
            # Yield so API queue/polling behavior remains part of these tests.
            await asyncio.sleep(0.01)
            if self.exercise_isolation:
                environment = isolated_ask_environment(store, job)
                isolated_wiki = Path(environment["OPENWIKI_CONFIG_DIR"]) / "wiki"
                self.scopes.append((job["space"], isolated_wiki))
                self.assertEqual((isolated_wiki / "private-fact.md").read_text(),
                                 "private to " + job["space"])
                (isolated_wiki / "private-fact.md").write_text("sandbox-only edit")
            job["answer"] = self.answer(job)

        self.app = create_app(base=Path(self.temp.name) / "data", runner=runner)
        self.client = TestClient(self.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    @staticmethod
    def software_answer(job):
        key = (job["space"], job.get("delegation_phase"))
        if key == ("central", "plan"):
            return plan(("software", "协调前端页面与后端接口设计。"))
        if key == ("software", "plan"):
            return plan(("software-frontend", "提出页面与接口交接要求。"),
                        ("software-backend", "提出接口与数据设计。"))
        if key == ("software-frontend", "execute"):
            return "前端实际结果：页面需要清晰的加载与错误状态。"
        if key == ("software-backend", "execute"):
            return "后端实际结果：接口返回可辨识的错误码。"
        if key == ("software", "summary"):
            return "软件模块汇总：前端与后端共同约定接口错误状态。"
        if key == ("central", "summary"):
            return "主 Agent 最终答复：由软件模块完成页面与接口方案的衔接。"
        raise AssertionError("Unexpected Agent invocation: " + repr(key))

    def room(self):
        response = self.client.post("/api/chat/rooms", json={
            "mode": "orchestrated", "participants": ["central"], "title": "临时委派测试"})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def send(self, room, content="请设计一个带前端和后端的网站方案。"):
        response = self.client.post("/api/chat/rooms/" + room["id"] + "/messages",
                                    json={"content": content})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["job"]

    def finish(self, job):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            response = self.client.get("/api/jobs/" + job["id"])
            self.assertEqual(response.status_code, 200, response.text)
            current = response.json()
            if current["status"] not in {"queued", "running"}:
                return current
            time.sleep(0.01)
        self.fail("Controlled delegation did not finish")

    def read(self, room):
        response = self.client.get("/api/chat/rooms/" + room["id"])
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_selected_branch_executes_downwards_then_summarizes_upwards(self):
        room = self.room()
        self.assertEqual(room["participants"], ["central"])
        completed = self.finish(self.send(room))
        self.assertEqual(completed["status"], "completed", completed)
        expected = [("central", "plan"), ("software", "plan"),
                    ("software-frontend", "execute"), ("software-backend", "execute"),
                    ("software", "summary"), ("central", "summary")]
        self.assertEqual([(job["space"], job["delegation_phase"]) for job in self.turns], expected)
        current = self.read(room)
        self.assertEqual(current["status"], "idle")
        self.assertIsNone(current["active_job_id"])
        self.assertIsNone(current["current_agent"])
        self.assertEqual(current["participants"],
                         ["central", "software", "software-frontend", "software-backend"])
        self.assertEqual(current["messages"][0]["role"], "user")
        self.assertEqual([m["agent_id"] for m in current["messages"] if m["role"] == "assistant"],
                         ["software-frontend", "software-backend", "software", "central"])
        self.assertEqual([(m["actor_agent_id"], m["recipient_agent_id"])
                          for m in current["messages"] if m.get("event_kind") == "delegation"],
                         [("central", "software"), ("software", "software-frontend"),
                          ("software", "software-backend")])
        self.assertEqual({m["round_id"] for m in current["messages"]}, {completed["id"]})
        tasks = {task["agent_id"]: task for task in current["delegations"]}
        self.assertEqual(set(tasks), set(current["participants"]))
        self.assertIsNone(tasks["central"]["parent_task_id"])
        self.assertEqual(tasks["software"]["parent_task_id"], tasks["central"]["id"])
        for specialist in ("software-frontend", "software-backend"):
            self.assertEqual(tasks[specialist]["parent_task_id"], tasks["software"]["id"])
            self.assertEqual(tasks[specialist]["depth"], 2)
        self.assertTrue(all(task["status"] == "completed" for task in tasks.values()))
        self.assertEqual({task["round_id"] for task in tasks.values()}, {completed["id"]})
        self.assertIn("前端实际结果", self.turns[4]["question"])
        self.assertIn("后端实际结果", self.turns[4]["question"])
        self.assertIn("软件模块汇总", self.turns[5]["question"])
        for recorded, expected_turn in zip(completed["turns"], self.turns):
            detail = self.client.get("/api/jobs/" + recorded["id"]).json()
            self.assertEqual(detail["status"], "completed")
            self.assertEqual(detail["space"], recorded["agent_id"])
            self.assertEqual(detail["parent_job_id"], completed["id"])
            self.assertEqual(detail["delegation_task_id"], recorded["task_id"])
            self.assertEqual(detail["delegation_phase"], recorded["phase"])
            self.assertEqual(detail["room_id"], room["id"])
            self.assertTrue(detail["structured_chat"])
            if detail["delegation_phase"] == "plan":
                self.assertIn("agent_id=" + detail["space"], expected_turn["question"])
            else:
                self.assertIn("唯一所属知识库是 " + detail["space"], expected_turn["question"])
        self.assertEqual(ChatStore(self.app.state.store).get_room(room["id"]), current)

    def test_each_delegated_turn_uses_own_disposable_wiki_copy(self):
        originals = {}
        for space in self.app.state.store.spaces():
            path = Path(space["wiki_dir"]) / "private-fact.md"
            path.write_text("private to " + space["id"])
            originals[path] = path.read_bytes()
        self.exercise_isolation = True
        completed = self.finish(self.send(self.room()))
        self.assertEqual(completed["status"], "completed", completed)
        self.assertEqual(len(self.scopes), 6)
        self.assertEqual(len({path for _, path in self.scopes}), 6)
        for agent_id, sandbox in self.scopes:
            self.assertNotEqual(sandbox, Path(self.app.state.store.space(agent_id)["wiki_dir"]))
        self.assertEqual({path: path.read_bytes() for path in originals}, originals)

    def test_product_ui_routes_through_software_to_uiux_without_using_film_design(self):
        """Controlled planning proves allowed hierarchy and scope, not live routing accuracy."""
        def uiux_answer(job):
            key = (job["space"], job.get("delegation_phase"))
            if key == ("central", "plan"):
                return plan(("software", "为微信小程序安排产品 UI/UX 设计，明确页面状态和开发交接。"))
            if key == ("software", "plan"):
                self.assertIn("software-uiux", job["question"])
                self.assertIn("UI/UX", job["question"])
                self.assertNotIn('"agent_id":"content-design"', job["question"])
                return plan(("software-uiux", "提供组件状态、无障碍要点与前端交接规范。"))
            if key == ("software-uiux", "execute"):
                self.assertIn("唯一所属知识库是 software-uiux", job["question"])
                return "UI/UX 交接：提交按钮包含默认、加载、禁用状态，表单错误应关联对应字段。"
            if key == ("software", "summary"):
                self.assertIn("UI/UX 交接", job["question"])
                return "软件模块汇总：设计师给出产品组件状态和无障碍交接，待前端实现。"
            if key == ("central", "summary"):
                self.assertIn("产品组件状态和无障碍交接", job["question"])
                return "主 Agent：软件模块的 UI/UX 设计师已提供界面方案，尚未修改项目代码。"
            raise AssertionError("Unexpected UI/UX Agent invocation: " + repr(key))

        originals = {}
        for space in self.app.state.store.spaces():
            path = Path(space["wiki_dir"]) / "private-fact.md"
            path.write_text("private to " + space["id"])
            originals[path] = path.read_bytes()
        self.exercise_isolation = True
        self.answer = uiux_answer
        room = self.room()
        completed = self.finish(self.send(room, "请给微信小程序设计产品 UI 和交互规范。"))
        self.assertEqual(completed["status"], "completed", completed)
        expected = [("central", "plan"), ("software", "plan"), ("software-uiux", "execute"),
                    ("software", "summary"), ("central", "summary")]
        self.assertEqual([(job["space"], job["delegation_phase"]) for job in self.turns], expected)
        current = self.read(room)
        self.assertEqual(current["participants"], ["central", "software", "software-uiux"])
        tasks = {task["agent_id"]: task for task in current["delegations"]}
        self.assertEqual(tasks["software"]["parent_task_id"], tasks["central"]["id"])
        self.assertEqual(tasks["software-uiux"]["parent_task_id"], tasks["software"]["id"])
        self.assertTrue(all(task["status"] == "completed" for task in tasks.values()))
        self.assertNotIn("content-design", tasks)
        self.assertEqual(len(self.scopes), 5)
        self.assertEqual(len({path for _, path in self.scopes}), 5)
        self.assertEqual({path: path.read_bytes() for path in originals}, originals)
        self.assertIn("尚未修改项目代码", current["messages"][-1]["content"])

    def test_followup_keeps_previous_round_and_uses_new_round_id(self):
        room = self.room()
        first = self.finish(self.send(room))
        before = self.read(room)
        second = self.finish(self.send(room, "请沿用刚才的方案，补充错误提示。"))
        self.assertEqual(first["status"], "completed")
        self.assertEqual(second["status"], "completed")
        self.assertNotEqual(first["id"], second["id"])
        current = self.read(room)
        previous_count = len(before["messages"])
        self.assertEqual(current["messages"][:previous_count], before["messages"])
        self.assertEqual(current["delegations"][:4], before["delegations"])
        self.assertEqual(len([m for m in current["messages"] if m["role"] == "user"]), 2)
        self.assertEqual(len([m for m in current["messages"]
                              if m["role"] == "assistant" and m["agent_id"] == "central"]), 2)
        self.assertEqual(len(current["delegations"]), 8)
        self.assertEqual({m["round_id"] for m in current["messages"][previous_count:]}, {second["id"]})
        self.assertEqual({t["round_id"] for t in current["delegations"][4:]}, {second["id"]})
        self.assertIn("主 Agent 最终答复", self.turns[6]["question"])
        self.assertIn("请沿用刚才的方案", self.turns[6]["question"])
        summaries = self.client.get("/api/chat/rooms").json()["rooms"]
        self.assertEqual(summaries[0]["message_count"], len(current["messages"]))
        self.assertNotIn("delegations", summaries[0])

    def test_simple_question_is_answered_without_invoking_teammates(self):
        template_scopes = {}
        def answer(job):
            environment = isolated_ask_environment(self.app.state.store, job)
            template_scopes[job["delegation_phase"]] = json.loads(environment["FEDERATION_TEMPLATE_SELECTION"])
            if job["delegation_phase"] == "plan":
                return json.dumps({"action": "answer", "answer": "未经证据读取的规划草稿"}, ensure_ascii=False)
            self.assertEqual(job["delegation_phase"], "execute")
            self.assertNotIn("未经证据读取的规划草稿", job["question"])
            self.assertTrue((Path(environment["OPENWIKI_CONFIG_DIR"]) / "wiki/_agent_templates/agent-standard/GUIDELINES.md").is_file())
            job["template_reads"] = [{"template_id": "agent-standard", "path": "/_agent_templates/agent-standard/GUIDELINES.md",
                                      "sha256": "controlled-reader-receipt"}]
            job["template_notices"] = ["受控验证：缺少某个专项模板"]
            return "你好，我是主 Agent。"
        self.answer = answer
        room = self.room()
        completed = self.finish(self.send(room, "你好，你是谁？"))
        self.assertEqual(completed["status"], "completed")
        self.assertEqual([(job["space"], job["delegation_phase"]) for job in self.turns], [("central", "plan"), ("central", "execute")])
        self.assertEqual(template_scopes["plan"], [])
        self.assertEqual(template_scopes["execute"][0]["id"], "agent-standard")
        current = self.read(room)
        self.assertEqual(current["participants"], ["central"])
        self.assertEqual(len(current["delegations"]), 1)
        self.assertEqual(current["delegations"][0]["phase"], "execute")
        self.assertEqual(current["messages"][-1]["content"], "你好，我是主 Agent。")
        self.assertEqual(current["messages"][-1]["template_reads"][0]["agent_id"], "central")
        self.assertEqual(current["messages"][-1]["template_notices"], [{"agent_id": "central", "text": "受控验证：缺少某个专项模板"}])
        self.assertIn("本轮实际读取", current["delegations"][0]["result"])

    def test_invalid_or_cross_level_plan_never_executes_even_valid_sibling(self):
        invalid_answers = ["", "not JSON", plan(("software", "合法的同级任务"),
                                           ("software-frontend", "中央不可越级直达前端")),
                           plan(("unknown-agent", "不存在的成员"))]
        for invalid in invalid_answers:
            with self.subTest(answer=invalid):
                self.turns.clear()
                self.answer = lambda job, value=invalid: value
                room = self.room()
                completed = self.finish(self.send(room))
                self.assertEqual(completed["status"], "failed")
                self.assertEqual([(job["space"], job["delegation_phase"]) for job in self.turns],
                                 [("central", "plan"), ("central", "plan")])
                current = self.read(room)
                self.assertEqual(current["participants"], ["central"])
                self.assertEqual(len(current["delegations"]), 1)
                self.assertEqual(current["delegations"][0]["status"], "failed")
                self.assertIn("两次", current["delegations"][0]["error"])
                self.assertEqual([m["agent_id"] for m in current["messages"] if m["role"] == "assistant"],
                                 ["central"])
                self.assertFalse(any(m.get("event_kind") == "delegation" for m in current["messages"]))
                self.assertEqual(current["messages"][-1]["status"], "failed")

    def test_one_bad_plan_can_be_corrected_before_execution(self):
        def corrected(job):
            if len(self.turns) == 1:
                return "无法解析的第一次计划"
            return self.software_answer(job)

        self.answer = corrected
        room = self.room()
        completed = self.finish(self.send(room))
        self.assertEqual(completed["status"], "completed", completed)
        self.assertEqual(len(self.turns), 7)
        self.assertEqual([job["space"] for job in self.turns[:3]], ["central", "central", "software"])
        self.assertIn("上一次计划未通过验证", self.turns[1]["question"])
        self.assertTrue(all(task["error"] is None for task in self.read(room)["delegations"]))

    def test_failed_specialist_keeps_completed_results_and_reports_partial_summary(self):
        def fail_backend(job):
            if (job["space"], job["delegation_phase"]) == ("software-backend", "execute"):
                raise RuntimeError("受控后端执行错误")
            if job["delegation_phase"] == "summary":
                return job["space"] + " 部分汇总：前端结果可用，后端任务失败，接口方案尚缺。"
            return self.software_answer(job)

        self.answer = fail_backend
        room = self.room()
        completed = self.finish(self.send(room))
        self.assertEqual(completed["status"], "failed")
        self.assertEqual(len(self.turns), 6)
        current = self.read(room)
        tasks = {task["agent_id"]: task for task in current["delegations"]}
        self.assertEqual(tasks["software-frontend"]["status"], "completed")
        self.assertIn("前端实际结果", tasks["software-frontend"]["result"])
        self.assertEqual(tasks["software-backend"]["status"], "failed")
        self.assertIn("受控后端执行错误", tasks["software-backend"]["error"])
        for agent_id in ("software", "central"):
            self.assertEqual(tasks[agent_id]["status"], "failed")
            self.assertIn("部分汇总", tasks[agent_id]["result"])
        child_results_json = self.turns[4]["question"].split("直属任务结果：\n", 1)[1].split(
            "\n当前节点的完整任务", 1)[0].strip()
        child_results = {item["agent_id"]: item for item in json.loads(child_results_json)}
        self.assertEqual(child_results["software-backend"]["status"], "failed")
        self.assertIn("受控后端执行错误", child_results["software-backend"]["error"])
        compact_records = {item['agent_id']: item for item in self.turns[4]['delegation_context']['records']}
        self.assertEqual(compact_records['software-backend']['status'], 'failed')
        self.assertIn('受控后端执行错误', compact_records['software-backend']['error'])
        self.assertEqual(compact_records['software-frontend']['status'], 'completed')
        self.assertTrue(compact_records['software-frontend']['result_artifact'])
        self.assertEqual(child_results["software-frontend"]["status"], "completed")
        self.assertIn("前端实际结果", child_results["software-frontend"]["result"])
        self.assertIn("software 部分汇总", self.turns[5]["question"])
        replies = [m for m in current["messages"] if m["role"] == "assistant"]
        self.assertEqual([m["agent_id"] for m in replies], ["software-frontend", "software", "central"])
        self.assertEqual([m["status"] for m in replies], ["completed", "failed", "failed"])
        backend_errors = [m for m in current["messages"] if m.get("event_kind") == "error"
                          and m.get("actor_agent_id") == "software-backend"]
        self.assertEqual(len(backend_errors), 1)
        self.assertIn("受控后端执行错误", backend_errors[0]["content"])
        self.assertEqual(current["messages"][-1]["status"], "failed")
        self.assertIn("后端任务失败", current["messages"][-1]["content"])
        self.answer = self.software_answer
        self.assertEqual(self.finish(self.send(room, "请重新完成方案。"))["status"], "completed")
        self.assertEqual(self.read(room)["delegations"][:4], current["delegations"])

    def test_restart_fails_only_unfinished_tasks_and_preserves_history(self):
        chat = self.app.state.chat
        agents = {agent["id"]: agent for agent in chat.agents()}
        for room_status in ("queued", "running"):
            with self.subTest(status=room_status):
                room = self.room()
                old_round = uuid.uuid4().hex
                chat.append_message(room, "user", "此前问题", round_id=old_round)
                chat.append_message(room, "assistant", "此前完整回答", "central", round_id=old_round)
                previous_messages = copy.deepcopy(room["messages"])
                round_id = uuid.uuid4().hex
                room["participants"] = ["central", "software", "software-frontend", "software-backend"]
                tasks = []
                for agent_id, status, parent_index in [
                        ("central", "running", None), ("software", "running", 0),
                        ("software-frontend", "completed", 1), ("software-backend", "queued", 1)]:
                    timestamp = _now()
                    tasks.append({"id": uuid.uuid4().hex, "round_id": round_id,
                                  "parent_task_id": tasks[parent_index]["id"] if parent_index is not None else None,
                                  "agent_id": agent_id, "agent_name": agents[agent_id]["name"],
                                  "depth": agents[agent_id]["depth"], "title": "中断任务",
                                  "instruction": "保留已有结果并恢复未完成状态", "status": status,
                                  "phase": "execute" if agents[agent_id]["depth"] == 2 else "plan",
                                  "result": "已保存的前端结果" if status == "completed" else "",
                                  "error": None, "created_at": timestamp, "updated_at": timestamp})
                room["delegations"] = tasks
                room.update(status=room_status, active_job_id=round_id, current_agent=agents["software"]["name"])
                chat.append_message(room, "user", "本轮未完成问题", round_id=round_id)
                chat.append_message(room, "assistant", "", "central", status="running", round_id=round_id)
                completed_task = copy.deepcopy(tasks[2])
                recovered = ChatStore(self.app.state.store).get_room(room["id"])
                self.assertEqual(recovered["status"], "failed")
                self.assertIsNone(recovered["active_job_id"])
                self.assertIsNone(recovered["current_agent"])
                self.assertEqual(recovered["messages"][:2], previous_messages)
                self.assertEqual(recovered["delegations"][2], completed_task)
                self.assertEqual([task["status"] for task in recovered["delegations"]],
                                 ["failed", "failed", "completed", "failed"])
                self.assertEqual(recovered["messages"][3]["status"], "failed")
                self.assertEqual(recovered["messages"][-1]["role"], "system")
                self.assertEqual(ChatStore(self.app.state.store).get_room(room["id"]), recovered)
        self.assertEqual(self.turns, [])

    def test_new_orchestrated_room_cannot_preselect_members_or_spoof_root(self):
        for participants in ([], ["software"], ["central", "software"], ["central", "central"]):
            with self.subTest(participants=participants):
                response = self.client.post("/api/chat/rooms", json={
                    "mode": "orchestrated", "participants": participants})
                self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.client.get("/api/chat/rooms").json()["rooms"], [])
        self.assertEqual(self.turns, [])


if __name__ == "__main__":
    unittest.main()
