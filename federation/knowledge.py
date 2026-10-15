"""Versioned, scoped provenance for learned pages, without claim-level assertions.

IDs identify logical objects and survive content updates. SHA-256 versions identify
bytes/content. A learning record links a page to *run inputs*, not to verified facts.
Only sidecar metadata is written; Wiki/source documents remain untouched.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import PurePosixPath
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .core import SNAPSHOT_NOTE, _write_json

SCHEMA_VERSION = 1
OBJECT_TYPES = {'page': 'knowledge_page', 'source': 'source', 'run': 'learning_run'}
RELATION_TYPES = {'input': 'run_inputs', 'snapshot': 'published_snapshot_of'}
REVIEW_AFTER_DAYS = 30
NON_KNOWLEDGE_NAMES = {'index.md', 'quickstart.md', 'INSTRUCTIONS.md', SNAPSHOT_NOTE}
ID_SEMANTICS = {
    'page_id': 'page- + SHA256(space_id + NUL + relative Wiki path)[:32]',
    'web_source_id': 'source-web- + SHA256(canonical public URL)[:32]; shared URL identity across spaces',
    'local_source_id': 'source-local- + SHA256(space_id + NUL + relative source path)[:32]',
    'published_source_id': 'source-published- + SHA256(upstream space + NUL + page path)[:32]',
    'version': 'SHA256 content; for verified web sources the extracted-body hash, with separate input-file hash',
}


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _id(prefix, identity):
    return prefix + _sha(identity.encode('utf-8'))[:32]


def page_id(space_id, path):
    return _id('page-', space_id + '\0' + path)


def _clock(now=None):
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, str):
        now = datetime.fromisoformat(now.replace('Z', '+00:00'))
    if not isinstance(now, datetime):
        raise ValueError('时间必须是 datetime 或 ISO 8601 字符串。')
    return now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)


def _time(value):
    try:
        return _clock(value) if value else None
    except (ValueError, TypeError):
        return None


def _canonical_url(value):
    if not isinstance(value, str) or len(value) > 2000 or re.search(r'[\x00-\x20\x7f\\]', value):
        raise ValueError('网页来源地址无效。')
    parts = urlsplit(value)
    if parts.scheme.lower() not in {'http', 'https'} or not parts.hostname or parts.username is not None or parts.password is not None:
        raise ValueError('网页来源地址必须是无凭据的 HTTP(S) URL。')
    scheme = parts.scheme.lower()
    host = parts.hostname.rstrip('.').encode('idna').decode('ascii').lower()
    host = '[' + host + ']' if ':' in host else host
    port = parts.port
    netloc = host + (':' + str(port) if port and port != (443 if scheme == 'https' else 80) else '')
    query = [(key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True)
             if not key.lower().startswith('utm_') and key.lower() not in {'fbclid', 'gclid'}]
    return urlunsplit((scheme, netloc, parts.path or '/', urlencode(query), ''))


def _sidecar_path(store, space_id):
    store._definition(space_id)
    return store._safe(store.base, 'metadata/knowledge/' + space_id + '.json')


def _read_sidecar(store, space_id):
    path = _sidecar_path(store, space_id)
    if not path.exists():
        return {'schema_version': SCHEMA_VERSION, 'space_id': space_id, 'pages': {}, 'runs': []}
    value = json.loads(path.read_text('utf-8'))
    if (not isinstance(value, dict) or value.get('schema_version') != SCHEMA_VERSION or
            value.get('space_id') != space_id or not isinstance(value.get('pages'), dict) or
            not isinstance(value.get('runs'), list)):
        raise ValueError('知识追溯登记格式或归属不一致。')
    return value


def _freshness(item, now):
    if item.get('freshness_override') in {'unknown', 'review_due'}:
        return item['freshness_override']
    upstream = item.get('upstream_checks', [])
    if upstream:
        freshness = [_freshness(source, now) for source in upstream]
        if 'unknown' in freshness:
            return 'unknown'
        if 'review_due' in freshness:
            return 'review_due'
    stamp = _time(item.get('checked_at'))
    if stamp is None:
        return 'unknown'
    if stamp > now + timedelta(minutes=5):
        return 'unknown'
    return 'review_due' if now - stamp > timedelta(days=REVIEW_AFTER_DAYS) else 'current'


def _base_source(space_id, name, version, kind='local'):
    return {'object_type': OBJECT_TYPES['source'], 'source_id': _id('source-local-', space_id + '\0' + name),
            'space_id': space_id, 'name': name, 'kind': kind, 'version': version,
            'input_sha256': version, 'inbox_sha256': version, 'status': 'available', 'reasons': [],
            'checked_at': None, 'check_basis': 'unknown', 'freshness': 'unknown'}


def _source_bytes(store, space_id, name):
    path = store._safe(store._source(space_id), name)
    if path.suffix.lower() not in {'.md', '.txt'}:
        raise ValueError('来源仅支持 Markdown/TXT。')
    return path.read_bytes() if path.is_file() else None


def _web_sources(store, space_id, visible):
    index_path = store._safe(store.base, 'web-learning/index.json')
    if not index_path.exists():
        return [], set(), None
    try:
        index = json.loads(index_path.read_text('utf-8'))
        if not isinstance(index, dict):
            raise ValueError('网页来源索引格式无效。')
    except (OSError, ValueError) as error:
        return [], set(), str(error)
    result, claimed, seen = [], set(), set()
    for record in index.values():
        if not isinstance(record, dict) or record.get('space_id') != space_id:
            continue
        name = record.get('filename')
        if not isinstance(name, str) or not name:
            continue
        # Safe path validation must precede all reads, even for an indexed name.
        raw = _source_bytes(store, space_id, name)
        claimed.add(name)
        actual = _sha(raw) if raw is not None else None
        item = _base_source(space_id, name, actual, 'web')
        expected = record.get('inbox_sha256')
        body_version = record.get('sha256')
        item.update(title=record.get('title', name), checked_at=record.get('fetched_at'),
                    check_basis='web_fetch', expected_input_sha256=expected,
                    indexed_version=body_version)
        try:
            item['url'] = _canonical_url(record.get('url'))
            item['source_id'] = _id('source-web-', item['url'])
        except (ValueError, UnicodeError):
            item['status'] = 'conflict'
            item['reasons'].append('invalid_web_url')
        if raw is None:
            item['status'] = 'missing'
            item['reasons'].append('source_missing')
        elif not re.fullmatch(r'[a-f0-9]{64}', str(expected)) or actual != expected:
            item['status'] = 'conflict'
            item['reasons'].append('web_index_hash_conflict')
        elif not re.fullmatch(r'[a-f0-9]{64}', str(body_version)):
            item['status'] = 'conflict'
            item['reasons'].append('web_content_version_missing')
        else:
            item['version'] = body_version
        # Recognize previous versions still present in the inbox. They must never
        # silently become unrelated local sources and appear to be current input.
        histories = record.get('versions', {})
        histories = histories if isinstance(histories, dict) else {}
        obsolete = []
        for version, history in histories.items():
            previous = history.get('filename') if isinstance(history, dict) else None
            if isinstance(previous, str) and previous != name and previous in visible:
                store._safe(store._source(space_id), previous)
                claimed.add(previous)
                obsolete.append({'name': previous, 'version': version})
        if obsolete:
            item['status'] = 'conflict'
            item['reasons'].append('superseded_source_still_in_inputs')
            item['obsolete_inputs'] = obsolete
        if item['source_id'] in seen:
            item['status'] = 'conflict'
            item['reasons'].append('duplicate_web_source_identity')
            for previous in result:
                if previous['source_id'] == item['source_id']:
                    previous['status'] = 'conflict'
                    previous['reasons'].append('duplicate_web_source_identity')
        seen.add(item['source_id'])
        result.append(item)
    return result, claimed, None


def _published_source(store, item, upstream_cache):
    parts = PurePosixPath(item['name']).parts
    item['kind'] = 'published'
    if len(parts) < 2:
        item['status'] = 'conflict'
        item['reasons'].append('published_origin_unknown')
        return item
    upstream_space, relative = parts[0], PurePosixPath(*parts[1:]).as_posix()
    item.update(source_id=_id('source-published-', upstream_space + '\0' + relative),
                upstream_space_id=upstream_space, upstream_path=relative,
                upstream_page_id=page_id(upstream_space, relative),
                relation=RELATION_TYPES['snapshot'])
    try:
        if upstream_space == 'central' or store._definition(upstream_space).get('role') != 'branch':
            raise ValueError('已发布来源必须归属独立分支。')
        manifest = store._manifest(upstream_space)
        if not isinstance(manifest, dict) or not isinstance(manifest.get('files'), dict):
            raise ValueError('发布清单格式无效。')
        expected = manifest['files'].get(relative)
        item.update(upstream_version=expected, publication_version=manifest.get('version'),
                    published_at=manifest.get('published_at'), checked_at=manifest.get('published_at'),
                    check_basis='published_snapshot_record')
        if relative == SNAPSHOT_NOTE:
            item['document_role'] = 'publication_metadata'
            if not manifest.get('version'):
                item['status'] = 'conflict'
                item['reasons'].append('publication_manifest_missing')
        elif not expected or expected != item['version']:
            item['status'] = 'conflict'
            item['reasons'].append('published_snapshot_hash_conflict')
        else:
            item['document_role'] = 'navigation' if PurePosixPath(relative).name in NON_KNOWLEDGE_NAMES else 'knowledge'
            if item['document_role'] == 'navigation':
                item['upstream_evidence_scope'] = 'navigation_metadata'
                item['provenance_basis'] = 'snapshot_manifest'
                return item
            # Prefer the frozen provenance reviewed with this publication. Never
            # replace it with newer draft facts merely because a filename matches.
            frozen = manifest.get('knowledge')
            frozen_pages = frozen.get('pages', []) if isinstance(frozen, dict) else []
            match = next((entry for entry in frozen_pages if isinstance(entry, dict) and
                          entry.get('path') == relative and entry.get('version') == expected), None)
            if match:
                item['upstream_run_id'] = match.get('run_id')
                item['upstream_recorded_at'] = match.get('recorded_at')
                item['upstream_evidence_scope'] = match.get('evidence_scope', 'run_inputs')
                item['upstream_source_versions'] = match.get('evidence', [])
                item['upstream_status_at_publication'] = match.get('status', 'untracked')
                item['provenance_basis'] = 'publication_manifest'
                if match.get('status') != 'current':
                    item['freshness_override'] = 'unknown'
                    item['reasons'].append('upstream_not_current_at_publication')
                    if match.get('status') == 'stale':
                        item['status'] = 'stale'
                evidence = match.get('evidence', [])
                if not isinstance(evidence, list) or not evidence:
                    item['freshness_override'] = 'unknown'
                else:
                    if upstream_space not in upstream_cache:
                        upstream_cache[upstream_space] = {source['source_id']: source for source in source_snapshot(store, upstream_space)}
                    current_sources = upstream_cache[upstream_space]
                    item['upstream_checks'] = []
                    changed = []
                    for original in evidence:
                        current = current_sources.get(original.get('source_id')) if isinstance(original, dict) else None
                        if (not current or current.get('status') != 'available' or
                                current.get('version') != original.get('version') or
                                (original.get('input_sha256') is not None and
                                 current.get('input_sha256') != original.get('input_sha256'))):
                            changed.append(original.get('source_id') if isinstance(original, dict) else None)
                        if current:
                            item['upstream_checks'].append({key: current.get(key) for key in
                                ('source_id', 'version', 'status', 'checked_at', 'freshness_override')})
                    if changed:
                        item['status'] = 'stale'
                        item['reasons'].append('upstream_source_changed_after_publication')
                        item['changed_upstream_source_ids'] = changed
            else:
                item['upstream_evidence_scope'] = 'untracked'
                item['provenance_basis'] = 'snapshot_manifest_only'
                item['freshness_override'] = 'unknown'
    except (ValueError, OSError) as error:
        item['status'] = 'conflict'
        item['reasons'].append('published_provenance_unavailable')
        item['provenance_error'] = str(error)
    return item


def source_snapshot(store, space_id):
    """Return scoped source identities and current verified content versions."""
    store._definition(space_id)
    visible = {item['name'] for item in store.sources(space_id)}
    web, claimed, index_error = _web_sources(store, space_id, visible) if space_id != 'central' else ([], set(), None)
    sources = list(web)
    upstream_cache = {}
    for name in sorted(visible - claimed):
        raw = _source_bytes(store, space_id, name)
        item = _base_source(space_id, name, _sha(raw) if raw is not None else None)
        if raw is None:
            item['status'] = 'missing'
            item['reasons'].append('source_missing')
        if index_error and name.startswith('web-'):
            item['status'] = 'conflict'
            item['reasons'].append('web_index_unreadable')
            item['index_error'] = index_error
        if space_id == 'central':
            item = _published_source(store, item, upstream_cache)
        sources.append(item)
    from .autonomy_provenance import archive_sources
    sources.extend(archive_sources(store, space_id))
    for item in sources:
        if space_id!='central':
            from .knowledge_lifecycle import _load
            imported=_load(store,'metadata/imports/'+space_id+'.json',{'items':{}})['items'].get(item['name'])
            if imported:
                item.update(source_id=imported['source_id'], imported_provenance=imported.get('provenance',{}),
                            source_versions=imported.get('versions',[]), observed_at=imported['updated_at'])
                if imported.get('provenance',{}).get('kind')=='reviewed_model_answer':
                    item['origin_note']='用户审核采用的模型输出；不是独立原始事实证据。'
        item['freshness'] = _freshness(item, _clock())
    return sorted(sources, key=lambda item: (item['source_id'], item['name']))


def _knowledge_path(path):
    return (PurePosixPath(path).name not in NON_KNOWLEDGE_NAMES and
            not any(part.startswith('.') for part in PurePosixPath(path).parts) and
            not path.startswith(('_agent_templates/', '_agent_skills/')))


def _normalize_inputs(store, space_id, sources):
    if sources is None:
        sources = source_snapshot(store, space_id)
    if not isinstance(sources, list):
        raise ValueError('来源版本必须是 source_snapshot 返回的列表。')
    result, seen = [], set()
    for item in sources:
        if not isinstance(item, dict) or item.get('space_id') != space_id:
            raise ValueError('学习来源归属不一致。')
        source_id, version, name = item.get('source_id'), item.get('version'), item.get('name')
        if not isinstance(source_id, str) or not source_id.startswith('source-') or not isinstance(name, str):
            raise ValueError('学习来源身份无效。')
        store._safe(store._source(space_id), name)
        if version is not None and not re.fullmatch(r'[a-f0-9]{64}', str(version)):
            raise ValueError('学习来源版本无效。')
        if source_id in seen:
            raise ValueError('学习来源身份重复，需先修复来源冲突。')
        seen.add(source_id)
        # JSON roundtrip makes an independent snapshot and rejects non-JSON data.
        result.append(json.loads(json.dumps(item, ensure_ascii=False)))
    return result


def record_learning(store, space_id, run_id, source_versions=None, paths=None, now=None):
    """Record only caller-supplied successfully written pages and actual inputs.

    The caller owns proof that the learning run succeeded. This records evidence
    scope explicitly and never retroactively certifies older or unchanged pages.
    """
    store._definition(space_id)
    if not isinstance(run_id, str) or not run_id or len(run_id) > 160 or re.search(r'[\x00-\x1f]', run_id):
        raise ValueError('学习运行标识无效。')
    if paths is None:
        paths = []
    if not isinstance(paths, (list, tuple)) or not all(isinstance(path, str) for path in paths):
        raise ValueError('必须提供本轮实际写入的页面相对路径列表。')
    if not paths:
        return {'schema_version': SCHEMA_VERSION, 'space_id': space_id, 'run_id': run_id, 'recorded_count': 0, 'paths': [], 'status': 'no_pages'}
    pages, skipped_paths = [], []
    for path in dict.fromkeys(paths):
        page = store.page(space_id, path)
        if not _knowledge_path(page['path']):
            skipped_paths.append(page['path'])
            continue
        pages.append(page)
    if not pages:
        return {'schema_version': SCHEMA_VERSION, 'space_id': space_id, 'run_id': run_id, 'recorded_count': 0, 'paths': [], 'skipped_paths': skipped_paths, 'status': 'no_pages'}
    sources = _normalize_inputs(store, space_id, source_versions)
    stamp = _clock(now).isoformat()
    metadata_path = _sidecar_path(store, space_id)
    metadata_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = store._safe(metadata_path.parent, '.' + space_id + '.lock')
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        document = _read_sidecar(store, space_id)
        if any(run.get('run_id') == run_id for run in document['runs'] if isinstance(run, dict)):
            raise ValueError('学习运行标识已经登记，不能覆盖旧运行。')
        recorded = []
        for page in pages:
            # A page changing between initial read and metadata publication must
            # not acquire a receipt for a different version.
            if store.page(space_id, page['path'])['sha256'] != page['sha256']:
                raise ValueError('登记期间知识页面发生变化，请重新核验。')
            entry = {'object_type': OBJECT_TYPES['page'], 'page_id': page_id(space_id, page['path']),
                     'path': page['path'], 'version': page['sha256'], 'title': page['title'],
                     'run_id': run_id, 'recorded_at': stamp, 'evidence_scope': 'run_inputs', 'sources': sources}
            history = document['pages'].setdefault(page['path'], [])
            if not isinstance(history, list):
                raise ValueError('知识页面历史登记格式无效。')
            history.append(entry)
            recorded.append({'path': page['path'], 'page_id': entry['page_id'], 'version': entry['version']})
        document['runs'].append({'object_type': OBJECT_TYPES['run'], 'run_id': run_id, 'recorded_at': stamp,
                                 'evidence_scope': 'run_inputs', 'sources': sources, 'pages': recorded})
        document.update(updated_at=stamp, id_semantics=ID_SEMANTICS,
                        evidence_note='仅记录本轮输入资料与页面版本的关系，不代表逐条事实核验或事实级溯源。')
        _write_json(metadata_path, document)
    finally:
        os.close(fd)
    return {'schema_version': SCHEMA_VERSION, 'space_id': space_id, 'run_id': run_id,
            'recorded_count': len(recorded), 'paths': [item['path'] for item in recorded],
            'pages': recorded, 'skipped_paths': skipped_paths, 'status': 'recorded'}


def knowledge_health(store, space_id, now=None):
    """Inspect tracking, source consistency and review age without editing files."""
    store._definition(space_id)
    current_time = _clock(now)
    metadata_error = None
    try:
        document = _read_sidecar(store, space_id)
    except (ValueError, OSError) as error:
        document = {'pages': {}}
        metadata_error = str(error)
    sources = source_snapshot(store, space_id)
    for source in sources:
        source['freshness'] = _freshness(source, current_time)
    source_map = {item['source_id']: item for item in sources}
    pages = []
    for page in store.pages(space_id):
        if not _knowledge_path(page['path']):
            continue
        result = {'object_type': OBJECT_TYPES['page'], 'path': page['path'], 'page_id': page_id(space_id, page['path']),
                  'version': page['sha256'], 'title': page['title'], 'status': 'untracked', 'reasons': [],
                  'evidence_scope': 'run_inputs', 'evidence': [], 'review_due': False}
        history = document['pages'].get(page['path'], [])
        record = history[-1] if isinstance(history, list) and history and isinstance(history[-1], dict) else None
        if not record:
            result['reasons'].append('metadata_unreadable' if metadata_error else 'no_learning_record')
            pages.append(result)
            continue
        result.update(run_id=record.get('run_id'), recorded_at=record.get('recorded_at'), recorded_version=record.get('version'))
        if record.get('version') != page['sha256']:
            result['reasons'].append('page_changed_after_learning')
            pages.append(result)
            continue
        evidence = record.get('sources')
        if not isinstance(evidence, list) or not evidence:
            result['reasons'].append('learning_inputs_unavailable')
            pages.append(result)
            continue
        result['status'] = 'current'
        for previous in evidence:
            if not isinstance(previous, dict):
                result['status'] = 'stale'
                result['reasons'].append('invalid_source_record')
                continue
            item = {**previous, 'relation': RELATION_TYPES['input'], 'recorded_version': previous.get('version')}
            current = source_map.get(previous.get('source_id'))
            reasons = []
            if previous.get('status') != 'available':
                reasons.append('input_not_verified_at_learning')
            if current is None or current.get('status') == 'missing':
                item['status'] = 'missing'
                reasons.append('source_missing')
            elif current.get('status') in {'conflict', 'stale'}:
                item['status'] = current['status']
                reasons.extend(current.get('reasons') or ['source_conflict'])
            elif (previous.get('version') != current.get('version') or
                  (previous.get('input_sha256') is not None and previous.get('input_sha256') != current.get('input_sha256'))):
                item['status'] = 'changed'
                reasons.append('source_version_changed')
            else:
                item['status'] = 'current'
            if current:
                item.update(current_version=current.get('version'), current_name=current.get('name'),
                            checked_at=current.get('checked_at'), freshness=current.get('freshness'))
            if reasons:
                result['status'] = 'stale'
                result['reasons'].extend(reasons)
            elif current and current.get('freshness') != 'current':
                result['review_due'] = True
                result['reasons'].append('source_check_time_unknown' if current.get('freshness') == 'unknown' else 'source_review_due')
            item['reasons'] = reasons
            result['evidence'].append(item)
        if result['status'] == 'current' and result['review_due']:
            result['status'] = 'review_due'
        result['reasons'] = list(dict.fromkeys(result['reasons']))
        pages.append(result)
    # Claim annotations are an additional, independently reviewed layer. They
    # never relabel run-input provenance as semantic/factual verification.
    from .knowledge_evidence import claim_snapshot
    try:
        claims = claim_snapshot(store, space_id)
        for page in pages:
            page['claims'] = [claim for claim in claims if claim['path'] == page['path']]
    except (ValueError, OSError, KeyError, TypeError):
        for page in pages:
            page['claims'] = []
        metadata_error = (metadata_error or '') + ' 结论证据记录不可用，请复查。'
    summary = {'total': len(pages), **{status: sum(page['status'] == status for page in pages) for status in ('current', 'stale', 'untracked', 'review_due')}}
    return {'schema_version': SCHEMA_VERSION, 'space_id': space_id, 'summary': summary, 'pages': pages, 'sources': sources,
            'checked_at': current_time.isoformat(), 'review_after_days': REVIEW_AFTER_DAYS, 'id_semantics': ID_SEMANTICS,
            'metadata_error': metadata_error,
            'evidence_note': '来源关系是学习运行的输入快照，不代表逐条事实得到支持。current 仅表示所记录版本一致且核查时间未超过复核窗口。'}
