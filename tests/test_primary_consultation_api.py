"""Primary consult -> saved proposal -> explicit approval, through the real API.

Models and collection are controlled fixtures in disposable stores. These tests
exercise the real queue, worker, proposal persistence and approved orchestration;
they make no claim about a live model's planning or answer quality.
"""
import asyncio
import copy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from federation.app import create_app


def delegate(agent_id, goal):
    return json.dumps({"action": "delegate", "tasks": [{"agent_id": agent_id, "task": goal}]}, ensure_ascii=False)


class PrimaryConsultationAPITest(unittest.TestCase):
    PROJECT = "我想开发一个软件项目：客户预约网站，需要前端表单和错误提示。请先讨论方案。"
    REVISION = "修改方案：先只做前端表单原型，暂不开发后端，也不要开始执行。"
    LEARNING = "请制定前端 HTML 表单验证的自主联网学习方案。"
    PROPOSAL_TEXT = "建议先明确预约表单字段，再由软件模块安排前端整理页面状态。当前只提出方案，等待用户确认。"
    CONSULTATION_TEXT = "可以先讨论目标和限制，本次不创建任务群，也不安排其他成员执行。"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name) / "data"
        self.turns, self.collections, self.researches = [], [], []
        self.block_at = None
        self.entered, self.release = threading.Event(), threading.Event()
        self.branch = "software"
        self.proposal_text = self.PROPOSAL_TEXT
        self.proposal_outputs = []
        self.client = None
        self.open_client()
        response = self.client.post("/api/chat/primary", json={})
        self.assertEqual(response.status_code, 200, response.text)
        self.room_id = response.json()["id"]

    def tearDown(self):
        self.close_client()
        self.temp.cleanup()

    def test_explicit_online_search_uses_tool_route_without_duplicate_research(self):
        job = self.finish(self.send('请联网搜索 Playwright getByRole locators，并附上原文链接。'))
        self.assertEqual(job['status'], 'completed')
        self.assertTrue(job['research_only'])
        self.assertTrue(job['tool_request'])
        self.assertTrue(self.turns[-1]['tool_request'])
        self.assertTrue(self.turns[-1]['network_allowed'])
        self.assertEqual(self.researches, [])
        self.assertEqual(self.collections, [])
        self.assertEqual(self.read().get('proposals', []), [])

    def open_client(self):
        self.app = create_app(base=self.base, runner=self.runner, collector=self.collector,
                              template_maintainer=self.maintain_templates, researcher=self.researcher)
        self.client = TestClient(self.app)
        self.client.__enter__()

    def close_client(self):
        if self.client is not None:
            client, self.client = self.client, None
            client.__exit__(None, None, None)

    async def runner(self, job, store):
        self.turns.append(copy.deepcopy(job))
        key = (job["space"], job.get("delegation_phase"))
        if key == self.block_at:
            self.entered.set()
            while not self.release.is_set():
                await asyncio.sleep(0.01)
        await asyncio.sleep(0)
        if job["action"] == "learn":
            (Path(store.space(job["space"])["wiki_dir"]) / "approved-learning.md").write_text(
                "---\ntitle: 表单验证\n---\n# 表单验证\n本轮受控学习：HTML required 用于约束必填字段。", encoding="utf-8")
            job["source_reads"] = 1
        elif key == ("central", "consultation"):
            job["answer"] = self.CONSULTATION_TEXT
        elif key == ("central", "proposal"):
            result = self.proposal_outputs.pop(0) if self.proposal_outputs else {
                "type": "proposal", "title": "待确认的任务方案", "content": self.proposal_text}
            if isinstance(result, Exception):
                raise result
            job["answer"] = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        elif key == ("central", "plan"):
            job["answer"] = delegate(self.branch, "按已确认方案完成 " + self.branch + " 模块任务。")
        elif key == (self.branch, "plan"):
            child = "software-frontend" if self.branch == "software" else "content-planning"
            job["answer"] = delegate(child, "学习 HTML 表单验证" if job.get("learning") else "整理已确认范围的专业方案。")
        elif job.get("delegation_phase") == "research":
            job["answer"] = json.dumps({"queries": ["HTML form required validation"]})
        elif job.get("delegation_phase") in {"execute", "summary"}:
            job["answer"] = job["space"] + " 已返回受控任务结果，未发布到中央知识库。"
        else:
            raise AssertionError("Unexpected controlled turn: " + repr((job["action"], key)))

    async def collector(self, store, space, goal, urls=None, max_pages=2, run_id=None, queries=None, progress=None):
        self.collections.append({"space": space, "goal": goal, "urls": urls, "max_pages": max_pages})
        store.add_source(space, "approved-source.md", "受控来源：HTML required 支持必填字段约束。")
        result = {"sources": [{"url": "https://example.org/forms", "title": "Controlled forms",
                               "filename": "approved-source.md", "status": "new"}],
                  "errors": [], "provider": "fixture", "changed_count": 1}
        if progress:
            progress({**result, "status": "collecting"})
        return result

    async def researcher(self, store, goal, run_id, agents):
        self.researches.append({"goal": goal, "run_id": run_id})
        return {"run_id": run_id, "scope": "proposal-only", "status": "not_researched", "sources": [], "errors": [],
                "note": "受控测试不访问网络；方案资料保持待核实。"}

    @staticmethod
    async def maintain_templates(store, space, frameworks=None):
        return {"templates": [], "errors": []}

    def read(self):
        response = self.client.get("/api/chat/rooms/" + self.room_id)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def post(self, content, **fields):
        return self.client.post("/api/chat/rooms/" + self.room_id + "/messages", json={"content": content, **fields})

    def send(self, content, **fields):
        response = self.post(content, **fields)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["job"]

    def finish(self, job):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            response = self.client.get("/api/jobs/" + job["id"])
            self.assertEqual(response.status_code, 200, response.text)
            current = response.json()
            if current["status"] not in {"queued", "running"}:
                return current
            time.sleep(0.01)
        self.fail("Controlled primary job did not finish")

    def proposal(self, content=None, **fields):
        job = self.finish(self.send(content or self.PROJECT, **fields))
        self.assertEqual(job["status"], "completed", job)
        room = self.read()
        proposal = next(p for p in room.get("proposals", []) if p["id"] == room.get("active_proposal_id"))
        self.assertEqual(proposal["status"], "awaiting_confirmation")
        return copy.deepcopy(proposal)

    def assert_no_execution(self, room=None):
        room = room or self.read()
        self.assertEqual(room.get("task_groups", []), [])
        self.assertEqual(room.get("delegations", []), [])
        self.assertEqual(room["participants"], ["central"])
        self.assertEqual(self.collections, [])
        self.assertTrue(all(t["space"] == "central" for t in self.turns))
        self.assertFalse(any(t.get("delegation_phase") in {"plan", "execute", "summary", "research"}
                             or t["action"] == "learn" for t in self.turns))

    def test_analysis_withdrawal_supersedes_pending_and_provides_real_downloads(self):
        first = self.proposal('https://cephalon.cloud/aigc 请开发这个产品，给我待确认的开发方案')
        job = self.finish(self.send('暂时先不做开始做，先分析一下即可'))
        self.assertEqual(job['status'], 'completed', job)
        self.assertTrue(job['analysis'])
        self.assertTrue(job['research_only'])
        self.assertEqual(job['intake_kind'], 'answer')
        room = self.read()
        self.assertIsNone(room['active_proposal_id'])
        old = next(p for p in room['proposals'] if p['id'] == first['id'])
        self.assertEqual(old['status'], 'superseded')
        self.assertEqual(room['messages'][-1]['phase'], 'consultation')
        self.assert_no_execution(room)
        artifacts = room['messages'][-1]['artifacts']
        self.assertEqual({a['format'] for a in artifacts}, {'md', 'docx'})
        for artifact in artifacts:
            response = self.client.get(artifact['url'])
            self.assertEqual(response.status_code, 200)
            self.assertIn('attachment;', response.headers['content-disposition'])
            self.assertGreater(len(response.content), 20)
            if artifact['format'] == 'docx':
                self.assertTrue(response.content.startswith(b'PK'))
        self.assertIn('cephalon.cloud', self.researches[-1]['goal'])
        self.assertNotIn(self.PROPOSAL_TEXT, self.turns[-1]['question'])
        stale = self.post('确认方案并开始协作', confirm_proposal_id=first['id'])
        self.assertIn(stale.status_code, {400, 409})

    def test_product_report_with_mvp_is_readonly_without_any_confirmation(self):
        job = self.finish(self.send('https://cephalon.cloud/aigc 拆一下这个产品，怎么实现、获客、盈利，给我最小版本方案和可下载文档'))
        self.assertEqual(job['status'], 'completed', job)
        self.assertEqual(job['intake_kind'], 'answer')
        self.assertTrue(job['analysis'])
        self.assertEqual(self.read().get('proposals', []), [])
        self.assertIn('产品深度分析', self.turns[-1]['question'])
        self.assertNotIn('普通答复控制在400字以内', self.turns[-1]['question'])
        self.assert_no_execution()

    def test_document_failure_keeps_the_analysis_and_reports_the_export_error(self):
        with patch('federation.app.save_report', side_effect=OSError('controlled export failure')):
            job = self.finish(self.send('https://example.com/product 深度分析产品，给我可下载文档'))
        self.assertEqual(job['status'], 'completed')
        message = self.read()['messages'][-1]
        self.assertEqual(message['content'], self.CONSULTATION_TEXT)
        self.assertIn('文档生成失败', message['artifact_error'])
        self.assertNotIn('artifacts',message)
        self.assert_no_execution()

    def test_self_review_uses_own_model_report_and_never_host_supplement(self):
        self.finish(self.send('https://example.com/product 只分析产品并给我文档'))
        room=self.read()
        room['messages'][-1].update(response_origin='host_product_analysis_supplement',content='HOST_SUPPLEMENT_NOT_MODEL')
        self.app.state.chat.save_room(room)
        self.finish(self.send('https://example.com/product 只分析，请自行校对报告并给文档'))
        self.assertNotIn('analysis_review_draft',self.turns[-1])
        self.assertNotIn('HOST_SUPPLEMENT_NOT_MODEL',self.turns[-1]['question'])
        room=self.read()
        room['messages'][-1].update(response_origin='local_product_analysis_model',content='ACTUAL_PRIOR_MODEL_REPORT')
        self.app.state.chat.save_room(room)
        self.finish(self.send('https://example.com/product 只分析，请自行校对上一份报告并给文档'))
        self.assertEqual(self.turns[-1]['analysis_review_draft'],'ACTUAL_PRIOR_MODEL_REPORT')
        self.assert_no_execution()


    def test_capability_faq_and_ordinary_question_only_answer_as_main(self):
        for question in ("现在我可以做什么？", "知识库里的来源和结论有什么区别？"):
            with self.subTest(question=question):
                before_calls = len(self.turns)
                job = self.finish(self.send(question))
                self.assertEqual(job["status"], "completed", job)
                room = self.read()
                self.assert_no_execution(room)
                self.assertEqual(room.get("proposals", []), [])
                reply = room["messages"][-1]
                self.assertEqual((reply["role"], reply["agent_id"], reply["phase"]),
                                 ("assistant", "central", "consultation"))
                self.assertTrue(reply["content"].strip())
                self.assertLessEqual(len(self.turns) - before_calls, 1)
        self.assertTrue(any(t.get("delegation_phase") == "consultation" for t in self.turns))

    def test_skill_process_question_uses_inventory_without_model_or_execution(self):
        inventory = [
            {'id': 'pdf', 'display_name': 'PDF处理', 'execution_status': 'reference_only', 'status': 'ready'},
            {'id': 'documents', 'display_name': '文档编辑', 'execution_status': 'reference_only', 'status': 'ready'},
            {'id': 'broken', 'display_name': '损坏的技能', 'execution_status': 'reference_only', 'status': 'conflict'},
        ]
        before_calls = len(self.turns)
        with patch('federation.app.list_skills', return_value=inventory) as listing:
            job = self.finish(self.send('你可以调用skill 的进程吗？'))
        self.assertEqual(job['status'], 'completed', job)
        self.assertEqual(job['engine'], 'Host skill capability catalog')
        self.assertIn('2 份 Skill', job['answer'])
        self.assertEqual(len(self.turns), before_calls)
        self.assertEqual(listing.call_args.args[1], 'central')
        room = self.read()
        self.assert_no_execution(room)
        self.assertEqual(room.get('proposals', []), [])
        reply = room['messages'][-1]
        self.assertEqual(reply['response_origin'], 'host_skill_capability_catalog')
        self.assertEqual(reply['skill_inventory'], inventory)
        self.assertEqual(reply.get('skill_reads', []), [], 'Inventory is not a receipt of reading Skill bodies')

    def test_project_proposal_is_saved_and_revision_supersedes_without_execution(self):
        first = self.proposal()
        room = self.read()
        self.assert_no_execution(room)
        self.assertIn(self.PROJECT, first["goal"])
        message = next(m for m in room["messages"] if m["id"] == first["message_id"])
        self.assertEqual((message["role"], message["agent_id"], message["phase"], message["proposal_id"]),
                         ("assistant", "central", "proposal", first["id"]))
        self.assertEqual(message["content"], first["content"])
        self.assertIsNone(first.get("confirmed_job_id"))
        self.proposal_text = "修订方案：只由前端整理预约表单原型，排除后端开发；等待确认。"
        second = self.proposal(self.REVISION)
        current = self.read()
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(current["active_proposal_id"], second["id"])
        self.assertEqual([p["status"] for p in current["proposals"]], ["superseded", "awaiting_confirmation"])
        self.assertEqual(next(m for m in current["messages"] if m["id"] == first["message_id"]), message)
        self.assertIn("预约", second["goal"])
        self.assertIn("前端", second["goal"])
        self.assert_no_execution(current)

    def test_only_explicit_proposal_id_runs_and_repeated_confirmation_reuses_same_job(self):
        proposal = self.proposal()
        self.assert_no_execution()
        self.block_at = ("central", "plan")
        confirmed = self.send("确认这份方案。", confirm_proposal_id=proposal["id"])
        self.assertTrue(self.entered.wait(8), "Approved orchestration did not start")
        pending = self.read()
        frozen_count = len(pending["messages"])
        repeated = self.send("确认这份方案。", confirm_proposal_id=proposal["id"])
        self.assertEqual(repeated["id"], confirmed["id"])
        self.assertEqual(len(self.read()["messages"]), frozen_count)
        self.assertIn(proposal["goal"], confirmed["question"])
        self.assertEqual(confirmed["approved_plan"]["content"], proposal["content"])
        self.assertTrue(any(proposal["goal"] in t["question"] for t in self.turns if t.get("delegation_phase") == "plan"))
        self.assertTrue(any(proposal["content"] in t["question"] for t in self.turns if t.get("delegation_phase") == "plan"))
        self.release.set()
        self.assertEqual(self.finish(confirmed)["status"], "completed")
        completed = self.read()
        state = next(p for p in completed["proposals"] if p["id"] == proposal["id"])
        self.assertEqual(state["status"], "confirmed")
        self.assertEqual(state["confirmed_job_id"], confirmed["id"])
        self.assertEqual(len(completed["task_groups"]), 1)
        self.assertEqual({t["round_id"] for t in completed["delegations"]}, {confirmed["id"]})
        calls = len(self.turns)
        files = {p.name for p in (self.base / "jobs").glob("*.json")}
        again = self.send("再次点击确认。", confirm_proposal_id=proposal["id"])
        self.assertEqual(again["id"], confirmed["id"])
        self.assertEqual(len(self.turns), calls)
        self.assertEqual({p.name for p in (self.base / "jobs").glob("*.json")}, files)
        self.assertEqual(self.read()["messages"], completed["messages"])
        self.close_client()
        self.open_client()
        recovered = self.send("重启后再次确认。", confirm_proposal_id=proposal["id"])
        self.assertEqual(recovered["id"], confirmed["id"])
        self.assertEqual(len(self.turns), calls)
        self.assertEqual({p.name for p in (self.base / "jobs").glob("*.json")}, files)
        self.assertEqual(self.read()["messages"], completed["messages"])

    def test_stale_and_unknown_confirmation_fail_without_new_jobs_or_messages(self):
        stale = self.proposal()
        active = self.proposal(self.REVISION)
        before = self.read()
        files = {p.name for p in (self.base / "jobs").glob("*.json")}
        for identifier, status in ((stale["id"], 409), (uuid.uuid4().hex, 404)):
            with self.subTest(identifier=identifier):
                response = self.post("确认", confirm_proposal_id=identifier)
                self.assertEqual(response.status_code, status, response.text)
        self.assertEqual(self.read(), before)
        self.assertEqual({p.name for p in (self.base / "jobs").glob("*.json")}, files)
        self.assertEqual(before["active_proposal_id"], active["id"])
        self.assert_no_execution()

    def test_approval_words_in_discussion_or_denial_do_not_start_execution(self):
        self.proposal()
        for content in ("确认按钮是什么意思？先别执行。", "不要开始，先讨论你说的‘确认方案’。", "同意这个思路，但暂时不要分派任务。"):
            with self.subTest(content=content):
                result = self.finish(self.send(content))
                self.assertEqual(result["status"], "completed", result)
                self.assert_no_execution()
                self.assertTrue(all(p["status"] != "confirmed" for p in self.read()["proposals"]))

    def test_pending_proposal_survives_questions_and_plain_confirmation_text_until_button_confirmation(self):
        proposal = self.proposal()
        for question in ("为什么采用这个方案？", "确认"):
            with self.subTest(question=question):
                job = self.finish(self.send(question))
                self.assertEqual(job["status"], "completed", job)
                room = self.read()
                self.assert_no_execution(room)
                self.assertEqual(room["active_proposal_id"], proposal["id"])
                self.assertEqual(room["proposals"], [proposal])
                self.assertEqual(room["messages"][-1]["phase"], "consultation")
        confirmed = self.send("点击方案确认按钮", confirm_proposal_id=proposal["id"])
        self.assertEqual(self.finish(confirmed)["status"], "completed")
        room = self.read()
        self.assertEqual(room["proposals"][0]["confirmed_job_id"], confirmed["id"])
        self.assertEqual(len(room["task_groups"]), 1)

    def test_explicit_cancellation_invalidates_old_proposal_and_prevents_button_replay(self):
        proposal = self.proposal()
        cancelled = self.finish(self.send("取消这个方案，先不做了。"))
        self.assertEqual(cancelled["status"], "completed", cancelled)
        room = self.read()
        self.assert_no_execution(room)
        self.assertIsNone(room.get("active_proposal_id"))
        self.assertEqual(room["proposals"][0]["status"], "superseded")
        response = self.post("再次点击旧方案确认按钮", confirm_proposal_id=proposal["id"])
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.read(), room)

    def test_pending_proposal_survives_restart_and_consultation_interruption_is_not_completion(self):
        proposal = self.proposal()
        before = self.read()
        self.close_client()
        self.open_client()
        self.assertEqual(self.read()["proposals"], before["proposals"])
        self.assertEqual(self.read()["active_proposal_id"], proposal["id"])
        self.block_at = ("central", "consultation")
        pending = self.send("先不执行，请解释一下方案里的术语是什么意思？")
        self.assertTrue(self.entered.wait(8), "Consultation did not reach gate")
        self.close_client()
        self.open_client()
        interrupted = self.client.get("/api/jobs/" + pending["id"]).json()
        self.assertEqual(interrupted["status"], "failed")
        room = self.read()
        self.assertEqual(room["status"], "failed")
        preserved = next(p for p in room["proposals"] if p["id"] == proposal["id"])
        self.assertEqual(preserved["content"], proposal["content"])
        self.assertEqual(preserved["goal"], proposal["goal"])
        self.assertIn(preserved["status"], {"awaiting_confirmation", "superseded"})
        self.assertIsNone(preserved.get("confirmed_job_id"))
        self.assert_no_execution(room)

    def test_learning_proposal_requires_confirmation_and_uses_saved_scope(self):
        approved_url = "https://example.org/forms"
        proposal = self.proposal(self.LEARNING, learning=True, urls=[approved_url], max_pages=1)
        self.assert_no_execution()
        confirmed = self.send("确认学习方案。", confirm_proposal_id=proposal["id"])
        self.assertEqual(self.finish(confirmed)["status"], "completed")
        self.assertTrue(confirmed.get("learning"))
        self.assertEqual(confirmed.get("urls"), [approved_url])
        self.assertEqual(confirmed.get("max_pages"), 1)
        self.assertEqual(len(self.collections), 1)
        self.assertEqual(self.collections[0]["space"], "software-frontend")
        self.assertEqual(self.collections[0]["urls"], [approved_url])
        self.assertEqual(self.collections[0]["max_pages"], 1)
        self.assertEqual(sum(t["action"] == "learn" for t in self.turns), 1)
        self.assertEqual(self.app.state.store.space("central")["knowledge_count"], 0)
        self.assertFalse(list((self.base / "published").rglob("*.md")))

    def test_cancelled_approved_execution_stays_failed_and_cannot_be_confirmed_twice(self):
        proposal = self.proposal()
        self.block_at = ("software-frontend", "execute")
        confirmed = self.send("确认方案", confirm_proposal_id=proposal["id"])
        self.assertTrue(self.entered.wait(8), "Approved child did not reach gate")
        self.close_client()
        self.open_client()
        interrupted = self.client.get("/api/jobs/" + confirmed["id"]).json()
        self.assertEqual(interrupted["status"], "failed")
        room = self.read()
        self.assertEqual(room["task_groups"][0]["status"], "failed")
        saved = next(p for p in room["proposals"] if p["id"] == proposal["id"])
        self.assertEqual(saved["status"], "confirmed")
        self.assertEqual(saved["confirmed_job_id"], confirmed["id"])
        count = len(self.turns)
        again = self.send("重试确认同一方案", confirm_proposal_id=proposal["id"])
        self.assertEqual(again["id"], confirmed["id"])
        self.assertEqual(again["status"], "failed")
        self.assertEqual(len(self.turns), count)
        self.assertEqual(self.read()["messages"], room["messages"])

    def test_confirmation_cannot_upgrade_ordinary_proposal_to_learning_or_replace_goal(self):
        proposal = self.proposal()
        response = self.post("改为采集所有行业并立即发布中央。", confirm_proposal_id=proposal["id"],
                             learning=True, urls=["https://example.org/unapproved"], max_pages=5)
        # The saved scope may be used or the inconsistent payload rejected;
        # either policy must prevent new authority from the confirmation body.
        if response.status_code == 200:
            confirmed = response.json()["job"]
            self.assertFalse(confirmed.get("learning", False))
            self.assertEqual(confirmed.get("urls", []), [])
            self.assertIn(proposal["goal"], confirmed["question"])
            self.assertNotIn("采集所有行业", confirmed["question"])
            self.assertEqual(self.finish(confirmed)["status"], "completed")
        else:
            self.assertIn(response.status_code, {400, 409}, response.text)
            self.assert_no_execution()
        self.assertEqual(self.collections, [])
        self.assertFalse(any(t["action"] == "learn" for t in self.turns))

    def test_learning_revocation_invalidates_old_button_and_revised_plan_cannot_write_knowledge(self):
        old = self.proposal(self.LEARNING, learning=True, urls=["https://example.org/forms"], max_pages=1)
        self.assertTrue(old["execution_options"]["learning"])
        revision = self.proposal("不要联网学习了，只讨论方案。")
        self.assertNotEqual(revision["id"], old["id"])
        self.assertEqual(revision["execution_options"]["learning"], False)
        self.assertEqual(revision["execution_options"]["urls"], [])
        self.assertEqual(self.read()["proposals"][0]["status"], "superseded")
        self.assertEqual(self.post("旧按钮", confirm_proposal_id=old["id"]).status_code, 409)
        self.assert_no_execution()
        confirmed = self.send("确认新的只讨论方案", confirm_proposal_id=revision["id"])
        self.assertEqual(self.finish(confirmed)["status"], "completed")
        self.assertFalse(confirmed.get("learning", False))
        self.assertEqual(self.collections, [])
        self.assertFalse(any(turn["action"] == "learn" for turn in self.turns))
        self.assertTrue(all(space["knowledge_count"] == 0 for space in self.app.state.store.spaces()))

    def test_invalid_proposal_format_gets_one_main_only_repair_and_keeps_original_failed_turn(self):
        invalid = '{"type":"proposal","title":"预约网站","content":"表单需要错误提示","content":"---\\ntitle: 重复包装\\n---"}'
        repaired = ("# 预约网站方案\n\n## 目标与范围\n预约表单和错误提示。\n\n"
                    "## 调研事实与待核实信息\n外部资料待核实。\n\n## 建议方案\n整理表单状态。\n\n"
                    "## 建议分工\n建议软件模块安排前端。\n\n## 验收标准\n列出错误提示状态。\n\n"
                    "## 待确认事项\n等待用户确认，不执行。")
        self.proposal_outputs = [invalid, repaired]
        job = self.finish(self.send(self.PROJECT))
        self.assertEqual(job["status"], "completed", job)
        self.assertEqual(job["format_repair_count"], 1)
        self.assertEqual(len(job["format_errors"]), 1)
        self.assertEqual([(t["space"], t["delegation_phase"]) for t in self.turns],
                         [("central", "proposal"), ("central", "proposal")])
        self.assertEqual(len(job["turns"]), 2)
        first = self.client.get("/api/jobs/" + job["turns"][0]["id"]).json()
        second = self.client.get("/api/jobs/" + job["turns"][1]["id"]).json()
        self.assertEqual((first["status"], first["error_kind"], first["format_attempt"]),
                         ("failed", "response_format", 1))
        self.assertEqual(first["raw_answer"], invalid)
        self.assertEqual(first["answer"], invalid)
        self.assertEqual((second["status"], second["format_attempt"]), ("completed", 2))
        self.assertNotEqual(first["id"], second["id"])
        self.assertIn(json.dumps(invalid, ensure_ascii=False), second["question"])
        self.assertIn("不引入新事实", second["question"])
        self.assertIn("不得创建群", second["question"])
        self.assertEqual(len(self.researches), 1)
        room = self.read()
        self.assertEqual(len(room["proposals"]), 1)
        self.assertEqual(room["proposals"][0]["status"], "awaiting_confirmation")
        self.assertEqual(room["messages"][-1]["content"], repaired)
        self.assertEqual(room["proposals"][0]["content"], repaired)
        self.assert_no_execution(room)

    def test_research_followup_overrides_checked_learning_and_keeps_existing_plan(self):
        proposal = self.proposal()
        self.finish(self.send("那你找找现在做什么副业比较赚钱，不累不费时间的"))
        before = copy.deepcopy(self.read())
        self.turns.clear()
        self.researches.clear()
        job = self.finish(self.send("再找找呢", learning=True))
        self.assertEqual(job["status"], "completed", job)
        self.assertEqual(job["intake_kind"], "answer")
        self.assertTrue(job["research_only"])
        self.assertFalse(job["execution_options"]["learning"])
        self.assertIn("副业", self.researches[0]["goal"])
        self.assertIn("再找找呢", self.researches[0]["goal"])
        self.assertNotIn("预约网站", self.researches[0]["goal"])
        self.assertEqual(len(self.turns), 1)
        self.assertEqual(self.turns[0]["delegation_phase"], "consultation")
        self.assertIn("副业", self.turns[0]["question"])
        self.assertNotIn("format_repair_count", job)
        room = self.read()
        self.assertEqual(room["proposals"], before["proposals"])
        self.assertEqual(room["active_proposal_id"], proposal["id"])
        self.assertEqual(room["messages"][-1]["phase"], "consultation")
        self.assertTrue(room["messages"][-1]["research_only"])
        self.assertEqual(room["messages"][-1]["research"]["status"], "not_researched")
        self.assert_no_execution(room)

    def test_explicit_research_and_urls_do_not_grant_learning_and_survive_reload(self):
        job = self.finish(self.send("了解自由职业渠道", research=True,
                                    urls=["https://example.org/freelance"]))
        self.assertEqual(job["status"], "completed", job)
        self.assertIn("https://example.org/freelance", self.researches[-1]["goal"])
        self.assertFalse(job["execution_options"]["learning"])
        self.assertEqual(job["execution_options"]["urls"], [])
        before = copy.deepcopy(self.read())
        self.close_client()
        self.open_client()
        self.assertEqual(self.read(), before)
        self.assert_no_execution()

    def test_lookup_terms_do_not_grant_project_or_learning_authority(self):
        for content, fields in [
            ("帮我查询网站开发有哪些方式", {"research": True}),
            ("帮我查一下机器学习课程", {"learning": True}),
            ("不要学习，帮我查一下 React", {"learning": True}),
        ]:
            with self.subTest(content=content):
                job = self.finish(self.send(content, **fields))
                self.assertEqual(job["status"], "completed", job)
                self.assertEqual(job["intake_kind"], "answer")
                self.assertFalse(job["execution_options"]["learning"])
                self.assertTrue(job["research_only"])
                self.assertFalse(self.read().get("proposals"))
        self.assert_no_execution()

    def test_cancellation_wins_over_research_toggle(self):
        job = self.finish(self.send("取消项目", research=True))
        self.assertEqual(job["status"], "completed", job)
        self.assertFalse(job.get("research_only", False))
        self.assertEqual(self.researches, [])
        self.assert_no_execution()

    def test_research_learning_revocation_clears_persistent_clarification_authority(self):
        self.proposal_outputs = ["请补充学习范围、预算与平台。"]
        self.finish(self.send(self.LEARNING, learning=True))
        self.assertTrue(self.read()["clarification_context"]["execution_options"]["learning"])
        revoked = self.finish(self.send("不要学习，帮我查一下 React", research=True))
        self.assertEqual(revoked["status"], "completed", revoked)
        self.assertFalse(self.read().get("clarification_context"))
        self.close_client()
        self.open_client()
        following = self.finish(self.send("预算5000元，平台采用 Vue。"))
        self.assertFalse(following["execution_options"]["learning"])
        self.assertFalse(following.get("continue_clarification"))
        self.assertFalse(self.read().get("proposals"))
        self.assert_no_execution()

    def test_explicit_learning_lookup_keeps_confirmation_requirement(self):
        job = self.finish(self.send("/学习 搜索并学习 HTML 表单验证", research=True))
        self.assertEqual(job["status"], "completed", job)
        self.assertEqual(job["intake_kind"], "proposal")
        self.assertTrue(job["execution_options"]["learning"])
        self.assertFalse(job.get("research_only", False))
        self.assertIsNotNone(self.read()["active_proposal_id"])
        self.assert_no_execution()

    def test_plain_proposal_clarification_is_shown_without_retry_or_confirmation(self):
        text = "可以先分析几个方向。还需要确认你每周能投入多少时间，才能形成具体方案。"
        self.proposal_outputs = [text]
        job = self.finish(self.send(self.PROJECT))
        self.assertEqual(job["status"], "completed", job)
        self.assertEqual(len(job["turns"]), 1)
        self.assertNotIn("format_repair_count", job)
        room = self.read()
        self.assertEqual(room["messages"][-1]["content"], text)
        self.assertEqual(room["messages"][-1]["phase"], "consultation")
        self.assertFalse(room.get("proposals"))
        self.assertIsNone(room.get("active_proposal_id"))
        self.assert_no_execution()

    def test_two_invalid_formats_fail_with_raw_receipts_and_no_third_call_or_proposal(self):
        invalid = '{"type":"proposal","title":"重复","content":"第一段","content":"第二段"}'
        forbidden = '{"action":"delegate","tasks":[]}'
        self.proposal_outputs = [invalid, forbidden, {"type": "proposal", "title": "不得出现的第三次", "content": "不应重试"}]
        job = self.finish(self.send(self.PROJECT))
        self.assertEqual(job["status"], "failed")
        self.assertIn("连续两次回复格式无效", job["error"])
        self.assertEqual(job["format_repair_count"], 1)
        self.assertEqual(len(job["format_errors"]), 2)
        self.assertEqual(len(job["turns"]), 2)
        self.assertEqual(len(self.turns), 2)
        self.assertEqual(len(self.proposal_outputs), 1)
        for reference, raw in zip(job["turns"], (invalid, forbidden)):
            turn = self.client.get("/api/jobs/" + reference["id"]).json()
            self.assertEqual((turn["status"], turn["error_kind"]), ("failed", "response_format"))
            self.assertEqual(turn["raw_answer"], raw)
        room = self.read()
        self.assertEqual(room["status"], "failed")
        self.assertEqual(room.get("proposals", []), [])
        self.assertIsNone(room.get("active_proposal_id"))
        self.assertIn("格式无效", room["messages"][-1]["content"])
        self.assertEqual(room["messages"][-1]["status"], "failed")
        self.assert_no_execution(room)

    def test_link_first_answer_is_saved_once_without_format_repair(self):
        text = f'[下载测试文档](/api/chat/rooms/{self.room_id}/files/' + 'b' * 32 + ')\n\n文件大小约 3 KB。'
        self.CONSULTATION_TEXT = text
        job = self.finish(self.send('请提供测试文档的链接。'))
        self.assertEqual(job['status'], 'completed', job)
        self.assertEqual(len(job['turns']), 1)
        self.assertNotIn('format_repair_count', job)
        self.assertNotIn('format_errors', job)
        self.assertEqual(job['answer'], text)
        room = self.read()
        self.assertEqual(room['messages'][-1]['content'], text)
        self.assertEqual(room['messages'][-1]['status'], 'completed')
        self.assert_no_execution(room)

    def test_invalid_answer_format_does_not_claim_a_project_proposal_failed(self):
        self.CONSULTATION_TEXT = '{"type":'
        job = self.finish(self.send('请解释一个普通概念。'))
        self.assertEqual(job['status'], 'failed')
        self.assertEqual(len(job['turns']), 2)
        self.assertIn('未能保存完整答复', job['error'])
        self.assertNotIn('未生成可确认方案', job['error'])
        self.assertEqual(self.read()['messages'][-1]['status'], 'failed')
        self.assert_no_execution()

    def test_model_transport_failure_does_not_trigger_format_repair(self):
        self.proposal_outputs = [RuntimeError("受控网络故障")]
        job = self.finish(self.send(self.PROJECT))
        self.assertEqual(job["status"], "failed")
        self.assertIn("受控网络故障", job["error"])
        self.assertEqual(len(job["turns"]), 1)
        self.assertNotIn("format_repair_count", job)
        self.assertEqual(len(self.turns), 1)
        self.assert_no_execution()

    def test_history_over_one_hundred_recovers_every_job_and_polls_disk_backed_confirmation(self):
        proposal = self.proposal()
        confirmed = self.send("确认", confirm_proposal_id=proposal["id"])
        self.assertEqual(self.finish(confirmed)["status"], "completed")
        before = self.read()
        original_calls = len(self.turns)
        self.close_client()
        # Cache age and UUID ordering are deliberately different. These are only
        # persisted fixtures in this test's disposable store, never real jobs.
        job_dir = self.base / "jobs"
        path = job_dir / (confirmed["id"] + ".json")
        old_job = json.loads(path.read_text())
        old_job["created_at"] = "2000-01-01T00:00:00+00:00"
        path.write_text(json.dumps(old_job, ensure_ascii=False))
        interrupted_id = "00000000000000000000000000000001"
        interrupted_path = job_dir / (interrupted_id + ".json")
        interrupted_path.write_text(json.dumps({"id": interrupted_id, "action": "ask", "space": "software",
            "status": "running", "question": "重启前未完成的隔离任务", "output": "",
            "created_at": "1999-01-01T00:00:00+00:00"}))
        for index in range(130):
            identifier = f"{1000 + index:032x}"
            (job_dir / (identifier + ".json")).write_text(json.dumps({"id": identifier, "action": "ask",
                "space": "software", "status": "completed", "question": "历史夹具", "output": "已完成",
                "created_at": "2099-01-01T00:00:00+00:00"}))
        files = {p.name for p in job_dir.glob("*.json")}
        self.open_client()
        self.assertEqual(json.loads(interrupted_path.read_text())["status"], "failed")
        replay = self.send("重新打开旧方案确认记录", confirm_proposal_id=proposal["id"])
        self.assertEqual((replay["id"], replay["status"]), (confirmed["id"], "completed"))
        response = self.client.get("/api/jobs/" + confirmed["id"])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), replay)
        interrupted = self.client.get("/api/jobs/" + interrupted_id)
        self.assertEqual(interrupted.status_code, 200, interrupted.text)
        self.assertEqual(interrupted.json()["status"], "failed")
        self.assertIn("上次服务已结束", interrupted.json()["error"])
        self.assertEqual(len(self.turns), original_calls)
        self.assertEqual({p.name for p in job_dir.glob("*.json")}, files)
        self.assertEqual(self.read()["messages"], before["messages"])

    def test_clarification_survives_restart_unrelated_question_and_resumes_complete_project_goal(self):
        self.proposal_outputs = [{"type": "answer", "content": "请说明目标用户、预算和上线时间。"}]
        first = self.finish(self.send(self.PROJECT))
        self.assertEqual(first["status"], "completed", first)
        self.assertEqual(first["intake_stage"], "awaiting_clarification")
        room = self.read()
        self.assert_no_execution(room)
        self.assertEqual(room.get("proposals", []), [])
        context = copy.deepcopy(room["clarification_context"])
        self.assertEqual(context["goal"], self.PROJECT)
        self.assertFalse(context["execution_options"]["learning"])
        self.assertEqual(context["question"], "请说明目标用户、预算和上线时间。")
        self.close_client()
        self.open_client()
        self.assertEqual(self.read()["clarification_context"], context)
        ordinary = self.finish(self.send("什么是知识库里的来源与结论？"))
        self.assertEqual(ordinary["status"], "completed", ordinary)
        self.assertEqual(self.read()["clarification_context"], context)
        self.assertEqual(self.read().get("proposals", []), [])
        supplement = "面向学生，两周上线，预算5000元，平台采用 Vue。"
        proposal = self.proposal(supplement)
        self.assertIn(self.PROJECT, proposal["goal"])
        self.assertIn(supplement, proposal["goal"])
        self.assertNotIn("clarification_context", self.read())
        self.assert_no_execution()
        self.assertEqual(self.researches[-1]["goal"], proposal["goal"])
        prompt = next(t["question"] for t in reversed(self.turns) if t.get("delegation_phase") == "proposal")
        self.assertIn(self.PROJECT, prompt)
        self.assertIn(supplement, prompt)
        confirmed = self.send("确认完整方案", confirm_proposal_id=proposal["id"])
        self.assertEqual(confirmed["question"], proposal["goal"])
        self.assertEqual(self.finish(confirmed)["status"], "completed")

    def test_cancel_clears_clarification_and_old_learning_options_cannot_resume(self):
        self.proposal_outputs = [{"type": "answer", "content": "请补充预算和适用平台。"}]
        first = self.finish(self.send(self.LEARNING, learning=True, urls=["https://example.org/forms"], max_pages=1))
        self.assertEqual(first["status"], "completed", first)
        context = self.read()["clarification_context"]
        self.assertEqual(context["execution_options"], {"learning": True, "urls": ["https://example.org/forms"], "max_pages": 1})
        cancelled = self.finish(self.send("先不要执行。"))
        self.assertEqual(cancelled["status"], "completed", cancelled)
        self.assertNotIn("clarification_context", self.read())
        followup = self.finish(self.send("预算5000元，平台采用 Vue。"))
        self.assertEqual(followup["status"], "completed", followup)
        self.assertEqual(followup["intake_kind"], "answer")
        self.assertEqual(self.read().get("proposals", []), [])
        self.assert_no_execution()

    def test_two_confirmed_proposals_use_same_primary_and_only_current_actual_group_members(self):
        first = self.proposal()
        first_job = self.send("确认", confirm_proposal_id=first["id"])
        self.assertEqual(self.finish(first_job)["status"], "completed")
        old_room = self.read()
        self.branch = "content"
        self.proposal_text = "建议由内容模块安排编剧策划整理短片大纲，等待用户确认。"
        second = self.proposal("我想做一个新的短片项目，请先规划故事大纲方案。")
        self.assertEqual(len(self.read()["task_groups"]), 1)
        second_job = self.send("确认新方案", confirm_proposal_id=second["id"])
        self.assertEqual(self.finish(second_job)["status"], "completed")
        current = self.read()
        self.assertEqual(len(current["task_groups"]), 2)
        self.assertEqual(current["task_groups"][0], old_room["task_groups"][0])
        self.assertEqual(current["messages"][:len(old_room["messages"])], old_room["messages"])
        self.assertEqual(current["task_groups"][1]["members"], ["central", "content", "content-planning"])
        self.assertEqual(current["current_task_group_id"], second_job["id"])
        self.assertEqual(self.client.post("/api/chat/primary", json={}).json()["id"], self.room_id)
        self.assertEqual(len(self.client.get("/api/chat/rooms").json()["rooms"]), 1)

    def test_legacy_manual_orchestrated_room_keeps_immediate_execution_protocol(self):
        response = self.client.post("/api/chat/rooms", json={"mode": "orchestrated", "participants": ["central"]})
        self.assertEqual(response.status_code, 200, response.text)
        legacy_id = response.json()["id"]
        response = self.client.post("/api/chat/rooms/" + legacy_id + "/messages", json={"content": self.PROJECT})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.finish(response.json()["job"])["status"], "completed")
        legacy = self.client.get("/api/chat/rooms/" + legacy_id).json()
        self.assertEqual(len(legacy["task_groups"]), 1)
        self.assertTrue(legacy["delegations"])
        self.assertEqual(legacy.get("proposals", []), [])
        self.assertFalse(any(t.get("delegation_phase") in {"consultation", "proposal"} for t in self.turns))
        self.assertEqual(self.read()["messages"], [])


if __name__ == "__main__":
    unittest.main()
