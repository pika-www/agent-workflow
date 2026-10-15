"""Exercise the real API worker/run_native with a controlled subprocess boundary.

The subprocess is an explicit local Python fixture, not OpenWiki or a real LLM.
No runner override bypasses the production queue, command construction, receipt
validation, provenance registration, isolation, or job persistence paths.
"""
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from federation.app import create_app


CONTROLLED_PROCESS = r'''
import hashlib
import json
import os
from pathlib import Path
import sys

control_path = Path(sys.argv[1])
control = json.loads(control_path.read_text("utf-8"))
original_command = json.loads(sys.argv[2])
state = Path(os.environ["OPENWIKI_CONFIG_DIR"])
trace = {"command": original_command, "mode": control["mode"], "config_dir": str(state)}
if Path(original_command[1]).name == "agent-turn.mjs":
    payload = json.load(sys.stdin)
    trace["stdin"] = payload
    trace["space_id"] = os.environ.get("FEDERATION_SPACE_ID")
    metadata_path = Path(os.environ["FEDERATION_KNOWLEDGE_EVIDENCE"])
    metadata_bytes = metadata_path.read_bytes()
    trace["metadata_pin_valid"] = hashlib.sha256(metadata_bytes).hexdigest() == os.environ["FEDERATION_KNOWLEDGE_EVIDENCE_SHA256"]
    trace["metadata_space"] = json.loads(metadata_bytes)["space_id"]
    body = (state / "wiki/guide.md").read_bytes()
    digest = hashlib.sha256(body).hexdigest()
    result = {
        "answer": "受控子进程回答，未调用模型。[Wiki: /guide.md]",
        "model": "controlled-process-not-an-llm", "engine": "controlled subprocess fixture",
        "thread_id": "fixture-thread",
        "wiki_reads": [{"path": "/guide.md", "sha256": digest, "hash_scope": "provided_excerpt",
                        "page_version": digest, "knowledge_status": "untracked", "reasons": ["fixture_only"],
                        "sources": [], "citation_label": "[Wiki: /guide.md]", "truncated": False}],
        "wiki_citation_check": {"schema_version": 1, "scope": "prefetched_wiki_reads_only", "status": "valid", "semantic_correctness": "not_evaluated"},
        "template_reads": [], "skill_reads": []}
    # A fixture write is confined to the same disposable copy as a native turn.
    (state / "wiki/guide.md").write_text("Changed only in the isolated ask copy.", encoding="utf-8")
    Path(os.environ["FEDERATION_CHAT_RESULT"]).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
else:
    if original_command[1:3] != ["--input-type=module", "-e"]:
        raise RuntimeError("Expected real native ingestion command construction")
    request = json.loads(original_command[-1])
    trace["request_id"] = request["requestId"]
    trace["source_hashes"] = request["sourceHashes"]
    # Assert that the production payload identifies the actual controlled input.
    for filename, expected in request["sourceHashes"].items():
        if hashlib.sha256(Path(filename).read_bytes()).hexdigest() != expected:
            raise RuntimeError("Input payload hash did not match fixture bytes")
    receipt = {"status": "success", "operationCount": request["expectedReads"],
               "requestId": request["requestId"], "sourceFiles": request["sourceFiles"],
               "sourceHashes": request["sourceHashes"], "generatedAt": "controlled-fixture"}
    if control["mode"] == "replay_receipt":
        receipt = control["receipt"]
    elif control["mode"] == "wrong_source_hash":
        receipt["sourceHashes"] = {filename: "0" * 64 for filename in request["sourceHashes"]}
    Path(request["receipt"]).write_text(json.dumps(receipt), encoding="utf-8")
    if control["mode"] == "write_page":
        (state / "wiki/guide.md").write_text(control["page_body"], encoding="utf-8")
with control_path.with_suffix(".trace.jsonl").open("a", encoding="utf-8") as out:
    out.write(json.dumps(trace, ensure_ascii=False) + "\n")
print('{"phase":"controlled_fixture_only","model_called":false}', flush=True)
if control["mode"] == "fail_after_prefetch":
    sys.exit(1)
'''


class NativeLearningTrackingTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="native-learning-tracking-")
        self.root = Path(self.temporary.name).resolve()
        self.script = self.root / "controlled_process.py"
        self.script.write_text(CONTROLLED_PROCESS, encoding="utf-8")
        self.control = self.root / "control.json"
        self.trace = self.control.with_suffix(".trace.jsonl")
        self.app = create_app(base=self.root / "data")  # Deliberately no runner override.
        self.store = self.app.state.store
        actual_subprocess = asyncio.create_subprocess_exec

        async def controlled_subprocess(*command, **kwargs):
            # Replace only the executable boundary, keeping run_native itself.
            return await actual_subprocess(sys.executable, str(self.script), str(self.control),
                                           json.dumps(list(command)), **kwargs)

        self.process_patch = patch("federation.app.asyncio.create_subprocess_exec", side_effect=controlled_subprocess)
        self.process_patch.start()
        self.client = TestClient(self.app)
        self.client.__enter__()
        response = self.client.post("/api/spaces/software/sources",
                                    json={"filename": "source.md", "text": "Controlled source version A."})
        self.assertEqual(response.status_code, 200, response.text)
        self.source = self.store._source("software") / "source.md"
        self.page = self.store._wiki("software") / "guide.md"
        self.learned = self.store.base / "metadata/native-learning-learned/software.json"
        self.tracking = self.store.base / "metadata/knowledge/software.json"
        self.receipt_path = self.store._state("software") / "last-prefetch.json"

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.process_patch.stop()
        self.temporary.cleanup()

    def run_job(self, mode, action="learn", **control):
        self.control.write_text(json.dumps({"mode": mode, **control}), encoding="utf-8")
        response = self.client.post("/api/jobs", json={"action": action, "space": "software",
                                                      "question": "Controlled fixture request, no real model."})
        self.assertEqual(response.status_code, 200, response.text)
        queued = response.json()
        self.assertNotIn("structured_chat", queued)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            result = self.client.get("/api/jobs/" + queued["id"]).json()
            if result["status"] not in {"queued", "running"}:
                saved = json.loads((self.store.base / "jobs" / (queued["id"] + ".json")).read_text())
                # Completion status, receipts and evidence must survive readback.
                self.assertEqual(saved["status"], result["status"])
                return result
            time.sleep(.01)
        self.fail("Controlled native subprocess did not finish")

    def seed_success(self):
        result = self.run_job("write_page", page_body="# Controlled guide\nLearned source version A.\n")
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual(result["knowledge_tracking"]["recorded_count"], 1)
        return result

    def traces(self):
        return [json.loads(line) for line in self.trace.read_text("utf-8").splitlines()]

    def test_failed_prefetch_and_noop_retry_do_not_advance_successful_learning(self):
        first = self.seed_success()
        successful_a = self.learned.read_bytes()
        tracked_a = self.tracking.read_bytes()
        page_a = self.page.read_bytes()
        self.source.write_text("Controlled source version B.", encoding="utf-8")
        source_b_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()

        failed = self.run_job("fail_after_prefetch")
        self.assertEqual(failed["status"], "failed", failed)
        self.assertIn("退出码为 1", failed["error"])
        prefetched_b = json.loads(self.receipt_path.read_text())
        self.assertEqual(prefetched_b["sourceHashes"][str(self.source)], source_b_hash)
        self.assertEqual(self.learned.read_bytes(), successful_a)
        self.assertEqual(self.tracking.read_bytes(), tracked_a)

        retry = self.run_job("no_page_change")
        self.assertEqual(retry["status"], "failed", retry)
        self.assertIn("模型没有更新知识页面", retry["error"])
        self.assertNotEqual(json.loads(self.receipt_path.read_text())["requestId"], prefetched_b["requestId"])
        self.assertEqual(self.page.read_bytes(), page_a)
        self.assertEqual(self.learned.read_bytes(), successful_a)
        self.assertEqual(self.tracking.read_bytes(), tracked_a)

        updated = self.run_job("write_page", page_body="# Controlled guide\nLearned source version B.\n")
        self.assertEqual(updated["status"], "completed", updated)
        latest = json.loads(self.learned.read_text())
        self.assertEqual(latest["job_id"], updated["id"])
        self.assertEqual(latest["source_hashes"][str(self.source)], source_b_hash)
        self.assertEqual(latest["wiki"]["guide.md"], hashlib.sha256(self.page.read_bytes()).hexdigest())
        tracking = json.loads(self.tracking.read_text())
        self.assertEqual([run["run_id"] for run in tracking["runs"]], [first["id"], updated["id"]])
        self.assertEqual(len(tracking["pages"]["guide.md"]), 2)
        newest = tracking["pages"]["guide.md"][-1]
        self.assertEqual(newest["version"], hashlib.sha256(self.page.read_bytes()).hexdigest())
        self.assertEqual(newest["sources"][0]["version"], source_b_hash)
        self.assertEqual(len({trace["request_id"] for trace in self.traces()}), 4)

    def test_receipt_must_match_this_request_id_and_this_source_hash(self):
        self.seed_success()
        original = json.loads(self.receipt_path.read_text())
        successful = self.learned.read_bytes()
        tracking = self.tracking.read_bytes()
        replay = self.run_job("replay_receipt", receipt=original)
        self.assertEqual(replay["status"], "failed", replay)
        self.assertIn("凭证不属于本次来源版本", replay["error"])
        self.assertNotEqual(self.traces()[-1]["request_id"], original["requestId"])
        self.assertEqual(self.traces()[-1]["source_hashes"], original["sourceHashes"])
        wrong_hash = self.run_job("wrong_source_hash")
        self.assertEqual(wrong_hash["status"], "failed", wrong_hash)
        self.assertIn("凭证不属于本次来源版本", wrong_hash["error"])
        # Invalid receipts cannot mutate either successful-learning registry.
        self.assertEqual(self.learned.read_bytes(), successful)
        self.assertEqual(self.tracking.read_bytes(), tracking)

    def test_plain_jobs_ask_uses_structured_bridge_and_preserves_legacy_answer_output(self):
        self.page.write_text("# Controlled question fixture\nOriginal authoritative page.\n", encoding="utf-8")
        original = self.page.read_bytes()
        result = self.run_job("structured_answer", action="ask")
        self.assertEqual(result["status"], "completed", result)
        trace = self.traces()[-1]
        self.assertEqual(Path(trace["command"][1]).name, "agent-turn.mjs")
        self.assertEqual(trace["stdin"]["prompt"], result["question"])
        self.assertEqual(trace["space_id"], "software")
        self.assertEqual(trace["metadata_space"], "software")
        self.assertTrue(trace["metadata_pin_valid"])
        self.assertIn("ask-runs", Path(trace["config_dir"]).parts)
        self.assertEqual(result["output"], result["answer"])
        self.assertIn("未调用模型", result["answer"])
        self.assertEqual(result["model"], "controlled-process-not-an-llm")
        self.assertEqual(result["wiki_reads"][0]["path"], "/guide.md")
        self.assertEqual(result["wiki_reads"][0]["page_version"], hashlib.sha256(original).hexdigest())
        self.assertEqual(result["wiki_citation_check"]["status"], "valid")
        self.assertEqual(self.page.read_bytes(), original)
        self.assertFalse(self.learned.exists())
        self.assertFalse(self.tracking.exists())


if __name__ == "__main__":
    unittest.main()
