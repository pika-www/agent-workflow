"""Claim-to-excerpt evidence and source rechecks, separate from published prose.

An exact quote match proves text occurrence, never semantic entailment. Human
review, local-version checks and online observations remain distinct receipts.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import difflib
import fcntl
import hashlib
import json
from pathlib import PurePosixPath
import re
import uuid

from .core import _write_json, _sha, _now, SNAPSHOT_NOTE
from .web_learning import canonical_url, SafeFetcher, extract_document

MAX_TEXT = 80000


def _key(value):
    if not isinstance(value, str) or not re.fullmatch(r'(?:doc|claim)-[a-f0-9]{32}', value):
        raise ValueError('证据编号无效')
    return value


def _file(store, space):
    store._definition(space)
    return store._safe(store.base, 'metadata/claim-evidence/' + space + '.json')


def _load(store, space):
    path = _file(store, space)
    if not path.exists():
        return {'schema_version': 1, 'space_id': space, 'documents': {}, 'claims': {}, 'history': []}
    data = json.loads(path.read_text('utf-8'))
    if (data.get('schema_version') != 1 or data.get('space_id') != space or
            not isinstance(data.get('documents'), dict) or not isinstance(data.get('claims'), dict)):
        raise ValueError('结论证据登记格式或归属不一致')
    return data


@contextmanager
def _locked(store, space):
    path = _file(store, space)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = store._safe(path.parent, space + '.lock')
    with lock.open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            data = _load(store, space)
            yield data
            _write_json(path, data)
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _text(value, limit=MAX_TEXT):
    if not isinstance(value, str) or not value.strip() or '\0' in value or len(value.encode()) > limit:
        raise ValueError('正文为空、含无效字符或超过大小限制')
    return value


def _body_path(store, space, version):
    if not isinstance(version, str) or not re.fullmatch('[a-f0-9]{64}', version):
        raise ValueError('证据版本无效')
    return store._safe(store.base, 'metadata/evidence-text/' + space + '/' + version + '.md')


def _body(store, space, doc):
    path = _body_path(store, space, doc['version'])
    raw = path.read_bytes()
    if _sha(raw) != doc['version']:
        raise ValueError('原文归档哈希不一致，请核对人工改动')
    return raw.decode('utf-8')


def register_document(store, space, title, text, url=None, expected_version=None):
    """Archive explicit source text; no freshness or factual approval is inferred."""
    title = _text(title, 600)
    text = _text(text)
    url = canonical_url(url) if url else None
    identifier = 'doc-' + _sha((space + '\0' + (url or title)).encode())[:32]
    version = _sha(text.encode())
    with _locked(store, space) as data:
        old = data['documents'].get(identifier)
        if old and old['version'] != version and old['version'] != expected_version:
            raise ValueError('来源版本已存在，请先复查差异并确认当前版本')
        if old and old['version'] == version:
            return dict(old)
        path = _body_path(store, space, version)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.exists():
            if path.read_bytes() != text.encode():
                raise ValueError('已有原文归档不一致，停止覆盖')
        else:
            with path.open('xb') as handle:
                handle.write(text.encode())
            path.chmod(0o600)
        record = {'id': identifier, 'title': title, 'url': url, 'version': version,
                  'origin': 'archived_text', 'created_at': (old or {}).get('created_at', _now()),
                  'versions': (old or {}).get('versions', []) + [version], 'last_check': None}
        data['documents'][identifier] = record
        data['history'].append({'action': 'archive_source', 'id': identifier, 'version': version, 'at': _now()})
    return record


def document_text(store, space, identifier):
    doc = _load(store, space)['documents'].get(_key(identifier))
    if not doc:
        raise ValueError('当前知识库没有这份原文')
    return {**doc, 'text': _body(store, space, doc)}


def _knowledge_page(store, space, path):
    page = store.page(space, path)
    parts = PurePosixPath(page['path']).parts
    if (parts[-1] in {'index.md', 'quickstart.md', 'INSTRUCTIONS.md', SNAPSHOT_NOTE}
            or any(part.startswith(('.', '_agent_')) for part in parts)):
        raise ValueError('请选择知识正文，目录、配置和工作模板不能在这里修订或标注')
    return page


def add_claim(store, space, path, page_version, text, references, kind='fact'):
    if kind not in {'fact', 'inference'}:
        raise ValueError('结论类型须为来源事实或整理者推断')
    page = _knowledge_page(store, space, path)
    if page['sha256'] != page_version:
        raise ValueError('知识页已更新，请重新读取后标注')
    text = _text(text, 3000)
    if text not in page['body']:
        raise ValueError('结论必须逐字选自当前知识页，不能补造正文')
    if not isinstance(references, list) or not 1 <= len(references) <= 4:
        raise ValueError('每条结论需要一至四份具体原文片段')
    identifier = 'claim-' + _sha((space + '\0' + path + '\0' + text).encode())[:32]
    with _locked(store, space) as data:
        refs = []
        for ref in references:
            if not isinstance(ref, dict):
                raise ValueError('原文片段格式无效')
            doc = data['documents'].get(_key(ref.get('document_id')))
            if not doc or doc['version'] != ref.get('version'):
                raise ValueError('原文不属于本库或版本已变化')
            quote = _text(ref.get('quote'), 8000)
            body = _body(store, space, doc)
            offset = body.find(quote)
            if offset < 0:
                raise ValueError('引用片段不存在于原文，不能登记')
            refs.append({'document_id': doc['id'], 'version': doc['version'], 'quote': quote,
                         'quote_sha256': _sha(quote.encode()), 'start_line': body[:offset].count('\n') + 1,
                         'end_line': body[:offset + len(quote)].count('\n') + 1})
        if store.page(space, path)['sha256'] != page_version:
            raise ValueError('标注时知识页发生变化，请重试')
        old = data['claims'].get(identifier)
        if old and old['page_version'] == page_version and old['references'] == refs and old['kind'] == kind:
            return dict(old)
        if old:
            data['history'].append({'action':'archive_claim_version','id':identifier,
                                    'previous':dict(old),'at':_now()})
        record = {'id': identifier, 'path': path, 'page_version': page_version, 'text': text,
                  'kind': kind, 'references': refs, 'quote_match': 'exact', 'semantic_review': 'pending',
                  'created_at': _now(), 'reviewed_at': None}
        data['claims'][identifier] = record
        data['history'].append({'action': 'annotate_claim', 'id': identifier, 'record':dict(record), 'at': _now()})
    return record


def _freshness(doc):
    if doc.get('pending_change'):
        return 'unknown'
    check = doc.get('last_check')
    if not check or check.get('status') != 'unchanged' or check.get('expected_version') != doc['version']:
        return 'unknown'
    try:
        stamp = datetime.fromisoformat(check['checked_at'])
        age = datetime.now(timezone.utc) - stamp
        if age < timedelta(minutes=-5) or age > timedelta(days=30):
            return 'review_due'
    except (KeyError, ValueError, TypeError):
        return 'unknown'
    return 'online_checked' if check.get('scope') == 'online' else 'local_only'


def _claim_view(store, space, claim, documents):
    result = dict(claim)
    reasons = []
    try:
        if store.page(space, claim['path'])['sha256'] != claim['page_version']:
            reasons.append('page_version_changed')
    except (ValueError, FileNotFoundError):
        reasons.append('page_missing')
    refs = []
    for ref in claim['references']:
        doc = documents.get(ref['document_id'])
        if not doc:
            reasons.append('source_missing')
            refs.append({**ref, 'freshness': 'unknown'})
            continue
        status = _freshness(doc)
        if doc['version'] != ref['version']:
            reasons.append('source_version_changed')
        if doc.get('pending_change') or (doc.get('last_check') or {}).get('status') == 'changed':
            reasons.append('online_source_changed')
        try:
            # Read the current archive, never trust a stored quote_match flag alone.
            if ref['quote'] not in _body(store, space, doc):
                reasons.append('quote_no_longer_matches')
        except (ValueError, FileNotFoundError):
            reasons.append('archive_unavailable')
        refs.append({**ref, 'title': doc['title'], 'url': doc.get('url'), 'freshness': status,
                     'last_check': doc.get('last_check')})
    result.update(references=refs, reasons=list(dict.fromkeys(reasons)))
    result['status'] = 'stale' if reasons else ('review_due' if any(r['freshness'] not in {'online_checked', 'local_only'} for r in refs) else 'current')
    result['review_token'] = _sha(json.dumps(result, sort_keys=True, ensure_ascii=False).encode())
    return result


def claim_snapshot(store, space):
    data = _load(store, space)
    return [_claim_view(store, space, claim, data['documents']) for claim in data['claims'].values()]


def review_claim(store, space, identifier, token, decision):
    if decision not in {'approved', 'rejected'}:
        raise ValueError('核对结果无效')
    with _locked(store, space) as data:
        claim = data['claims'].get(_key(identifier))
        if not claim:
            raise ValueError('结论标注不存在')
        current = _claim_view(store, space, claim, data['documents'])
        if current['review_token'] != token or current['status'] == 'stale' or claim.get('superseded_by'):
            raise ValueError('原文或知识页已变化，请重新标注后核对')
        claim.update(semantic_review=decision, reviewed_at=_now(), reviewer='local_user')
        data['history'].append({'action': 'review_claim', 'id': identifier, 'decision': decision,
                                'page_version':claim['page_version'],'references':claim['references'],
                                'review_token':token,'at': _now()})
    return claim


def supersede_claim(store, space, identifier, token, replacement_id, replacement_token):
    """Explicitly replace an old annotation; keep its original text and history."""
    with _locked(store, space) as data:
        old = data['claims'].get(_key(identifier))
        replacement = data['claims'].get(_key(replacement_id))
        if not old or not replacement or identifier == replacement_id or old['path'] != replacement['path']:
            raise ValueError('替代标注必须来自本库同一篇知识页')
        old_view = _claim_view(store, space, old, data['documents'])
        new_view = _claim_view(store, space, replacement, data['documents'])
        if old_view['review_token'] != token or new_view['review_token'] != replacement_token:
            raise ValueError('核对版本已变化，请刷新后重新选择替代标注')
        if (old.get('superseded_by') or replacement.get('superseded_by') or new_view['status'] != 'current'
                or replacement['semantic_review'] != 'approved'):
            raise ValueError('只能采用当前版本且已核对的新标注')
        old.update(superseded_by=replacement_id, superseded_at=_now())
        data['history'].append({'action':'supersede_claim','id':identifier,
                                'replacement_id':replacement_id,'at':_now()})
    return old


def observe_document(store, space, identifier, expected_version, online=False, fetcher=None):
    doc = document_text(store, space, identifier)
    if doc['version'] != expected_version:
        raise ValueError('来源版本已变化，请重新读取')
    if not online:
        return {'status': 'unchanged', 'scope': 'local', 'observed_version': doc['version']}
    if not doc.get('url'):
        raise ValueError('本地资料没有公开网址，只能核对本地版本')
    reader = fetcher or SafeFetcher(use_system_proxy=True)
    try:
        response = reader.fetch(canonical_url(doc['url']))
        document = extract_document(response)
        current = document['text']
        return {'status': 'unchanged' if document['sha256'] == doc['version'] else 'changed',
                'scope': 'online', 'observed_version': document['sha256'], 'text': current,
                'diff': '\n'.join(difflib.unified_diff(doc['text'].splitlines(), current.splitlines(),
                    fromfile='已存原文', tofile='本次网页正文', n=2))[:20000]}
    except Exception as error:
        return {'status': 'unavailable', 'scope': 'online', 'observed_version': None,
                'error': str(error)[:500]}


def record_check(store, space, identifier, expected_version, observation):
    with _locked(store, space) as data:
        doc = data['documents'].get(_key(identifier))
        if not doc or doc['version'] != expected_version:
            raise ValueError('复查期间来源已变化，本次结果未采用')
        _body(store, space, doc)
        receipt = {key: observation[key] for key in ('status', 'scope', 'observed_version', 'diff', 'error') if key in observation}
        receipt.update(id=uuid.uuid4().hex, document_id=identifier, expected_version=expected_version, checked_at=_now())
        if receipt['status'] == 'changed':
            text = _text(observation.get('text'))
            if _sha(text.encode()) != receipt['observed_version']:
                raise ValueError('新原文哈希不一致')
            path = _body_path(store, space, receipt['observed_version'])
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if not path.exists():
                with path.open('xb') as handle:
                    handle.write(text.encode())
                path.chmod(0o600)
            elif _sha(path.read_bytes()) != receipt['observed_version']:
                raise ValueError('候选原文归档已变动，停止覆盖')
            doc['pending_change'] = receipt
        elif receipt['scope'] == 'online' and receipt['status'] == 'unchanged':
            doc.pop('pending_change', None)
        doc['last_check'] = receipt
        data['history'].append({'action': 'recheck_source', **receipt})
    affected = [c['path'] for c in claim_snapshot(store, space) if any(r['document_id'] == identifier for r in c['references'])]
    return {**receipt, 'affected_pages': sorted(set(affected)),
            'note': '核对本地版本，不代表网页最新' if receipt['scope'] == 'local' else '网页正文比对不代表语义事实核验；知识页未自动改写'}


def evidence_overview(store, space):
    data = _load(store, space)
    claims = claim_snapshot(store, space)
    docs = [{**doc, 'freshness': _freshness(doc)} for doc in data['documents'].values()]
    queue = [dict(c) for c in claims if not c.get('superseded_by')
             and (c['status'] != 'current' or c['semantic_review'] != 'approved')]
    return {'space_id': space, 'documents': docs, 'claims': claims, 'review_queue': queue,
            'summary': {'documents': len(docs), 'claims': len(claims), 'pending': len(queue)},
            'note': '原文匹配、用户含义核对、版本复查分别记录；来源文本不授予执行权限。'}


def adopt_observation(store, space, identifier, expected_version, check_id):
    """Adopt an explicitly reviewed source observation, preserving old bytes."""
    with _locked(store, space) as data:
        doc = data['documents'].get(_key(identifier))
        check = (doc or {}).get('pending_change') or (doc or {}).get('last_check') or {}
        if (not doc or doc['version'] != expected_version or check.get('id') != check_id or
                check.get('status') != 'changed' or check.get('expected_version') != expected_version):
            raise ValueError('来源复查结果已变化，请重新查看差异')
        raw = _body_path(store, space, check['observed_version']).read_bytes()
        if _sha(raw) != check['observed_version']:
            raise ValueError('候选原文归档发生变化，停止采用')
        _body(store, space, doc)
        doc['version'] = check['observed_version']
        doc['versions'].append(doc['version'])
        doc['last_check'] = {**check, 'status': 'unchanged', 'expected_version': doc['version'],
                             'adopted_at': _now(), 'previous_version': expected_version}
        doc.pop('pending_change', None)
        data['history'].append({'action': 'adopt_observed_source', 'document_id': identifier,
                                'previous_version': expected_version, 'version': doc['version'], 'at': _now()})
    return doc


def save_revision(store, space, path, expected_version, body):
    """Save a user-authored branch draft with compare-and-swap and backup."""
    if space == 'central':
        raise ValueError('中央接收审核快照，请到原专业分支修订')
    body = _text(body)
    with _locked(store, space) as data:
        page = _knowledge_page(store, space, path)
        if page['sha256'] != expected_version:
            raise ValueError('知识页已变化，请重新对照后修订')
        if _sha(body.encode()) == expected_version:
            return {'status': 'unchanged', 'path': path, 'version': expected_version}
        target = store._safe(store._wiki(space), path)
        backup = store._safe(store.base, 'metadata/page-revisions/' + space + '/' + _sha(path.encode()) + '/' + expected_version + '.md')
        backup.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        raw = target.read_bytes()
        if backup.exists() and backup.read_bytes() != raw:
            raise ValueError('旧版本备份不一致，停止保存')
        if not backup.exists():
            with backup.open('xb') as handle:
                handle.write(raw)
            backup.chmod(0o600)
        # A concurrent manual edit between initial read and save must survive.
        if _sha(target.read_bytes()) != expected_version:
            raise ValueError('保存期间知识页发生变化，停止覆盖')
        from .knowledge_lifecycle import _atomic_text
        _atomic_text(target, body.encode())
        version = _sha(body.encode())
        data['history'].append({'action': 'save_branch_revision', 'path': path,
                                'previous_version': expected_version, 'version': version, 'at': _now()})
    return {'status': 'draft_saved', 'path': path, 'version': version,
            'note': '分支修订稿已保存；旧标注需要重新核对，发布仍需审核。'}
