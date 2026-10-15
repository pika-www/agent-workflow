"""Evidence-backed web learning using the existing scoped OpenWiki updater."""
from __future__ import annotations

import hashlib
import json

from .core import _now, _write_json
from .web_learning import validate_inbox_integrity
from .knowledge import record_learning, source_snapshot


def parse_research_queries(answer):
    try:
        data = json.loads(answer)
    except (TypeError, ValueError) as exc:
        raise ValueError("专业 Agent 未生成有效的检索主题。") from exc
    queries = data.get("queries") if isinstance(data, dict) else None
    if (set(data) != {"queries"} if isinstance(data, dict) else True) or not isinstance(queries, list) or not 1 <= len(queries) <= 3:
        raise ValueError("检索规划必须包含 1 至 3 个主题。")
    if any(not isinstance(q, str) or not q.strip() or len(q) > 240 or "\x00" in q or "://" in q for q in queries):
        raise ValueError("检索主题必须为有效文本，不能用编造网址代替检索。")
    return list(dict.fromkeys(q.strip() for q in queries))


def source_signature(store, space):
    return {item["name"]: hashlib.sha256(store._safe(store._source(space), item["name"]).read_bytes()).hexdigest()
            for item in store.sources(space)}


def wiki_signature(store, space):
    return {page["path"]: page["sha256"] for page in store.pages(space)}


def page_changes(before, after):
    return [{"path": path, "change": "new" if path not in before else "removed" if path not in after else "updated"}
            for path in sorted(set(before) | set(after)) if before.get(path) != after.get(path)]


async def run_web_learning(store, space, goal, run_id, research, learn, collect, progress,
                           urls=None, max_pages=2, maintain_templates=None, refresh_standards=None):
    """Callbacks perform real model/collector work; tests can supply controlled I/O.

    An unchanged crawl only skips learning after a prior *successful* learning
    receipt matches both the inbox and current Wiki. A failed run is retryable.
    """
    if space == "central":
        raise ValueError("中央只采用审核发布的知识，原始采集必须交给专业分支。")
    store.space(space)
    root = store._safe(store.base, "web-learning/" + run_id)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    report_path = store._safe(root, "learning-report.json")
    report = {"run_id": run_id, "space": space, "status": "planning", "goal": goal,
              "queries": [], "sources": [], "errors": [], "changed_pages": [],
              "published": False, "central_updated": False, "started_at": _now(),
              "report_path": str(report_path.relative_to(store.base))}

    def update(values):
        report.update(values, updated_at=_now())
        _write_json(report_path, report)
        progress(dict(report))

    before = wiki_signature(store, space)
    try:
        update({})
        queries = parse_research_queries(await research(goal))
        update({"queries": queries, "status": "collecting"})
        if maintain_templates:
            template_result = await maintain_templates(goal, queries)
            update({"templates": template_result.get("templates", []),
                    "template_errors": template_result.get("errors", [])})
            if report["template_errors"] or any(item.get("status") in {"conflict", "failed"}
                                                 for item in report["templates"]):
                raise ValueError("框架模板维护未完成，已保留原版本；请查看模板错误后重试。")
        def collection_progress(values):
            update({key: value for key, value in values.items()
                    if key in {"status", "provider", "sources", "errors", "phase"}})

        collected = await collect(store, space, goal, urls=urls, max_pages=max_pages,
                                  run_id=run_id + "-collect", queries=queries, progress=collection_progress)
        # Collector metadata does not replace the authoritative learning report.
        update({key: value for key, value in collected.items()
                if key in {"sources", "errors", "provider", "changed_count", "discovery"}})
        if any(isinstance(error, dict) and error.get("code") == "local_source_conflict"
               for error in report["errors"]):
            raise ValueError("本库来源存在人工修改冲突，已保留文件；请核对后再学习，本轮不调用知识更新。")
        if not report["sources"]:
            detail = "；".join(str(item) for item in report["errors"][-3:])[:900]
            raise ValueError("没有成功取得可学习的公开网页正文。" + detail)
        validate_inbox_integrity(store, space)
        signature = source_signature(store, space)
        learning_sources = source_snapshot(store, space)
        learned_path = store._safe(store.base, "metadata/web-learning-learned/" + space + ".json")
        learned = json.loads(learned_path.read_text()) if learned_path.is_file() else {}
        if (signature == learned.get("sources") and before == learned.get("wiki")
                and store.space(space)["knowledge_count"] > 0):
            update({"status": "unchanged", "skipped_learning": True,
                    "learning_job_id": learned.get("learning_job_id"),
                    "notice": "来源与已成功学习的知识版本均未变化，本轮无需重复更新。"})
        else:
            backup = store._safe(root, "wiki-before")
            backup.mkdir(mode=0o700)
            for page in store.pages(space):
                destination = store._safe(backup, page["path"])
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                destination.write_text(page["body"], encoding="utf-8")
                destination.chmod(0o600)
            update({"status": "learning", "backup_path": str(backup.relative_to(store.base))})
            receipt = await learn(goal)
            after = wiki_signature(store, space)
            if store.space(space)["knowledge_count"] == 0:
                raise ValueError("采集已完成，但尚未生成实际主题知识页。")
            changes = page_changes(before, after)
            if not changes and signature != learned.get("sources"):
                raise ValueError("取得了新来源，但知识页未发生更新，不能记录为学会。")
            tracking = record_learning(store, space, receipt.get("id") or run_id,
                                       source_versions=learning_sources,
                                       paths=[item["path"] for item in changes if item["change"] != "removed"])
            update({"status": "completed", "changed_pages": changes,
                    "knowledge_tracking": tracking,
                    "learning_job_id": receipt.get("id"), "source_reads": receipt.get("source_reads"),
                    "notice": "相关分支的知识草稿已更新；尚未审核发布，中央正式知识未更新。"})
            _write_json(learned_path, {"sources": signature, "wiki": after,
                                      "learning_job_id": receipt.get("id"), "learned_at": _now()})
        if refresh_standards:
            maintained = refresh_standards()
            update({"templates": report.get("templates", []) + maintained})
        update({"finished_at": _now()})
        return report
    except BaseException as exc:
        update({"status": "failed", "error": str(exc) or "本轮学习已中断。",
                "changed_pages": page_changes(before, wiki_signature(store, space)),
                "finished_at": _now()})
        raise


def learning_receipt_text(report):
    """Authoritative receipt remains visible even if an LLM summary omits it."""
    sources = report.get("sources", [])
    changes = report.get("changed_pages", [])
    lines = ["联网学习执行回执（实际运行记录）", "知识库：" + report["space"],
             "状态：" + report["status"], "自主检索主题：" + "；".join(report.get("queries", [])),
             f"实际保存或核对 {len(sources)} 份来源；知识页面变化 {len(changes)} 项。"]
    for source in sources:
        lines.append(f"- 来源：{source.get('title', '')} | {source.get('url', '')} | {source.get('status', '')}")
    for page in changes:
        lines.append(f"- 知识页：{page['path']}（{page['change']}）")
    for template in report.get("templates", []):
        lines.append(f"- 专项模板：{template.get('id')} | {template.get('status')} | "
                     f"{template.get('source_version')} | {template.get('upstream_commit', '')[:12]}")
    if report.get("template_errors"):
        lines.append("模板维护缺口：" + json.dumps(report["template_errors"], ensure_ascii=False)[:1800])
    if report.get("error"):
        lines.append("未完成原因：" + report["error"])
    if report.get("errors"):
        lines.append("采集缺口：" + json.dumps(report["errors"], ensure_ascii=False)[:1800])
    lines.append(report.get("notice", "已保存结果以任务记录为准。"))
    lines.append("发布状态：待审核。中央正式知识库未更新；学习不改变模型权重。")
    return "\n".join(lines)
