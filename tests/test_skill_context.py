"""Scoped Skill selection, real copied bytes and API receipts, without a model."""
import asyncio
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest

from fastapi.testclient import TestClient
from federation.app import create_app, isolated_ask_environment
from federation.agent_skills import sync_local_skills, list_skills
from federation.skill_context import select_skills, prepare_skill_context


class SkillSelectionTest(unittest.TestCase):
    def setUp(self):
        self.items = [
            {"id":"java-server-framework-development", "name":"java-server-framework-development",
             "display_name":"Java 服务端框架开发", "keywords":["Java", "Spring", "接口"]},
            {"id":"figma-generate-library", "display_name":"Figma 设计系统", "keywords":["Figma", "设计系统"]},
        ]

    def test_current_task_explicit_identity_boundaries_and_no_irrelevant_default(self):
        self.assertEqual(select_skills(self.items, {"question":"你好"}), [])
        self.assertEqual(select_skills(self.items, {"question":"Javascript function"}), [])
        picked = select_skills(self.items, {"question":"使用 $java-server-framework-development"})
        self.assertEqual(picked, [("java-server-framework-development", "explicit-skill-name")])
        picked = select_skills(self.items, {"template_query":"设计系统", "template_fallback":"Java API"})
        self.assertEqual([x[0] for x in picked], ["figma-generate-library"])

    def test_prior_task_only_reused_for_follow_up_and_negative_mentions_not_selected(self):
        self.assertEqual(select_skills(self.items, {"question":"今天天气", "template_history":["Java"]}), [])
        self.assertEqual(select_skills(self.items, {"question":"继续完善", "template_history":["Java"]})[0][0], self.items[0]["id"])
        self.assertEqual(select_skills(self.items, {"question":"不用 Figma，使用 Java"})[0][0], self.items[0]["id"])
        self.assertEqual(select_skills(self.items, {"question":"继续，但不要 Figma", "template_history":["Figma 设计系统"]}), [])
        self.assertEqual(select_skills(self.items, {"template_query":"不要 $figma-generate-library，设计系统规则即可", "template_fallback":"Figma"}), [])

    def test_sample_data_reply_keeps_only_immediate_task_skill(self):
        items = [{"id": "visualize", "display_name": "交互式可视化", "keywords": ["可视化"]}]
        for question in ["随便，给我个就行", "用示例数据", "你决定", "都可以"]:
            picked = select_skills(items, {"question": question,
                "template_history": ["$visualize 帮我写个报表出来", question]})
            self.assertEqual([x[0] for x in picked], ["visualize"])
        for question, history in [
            ("随便，给我个就行", ["$visualize 帮我写个报表出来", "写首诗"]),
            ("随便，给我个就行", []),
            ("你好", ["$visualize 帮我写个报表出来"]),
            ("你决定今天去哪里旅游", ["$visualize 帮我写个报表出来"]),
            ("不用 visualize，用示例数据", ["$visualize 帮我写个报表出来"]),
        ]:
            self.assertEqual(select_skills(items, {"question": question, "template_history": history}), [])


class SkillContextTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "skills/java-server-framework-development"
        self.source.mkdir(parents=True)
        self.body = "---\nname: java-server-framework-development\ndescription: Java Spring 接口开发\n---\n# Java 规范\nSkillSourceMarker\n"
        (self.source / "SKILL.md").write_text(self.body)
        (self.source / "references").mkdir()
        (self.source / "references/check.md").write_text("ReferenceSourceMarker")
        async def runner(job, store):
            if job.get("delegation_phase") == "plan":
                member = "software" if job["space"] == "central" else "software-backend"
                job["answer"] = json.dumps({"action":"delegate", "tasks":[{"agent_id":member,"task":"使用 Java 开发接口"}]})
            else:
                environment = isolated_ask_environment(store, job)
                selected = json.loads(environment["FEDERATION_SKILL_SELECTION"])
                job["skill_reads"] = [{"skill_id":item["id"],"path":"/_agent_skills/"+item["id"]+"/SKILL.md", "sha256":"a"*64}
                                      for item in selected]
                job["answer"] = "受控回答，未调用模型或执行外部工具。"
            await asyncio.sleep(.001)
        self.app = create_app(base=self.root / "data", runner=runner)
        self.store = self.app.state.store
        report = sync_local_skills(self.store, roots=[self.source.parent])
        self.assertFalse(report["source_errors"], report)
        self.assertEqual(report["status_counts"]["conflict"], 0, report)
        self.client = TestClient(self.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def test_api_files_are_agent_scoped_and_isolation_pins_manifest_and_all_resources(self):
        response = self.client.get("/api/spaces/software-backend/skills")
        self.assertEqual(response.status_code, 200, response.text)
        skill = next(x for x in response.json()["skills"] if x["id"] == self.source.name)
        url = "/api/spaces/software-backend/skills/" + skill["id"] + "/files/SKILL.md"
        self.assertEqual(self.client.get(url).text, self.body)
        self.assertIn(self.client.get(url.replace("software-backend", "commerce-service")).status_code, [400,404])
        self.assertEqual(self.client.get(url.replace("SKILL.md", "manifest.json")).status_code, 404)
        job = {"id":"skill-isolation", "space":"software-backend", "question":"Java 接口"}
        environment = isolated_ask_environment(self.store, job)
        copied = Path(environment["OPENWIKI_CONFIG_DIR"]) / "wiki/_agent_skills" / skill["id"]
        self.assertEqual((copied / "SKILL.md").read_text(), self.body)
        self.assertEqual((copied / "references/check.md").read_text(), "ReferenceSourceMarker")
        self.assertEqual(job["skill_selection"][0]["manifest_sha256"], hashlib.sha256((copied / "manifest.json").read_bytes()).hexdigest())
        (copied / "SKILL.md").write_text("isolation-only-change")
        self.assertEqual((self.source / "SKILL.md").read_text(), self.body)
        self.assertEqual(self.client.get(url).text, self.body)

    def test_plan_never_loads_skill_and_tamper_fails_before_context(self):
        wiki = self.store.base / "plan-wiki"; wiki.mkdir()
        self.assertEqual(prepare_skill_context(self.store, {"space":"software-backend", "delegation_phase":"plan"}, wiki), ([], ""))
        target = self.store._home("software-backend") / "skills" / self.source.name / "SKILL.md"
        target.write_text("changed locally")
        with self.assertRaises(ValueError):
            isolated_ask_environment(self.store, {"id":"tampered", "space":"software-backend", "question":"Java 接口"})

    def finish(self, job):
        for _ in range(250):
            result = self.client.get("/api/jobs/" + job["id"]).json()
            if result["status"] not in {"queued", "running"}:
                self.assertEqual(result["status"], "completed", result)
                return result
            time.sleep(.02)
        self.fail("controlled skill round did not complete")

    def test_direct_and_delegated_receipts_are_saved_without_claiming_execution(self):
        for mode, members in [("direct", ["software-backend"]), ("orchestrated", ["central"])]:
            room = self.client.post("/api/chat/rooms", json={"mode":mode,"participants":members}).json()
            job = self.client.post("/api/chat/rooms/" + room["id"] + "/messages", json={"content":"使用 Java 开发接口"}).json()["job"]
            self.finish(job)
            saved = self.client.get("/api/chat/rooms/" + room["id"]).json()
            message = saved["messages"][-1]
            self.assertTrue(message["skill_reads"])
            self.assertNotIn("【本轮实际读取的技能规范】", message["content"])
            if mode == "orchestrated":
                self.assertTrue(any(x.get("skill_reads") for x in saved["delegations"]))
                self.assertTrue(all("agent_id" in x for x in message["skill_reads"]))

    def test_employee_and_explicit_skill_from_composer_select_the_owned_specification(self):
        member = next(item for item in self.client.get('/api/agents').json()['agents']
                      if item['id'] == 'software-backend')
        room = self.client.post('/api/chat/primary', json={}).json()
        content = '@' + member['name'] + ' $java-server-framework-development 请解释参数校验的检查步骤。'
        response = self.client.post('/api/chat/rooms/' + room['id'] + '/messages', json={'content': content})
        self.assertEqual(response.status_code, 200, response.text)
        self.finish(response.json()['job'])
        saved = self.client.get('/api/chat/rooms/' + room['id']).json()
        answer = saved['messages'][-1]
        self.assertEqual(answer['agent_id'], 'software-backend')
        turn = self.client.get('/api/jobs/' + answer['stream_turn_id']).json()
        self.assertEqual(turn['skill_selection'][0]['id'], self.source.name)
        self.assertEqual(turn['skill_selection'][0]['selection_reason'], 'explicit-skill-name')
        self.assertTrue(any(item['skill_id'] == self.source.name for item in answer['skill_reads']))
        self.assertFalse(saved.get('task_groups'))


if __name__ == "__main__":
    unittest.main()
