"""Read-only receipts for history and pending work, without copying message text."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import ProxyHandler, build_opener


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def receipt(base):
    http = build_opener(ProxyHandler({}))
    def get(path):
        with http.open(base.rstrip('/') + path, timeout=60) as response:
            return json.load(response)
    federation, autonomy, workspace = get('/api/federation'), get('/api/autonomy'), get('/api/workspace')
    rooms = {}
    for item in get('/api/chat/rooms')['rooms']:
        room = get('/api/chat/rooms/' + item['id'])
        rooms[room['id']] = {'messages': len(room['messages']), 'messages_sha256': digest(room['messages']),
                             'status': room['status'], 'participants': room['participants'], 'title': room['title']}
    active_jobs = [j['id'] for j in workspace['jobs'] if j.get('status') in ('queued', 'running')]
    if (workspace['running'] or workspace['queued']) and not active_jobs:
        active_jobs = ['workspace-active-jobs-outside-recent-window']
    return {'instance': federation['instance'], 'model': federation['model'],
            'agent_ids': sorted(['central'] + [item['id'] for item in federation['branches']]),
            'rooms': rooms,
            # /api/federation deliberately excludes ordinary chats. Counts in
            # /api/workspace cover all roots even when its recent list is capped.
            'active_jobs': active_jobs,
            'foreground_running': workspace['running'], 'foreground_queued': workspace['queued'],
            'active_run': autonomy['active_run'], 'budget': autonomy['budget'], 'settings': autonomy['settings'],
            'pending': {a['id']: {key: a.get(key) for key in ('pending_run', 'status', 'last_goal', 'retry_count')}
                        for a in autonomy['agents'] if a.get('pending_run')}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = receipt(args.url)
    args.output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    args.output.chmod(0o600)
    print(json.dumps({'rooms': len(result['rooms']), 'agents': len(result['agent_ids']),
                      'pending': len(result['pending']), 'active_jobs': result['active_jobs'],
                      'active_run': result['active_run'], 'budget': result['budget']}))
