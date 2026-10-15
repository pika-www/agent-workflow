"""Check a stopped data copy without modifying database bytes."""
import argparse
import json
from pathlib import Path
import sqlite3


def check(project):
    results = {}
    for root in ('openwiki-federation', 'openwiki-data', 'data'):
        for path in sorted((project / root).rglob('*')):
            if path.suffix not in ('.sqlite', '.sqlite3') or not path.is_file():
                continue
            wal = path.with_name(path.name + '-wal')
            if wal.exists() and wal.stat().st_size:
                raise ValueError('Database is not checkpointed: ' + str(path))
            with sqlite3.connect(path.resolve().as_uri() + '?mode=ro&immutable=1', uri=True) as db:
                result = [row[0] for row in db.execute('PRAGMA quick_check')]
                assert result == ['ok'], (path, result)
                tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
                counts = {name: db.execute('SELECT count(*) FROM "' + name.replace('"', '""') + '"').fetchone()[0] for name in tables}
            results[str(path.relative_to(project))] = {'quick_check': 'ok', 'rows': counts}
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = check(args.project.resolve())
    args.output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    print(json.dumps({'databases': len(result), 'all_quick_check': 'ok'}))
