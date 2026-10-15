"""Relocate active connector paths, preserving historical conversations and receipts.

Run only on the server after copying a stopped source instance. Every changed
file is preserved under --backup before replacement. Never rewrites Wiki pages,
chat messages, saved tool receipts or past run directories.
"""
import argparse
import json
from pathlib import Path
import shutil


def relocate(project, old_root, old_node, node, backup, data=None):
    files = []
    data = Path(data) if data else project / 'openwiki-federation'
    states = [data / 'central/state', *(data / 'branches').glob('*/state'), project / 'openwiki-data']
    for state in states:
        files.extend([state / 'INSTRUCTIONS.md', state / 'onboarding.json'])
        files.extend((state / 'connectors').glob('*/config.json'))
    changes = []
    for path in files:
        if not path.is_file() or path.is_symlink():
            continue
        before = path.read_text(encoding='utf-8')
        after = before.replace(old_root + '/openwiki-federation', str(data)).replace(old_root, str(project)).replace(old_node, node)
        if after == before:
            continue
        if path.suffix == '.json':
            json.loads(after)
        relative = (Path('openwiki-federation') / path.relative_to(data)) if path.is_relative_to(data) else path.relative_to(project)
        saved = backup / relative
        saved.parent.mkdir(parents=True, exist_ok=True)
        if not saved.exists():
            shutil.copy2(path, saved)
        temporary = path.with_name(path.name + '.relocate.tmp')
        temporary.write_text(after, encoding='utf-8')
        temporary.chmod(path.stat().st_mode & 0o777)
        temporary.replace(path)
        changes.append(str(relative))
    return changes


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--old-root', required=True)
    parser.add_argument('--old-node', required=True)
    parser.add_argument('--node', required=True)
    parser.add_argument('--backup', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path)
    args = parser.parse_args()
    changed = relocate(args.project.resolve(), args.old_root, args.old_node, args.node, args.backup.resolve(), args.data_dir)
    print(json.dumps({'changed': changed}, ensure_ascii=False, indent=2))
