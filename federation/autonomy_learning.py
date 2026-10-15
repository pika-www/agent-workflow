"""Resumable learning: repair the same goal, never turn a failed check into approval."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import uuid

from .core import _now, _write_json
from .autonomy import digest, read_json, valid_text, AutonomyDeferred

MAX_REPAIRS_PER_VISIT = 2
PENDING = {'failed', 'needs_attention', 'interrupted', 'retry_pending', 'budget_wait', 'paused', 'foreground_wait'}


def bounded_query(value):
    """Normalize a search hint without changing the actual learning goal."""
    if not isinstance(value, str) or not value.strip() or '\0' in value:
        raise ValueError('补查查询无效')
    value = ' '.join(value.split())
    if len(value) <= 180:
        return value
    parts = re.findall(r'"[^"]*"|\S+', value)
    result = []
    for part in parts:
        if len(' '.join(result + [part])) > 180:
            break
        result.append(part)
    return ' '.join(result) or value[:180].strip('"')


def knowledge_snapshot(manager, agent):
    pages = manager.store.pages(agent['id'])
    existing = [{'path': p['path'], 'body': p['body'].encode()[:1400].decode(errors='ignore'),
                 'truncated': len(p['body'].encode()) > 1400}
                for p in pages if Path(p['path']).name != 'index.md'][-18:]
    return existing, {p['path']: p['sha256'] for p in pages}


def approved(review, draft):
    return (review.get('approved') is True and review.get('role_relevant') is True
            and review.get('goal_relevant') is True and review.get('goal_complete') is True
            and isinstance(review.get('claims_supported'), list)
            and len(review['claims_supported']) == len(draft['claims'])
            and all(value is True for value in review['claims_supported'])
            and review.get('conflicts') == [] and review.get('issues') == []
            and isinstance(review.get('answers'), list) and len(review['answers']) == 2
            and all(valid_text(a, 3000) for a in review['answers']))


def publication_current(manager, agent, owned):
    if not owned:
        return False
    for relative, version in owned.items():
        page = manager.store._safe(manager.store._wiki(agent['id']), relative)
        if not page.is_file() or digest(page.read_bytes()) != version:
            return False
        if agent['id'] != 'central':
            published = manager.store._safe(manager.store.base, 'published/' + agent['id'] + '/' + relative)
            central = manager.store._safe(manager.store._wiki('central'), 'autonomous/' + agent['id'] + '/' + Path(relative).name)
            if any(not p.is_file() or digest(p.read_bytes()) != version for p in (published, central)):
                return False
    return True


def prior_run(manager, agent):
    state = manager.states().get(agent['id'], {})
    identifier = state.get('pending_run') or (state.get('last_run') if state.get('status') in PENDING else None)
    if not identifier or not re.fullmatch(r'[a-f0-9]{32}', identifier):
        return None
    run = read_json(manager.root / 'runs' / identifier / 'run.json', {})
    return run if run.get('agent_id') == agent['id'] and run.get('kind') == 'learning' and run.get('status') in PENDING else None


def carry_sources(manager, previous, directory):
    old = manager.root / 'runs' / previous['id']
    receipt = read_json(old / 'sources.json', {})
    sources = receipt.get('sources', [])
    result = []
    for index, source in enumerate(sources[:3]):
        path = manager.store._safe(old, source['file'])
        raw = path.read_bytes()
        if digest(raw) != source['sha256'] or source['excerpt'] not in raw.decode('utf-8'):
            raise ValueError('续跑原文版本已变化，将重新读取来源')
        name = 'source-' + str(index + 1) + '.txt'
        manager.atomic_bytes(directory / name, raw)
        result.append({**source, 'file': name})
    _write_json(directory / 'sources.json', {**receipt, 'sources': result, 'carried_from': previous['id']})
    return result


def feedback(directory, run, kind, detail):
    item = {'time': _now(), 'kind': kind, 'detail': detail}
    run.setdefault('repairs', []).append(item)
    _write_json(directory / ('feedback-' + str(len(run['repairs'])) + '.json'), item)
    run['feedback'] = item
    run['cursor'] = 'repair'


async def learn(manager, agent):
    cfg = manager.settings()
    previous = prior_run(manager, agent)
    run = {'id': uuid.uuid4().hex, 'agent_id': agent['id'], 'agent_name': agent['name'],
           'kind': 'learning', 'status': 'planning', 'cursor': 'plan', 'started_at': _now(),
           'source_count': 0, 'changed_pages': [], 'model_calls': [], 'repairs': []}
    manager.active = run['id']; manager.save(run)
    directory = manager.root / 'runs' / run['id']
    sources, draft, review = [], None, None
    existing, expected = knowledge_snapshot(manager, agent)
    repairs = 0
    try:
        if previous and isinstance(previous.get('plan'), dict):
            run.update(resumed_from=previous['id'], plan=previous['plan'],
                       original_goal=previous.get('original_goal') or previous['plan']['goal'],
                       cursor=previous.get('cursor', 'repair'), feedback=previous.get('feedback') or
                       {'kind': 'previous_failure', 'detail': previous.get('review') or previous.get('error')},
                       resume_count=previous.get('resume_count', 0) + 1)
            old = manager.root / 'runs' / previous['id']
            _write_json(directory / 'previous-run.json', previous)
            draft = read_json(old / 'draft.json', None)
            review = read_json(old / 'review.json', None)
            if draft: _write_json(directory / 'draft.json', draft)
            if review: _write_json(directory / 'review.json', review)
            try:
                sources = carry_sources(manager, previous, directory)
                run.update(source_count=len(sources), sources=[{k: s[k] for k in
                    ('id', 'title', 'url', 'sha256', 'checked_at')} for s in sources])
            except (ValueError, OSError, KeyError):
                run['cursor'] = 'collect'
            if run['cursor'] in {'draft', 'review', 'publish'} and not sources:
                run['cursor'] = 'collect'
            if run['cursor'] == 'publish': run['cursor'] = 'review'
            if run['cursor'] == 'review' and not draft: run['cursor'] = 'draft'
            if run['cursor'] not in {'collect', 'draft', 'review', 'repair'}: run['cursor'] = 'repair'
            manager.save(run)
        while True:
            step = run['cursor']
            if step == 'plan':
                from .autonomy_model import structured_call
                from .autonomy_strategy import strategy
                from .web_learning import official_sites
                focus = await strategy(manager.store, 'learningFocus',
                    agent={k: agent[k] for k in ('id', 'name', 'description')},
                    history=manager.states().get(agent['id'], {})) if manager.model is structured_call else {}
                plan = await manager.call(run, '行业学习选题', {
                    'agent': {k: agent[k] for k in ('id', 'name', 'description')}, 'existing_knowledge': existing,
                    'recent_learning': manager.states().get(agent['id'], {}), 'learned_strategy': focus,
                    'official_entrypoints': official_sites(manager.store, agent['id']) if agent['id'] != 'central' else [],
                    'task': '选择一个属于本 Agent 职责、用一至两份正文能完整回答的具体小问题。不要同时要求完整体系与多个功能，不把字数约束当学习目标。'
                            '优先补足既有知识缺口。中央 Agent 聚焦知识组织、检索和协作方法。返回 query（英文文档使用英文术语，<=180字）、'
                            'goal（<=500字）、reason（<=500字）、urls（1至2个相关正文候选 URL，避免文档首页；宿主会真实读取）。'})
                validate_plan(plan)
                run.update(plan=plan, original_goal=plan['goal'], cursor='collect')
                manager.save(run)
            elif step == 'collect':
                if not manager.settings()['enabled']: raise AutonomyDeferred('paused', '自主学习已暂停，原目标与进度保留')
                attempt = run.get('source_attempt', 0) + 1
                run['source_attempt'] = attempt
                sub = directory / 'attempts' / str(attempt); sub.mkdir(parents=True, exist_ok=False)
                manager.save(run, status='collecting')
                try:
                    gathered = await manager.collect(manager.store, agent, run['plan'], sub, cfg['pages_per_run'])
                    sources = [{**s, 'file': str((sub / s['file']).relative_to(directory))} for s in gathered]
                    if not sources: raise ValueError('没有可用的来源正文')
                    receipt = read_json(sub / 'sources.json', {})
                    _write_json(directory / 'sources.json', {**receipt, 'sources': sources})
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    feedback(directory, run, 'source_read', {'error': str(exc)[:700], 'reads': read_json(sub / 'sources.json', {})})
                    manager.save(run); continue
                manager.save(run, sources=[{k: s[k] for k in ('id', 'title', 'url', 'sha256', 'checked_at')} for s in sources],
                             source_count=len(sources), cursor='draft')
                signature = digest(json.dumps({'goal': run['original_goal'],
                    'sources': sorted((s['url'], s['sha256']) for s in sources)}, ensure_ascii=False))
                prior = manager.states().get(agent['id'], {})
                if signature == prior.get('source_signature') and prior.get('last_success') and publication_current(
                        manager, agent, prior.get('managed_pages', {})):
                    manager.save(run, status='unchanged', cursor='done', note='原目标已完成，来源与入库正文均未变化')
                    return run
            elif step == 'draft':
                manager.save(run, status='drafting')
                draft = await manager.call(run, '有依据的知识整理', {
                    'agent_scope': agent['description'], 'goal': run['original_goal'], 'sources': sources,
                    'existing_knowledge': existing, 'previous_draft': draft, 'repair_feedback': run.get('feedback'),
                    'task': '依据实际原文整理简短中文知识页，修正反馈指出的问题。返回 title（<=120字）、claims（1至5项，各含 text、source_id、'
                            'quote；quote 必须为 excerpt 中连续逐字原文，保留空白、标点与大小写，不拼接或省略）、application（明确是建议，<=1500字）、'
                            'limitations（范围、版本、未知，<=800字）、questions（2个本页能回答的实际问题）。事实需有原文语义支持，不能编造数字、效果。'
                            '保留原 goal；缺少核心内容时返回 insufficient_evidence=true、reason、missing_questions。不要换成更容易但不相关的话题。'
                            '遇到已有知识冲突，应区分版本、平台和适用条件，必要时在 limitations 中保留分歧，不能掩盖矛盾或把推测当定论。'})
                _write_json(directory / 'draft.json', draft)
                _write_json(directory / ('draft-' + str(len(run['model_calls'])) + '.json'), draft)
                if draft.get('insufficient_evidence'):
                    feedback(directory, run, 'evidence_gap', {k: draft.get(k) for k in ('reason', 'missing_questions')})
                    manager.save(run); continue
                try:
                    manager.validate_draft(draft, sources)
                except ValueError as exc:
                    _write_json(directory / 'draft-before-repair.json', draft)
                    draft = await manager.call(run, '修正知识草稿格式与逐字引用', {
                        'draft': draft, 'sources': sources, 'error': str(exc),
                        'task': '仅据给定原文修正 title、claims、application、limitations、questions。保留1至5项有依据的事实，'
                                'quote 复制 excerpt 连续逐字内容，不拼接、不改空格换行；questions 恰为2项。不得降低依据要求。'})
                    _write_json(directory / 'draft.json', draft)
                    try: manager.validate_draft(draft, sources)
                    except ValueError as error:
                        feedback(directory, run, 'invalid_draft', str(error)); manager.save(run); continue
                manager.save(run, cursor='review')
            elif step == 'review':
                manager.validate_draft(draft, sources)
                manager.save(run, status='reviewing', title=draft['title'])
                review = await manager.call(run, '独立来源与冲突核对', {
                    'agent_scope': agent['description'], 'goal': run['original_goal'], 'draft': draft,
                    'sources': sources, 'existing_knowledge': existing,
                    'task': '独立核对，不因生成者或修复次数而批准。逐项判断原文语义支持、职责相关、原 goal 是否完整覆盖、建议有无冒充事实、'
                            '与已有知识有无未解释的矛盾。不同版本/条件已准确区分、剩余未知不属于原 goal 时不构成冲突。'
                            '返回 approved、role_relevant、goal_relevant、goal_complete（全部为布尔）、claims_supported（按 claims 顺序的布尔数组）、'
                            'conflicts、issues（具体阻断项的字符串数组）、missing_questions（未完成的原目标问题）、answers（按 questions 顺序的2个答案，只能来自 draft）。'
                            '尚缺原目标核心证据时 goal_complete=false，不能靠缩窄标题宣布完成。无依据或未解释冲突时 approved=false。'})
                _write_json(directory / 'review.json', review)
                _write_json(directory / ('review-' + str(len(run['model_calls'])) + '.json'), review)
                if not approved(review, draft):
                    feedback(directory, run, 'review', review); manager.save(run, review=review); continue
                manager.save(run, cursor='publish')
            elif step == 'repair':
                if repairs >= MAX_REPAIRS_PER_VISIT:
                    manager.save(run, status='retry_pending', error='本轮修复仍有未通过项；已保存原目标和反馈，将自动继续补查、修订与核对')
                    return run
                manager.save(run, status='recovering')
                repair = await manager.call(run, '修订学习路径', {
                    'agent_scope': agent['description'], 'original_goal': run['original_goal'], 'previous_plan': run['plan'],
                    'feedback': run.get('feedback'), 'draft': draft, 'review': review,
                    'sources': sources, 'discovery': read_json(directory / 'sources.json', {}).get('discovered_links', [])[:20],
                    'task': '自行处理失败，保持原始学习目标。只读到目录或缺正文时找具体章节/API/规范条目，不能继续用总首页凑证据；'
                            '已有原文足够而草稿有误时修订草稿。实质矛盾需补查版本与适用条件，不能简单要求审核器批准。'
                            '返回 action（research 或 revise）、query（<=180字，仅搜索关键词，不写解释或操作要求）、urls（最多3个正文候选 URL）、reason（<=500字）。'
                            '候选网址可推测但只有宿主实际读取后才是证据；不要改变 goal，不要求用户自行修复，不绕过来源限制。'})
                if not isinstance(repair, dict) or repair.get('action') not in {'research', 'revise'} or not valid_text(repair.get('reason'), 500):
                    raise ValueError('自动修复路径无效，保留原目标等待重试')
                _write_json(directory / ('repair-' + str(len(run['model_calls'])) + '.json'), repair)
                repairs += 1
                if repair['action'] == 'research' or not sources:
                    query = bounded_query(repair.get('query'))
                    urls = repair.get('urls', [])
                    if not isinstance(urls, list) or len(urls) > 3 or any(not valid_text(u, 2000) for u in urls): raise ValueError('补查网址无效')
                    run['plan'] = {**run['plan'], 'goal': run['original_goal'], 'query': query, 'urls': urls, 'reason': repair['reason']}
                    run['cursor'] = 'collect'
                else:
                    run['cursor'] = 'draft'
                manager.save(run)
            elif step == 'publish':
                manager.save(run, status='publishing')
                async with manager.write_lock:
                    if not manager.settings()['enabled']: raise AutonomyDeferred('paused', '自主学习已暂停，候选与进度保留')
                    current, versions = knowledge_snapshot(manager, agent)
                    if versions != expected:
                        existing, expected = current, versions
                        feedback(directory, run, 'concurrent_change', '知识页在审核期间变化，已读取新版本，需要重新核对冲突')
                        manager.save(run); continue
                    publication = manager.publish(run, agent, draft, sources, expected, directory)
                signature = digest(json.dumps({'goal': run['original_goal'],
                    'sources': sorted((s['url'], s['sha256']) for s in sources)}, ensure_ascii=False))
                manager.save(run, status='completed', cursor='done', error=None, publication=publication,
                    changed_pages=publication['pages'], source_signature=signature,
                    verification={'quote_locations': True, 'semantic_review': 'automated_pass', 'goal_complete': True,
                                  'human_reviewed': False, 'readback': True, 'questions': draft['questions'], 'answers': review['answers']})
                return run
            else:
                raise ValueError('学习进度标记无效，保留目标重新检查')
    except asyncio.CancelledError:
        manager.save(run, status='interrupted', error='服务停止，已保存当前步骤，下次自动续跑')
        raise
    except AutonomyDeferred as exc:
        manager.save(run, status=exc.status, error=str(exc))
        return run
    except Exception as exc:
        manager.save(run, status='retry_pending', error=str(exc)[:700])
        return run
    finally:
        manager.save(run, finished_at=_now())
        states = manager.states(); state = states.setdefault(agent['id'], {})
        state.pop('requested', None)
        good = run['status'] in {'completed', 'unchanged'}
        retry_count = 0 if good else state.get('retry_count', 0) + 1
        next_at = datetime.now(timezone.utc) + ((timedelta(minutes=1) if cfg['continuous_learning'] else timedelta(hours=cfg['interval_hours'])) if good else
                  timedelta(minutes=min(cfg['retry_hours'] * 60, 5 * 2 ** min(retry_count - 1, 8))))
        if run['status'] == 'foreground_wait':
            retry_count = state.get('retry_count', 0)
            next_at = datetime.now(timezone.utc) + timedelta(seconds=10)
        if run['status'] == 'budget_wait':
            local = datetime.now(timezone(timedelta(hours=8)))
            next_at = (local + timedelta(days=1)).replace(hour=0, minute=0, second=1, microsecond=0)
        state.update(last_attempt=run['started_at'], last_run=run['id'], status=run['status'],
            last_goal=run.get('original_goal') or run.get('plan', {}).get('goal'), error=run.get('error'),
            retry_count=retry_count, pending_run=None if good else run['id'], next_at=next_at.isoformat(),
            source_errors=read_json(directory / 'sources.json', {}).get('errors', [])[-5:])
        if run['status'] == 'completed':
            state.update(last_success=_now(), source_signature=run['source_signature'],
                         managed_pages={**state.get('managed_pages', {}), **run['publication']['managed_pages']})
        _write_json(manager.root / 'agents.json', states)
        manager.active = None


def validate_plan(plan):
    if not isinstance(plan, dict) or any(not valid_text(plan.get(k), n) for k, n in [('query', 180), ('goal', 500), ('reason', 500)]):
        raise ValueError('学习选题未通过格式检查')
