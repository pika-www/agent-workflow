"""Verify the UI adapter's real isolation, queue and publication boundaries."""
import asyncio
from pathlib import Path
import tempfile
import time
import unittest

from fastapi.testclient import TestClient

from federation.app import create_app, isolated_ask_environment


class FederationAPITest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.started = []

        async def fake_runner(job, store):
            self.started.append((job["action"], job["space"]))
            await asyncio.sleep(0.05)
            job["output"] = "Controlled adapter test; no model called."

        self.app = create_app(base=Path(self.temp.name) / "data", runner=fake_runner)
        self.client = TestClient(self.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def finished(self, job):
        for _ in range(100):
            value = self.client.get("/api/jobs/" + job["id"]).json()
            if value["status"] not in {"queued", "running"}:
                return value
            time.sleep(0.01)
        self.fail("Adapter test job did not finish")

    def test_empty_branches_and_central_have_honest_state(self):
        data = self.client.get("/api/federation").json()
        self.assertEqual(len(data["branches"]), 25)
        self.assertEqual(len([s for s in data["branches"] if s["parent_id"] == "central"]), 4)
        self.assertEqual(data["central"]["id"], "central")
        self.assertTrue(all(s["source_count"] == 0 and s["published_count"] == 0 for s in data["branches"]))
        response = self.client.post("/api/jobs", json={"action": "sync", "space": "central"})
        self.assertEqual(response.status_code, 409)
        response = self.client.post("/api/jobs", json={"action": "learn", "space": "software"})
        self.assertEqual(response.status_code, 409)

    def test_sources_stay_in_selected_industry(self):
        response = self.client.post("/api/spaces/software/sources", json={"filename": "验收.md", "text": "测试资料，不是真实业务。"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(self.client.get("/api/spaces/software/sources").json()["sources"]), 1)
        self.assertEqual(self.client.get("/api/spaces/commerce/sources").json()["sources"], [])
        response = self.client.post("/api/spaces/software/sources", json={"filename": "../escape.md", "text": "x"})
        self.assertGreaterEqual(response.status_code, 400)
        self.assertFalse((Path(self.temp.name) / "escape.md").exists())

    def test_learning_stays_draft_until_publication(self):
        self.client.post("/api/spaces/software/sources", json={"filename": "验收.md", "text": "测试资料。"})
        response = self.client.post("/api/jobs", json={"action": "learn", "space": "software"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.finished(response.json())["status"], "completed")
        self.assertEqual(self.started, [("learn", "software")])
        data = self.client.get("/api/federation").json()
        self.assertTrue(all(s["published_count"] == 0 for s in data["branches"]))

    def test_no_cross_origin_mutation(self):
        response = self.client.post("/api/spaces/software/sources", json={"filename": "no.md", "text": "x"}, headers={"Origin": "https://unrelated.example"})
        self.assertEqual(response.status_code, 403)
        response = self.client.post("/api/jobs", content='{"action":"learn","space":"software"}', headers={"Content-Type": "text/plain"})
        self.assertEqual(response.status_code, 415)

    def test_ask_tools_cannot_modify_authoritative_wiki(self):
        store = self.app.state.store
        wiki = Path(store.space("software")["wiki_dir"])
        original = wiki / "fact.md"
        original.write_text("# 原始事实\n受审核保护。", encoding="utf-8")
        env = isolated_ask_environment(store, {"id":"test-only-ask", "space":"software"})
        sandbox = Path(env["OPENWIKI_CONFIG_DIR"])
        self.assertNotEqual(sandbox, wiki.parent)
        (sandbox / "wiki/fact.md").write_text("尝试在问答中改写。", encoding="utf-8")
        self.assertEqual(original.read_text(), "# 原始事实\n受审核保护。")
        config = (sandbox / "connectors/custom-mcp/config.json").read_text()
        self.assertIn(str(store.base / "branches/software/inbox"), config)
        import json
        self.assertFalse(json.loads((sandbox / "connectors/hackernews/config.json").read_text())["enabled"])

    def test_native_visualizer_keeps_original_styles_and_namespaced_nodes(self):
        from federation.app import NATIVE_VISUALIZER
        response = self.client.get("/styles.css")
        self.assertEqual(response.content, (NATIVE_VISUALIZER / "styles.css").read_bytes())
        home = self.client.get("/")
        self.assertIn('id="ws-chat-host"', home.text)
        page = self.client.get("/library")
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn('id="sidebar"', page.text)
        self.assertIn('id="graph"', page.text)
        self.assertIn('id="detail"', page.text)
        self.assertIn('data-theme="dark"', page.text)
        self.assertIn('federation-controls.js', page.text)
        self.assertIn('knowledge-graph-3d.css', page.text)
        self.assertNotIn('npm/force-graph@', page.text)
        graph = self.client.get("/api/graph").json()
        self.assertEqual(len(graph["nodes"]), 26)
        self.assertEqual(len(graph["edges"]), 25)
        self.assertEqual(len([edge for edge in graph["edges"] if edge["source"] == "central/index"]), 4)
        self.assertTrue(all('/' in node['id'] for node in graph['nodes']))
        script = self.client.get('/client.js')
        self.assertEqual(script.status_code, 200, script.text)
        self.assertIn('openwiki:select', script.text)
        self.assertIn('n.spaceId === "central" ? 24 : (n.spaceDepth > 1 ? 8 : 13)', script.text)
        self.assertIn('hierarchyNodePositions3D(graph.nodes)', script.text)
        self.assertIn('o.z = o.fz = point.z', script.text)
        self.assertIn('createKnowledgeGraph3D', script.text)
        self.assertNotIn('ForceGraph()(container)', script.text)
        for asset in ['/hierarchy-layout.js', '/knowledge-graph-3d.css', '/vendor/knowledge-graph-3d.js']:
            resource = self.client.get(asset)
            self.assertEqual(resource.status_code, 200, asset)
            self.assertTrue(resource.content, asset)

    def test_new_industry_appears_as_another_connected_branch(self):
        response = self.client.post('/api/branches', json={'name':'制造业', 'description':'隔离测试行业'})
        self.assertEqual(response.status_code, 200, response.text)
        branch = response.json()
        graph = self.client.get('/api/graph').json()
        self.assertEqual(len(graph['nodes']), 27)
        self.assertIn({'source':'central/index','target':branch['id']+'/index'}, graph['edges'])
        self.assertEqual(self.client.get('/api/spaces/'+branch['id']+'/sources').json()['sources'], [])

    def test_publish_queues_central_only_after_review(self):
        wiki = Path(self.app.state.store.space("software")["wiki_dir"])
        (wiki / "reviewed-topic.md").write_text("# 审核测试\n\n只是隔离测试数据。\n", encoding="utf-8")
        review = self.client.get("/api/spaces/software/review").json()
        response = self.client.post("/api/spaces/software/publish", json={"token": review["token"]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertGreater(response.json()["published_count"], 0)
        self.assertEqual(self.finished(response.json()["job"])["status"], "completed")
        self.assertEqual(self.started, [("sync", "central")])


if __name__ == "__main__":
    unittest.main()
