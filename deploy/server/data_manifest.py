"""Read-only integrity inventory for a quiescent migration snapshot."""
import argparse
import hashlib
import json
from pathlib import Path

ROOTS = ('openwiki-federation', 'openwiki-data', 'data', 'models')


def manifest(project):
    result = {}
    for root in ROOTS:
        for path in sorted((project / root).rglob('*')):
            if path.is_symlink():
                raise ValueError('Data symlink requires manual review: ' + str(path))
            if not path.is_file() or path.name.endswith(('.lock', '-shm')) or path.name == '.DS_Store':
                continue
            if path.name.endswith('-wal'):
                if path.stat().st_size:
                    raise ValueError('Live SQLite WAL must be checkpointed before migration: ' + str(path))
                continue
            digest = hashlib.sha256()
            with path.open('rb') as source:
                for block in iter(lambda: source.read(1024 * 1024), b''):
                    digest.update(block)
            result[str(path.relative_to(project))] = {'bytes': path.stat().st_size, 'sha256': digest.hexdigest()}
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    data = manifest(args.project.resolve())
    args.output.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2))
    print(json.dumps({'files': len(data), 'bytes': sum(x['bytes'] for x in data.values())}))
