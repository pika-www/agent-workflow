"""Host-verified archives and lineage for automatically reviewed knowledge."""
import json
import re

from .core import _now, _sha


def archive_sources(store, space):
    from .knowledge import _base_source
    path = store._safe(store.base, 'metadata/autonomy/sources/' + space + '.json')
    records = json.loads(path.read_text()) if path.exists() else {}
    result = []
    for entry in records.values():
        name = entry['name']
        if not re.fullmatch(r'autonomy/[a-f0-9]{32}\.txt', name):
            raise ValueError('自主来源名称无效')
        if not re.fullmatch(r'metadata/autonomy/runs/[a-f0-9]{32}/(?:attempts/[1-9][0-9]*/)?source-[1-3]\.txt', entry['archive']):
            raise ValueError('自主来源归档位置无效')
        source = _base_source(space, name, entry['version'], 'web')
        source.update(source_id=entry['source_id'], url=entry['url'], checked_at=entry['checked_at'],
                      check_basis='autonomous_public_read', archive=entry['archive'])
        archived = store._safe(store.base, entry['archive'])
        if not archived.is_file():
            source.update(status='missing', reasons=['autonomous_archive_missing'])
        elif _sha(archived.read_bytes()) != entry['version']:
            source.update(status='conflict', reasons=['autonomous_archive_changed'])
        result.append(source)
    return result


def prepare_lineage(store, space, relative, body, run_id, sources, directory):
    from .knowledge import _base_source, _read_sidecar, page_id, OBJECT_TYPES, ID_SEMANTICS
    index_path = store._safe(store.base, 'metadata/autonomy/sources/' + space + '.json')
    index = json.loads(index_path.read_text()) if index_path.exists() else {}
    inputs = []
    for s in sources:
        path = store._safe(directory, s['file'])
        if _sha(path.read_bytes()) != s['sha256']:
            raise ValueError('本轮原文归档被修改，停止入库')
        key = _sha((space + '\0' + s['url']).encode())[:32]
        name = 'autonomy/' + key + '.txt'
        source = _base_source(space, name, s['sha256'], 'web')
        source.update(source_id='source-auto-' + key, url=s['url'], checked_at=s['checked_at'],
                      check_basis='autonomous_public_read', freshness='current',
                      archive=str(path.relative_to(store.base)))
        inputs.append(source)
        index[key] = source
    version, stamp = _sha(body), _now()
    entry = {'object_type': OBJECT_TYPES['page'], 'page_id': page_id(space, relative), 'path': relative,
             'version': version, 'title': body.decode().splitlines()[0].removeprefix('# '),
             'run_id': run_id, 'recorded_at': stamp, 'evidence_scope': 'run_inputs', 'sources': inputs,
             'review_kind': 'automatic', 'human_reviewed': False}
    data = _read_sidecar(store, space)
    if any(r.get('run_id') == run_id for r in data['runs']):
        raise ValueError('本轮知识已经登记，不能重复采用')
    data['pages'].setdefault(relative, []).append(entry)
    data['runs'].append({'object_type': OBJECT_TYPES['run'], 'run_id': run_id, 'recorded_at': stamp,
                        'evidence_scope': 'run_inputs', 'sources': inputs,
                        'pages': [{k: entry[k] for k in ('path', 'page_id', 'version')}]})
    data.update(updated_at=stamp, id_semantics=ID_SEMANTICS,
                evidence_note='原文与内容版本可追溯。自动模型核对可能有误，不等于人工审核。')
    changes = {str(index_path.relative_to(store.base)): json.dumps(index, ensure_ascii=False).encode(),
               'metadata/knowledge/' + space + '.json': json.dumps(data, ensure_ascii=False).encode()}
    frozen = {**entry, 'status': 'current', 'reasons': [], 'evidence': inputs, 'review_due': False}
    return changes, frozen
