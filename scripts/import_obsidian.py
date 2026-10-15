#!/usr/bin/env python3
"""Copy an explicit OpenWiki knowledge/source allowlist into a new Obsidian vault.

The source tree is read-only. Every destination must be absent before any write.
No connector configs, runtime state, chats, templates, dependencies or credentials
are traversed. Original source documents and Markdown frontmatter are preserved.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit
from zoneinfo import ZoneInfo


HOME = Path("00 开始/未明.md")
DOMAIN_INDEX = Path("01 知识领域/知识领域.md")
SOURCE_INDEX = Path("02 来源档案/来源档案.md")
MANIFEST = Path("90 迁移记录/迁移清单.json")
VERIFY = Path("90 迁移记录/迁移校验.json")
REPORT = Path("90 迁移记录/迁移说明.md")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def filename(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\[\]#^\x00-\x1f]', "-", value.strip())
    value = re.sub(r"\s+", " ", value).rstrip(" .")
    if not value or value in {".", ".."}:
        raise ValueError("Empty or unsafe note name")
    return value


def wiki(path: Path, label: str | None = None, anchor: str = "") -> str:
    target = path.with_suffix("").as_posix()
    return "[[" + target + anchor + ("|" + label if label else "") + "]]"


def frontmatter(text: str) -> str:
    match = re.match(r"\A---\r?\n.*?\r?\n---(?:\r?\n|$)", text, re.S)
    return match.group(0) if match else ""


def title(text: str, fallback: str) -> str:
    match = re.search(r"^title:\s*(.*?)\s*$", frontmatter(text), re.M)
    if match:
        return match.group(1).strip("\"'")
    return fallback


def outside_code(text: str, transform):
    """Transform prose only, keeping YAML, fenced code and inline code unchanged."""
    fm = frontmatter(text)
    lines = text[len(fm):].splitlines(keepends=True)
    result = [fm]
    fence = None
    for line in lines:
        match = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if match:
            marker = match.group(1)
            if fence is None:
                fence = (marker[0], len(marker))
            elif marker[0] == fence[0] and len(marker) >= fence[1]:
                fence = None
            result.append(line)
        elif fence:
            result.append(line)
        else:
            parts = re.split(r"(`+[^`\n]*`+)", line)
            result.append("".join(part if part.startswith("`") else transform(part) for part in parts))
    return "".join(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--vault", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    project, vault = args.project.absolute(), args.vault.absolute()
    snapshots: dict[Path, bytes] = {}

    def read(path: Path) -> bytes:
        path = path.absolute()
        if not path.is_relative_to(project):
            raise ValueError("Source escaped project")
        if any(parent.is_symlink() for parent in [path, *path.parents] if parent.is_relative_to(project)):
            raise ValueError("Refusing source symlink")
        value = path.read_bytes()
        if path in snapshots and snapshots[path] != value:
            raise ValueError("Source changed during planning")
        snapshots[path] = value
        return value

    core = project / "federation/core.py"
    tree = ast.parse(read(core).decode())
    literals = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in {"BRANCHES", "SPECIALTIES"}:
                    literals[target.id] = ast.literal_eval(node.value)
    definitions = {"central": {"name": "中央智能体知识库", "parent": None}}
    for key, name, _scope in literals["BRANCHES"]:
        definitions[key] = {"name": name, "parent": "central"}
        for suffix, name, _scope in literals["SPECIALTIES"][key]:
            definitions[f"{key}-{suffix}"] = {"name": name, "parent": key}
    registry_path = project / "openwiki-federation/registry.json"
    registry = json.loads(read(registry_path))
    for branch in registry["branches"]:
        if branch["id"] in definitions:
            raise ValueError("Registry attempts to replace a builtin space")
        definitions[branch["id"]] = {
            "name": branch["name"],
            "parent": branch.get("parent_id", "central") if registry["version"] == 2 else "central",
        }

    def ancestors(key):
        seen, chain = set(), []
        while key != "central":
            if key in seen or key not in definitions:
                raise ValueError("Invalid hierarchy")
            seen.add(key)
            chain.append(filename(definitions[key]["name"]))
            key = definitions[key]["parent"]
        return list(reversed(chain))

    roots = {}
    entries = []
    destinations = set()
    source_to_dest = {}

    def add(source, dest, kind, space=None, **extra):
        source = source.absolute()
        if dest.as_posix().casefold() in destinations:
            raise ValueError(f"Destination collision: {dest}")
        data = read(source)
        text = data.decode("utf-8")
        destinations.add(dest.as_posix().casefold())
        source_to_dest[source] = dest
        entry = {"source": source, "destination": dest, "kind": kind,
                 "space": space, "data": data, "text": text, **extra}
        entries.append(entry)
        return entry

    space_entries = {}
    for key, definition in definitions.items():
        root = project / "openwiki-federation" / ("central" if key == "central" else f"branches/{key}") / "state/wiki"
        if not root.is_dir():
            raise ValueError(f"Missing registered wiki: {key}")
        roots[key] = root
        folder = Path("01 知识领域").joinpath(*ancestors(key)) if key != "central" else Path("90 迁移记录")
        for source in sorted(root.rglob("*.md")):
            relative = source.relative_to(root)
            text = read(source).decode()
            if relative == Path("index.md"):
                dest = folder / (filename(definition["name"]) + ".md")
                kind = "archived-central-entry" if key == "central" else "knowledge-space-entry"
            elif relative.parts[0] == "sources":
                label = "来源索引" if source.name == "index.md" else title(text, source.stem)
                dest = Path("02 来源档案").joinpath(*ancestors(key)[1:]) / (filename(label) + ".md")
                kind = "source-reference"
            else:
                dest = folder.joinpath(*relative.parts[:-1]) / (filename(title(text, source.stem)) + ".md")
                kind = "knowledge-draft"
            item = add(source, dest, kind, key)
            if relative == Path("index.md"):
                space_entries[key] = item

    legacy_root = project / "openwiki-data/wiki"
    legacy_dirs = {"sources": "来源", "tools": "工具", "topics": "主题"}
    fallback_titles = {"index.md": "旧单库", "commitments.md": "承诺追踪器", "personal-logistics.md": "个人事项跟踪器",
                       "sources/index.md": "来源索引", "tools/index.md": "工具索引", "topics/index.md": "主题目录"}
    for source in sorted(legacy_root.rglob("*.md")):
        relative = source.relative_to(legacy_root)
        text = read(source).decode()
        label = title(text, fallback_titles.get(relative.as_posix(), source.stem))
        folder = Path("90 迁移记录/旧单库").joinpath(*(legacy_dirs.get(part, part) for part in relative.parts[:-1]))
        add(source, folder / (filename(label) + ".md"), "legacy-wiki")

    raw_specs = [
        ("openwiki-federation/branches/software-frontend/inbox/web-8dc19488153757ed-a037dbe1aa81cf5e.md",
         "02 来源档案/前端/MDN HTML 约束验证（采集元数据）.md", "collected-source", "software-frontend"),
        ("openwiki-federation/web-learning/a32ab4b8b4ac49f186e8207a17503537-collect/8dc19488153757ed-a037dbe1aa81cf5e.md",
         "02 来源档案/前端/MDN HTML 约束验证（网页原文）.md", "raw-web-source", "software-frontend"),
        ("openwiki-inbox/示例-海岚读书计划.md",
         "02 来源档案/历史示例/海岚读书计划（虚构验收原文）.md", "fictional-source", None),
    ]
    for source, dest, kind, space in raw_specs:
        add(project / source, Path(dest), kind, space, preserve_bytes=True)

    research_dedup = {}
    research_receipts = []
    for report in sorted((project / "openwiki-federation/research-runs").glob("*/report.json")):
        receipt = json.loads(read(report))
        sources = receipt.get("sources", [])
        for source in sorted(report.parent.glob("*.md")):
            data = read(source)
            digest = sha(data)
            matches = [item for item in sources if item.get("sha256") == digest]
            if not matches:
                raise ValueError("Research document has no matching source receipt")
            evidence = {"report": str(report.relative_to(project)), "source": str(source.relative_to(project)),
                        "source_sha256": digest, "run_id": receipt.get("run_id"), "scope": receipt.get("scope"),
                        "status": receipt.get("status"), "url": matches[0].get("url"),
                        "captured_at": receipt.get("finished_at")}
            research_receipts.append(evidence)
            if digest in research_dedup:
                source_to_dest[source] = research_dedup[digest]["destination"]
                research_dedup[digest].setdefault("duplicate_sources", []).append(source)
            else:
                text = data.decode()
                label = title(text, "网页资料")
                if matches[0].get("url", "").startswith("https://react.dev/"):
                    label = "React " + label
                item = add(source, Path("02 来源档案/未整理网页") / (filename(label) + "（未整理原文）.md"),
                           "research-only-source", preserve_bytes=True, url=matches[0].get("url"))
                research_dedup[digest] = item

    rewritten_links = []
    unresolved_links = []
    generated_links = set()

    def link(path, label=None):
        generated_links.add(path)
        return wiki(path, label)

    def transform_markdown(entry):
        source = entry["source"]
        root = roots.get(entry["space"], legacy_root)

        def replace(match):
            label, raw = match.group(1), match.group(2).strip()
            target = raw[1:-1] if raw.startswith("<") and raw.endswith(">") else raw
            # Existing external URLs, anchors and link titles remain untouched.
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path or target.startswith("#"):
                return match.group(0)
            part = unquote(parsed.path)
            candidate = ((root / part.lstrip("/")) if part.startswith("/") else source.parent / part).resolve()
            if candidate.is_dir():
                candidate /= "index.md"
            if candidate in source_to_dest:
                dest = source_to_dest[candidate]
                anchor = "#" + unquote(parsed.fragment) if parsed.fragment else ""
                rewritten_links.append({"source": str(source.relative_to(project)), "original": target,
                                        "destination": dest.as_posix(), "anchor": anchor})
                generated_links.add(dest)
                converted = wiki(dest, None if label == dest.stem else label, anchor)
                # Obsidian aliases need an escaped separator inside Markdown tables.
                if match.string.lstrip().startswith("|"):
                    converted = converted.replace("|", r"\|")
                return converted
            if part.endswith(".md") or part.endswith("/"):
                unresolved_links.append({"source": str(source.relative_to(project)), "target": target})
            return match.group(0)

        return outside_code(entry["text"], lambda s: re.sub(r"(?<!!)\[([^\]\n]+)\]\(([^)\n]+)\)", replace, s))

    output = {}
    raw_destinations = {entry["kind"]: entry["destination"] for entry in entries if entry.get("preserve_bytes")}
    for entry in entries:
        if entry.get("preserve_bytes"):
            output[entry["destination"]] = entry["data"]
            continue
        body = transform_markdown(entry)
        kind, key = entry["kind"], entry["space"]
        navigation = []
        if kind == "knowledge-space-entry":
            parent = definitions[key]["parent"]
            parent_dest = HOME if parent == "central" else space_entries[parent]["destination"]
            navigation = ["## 在知识库中继续探索", "", "- " + link(HOME, "回到未明"),
                          "- 上一级：" + link(parent_dest, "知识库首页" if parent == "central" else definitions[parent]["name"])]
            children = [child for child in definitions if definitions[child]["parent"] == key]
            if children:
                navigation.extend(["", "### 下级领域", ""])
                navigation.extend("- " + link(space_entries[child]["destination"], definitions[child]["name"]) for child in children)
            if key == "software-frontend":
                navigation.extend(["", "> 当前四篇技术页保留 corrected-draft 与 unpublished 状态；迁入不等于审核发布。"])
        elif kind == "archived-central-entry":
            navigation = ["## 迁移后的入口", "", "> 本文保留原中央页的历史描述，新的 Obsidian 首页另设。", "", "- " + link(HOME, "未明首页")]
            navigation.extend("- " + link(space_entries[child]["destination"], definitions[child]["name"]) for child in definitions if definitions[child]["parent"] == "central")
        elif kind == "knowledge-draft":
            navigation = ["## 关联档案", "", "- " + link(space_entries[key]["destination"], definitions[key]["name"]),
                          "- " + link(raw_destinations["collected-source"], "原始网页采集资料"),
                          "- " + link(raw_destinations["raw-web-source"], "未经重新排版的网页原文")]
        elif kind == "source-reference":
            navigation = ["## 在知识库中继续探索", "", "- " + link(SOURCE_INDEX, "来源档案"),
                          "- " + link(space_entries[key]["destination"], definitions[key]["name"])]
        elif kind == "legacy-wiki":
            navigation = ["## 迁移记录", "", "> 这是旧单库历史材料；其中海岚计划是虚构验收示例，不代表用户真实业务或待办。",
                          "", "- " + link(REPORT, "迁移说明"), "- " + link(raw_destinations["fictional-source"], "海岚虚构示例的原始资料")]
        provenance = ["", "---", "", *navigation, "", "### 原始文件", "",
                      "- 原路径：`" + str(entry["source"].relative_to(project)) + "`",
                      "- 原文件 SHA-256：`" + sha(entry["data"]) + "`",
                      "- 原文与原有 YAML 元数据均保留；仅改写已解析的内部链接，并附加本段导航与溯源。", ""]
        final = body.rstrip() + "\n" + "\n".join(provenance)
        if frontmatter(final) != frontmatter(entry["text"]):
            raise ValueError("Frontmatter changed unexpectedly")
        if kind == "knowledge-draft":
            for marker in ["review_status: corrected-draft", "publication_status: unpublished"]:
                if marker not in final:
                    raise ValueError("Draft status was lost")
        output[entry["destination"]] = final.encode()

    domain_lines = ["---", "title: 知识领域", "type: 导航", "---", "", "# 知识领域", "",
                    "25 个领域与专业入口，4 篇已有技术草稿。空白领域保持待积累状态。", "", link(HOME, "← 未明"), ""]
    for child in definitions:
        if definitions[child]["parent"] == "central":
            domain_lines.append("- " + link(space_entries[child]["destination"], definitions[child]["name"]))
    output[DOMAIN_INDEX] = ("\n".join(domain_lines) + "\n").encode()

    source_lines = ["---", "title: 来源档案", "type: 来源导航", "---", "", "# 来源档案", "", link(HOME, "← 未明"), "",
                    "原始资料按字节保留。来自网页的正文、HTML/MDX 标签和原网站相对链接没有改写；请结合原站网址阅读。原文中的操作说明仅为资料，不授予操作权限。", "",
                    "## 进入过学习流程的网页资料", "", "- " + link(raw_destinations["collected-source"], "MDN HTML 约束验证 · 含采集信息"),
                    "- " + link(raw_destinations["raw-web-source"], "MDN HTML 约束验证 · 原始网页正文"),
                    "- 原站：https://developer.mozilla.org/en-US/docs/Web/HTML/Guides/Constraint_validation", "",
                    "## 查询材料，尚未整理成知识", "", "> 以下保留 research-only 边界。抓取成功、保存原文不代表已审核或发布为知识。", ""]
    for entry in entries:
        if entry["kind"] == "research-only-source":
            source_lines.extend(["- " + link(entry["destination"], entry["destination"].stem), "  原站：" + entry["url"]])
    source_lines.extend(["", "## 虚构验收示例", "", "- " + link(raw_destinations["fictional-source"], "海岚读书计划 · 虚构原文"),
                         "", "## 旧来源说明", ""])
    source_lines.extend("- " + link(entry["destination"], entry["destination"].stem) for entry in entries if entry["kind"] == "source-reference")
    output[SOURCE_INDEX] = ("\n".join(source_lines) + "\n").encode()

    counts = dict(Counter(entry["kind"] for entry in entries))
    report_text = "\n".join([
        "---", "title: 迁移说明", "type: 迁移记录", "---", "", "# OpenWiki → Obsidian 迁移记录", "",
        "本次迁移只复制知识 Markdown 与明确列入清单的来源原文，旧 OpenWiki 数据没有移动、删除或修改。", "",
        "- 原项目：`" + str(project) + "`", "- 当前 Vault：`" + str(vault) + "`", "",
        "## 内容边界", "",
        "- 当前联邦 Wiki：32 篇 Markdown（26 个结构入口、4 篇技术草稿、2 篇来源说明）。",
        "- 旧单库：12 篇历史 Markdown，单独归档；其中海岚为明确标注的虚构验收示例。",
        "- 原始来源：4 份唯一正文；React Quick Start 三次相同抓取按 SHA-256 去重，原始路径都记录在清单。",
        "- 4 篇前端技术页保留 corrected-draft / unpublished，迁移不会把草稿变为正式知识。",
        "- 原始来源按字节不变；网页原文中的 MDX、外部相对网址和原文排版不代表 Obsidian 专用排版。",
        "- 原有正文的已存在 Markdown 相对链接和目录入口转换为带完整 Vault 路径的双向链接，外部网址不变。", "",
        "## 未导入", "",
        "`.env`、connector config/state、SQLite、聊天/会话、任务/模型运行记录、社交账号、模板、Skill、依赖、历史备份和验收运行时数据均保留在旧项目。",
        "采集 JSON 回执不直接导入；可核验的 source URL、抓取批次和 SHA-256 写入清单。", "",
        "## 导航", "", "- " + link(HOME, "未明首页"), "- " + link(DOMAIN_INDEX, "知识领域"),
        "- " + link(SOURCE_INDEX, "来源档案"), "- " + link(source_to_dest[legacy_root / "index.md"], "旧单库"),
        "- " + link(space_entries["central"]["destination"], "原中央知识库入口"), "",
        "## 机器校验", "", "清单：`迁移清单.json`；校验：`迁移校验.json`。记录源路径、源文件哈希、目标文件哈希、链接转换和来源回执。", ""
    ])
    output[REPORT] = report_text.encode()

    # Refuse the entire plan before writes if any target already exists.
    all_targets = [*output, MANIFEST, VERIFY]
    if len({path.as_posix().casefold() for path in all_targets}) != len(all_targets):
        raise ValueError("Generated output collides with imported note")
    for relative in all_targets:
        target = vault / relative
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"Refusing to overwrite: {target}")
        for ancestor in [target.parent, *target.parents]:
            if ancestor.is_symlink():
                raise ValueError("Refusing destination symlink")
    if unresolved_links:
        raise ValueError("Unresolved internal Markdown links: " + json.dumps(unresolved_links, ensure_ascii=False))
    known = set(output)
    broken = sorted(str(path) for path in generated_links if path not in known and not (vault / path).is_file() and path != HOME)
    if broken:
        raise ValueError("Broken planned Vault links: " + repr(broken))
    for source, original in snapshots.items():
        if source.read_bytes() != original:
            raise ValueError("Source changed before write")

    summary = {"vault": str(vault), "imported_markdown": len(entries), "generated_markdown": len(output) - len(entries),
               "counts": counts, "rewritten_internal_links": len(rewritten_links), "source_files_checked": len(snapshots),
               "pending_parent_home": not (vault / HOME).is_file()}
    if args.dry_run:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    created = []
    try:
        for relative, data in output.items():
            target = vault / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as handle:
                handle.write(data)
            created.append(target)
        changed = [str(path.relative_to(project)) for path, data in snapshots.items() if path.read_bytes() != data]
        output_mismatches = [path.as_posix() for path, data in output.items() if (vault / path).read_bytes() != data]
        if changed or output_mismatches:
            raise ValueError("Post-write source/output mismatch")
        stamp = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
        manifest = {"schema_version": 1, "created_at": stamp, "project": str(project), **summary,
                    "entries": [{"source": str(item["source"]), "source_sha256": sha(item["data"]),
                                 "destination": item["destination"].as_posix(), "destination_sha256": sha(output[item["destination"]]),
                                 "kind": item["kind"], "space": item["space"], "original_bytes_preserved": bool(item.get("preserve_bytes")),
                                 "duplicate_sources": [str(path) for path in item.get("duplicate_sources", [])]}
                                for item in entries],
                    "generated_files": [{"path": path.as_posix(), "sha256": sha(data)} for path, data in output.items() if path not in {item["destination"] for item in entries}],
                    "source_snapshots": {str(path): sha(data) for path, data in snapshots.items()},
                    "hierarchy": definitions, "rewritten_links": rewritten_links, "research_receipts": research_receipts,
                    "external_raw_document_links": "Preserved verbatim; see the source index for original websites. They are not asserted to be Vault links."}
        verification = {"checked_at": stamp, "source_count": len(snapshots), "source_changed": 0, "source_missing": 0,
                        "destination_count": len(output), "destination_hash_mismatches": output_mismatches,
                        "rewritten_links": len(rewritten_links), "broken_generated_vault_links": broken,
                        "unresolved_internal_markdown_links": unresolved_links,
                        "pending_parent_links": [HOME.as_posix()] if not (vault / HOME).is_file() else [],
                        "original_frontmatter_preserved": True, "draft_and_unpublished_markers_preserved": True,
                        "raw_source_bytes_preserved": True, "no_existing_files_overwritten": True}
        for relative, value in [(MANIFEST, manifest), (VERIFY, verification)]:
            target = vault / relative
            with target.open("xb") as handle:
                handle.write((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())
            created.append(target)
    except Exception:
        # Remove only files this invocation successfully created, never existing work.
        for path in reversed(created):
            path.unlink()
        raise
    print(json.dumps({**summary, "manifest": str(vault / MANIFEST), "verification": str(vault / VERIFY)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
