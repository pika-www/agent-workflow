"""Repeat a small frozen answer evaluation through the real native chat path.

The corpus and source updates are controlled local fixtures, never HTTP fetches.
Only --live calls the configured model. No production Wiki/chat data is modified.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import uuid

from .app import isolated_ask_environment
from .core import FederationStore, ROOT, _write_json
from .knowledge import knowledge_health, record_learning, source_snapshot
from .web_learning import _save_source
from .agent_templates import initialize_standards

FIXTURE = ROOT / "tests/fixtures/knowledge-answer-eval.json"


def prepare_case(store, fixture, case):
    """Create the same production source/page records from controlled content."""
    space = fixture["space_id"]
    source = fixture["source"]

    def save(body, label):
        run_dir = store.base / "web-learning" / label
        run_dir.mkdir(parents=True)
        document = {"title": "Frozen evaluation fixture", "text": body,
                    "sha256": hashlib.sha256(body.encode()).hexdigest()}
        _save_source(store, space, document,
                     {"url": "https://example.invalid/frozen/probe", "body": body.encode()}, run_dir)

    save(source["body"], "fixture-v1")
    wiki_page = store._wiki(space) / fixture["page"]["path"]
    wiki_page.parent.mkdir(parents=True, exist_ok=True)
    wiki_page.write_text(fixture["page"]["body"], encoding="utf-8")
    if not case.get("metadata_missing"):
        record_learning(store, space, "fixture-learning", source_versions=source_snapshot(store, space),
                        paths=[fixture["page"]["path"]])
    if case["knowledge_status"] == "stale":
        save(source["body"] + "\n受控来源已变更；旧页面尚未更新。", "fixture-v2")
    actual = next(p for p in knowledge_health(store, space)["pages"] if p["path"] == fixture["page"]["path"])
    if actual["status"] != case["knowledge_status"]:
        raise ValueError("评测前置状态不符：" + case["id"] + " / " + actual["status"])


def run_case(profile, fixture, case, timeout):
    with tempfile.TemporaryDirectory(prefix="openwiki-answer-eval-") as temporary:
        store = FederationStore(Path(temporary).resolve() / "data", project_root=ROOT)
        store.init()
        initialize_standards(store)
        space = fixture["space_id"]
        configured = profile._safe(profile._state(space), ".env")
        if not configured.is_file():
            raise ValueError("当前 Agent 没有模型配置，无法进行真实回答评测。")
        destination = store._safe(store._state(space), ".env")
        shutil.copyfile(configured, destination)
        destination.chmod(0o600)
        prepare_case(store, fixture, case)
        job = {"id": uuid.uuid4().hex, "space": space, "question": case["question"]}
        environment = isolated_ask_environment(store, job)
        result_path = Path(environment["OPENWIKI_CONFIG_DIR"]) / "final-answer.json"
        environment["FEDERATION_CHAT_RESULT"] = str(result_path)
        command = [store.node, str(ROOT / "federation/agent-turn.mjs")]
        prompt = ("本轮是冻结资料问答评测。仅依据本轮预读 Wiki 和宿主提供的追溯状态回答；"
                  "不调用额外工具，不查询原始来源，不修改任何文件。\n" + case["question"])
        process = subprocess.Popen(command, cwd=ROOT, env=environment, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            output, _ = process.communicate(json.dumps({"prompt": prompt}).encode(), timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
            raise ValueError("本题模型调用超时：" + case["id"]) from None
        if process.returncode or not result_path.is_file():
            # The native bridge sanitizes diagnostics; avoid exporting entire logs/config.
            detail = output.decode("utf-8", errors="replace").strip().splitlines()
            raise ValueError("本题模型调用失败：" + case["id"] + " / " + (detail[-1][-300:] if detail else "无结果"))
        result = json.loads(result_path.read_text("utf-8"))
        return {"case_id": case["id"], "answer": result["answer"], "model": result.get("model"),
                "wiki_reads": result.get("wiki_reads", []), "wiki_citation_check": result.get("wiki_citation_check"),
                "evidence_class": "real_model_with_controlled_local_corpus"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="调用当前 Agent 已配置的模型；可能产生服务商费用")
    parser.add_argument("--base", type=Path, default=ROOT / "openwiki-federation")
    parser.add_argument("--report", type=Path, default=ROOT / "openwiki-federation/validation/knowledge-answer-eval.json")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    if not args.live:
        parser.error("真实回答评测需要 --live；无模型的检查请运行 node federation/evaluate-wiki-evidence.mjs。")
    fixture = json.loads(FIXTURE.read_text("utf-8"))
    profile = FederationStore(args.base, project_root=ROOT)
    report_path = args.report.resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    answers_path = report_path.with_name(report_path.stem + "-answers.json")
    answers = []
    for case in fixture["cases"]:
        print("Running " + case["id"], flush=True)
        try:
            answers.append(run_case(profile, fixture, case, args.timeout))
        except Exception as error:
            answers.append({"case_id": case["id"], "error": str(error)})
        _write_json(answers_path, answers)
    with tempfile.TemporaryDirectory(prefix=".answer-score-", dir=report_path.parent) as scoring:
        candidate = Path(scoring) / "report.json"
        result = subprocess.run([profile.node, str(ROOT / "federation/score-knowledge-answers.mjs"),
                                 "--answers", str(answers_path), "--output", str(candidate)], cwd=ROOT)
        if result.returncode not in {0, 1} or not candidate.is_file():
            raise RuntimeError("本轮评分器未生成结果；已有报告未覆盖。")
        report = json.loads(candidate.read_text("utf-8"))
        if (report.get("schema_version") != 1 or report.get("fixture_sha256") != hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
                or [item.get("id") for item in report.get("cases", [])] != [item["id"] for item in fixture["cases"]]
                or result.returncode != int(bool(report.get("failed")))):
            raise RuntimeError("本轮评分器结果不匹配冻结题集；已有报告未覆盖。")
    report.update(evidence_class="real_model_with_controlled_local_corpus",
                  answers_path=str(answers_path), fixture_sources="controlled_local_no_http",
                  errors=[item for item in answers if "error" in item])
    _write_json(report_path, report)
    print(json.dumps({"total": report["total"], "passed": report["passed"], "failed": report["failed"],
                      "report": str(report_path)}, ensure_ascii=False), flush=True)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
