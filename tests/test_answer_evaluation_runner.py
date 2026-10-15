"""Evaluation setup/report integrity; does not call a model or fetch the Web."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from federation.core import FederationStore
from federation.evaluate_answers import FIXTURE, main, prepare_case
from federation.knowledge import knowledge_health


class AnswerEvaluationRunnerTest(unittest.TestCase):
    def test_frozen_cases_create_real_provenance_states_without_network(self):
        fixture = json.loads(FIXTURE.read_text())
        with tempfile.TemporaryDirectory() as directory:
            for case in fixture["cases"]:
                store = FederationStore(Path(directory).resolve() / case["id"])
                store.init()
                prepare_case(store, fixture, case)
                page = next(p for p in knowledge_health(store, fixture["space_id"])["pages"] if p["path"] == fixture["page"]["path"])
                self.assertEqual(page["status"], case["knowledge_status"])
                self.assertEqual(store.page(fixture["space_id"], fixture["page"]["path"])["body"], fixture["page"]["body"])

    def test_failed_scorer_cannot_relabel_an_older_report_as_current(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "existing-report.json"
            original = '{"run":"old-run","passed":4}'
            report.write_text(original)
            args = ["evaluate_answers", "--live", "--base", str(Path(directory) / "profile"), "--report", str(report)]
            with patch("sys.argv", args), patch("federation.evaluate_answers.run_case", side_effect=lambda _, __, case, timeout: {"case_id": case["id"], "answer": "controlled fixture", "model": "controlled", "wiki_reads": []}), patch("federation.evaluate_answers.subprocess.run", return_value=SimpleNamespace(returncode=1)):
                with self.assertRaisesRegex(RuntimeError, "本轮评分器未生成"):
                    main()
            self.assertEqual(report.read_text(), original)
            self.assertFalse(list(Path(directory).glob(".answer-score-*")))


if __name__ == "__main__":
    unittest.main()
