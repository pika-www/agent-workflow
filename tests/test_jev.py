"""Jev transport contract, fallback and host permission boundaries."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch, AsyncMock

import httpx
from fastapi.testclient import TestClient

from federation.app import create_app
from federation.core import FederationStore
from federation.jev import ENDPOINT, INTENTS, JevRouter, _Deadline, apply_decision


def choice(options, value, confidence=.99):
    return {"type": "choice", "choice": value, "confidence": confidence,
            "probabilities": {key: 1.0 if key == value else 0.0 for key in options}}


def output(payload, intent="answer", role="central", confidence=.99):
    return {"model": "jev-1.13.0", "answers": {
        "intent": choice(payload["questions"]["intent"]["criteria"], intent, confidence),
        "route": choice(payload["questions"]["route"]["criteria"], role)},
        "usage": {"input_tokens": 50, "output_tokens": 6}}


class JevTransportTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = FederationStore(base=Path(self.temp.name) / "data")
        self.store.init()
        self.env = patch.dict(os.environ, {"JEV_AI_API_KEY": "sk-test-secret-value", "JEV_AI_ENABLED": "true"})
        self.env.start()
        self.agents = [{"id": "central", "name": "主 Agent"}, {"id": "software-frontend", "name": "前端工程师"}]

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    async def test_exact_destination_redacted_context_and_sanitized_receipt(self):
        requests = []
        def handle(request):
            requests.append(request)
            self.assertEqual(str(request.url), ENDPOINT)
            self.assertEqual(request.headers["Authorization"], "Bearer sk-test-secret-value")
            data = json.loads(request.content)
            self.assertEqual(data["model"], "jev-latest")
            self.assertNotIn("sk-test-secret-value", request.content.decode())
            self.assertNotIn("private assistant", request.content.decode())
            self.assertNotIn("wiki-secret", request.content.decode())
            self.assertTrue(data["state"]["has_pending_proposal"])
            return httpx.Response(200, json=output(data, role="software-frontend"),
                headers={"X-Jev-Billing": "tokens", "X-Jev-Paid-Input-Tokens-Used": "50", "X-Jev-Credits-Charged": "0"})
        router = JevRouter(self.store, httpx.MockTransport(handle))
        room = {"messages": [{"role": "assistant", "content": "private assistant"},
                             {"role": "user", "content": "sk-test-secret-value"}],
                "wiki": "wiki-secret", "active_proposal_id": "p", "proposals": [{"id": "p", "status": "awaiting_confirmation", "goal": "前端"}]}
        result = await router.classify("请解释 sk-test-secret-value", room, self.agents)
        self.assertEqual(result["status"], "classified")
        self.assertEqual(result["suggested_agent"], "software-frontend")
        self.assertEqual(result["paid_input_tokens_used"], 50)
        self.assertNotIn("sk-test-secret-value", json.dumps(result))
        self.assertEqual(len(requests), 1)
        self.assertNotIn("sk-test-secret-value", json.dumps(router.status()))

    async def test_http_errors_do_not_retry_or_expose_provider_body(self):
        for status in (401, 402, 422, 429, 502, 504, 302):
            calls = []
            def handle(request):
                calls.append(request)
                return httpx.Response(status, text="sk-provider-secret-value", headers={"Location": "https://example.org"})
            result = await JevRouter(self.store, httpx.MockTransport(handle)).classify("问题", {}, self.agents)
            self.assertEqual(result["status"], "unavailable")
            self.assertEqual(result["http_status"], status)
            if status == 402:
                self.assertEqual(result["reason"], "insufficient_balance")
                self.assertIn("余额不足", result["notice"])
            self.assertEqual(len(calls), 1)
            self.assertNotIn("sk-provider-secret-value", json.dumps(result))
            if status == 402:
                JevRouter(self.store).reset_balance_block()

    async def test_bad_choices_confidence_probabilities_or_response_are_fallback(self):
        def bad_intent(data):
            data["answers"]["intent"]["choice"] = "execute"
        def bad_role(data):
            data["answers"]["route"]["choice"] = "fake-role"
        def bad_confidence(data):
            data["answers"]["intent"]["confidence"] = float("nan")
        def bad_probability(data):
            data["answers"]["route"]["probabilities"]["central"] = 8
        for corrupt in (bad_intent, bad_role, bad_confidence, bad_probability):
            def handle(request):
                data = output(json.loads(request.content)); corrupt(data)
                return httpx.Response(200, text=json.dumps(data))
            result = await JevRouter(self.store, httpx.MockTransport(handle)).classify("问题", {}, self.agents)
            self.assertEqual(result["reason"], "invalid_response")
        for content in (b"not json", b"x" * 256001, b"[]"):
            result = await JevRouter(self.store, httpx.MockTransport(lambda request: httpx.Response(200, content=content))).classify("问题", {}, self.agents)
            self.assertEqual(result["reason"], "invalid_response")

    async def test_balance_failure_stays_blocked_after_time_restart_and_model_change(self):
        calls = []
        def handle(request):
            calls.append(request)
            return httpx.Response(402)
        router = JevRouter(self.store, httpx.MockTransport(handle))
        first = await router.classify('解释前后端', {}, self.agents)
        second = await router.classify('再解释一个问题', {}, self.agents)
        self.assertEqual(first['calls'], 1)
        self.assertEqual(second['calls'], 0)
        self.assertTrue(second['cached_failure'])
        self.assertEqual(second['reason'], 'insufficient_balance')
        self.assertNotEqual(first['usage_event_id'], second['usage_event_id'])
        self.assertEqual(len(calls), 1)
        self.assertEqual(router.status()['retry_after_seconds'], 0)
        self.assertFalse(router.status()['enabled'])
        self.assertTrue(router.status()['resume_required'])
        self.assertNotIn('sk-test-secret-value', json.dumps(router.status()))
        self.assertNotIn('sk-test-secret-value', router._balance_path().read_text())
        self.assertEqual(router._balance_path().stat().st_mode & 0o777, 0o600)
        # Restart and elapsed time do not revive the exhausted account.
        router = JevRouter(self.store, httpx.MockTransport(handle))
        with patch('federation.jev.time.monotonic', return_value=time.monotonic()+86400):
            self.assertEqual((await router.classify('隔天继续', {}, self.agents))['calls'], 0)
        with patch.dict(os.environ, {'JEV_AI_MODEL':'jev-other-model'}):
            self.assertEqual((await router.classify('换模型', {}, self.agents))['calls'], 0)
        with patch.dict(os.environ, {'JEV_AI_ENABLED':'false'}):
            self.assertEqual((await router.classify('关闭', {}, self.agents))['status'], 'disabled')
        self.assertEqual((await router.classify('只打开开关', {}, self.agents))['calls'], 0)
        # A different credential may be tried, but cannot clear the original block.
        with patch.dict(os.environ, {'JEV_AI_API_KEY':'sk-new-test-secret-value'}):
            third = await router.classify('配置已更新', {}, self.agents)
            self.assertEqual(third['calls'], 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual((await router.classify('切回原账号', {}, self.agents))['calls'], 0)
        # Only explicit reset authorizes another attempt for the same account.
        # Recovery can be performed by an operator process while the server remains up.
        JevRouter(self.store).reset_balance_block()
        self.assertTrue(router.status()['enabled'])
        await router.classify('余额恢复后重试', {}, self.agents)
        self.assertEqual(len(calls), 3)

    async def test_concurrent_requests_recheck_balance_after_first_failure(self):
        calls = []
        async def handle(request):
            calls.append(request)
            await asyncio.sleep(.01)
            return httpx.Response(402)
        router = JevRouter(self.store, httpx.MockTransport(handle))
        results = await asyncio.gather(*(router.classify('问题', {}, self.agents) for _ in range(4)))
        self.assertEqual(len(calls), 1)
        self.assertEqual([r['calls'] for r in results], [1, 0, 0, 0])

    async def test_unreadable_stop_record_does_not_resume_requests(self):
        router = JevRouter(self.store, httpx.MockTransport(lambda request: self.fail('blocked router called')))
        router._balance_path().parent.mkdir(parents=True, exist_ok=True)
        router._balance_path().write_text('not json')
        self.assertFalse(router.status()['enabled'])
        result = await router.classify('问题', {}, self.agents)
        self.assertEqual(result['calls'], 0)
        self.assertEqual(result['reason'], 'balance_state_unavailable')

    async def test_timeout_is_bounded_and_disabled_makes_no_call(self):
        def timeout(request):
            raise httpx.ReadTimeout("sk-test-secret-value")
        result = await JevRouter(self.store, httpx.MockTransport(timeout)).classify("问题", {}, self.agents)
        self.assertEqual(result["reason"], "timeout")
        with patch.dict(os.environ, {"JEV_AI_ENABLED": "false"}):
            result = await JevRouter(self.store, httpx.MockTransport(lambda request: self.fail("disabled router called"))).classify("问题", {}, self.agents)
            self.assertEqual(result["status"], "disabled")
        with self.assertRaises(asyncio.TimeoutError):
            async with _Deadline(.01):
                await asyncio.sleep(.1)

    async def test_provider_namespaced_model_id_is_preserved(self):
        def handle(request):
            data = output(json.loads(request.content))
            data["model"] = "typesafe-ai/jev"
            return httpx.Response(200, json=data)
        result = await JevRouter(self.store, httpx.MockTransport(handle)).classify("问题", {}, self.agents)
        self.assertEqual(result["status"], "classified")
        self.assertEqual(result["model"], "typesafe-ai/jev")

    def test_confidence_and_host_guards_override_remote_proposal(self):
        receipt = {"status": "classified", "suggested_kind": "proposal", "intent_confidence": .99}
        for question in ("确认", "解释一下网站怎么开发", "我想了解商城架构"):
            kind, result = apply_decision(receipt, "answer", question)
            self.assertEqual(kind, "answer")
            self.assertEqual(result["status"], "host_override")
        self.assertEqual(apply_decision(receipt, "answer", "教我", guarded=True)[0], "answer")
        self.assertEqual(apply_decision({**receipt, "intent_confidence": .6}, "answer", "需要交付商城")[0], "answer")
        self.assertEqual(apply_decision({**receipt, "suggested_kind": "revision"}, "answer", "新增功能")[0], "answer")
        self.assertEqual(apply_decision(receipt, "answer", "需要交付商城")[0], "proposal")


class JevAPITest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.intent = "answer"
        self.turns = []
        self.confidence = .99
        self.status = 200
        self.calls = []
        self.mutate = None
        async def runner(job, store):
            self.turns.append(dict(job))
            job["answer"] = "前端负责界面，后端负责业务与数据。"
        def handle(request):
            self.calls.append(request)
            if self.mutate:
                self.mutate()
            return httpx.Response(self.status, json=output(json.loads(request.content), self.intent, "software-frontend", self.confidence))
        self.env = patch.dict(os.environ, {"JEV_AI_API_KEY": "sk-api-test-secret", "JEV_AI_ENABLED": "true"})
        self.env.start()
        store = FederationStore(base=Path(self.temp.name) / "data")
        store.init()
        # The injected transport exercises the real routing code, not a stub receipt.
        self.router = JevRouter(store, httpx.MockTransport(handle))
        self.app = create_app(base=Path(self.temp.name) / "data", runner=runner, decision_router=self.router)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.room = self.client.post("/api/chat/primary", json={}).json()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.env.stop()
        self.temp.cleanup()

    def send(self, content, **extra):
        return self.client.post("/api/chat/rooms/" + self.room["id"] + "/messages", json={"content": content, **extra})

    def finish(self, job):
        for _ in range(200):
            value = self.client.get("/api/jobs/" + job["id"]).json()
            if value["status"] not in {"queued", "running"}:
                return value
            time.sleep(.01)
        self.fail("queue did not finish")

    def test_main_reply_uses_existing_runner_and_route_never_invites_specialist(self):
        result = self.send("前后端有什么区别").json()
        job = self.finish(result["job"])
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["decision"]["model"], "jev-1.13.0")
        self.assertEqual(job["intake_kind"], "answer")
        self.assertEqual([turn["space"] for turn in self.turns], ["central"])
        self.assertIn("Jev 建议", self.turns[0]["question"])
        self.assertIn("software-frontend", self.turns[0]["question"])
        room = self.client.get("/api/chat/rooms/" + self.room["id"]).json()
        self.assertEqual(room["participants"], ["central"])
        self.assertFalse(room.get("proposals"))
        self.assertFalse(room.get("task_groups"))
        self.assertNotIn("sk-api-test-secret", json.dumps(job))
        self.assertFalse(self.client.get("/api/agents/decision-model").json()["generates_replies"])

    def test_remote_can_select_inert_proposal_but_cannot_start_tasks_or_learning(self):
        self.intent = "proposal"
        response = self.send("需要一套库存预警功能")
        self.assertEqual(response.status_code, 200, response.text)
        job = self.finish(response.json()["job"])
        self.assertEqual(job["intake_kind"], "proposal")
        self.assertEqual(job["decision"]["applied_kind"], "proposal")
        self.assertNotIn("dispatch_confirmed", job)
        self.assertNotIn("learning", job)
        self.assertEqual([turn["space"] for turn in self.turns], ["central"])
        self.assertFalse(self.client.get("/api/chat/rooms/" + self.room["id"]).json().get("task_groups"))

    def test_research_teaching_confirmation_and_stop_keep_host_policy(self):
        self.intent = "proposal"
        for content, extras in [("教我产品思维", {}), ("确认", {}), ("取消项目", {}),
                                ("查询 React 官方文档", {"research": True}),
                                ("https://example.com/product 拆一下产品，给我最小版本方案和文档", {}),
                                ("暂时先不做开始做，先分析一下即可", {})]:
            with self.subTest(content=content), patch("federation.app.research_project", new=AsyncMock(return_value={"status": "unavailable", "sources": []})):
                response = self.send(content, **extras)
                self.assertEqual(response.status_code, 200, response.text)
                job = self.finish(response.json()["job"])
                self.assertEqual(job["intake_kind"], "answer")
                self.assertEqual(job["decision"]["status"], "bypassed" if job.get("research_only") or job['decision'].get('reason')=='host_control' else "host_override")
                if content=='取消项目': self.assertEqual(job['decision'].get('reason'),'host_control')
                self.assertNotIn("dispatch_confirmed", job)

    def test_failed_jev_falls_back_and_stale_room_is_not_overwritten(self):
        self.status = 401
        job = self.finish(self.send("前端后端的区别").json()["job"])
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["decision"]["http_status"], 401)
        self.status = 200
        def change_room():
            room = self.app.state.chat.get_room(self.room["id"])
            room["title"] = "changed during inference"
            self.app.state.chat.save_room(room)
        self.mutate = change_room
        response = self.send("不要覆盖其他消息")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.app.state.chat.get_room(self.room["id"])["title"], "changed during inference")
        self.assertEqual(len(self.turns), 1)

    def test_balance_block_keeps_normal_replies_without_more_jev_requests(self):
        self.status = 402
        first = self.finish(self.send('前后端有什么区别').json()['job'])
        second = self.finish(self.send('数据库有什么作用').json()['job'])
        self.assertEqual([first['status'], second['status']], ['completed', 'completed'])
        self.assertEqual(first['decision']['calls'], 1)
        self.assertEqual(second['decision']['calls'], 0)
        self.assertEqual(second['decision']['reason'], 'insufficient_balance')
        self.assertEqual(second['decision']['applied_kind'], 'answer')
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(self.turns), 2)
        status = self.client.get('/api/agents/decision-model').json()
        self.assertFalse(status['enabled'])
        self.assertTrue(status['resume_required'])

    def test_non_primary_chat_does_not_use_jev(self):
        room = self.client.post("/api/chat/rooms", json={"mode": "direct", "participants": ["software-frontend"]}).json()
        response = self.client.post("/api/chat/rooms/" + room["id"] + "/messages", json={"content": "前端问题"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.finish(response.json()["job"])["status"], "completed")
        self.assertEqual(self.calls, [])
