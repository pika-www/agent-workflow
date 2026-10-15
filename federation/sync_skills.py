"""Explicit, local-only import of existing Skills into Agent-owned libraries."""
import argparse
import json
from pathlib import Path

from .agent_skills import sync_local_skills
from .core import FederationStore


def main():
    parser = argparse.ArgumentParser(description="将本机既有 Skill 同步到对应 Agent；保留原文件和冲突副本")
    parser.add_argument("--data-dir", type=Path, help="知识库数据目录，默认使用当前项目")
    parser.add_argument("--report", type=Path, help="将完整导入报告保存到此 JSON 文件")
    args = parser.parse_args()
    store = FederationStore(base=args.data_dir)
    store.init()
    report = sync_local_skills(store)
    content = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(content + "\n", encoding="utf-8")
        args.report.chmod(0o600)
        print("Skill 导入报告已保存：" + str(args.report.resolve()))
    else:
        print(content)


if __name__ == "__main__":
    main()
