"""Durable per-agent learning, automatic review and bounded self-improvement.

Ordinary chats retain their existing semantics. A separately authorized policy
owns these background runs, their budgets, published pages and audit receipts.
"""
import asyncio
import base64
from contextlib import suppress, nullcontext
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

from .core import _now, _write_json
from .autonomy_model import structured_call
from .autonomy_sources import discover


DEFAULTS = {'enabled': False, 'code_enabled': False, 'interval_hours': 24,
            'daily_model_calls': 96, 'pages_per_run': 2, 'retry_hours': 2,
            'disabled_agents': [], 'authorization': None}
DEFAULTS.update(conversation_online=True, conversation_refresh=False)
DEFAULTS.update(model_policy='tool_agent', continuous_learning=False)
ACTIVE = {'planning', 'collecting', 'drafting', 'reviewing', 'recovering', 'publishing', 'upgrading'}


class AutonomyDeferred(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def digest(raw):
    return hashlib.sha256(raw if isinstance(raw, bytes) else raw.encode()).hexdigest()


def read_json(path, default):
    if path.is_symlink():
        raise ValueError('自主任务路径不能是符号链接')
    return json.loads(path.read_text()) if path.exists() else default


def parse_time(value):
    return datetime.fromisoformat(value) if value else datetime.min.replace(tzinfo=timezone.utc)


def valid_text(value, limit):
    return isinstance(value, str) and 0 < len(value.strip()) <= limit and '\0' not in value


class Autonomy:
    def __init__(self, store, idle, write_lock, model=None, collect=None):
        self.store, self.idle, self.write_lock = store, idle, write_lock
        self.model = model or structured_call
        self.collect = collect or discover
        self.root = store._safe(store.base, 'metadata/autonomy')
        self.task, self.active, self.lock_file = None, None, None
        self.wake = None
        self.stopping = False
        self.release_fence = None

    def settings(self):
        result = {**DEFAULTS, **read_json(self.root / 'settings.json', {})}
        if os.environ.get('WEIMING_AUTONOMY_LOCAL_ONLY') == '1':
            result['model_policy'] = 'local'
        return result

    def configure(self, changes):
        if set(changes) - set(DEFAULTS):
            raise ValueError('未知自主运行设置')
        config = {**self.settings(), **changes}
        for field in ('enabled', 'code_enabled', 'conversation_online', 'conversation_refresh', 'continuous_learning'):
            if type(config[field]) is not bool:
                raise ValueError('开关必须为布尔值')
        if config['model_policy'] not in {'tool_agent', 'local'}:
            raise ValueError('自主学习模型策略无效')
        for field, low, high in [('interval_hours', 6, 168), ('daily_model_calls', 1, 300),
                                 ('pages_per_run', 1, 3), ('retry_hours', 1, 24)]:
            if type(config[field]) is not int or not low <= config[field] <= high:
                raise ValueError('自主运行预算无效：' + field)
        agents = config['disabled_agents']
        if not isinstance(agents, list) or any(a not in self.store._definitions for a in agents):
            raise ValueError('暂停成员无效')
        if (config['enabled'] or config['conversation_refresh']) and not config.get('authorization'):
            raise ValueError('需要记录用户对持续自主运行的授权')
        if config['authorization'] is not None and not valid_text(config['authorization'], 2000):
            raise ValueError('授权记录无效')
        _write_json(self.root / 'settings.json', config)
        if self.wake:
            self.wake.set()
        return self.snapshot()

    def states(self):
        return read_json(self.root / 'agents.json', {})

    def runs(self, limit=40):
        paths = sorted((self.root / 'runs').glob('*/run.json'), key=lambda p: p.stat().st_mtime, reverse=True)
        return [read_json(p, {}) for p in paths[:limit]]

    def snapshot(self):
        states = self.states()
        agents = []
        settings = self.settings()
        # This view uses identity and saved run state, never Wiki inventories.
        for a in list(self.store._definitions.values()):
            state = states.get(a['id'], {})
            agents.append({'id': a['id'], 'name': a['name'], 'scope': a['description'],
                           'enabled': a['id'] not in settings['disabled_agents'], **state})
        runs = self.runs()
        return {'settings': settings, 'agents': agents, 'runs': runs,
                'worker_running': bool(self.task and not self.task.done()),
                'active_run': self.active, 'budget': self.budget(),
                'verification': '来源逐字定位、独立模型核对、版本检查与入库回读；自动核对不等于人工审核',
                'code_scope': ['federation/retrieval.mjs', 'federation/learning-strategy.mjs', 'federation/tool-strategy.mjs'],
                'code_note': '自动修改检索、工具选用和行业学习策略；固定测试与隔离规则不由 Agent 修改。'}

    def budget(self):
        date = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
        usage = read_json(self.budget_path(), {})
        return usage if usage.get('date') == date else {'date': date, 'calls': 0}

    def budget_path(self):
        return self.root / ('local-budget.json' if self.settings()['model_policy'] == 'local' else 'budget.json')

    def budget_available(self, calls=1):
        return (self.settings()['model_policy'] == 'local'
                or self.budget()['calls'] + calls <= self.settings()['daily_model_calls'])

    async def call(self, run, purpose, payload):
        if not self.settings()['enabled']:
            raise AutonomyDeferred('paused', '自主运行已暂停，候选、原文与当前步骤保留')
        budget = self.budget()
        if not self.budget_available():
            raise AutonomyDeferred('budget_wait', '今日自主模型调用预算已用完，明日从当前步骤自动继续')
        local = self.settings()['model_policy'] == 'local'
        if local and not self.idle():
            raise AutonomyDeferred('foreground_wait', '前台任务优先，已保存步骤，空闲后自动继续')
        budget['calls'] += 1
        _write_json(self.budget_path(), budget)
        operation = asyncio.create_task(self.model(self.store, purpose,
            {**payload, '_host_agent_id': run.get('agent_id', 'central')} if self.model is structured_call else payload))
        try:
            if local:
                while not operation.done():
                    await asyncio.wait({operation}, timeout=0.5)
                    if operation.done():
                        break
                    if not self.settings()['enabled']:
                        raise AutonomyDeferred('paused', '自主运行已暂停，当前步骤保留')
                    if not self.idle():
                        raise AutonomyDeferred('foreground_wait', '前台任务优先，已中断本次后台推理，空闲后从保存步骤继续')
            value, receipt = await operation
        finally:
            if not operation.done():
                operation.cancel()
                with suppress(asyncio.CancelledError):
                    await operation
        run.setdefault('model_calls', []).append(receipt)
        self.save(run)
        return value

    def save(self, run, **changes):
        run.update(changes, updated_at=_now())
        _write_json(self.root / 'runs' / run['id'] / 'run.json', run)
        if run.get('status') in {'completed', 'unchanged', 'failed', 'interrupted', 'budget_wait', 'foreground_wait'}:
            from .agent_workspace import AgentWorkspace
            workspace = AgentWorkspace(self.store)
            agent = run.get('agent_id', 'central')
            try:
                workspace.ensure(agent)
                with workspace.locked(agent):
                    workspace.journal(agent, run['id'], run['status'], run.get('original_goal') or run.get('kind', 'autonomy'),
                        'metadata/autonomy/runs/' + run['id'] + '/run.json')
            except (ValueError, OSError) as exc:
                run['journal_error'] = str(exc)[:200]
                _write_json(self.root / 'runs' / run['id'] / 'run.json', run)

    def request(self, agent=None):
        if agent and agent not in self.store._definitions:
            raise ValueError('Agent 不存在')
        states = self.states()
        for key in ([agent] if agent else self.store._definitions):
            states.setdefault(key, {})['next_at'] = _now()
            if agent:
                states[key]['requested'] = True
                states[key]['requested_at'] = _now()
        _write_json(self.root / 'agents.json', states)
        if self.wake:
            self.wake.set()

    def due(self, now=None):
        now = now or datetime.now(timezone.utc)
        cfg, states = self.settings(), self.states()
        if not cfg['enabled'] or not self.budget_available():
            return None
        def eligible(state):
            if cfg['model_policy'] == 'local' and state.get('status') == 'budget_wait':
                return True
            if cfg['continuous_learning'] and state.get('status') in {'completed', 'unchanged'}:
                return parse_time(state.get('last_attempt')) + timedelta(minutes=1) <= now
            return parse_time(state.get('next_at')) <= now
        agents = [a for a in self.store.spaces() if a['id'] not in cfg['disabled_agents']
                  and eligible(states.get(a['id'], {}))]
        # A selected member's new request takes the next idle slot. Automatic
        # work still rotates fairly instead of letting a failing role monopolize it.
        agents.sort(key=lambda a: (not states.get(a['id'], {}).get('requested', False),
                                  -parse_time(states[a['id']]['requested_at']).timestamp()
                                  if states.get(a['id'], {}).get('requested') and states.get(a['id'], {}).get('requested_at') else 0,
                                  bool(states.get(a['id'], {}).get('last_attempt')),
                                  states.get(a['id'], {}).get('last_attempt', ''), a['id'] == 'central'))
        return agents[0] if agents else None

    def start(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self.root / 'worker.lock'
        if path.is_symlink():
            raise ValueError('自主运行锁路径无效')
        self.lock_file = path.open('a')
        try:
            fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock_file.close()
            self.lock_file = None
            return
        self.recover()
        self.wake = asyncio.Event()
        self.stopping = False
        self.task = asyncio.create_task(self.loop())

    async def close(self):
        self.stopping = True
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
        if self.lock_file:
            fcntl.flock(self.lock_file, fcntl.LOCK_UN)
            self.lock_file.close()
            self.lock_file = None

    def recover(self):
        from .autonomy_upgrade import recover_upgrades
        recover_upgrades(self.store, self.root)
        for journal in (self.root / 'runs').glob('*/transaction.json'):
            tx = read_json(journal, {})
            if tx.get('status') == 'prepared':
                self.rollback_transaction(journal, tx)
        for path in (self.root / 'runs').glob('*/run.json'):
            run = read_json(path, {})
            if run.get('status') in ACTIVE:
                self.save(run, status='interrupted', error='服务重启，未完成步骤将在该成员下次轮转时重试')
                if run.get('kind') == 'learning':
                    states = self.states()
                    state = states.setdefault(run['agent_id'], {})
                    if parse_time(run.get('started_at')) >= parse_time(state.get('last_attempt')):
                        state.update(pending_run=run['id'], last_attempt=run.get('started_at'),
                                     status='interrupted', next_at=_now())
                        _write_json(self.root / 'agents.json', states)

    async def loop(self):
        while not self.stopping:
            try:
                with (self.release_fence.background() if self.release_fence else nullcontext(True)) as allowed:
                    if allowed and self.idle():
                        from .conversation_knowledge import pending, refresh
                        revision = pending(self)
                        if revision:
                            await refresh(self, revision)
                            continue
                        agent = self.due()
                        upgrade = read_json(self.root / 'upgrade.json', {})
                        # Explicit requests run at the next idle point. Automatic code
                        # review also gets a turn after four learning attempts.
                        code_due = (self.settings()['enabled'] and self.settings()['code_enabled']
                                    and parse_time(upgrade.get('next_at')) <= datetime.now(timezone.utc)
                                    and self.budget_available(2))
                        attempted = sum(bool(s.get('last_attempt')) for s in self.states().values())
                        if code_due and (not agent or upgrade.get('requested') or attempted >= 4):
                            from .autonomy_upgrade import maybe_upgrade
                            await maybe_upgrade(self)
                        elif agent:
                            await self.learn(agent)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _write_json(self.root / 'worker-error.json', {'time': _now(), 'error': str(exc)[:500]})
            self.wake.clear()
            try:
                await asyncio.wait_for(self.wake.wait(), 10)
            except asyncio.TimeoutError:
                pass

    async def learn(self, agent):
        from .autonomy_learning import learn
        return await learn(self, agent)

    @staticmethod
    def validate_draft(draft, sources):
        if any(not valid_text(draft.get(k), n) for k, n in [('title', 120), ('application', 1500), ('limitations', 800)]):
            raise ValueError('知识草稿标题、方法或适用边界不完整')
        if not isinstance(draft.get('claims'), list) or not 1 <= len(draft['claims']) <= 5:
            raise ValueError('知识草稿必须包含1至5项可核对的事实')
        if not isinstance(draft.get('questions'), list) or len(draft['questions']) != 2 or any(not valid_text(q, 300) for q in draft['questions']):
            raise ValueError('知识草稿缺少回读问题')
        by_id = {s['id']: s for s in sources}
        for c in draft['claims']:
            if not isinstance(c, dict) or not valid_text(c.get('text'), 1000) or not valid_text(c.get('quote'), 1000):
                raise ValueError('事实与原文片段不完整')
            source = by_id.get(str(c.get('source_id')))
            if not source or c['quote'] not in source['excerpt']:
                raise ValueError('引用片段不在本轮实际读取原文中')

    def publish(self, run, agent, draft, sources, expected, directory):
        sid = agent['id']
        topic = digest(draft['title'].strip() + '\n' + '\n'.join(sorted(s['url'] for s in sources)))[:20]
        relative = 'autonomous/' + topic + '.md'
        wiki = self.store._wiki(sid)
        target = self.store._safe(wiki, relative)
        actual = digest(target.read_bytes()) if target.exists() else None
        managed = self.states().get(sid, {}).get('managed_pages', {})
        preserved = []
        if actual != expected.get(relative) or (actual is not None and managed.get(relative) != actual):
            preserved.append(str(target.relative_to(self.store.base)))
        if sid != 'central':
            old_published = self.store._safe(self.store.base, 'published/' + sid + '/' + relative)
            old_manifest = read_json(self.store._safe(self.store.base, 'metadata/' + sid + '.json'), {})
            old_central = self.store._safe(self.store._wiki('central'), 'autonomous/' + sid + '/' + topic + '.md')
            if old_published.exists() and digest(old_published.read_bytes()) != old_manifest.get('files', {}).get(relative):
                preserved.append(str(old_published.relative_to(self.store.base)))
            if old_central.exists() and (not old_published.exists() or old_central.read_bytes() != old_published.read_bytes()):
                preserved.append(str(old_central.relative_to(self.store.base)))
        original_relative = relative
        if preserved:
            # The reviewed new page gets its own version. Never overwrite a
            # human edit to make an automatic run appear successful.
            topic += '-' + run['id'][:12]
            relative = 'autonomous/' + topic + '.md'
            target = self.store._safe(wiki, relative)
            if target.exists(): raise ValueError('新版本路径已存在，等待下轮重新核对')
        by_id = {s['id']: s for s in sources}
        body = '# ' + draft['title'] + '\n\n'
        body += '归属：' + agent['name'] + '。更新：' + _now() + '。审核方式：来源定位与模型自动核对，未经人工审核。\n\n'
        if preserved:
            body += '此前版本存在独立修改，已原样保留。本页为重新核对后的独立版本，不表示覆盖或批准此前修改。\n\n'
        body += '\n\n'.join(c['text'] + ' [' + by_id[str(c['source_id'])]['title'].replace('[', '').replace(']', '') + ']('
                            + by_id[str(c['source_id'])]['url'] + ')' for c in draft['claims'])
        body += '\n\n## 应用建议\n\n' + draft['application'] + '\n\n## 适用范围与未知\n\n' + draft['limitations']
        body += '\n\n## 本页可以回答\n\n' + '\n'.join('- ' + q for q in draft['questions'])
        body += '\n\n## 来源与版本\n\n' + '\n'.join('- [' + s['title'].replace('[', '').replace(']', '') + '](' + s['url'] + ')；正文 SHA-256：' + s['sha256'] for s in sources)
        body += '\n\n自动学习记录：' + run['id'] + '。原文、草稿与核对回执分别归档，模型判断可能有误。\n'
        changes = {str(target.relative_to(self.store.base)): body.encode()}
        from .autonomy_provenance import prepare_lineage
        lineage, frozen = prepare_lineage(self.store, sid, relative, body.encode(), run['id'], sources, directory)
        changes.update(lineage)
        version = 'auto-' + run['id']
        if sid != 'central':
            published = self.store._safe(self.store.base, 'published/' + sid + '/' + relative)
            manifest_path = self.store._safe(self.store.base, 'metadata/' + sid + '.json')
            manifest = read_json(manifest_path, {})
            old_files = manifest.get('files', {})
            if published.exists() and digest(published.read_bytes()) != old_files.get(relative):
                raise ValueError('已发布快照存在外部修改，停止自动覆盖')
            central = self.store._safe(self.store._wiki('central'), 'autonomous/' + sid + '/' + topic + '.md')
            if central.exists() and (not published.exists() or central.read_bytes() != published.read_bytes()):
                raise ValueError('中央收录页有独立修改，停止自动覆盖')
            files = {**old_files, relative: digest(body)}
            manifest.update(space_id=sid, version=version, published_at=_now(),
                            source_wiki=str(wiki), files=files, published_count=len(files),
                            token=digest(json.dumps(files, sort_keys=True)),
                            automatic_reviews={**manifest.get('automatic_reviews', {}), relative: run['id']})
            previous_knowledge = manifest.get('knowledge', {})
            manifest['knowledge'] = {**previous_knowledge, 'pages': [
                p for p in previous_knowledge.get('pages', []) if p.get('path') != relative] + [frozen]}
            changes[str(published.relative_to(self.store.base))] = body.encode()
            changes[str(central.relative_to(self.store.base))] = body.encode()
            central_lineage, _ = prepare_lineage(self.store, 'central',
                str(central.relative_to(self.store._wiki('central'))), body.encode(), run['id'] + '-central', sources, directory)
            changes.update(central_lineage)
            changes[str(manifest_path.relative_to(self.store.base))] = json.dumps(manifest, ensure_ascii=False, indent=2).encode()
        # Persist ownership in the same transaction as the page: a crash after
        # publication must not turn our own page into an apparent manual edit.
        states = self.states()
        owned = states.setdefault(sid, {})
        if preserved:
            owned.setdefault('managed_pages', {}).pop(original_relative, None)
        owned['managed_pages'] = {**owned.get('managed_pages', {}), relative: digest(body)}
        changes[str((self.root / 'agents.json').relative_to(self.store.base))] = json.dumps(states, ensure_ascii=False, indent=2).encode()
        self.commit_transaction(directory, changes)
        # Authoritative readback checks the actual bytes at every destination.
        for path, raw in changes.items():
            if self.store._safe(self.store.base, path).read_bytes() != raw:
                raise ValueError('知识入库回读不一致')
        return {'version': version, 'pages': [relative], 'central_updated': True,
                'managed_pages': {relative: digest(body)}, 'review_kind': 'automatic',
                'conflict_resolution': {'strategy': 'preserve_and_version' if preserved else 'normal_update', 'preserved_paths': preserved},
                'human_reviewed': False}

    def commit_transaction(self, directory, changes):
        items = []
        for relative, raw in changes.items():
            path = self.store._safe(self.store.base, relative)
            old = path.read_bytes() if path.exists() else None
            items.append({'path': relative, 'before': base64.b64encode(old).decode() if old is not None else None,
                          'after': base64.b64encode(raw).decode()})
        tx = {'status': 'prepared', 'items': items}
        journal = directory / 'transaction.json'
        _write_json(journal, tx)
        try:
            for item in items:
                path = self.store._safe(self.store.base, item['path'])
                expected = base64.b64decode(item['before']) if item['before'] is not None else None
                if (path.read_bytes() if path.exists() else None) != expected:
                    raise ValueError('提交期间文件已变化，停止覆盖')
                self.atomic_bytes(path, base64.b64decode(item['after']))
            tx['status'] = 'committed'
            _write_json(journal, tx)
        except BaseException:
            self.rollback_transaction(journal, tx)
            raise

    @staticmethod
    def atomic_bytes(path, raw):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = path.with_name('.auto-' + uuid.uuid4().hex)
        try:
            with temporary.open('xb') as handle:
                handle.write(raw)
            temporary.chmod(0o600)
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def rollback_transaction(self, journal, tx):
        conflicts = []
        for item in reversed(tx['items']):
            path = self.store._safe(self.store.base, item['path'])
            current = path.read_bytes() if path.exists() else None
            old = base64.b64decode(item['before']) if item['before'] is not None else None
            new = base64.b64decode(item['after'])
            if current == new:
                if old is None:
                    path.unlink()
                else:
                    self.atomic_bytes(path, old)
            elif current != old:
                conflicts.append(item['path'])
        tx.update(status='conflict' if conflicts else 'rolled_back', conflicts=conflicts)
        _write_json(journal, tx)
