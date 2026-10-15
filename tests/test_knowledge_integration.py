"""Cross-layer provenance checks; controlled local files, no network or LLM."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from federation.app import create_app, isolated_ask_environment
from federation.knowledge import record_learning, source_snapshot


class KnowledgeIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(base=Path(self.temp.name) / "data")
        self.store = self.app.state.store
        self.client = TestClient(self.app)
        self.store.add_source("software", "policy.txt", "Frozen example: branch limit is 17.")
        self.page = self.store._wiki("software") / "limits.md"
        self.page.write_text("# Frozen example\nThe branch limit is 17.\n", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_health_is_read_only_and_old_pages_are_untracked(self):
        before = {p: p.read_bytes() for p in self.store._wiki("software").glob("*.md")}
        response = self.client.get("/api/spaces/software/knowledge-health")
        self.assertEqual(response.status_code, 200, response.text)
        page = next(p for p in response.json()["pages"] if p["path"] == "limits.md")
        self.assertEqual(page["status"], "untracked")
        self.assertTrue(page["page_id"])
        self.assertEqual(page["version"], hashlib.sha256(self.page.read_bytes()).hexdigest())
        self.assertFalse((self.store.base / "metadata/knowledge/software.json").exists())
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        self.assertGreaterEqual(self.client.get("/api/spaces/unknown/knowledge-health").status_code, 400)

    def test_source_change_after_review_requires_new_approval(self):
        review = self.store.review("software")
        (self.store._source("software") / "policy.txt").write_text("Frozen example: branch limit is 23.")
        self.assertNotEqual(review["token"], self.store.review("software")["token"])
        with self.assertRaisesRegex(ValueError, "重新"):
            self.store.publish("software", review["token"])
        self.assertFalse((self.store.base / "published/software").exists())

    def test_review_is_repeatable_and_publish_preserves_provenance(self):
        record_learning(self.store, "software", "fixture-run", source_versions=source_snapshot(self.store, "software"), paths=["limits.md"])
        reviewed = self.store.review("software")
        self.assertEqual(reviewed["token"], self.store.review("software")["token"])
        self.store.publish("software", reviewed["token"])
        manifest = self.store._manifest("software")
        self.assertEqual(manifest["knowledge"]["pages"], reviewed["knowledge"]["pages"])
        self.assertEqual(manifest["knowledge"]["sources"], reviewed["knowledge"]["sources"])
        self.assertEqual((self.store.base / "published/software/limits.md").read_bytes(), self.page.read_bytes())
        central = self.client.get("/api/spaces/central/knowledge-health").json()
        source = next(s for s in central["sources"] if s["name"] == "software/limits.md")
        self.assertEqual(source["kind"], "published")
        self.assertEqual(source["upstream_page_id"], next(p["page_id"] for p in reviewed["knowledge"]["pages"] if p["path"] == "limits.md"))

    def test_ask_receives_only_own_pinned_versions_and_does_not_write_back(self):
        other = self.store._wiki("commerce") / "private.md"
        other.write_text("# Other branch\nDo not mix scopes.\n")
        record_learning(self.store, "software", "fixture-run", paths=["limits.md"])
        env = isolated_ask_environment(self.store, {"id": "frozen-evidence", "space": "software"})
        self.assertEqual(env["FEDERATION_SPACE_ID"], "software")
        metadata = Path(env["FEDERATION_KNOWLEDGE_EVIDENCE"])
        self.assertEqual(hashlib.sha256(metadata.read_bytes()).hexdigest(), env["FEDERATION_KNOWLEDGE_EVIDENCE_SHA256"])
        snapshot = json.loads(metadata.read_text())
        self.assertEqual(snapshot["space_id"], "software")
        self.assertNotIn("private.md", [p["path"] for p in snapshot["pages"]])
        page = next(p for p in snapshot["pages"] if p["path"] == "limits.md")
        self.assertEqual(page["version"], hashlib.sha256(self.page.read_bytes()).hexdigest())
        (Path(env["OPENWIKI_CONFIG_DIR"]) / "wiki/limits.md").write_text("local attempted edit")
        self.assertIn("17", self.page.read_text())


if __name__ == "__main__":
    unittest.main()
