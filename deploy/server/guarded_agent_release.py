"""Checkpoint and verify one authorized source-only Agent release on the host.

All private backups remain on that host. No database is restored or replaced.
Activation requires the atomic release fence; snapshots alone never authorize restart.
"""
import argparse
import hashlib
import json
import os
import shutil
import time
import urllib.request
from pathlib import Path


def hash_file(path):
    digest=hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()


def get(path,payload=None):
    data=json.dumps(payload).encode() if payload is not None else None
    request=urllib.request.Request('http://127.0.0.1:18732'+path,data=data,method='PUT' if data else 'GET',headers={'Content-Type':'application/json'})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=30) as response:return json.load(response)


def checkpoint(project,release):
    from deploy.server.state_receipt import receipt
    state=receipt('http://127.0.0.1:18732')
    if state['active_jobs'] or state['foreground_running'] or state['foreground_queued']:
        raise ValueError('Foreground jobs still active')
    gate = get('/api/release/status')
    if gate.get('protocol') != 1 or gate.get('phase') != 'sealed' or gate.get('activities') or state['active_run']:
        raise ValueError('Atomic release seal required; use deploy.server.atomic_release')
    release.mkdir(parents=True,exist_ok=True,mode=0o700)
    path=release/'before-state.json'
    if path.exists(): raise ValueError('Do not overwrite the original checkpoint')
    path.write_text(json.dumps(state,ensure_ascii=False,indent=2));path.chmod(0o600)
    # A sealed drain has finished active rounds and retained pending work.
    # Do not mutate settings or special-case knowledge_refresh pointers.
    (release/'checkpoint-state.json').write_text(json.dumps(state,ensure_ascii=False,indent=2))
    print(json.dumps({'sealed_owner':gate['owner'],'active_run':None,'pending':len(state['pending']),'rooms':len(state['rooms'])}))


def protected_snapshot(project,release):
    base=project/'openwiki-federation';files={}
    # Runtime scratch and diagnostics are excluded; formal knowledge, chat,
    # attachments, private settings, jobs and archived source material are hashed.
    ignored={'ask-runs','validation','metadata/autonomy','metadata/context-metrics.sqlite3'}
    for path in base.rglob('*'):
        rel=path.relative_to(base).as_posix()
        if path.is_symlink() or not path.is_file() or any(rel==p or rel.startswith(p+'/') for p in ignored):continue
        if path.suffix in {'.lock'} or path.name.endswith(('-wal','-shm')):continue
        files[rel]=hash_file(path)
    target=release/'protected-before.json'
    if not target.exists():
        target.write_text(json.dumps(files,indent=2));print(json.dumps({'protected_files':len(files)}))
    else:
        before=json.loads(target.read_text());changed=[p for p,h in before.items() if files.get(p)!=h]
        result={'protected_files':len(before),'changed_or_missing':changed,'new_files':len(set(files)-set(before))}
        (release/'protected-verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
        if changed:raise ValueError('Protected files changed')


def restore_settings(project,release):
    source=release/'autonomy-settings-original.json';target=project/'openwiki-federation/metadata/autonomy/settings.json'
    temporary=target.with_name('.release-settings.tmp');shutil.copy2(source,temporary);os.replace(temporary,target)
    print(json.dumps({'settings_restored':hash_file(source)==hash_file(target),'enabled':get('/api/autonomy')['settings']['enabled']}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['checkpoint','snapshot','restore-settings']);parser.add_argument('--project',type=Path,required=True);parser.add_argument('--release',type=Path,required=True);args=parser.parse_args()
    {'checkpoint':checkpoint,'snapshot':protected_snapshot,'restore-settings':restore_settings}[args.action](args.project,args.release)
