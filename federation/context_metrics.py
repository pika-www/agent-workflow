"""Incremental, idempotent consultation receipt totals; no inferred billing."""
import json
import math
import sqlite3
import os
from contextlib import contextmanager
from .core import _sha


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 else None


class ContextMetrics:
    def __init__(self, store, projects):
        self.path = store._safe(store.base, 'metadata/context-usage.sqlite')
        self.projects = projects

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE IF NOT EXISTS rooms (id TEXT PRIMARY KEY, count INTEGER, last_id TEXT)')
        db.execute('''CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY, room_id TEXT, agent_id TEXT, task_id TEXT, project_id TEXT, created_at TEXT,
            failed INTEGER, receipt INTEGER, calls REAL, input REAL, output REAL, estimate REAL, cached REAL,
            summary_calls REAL, summary_input REAL, summary_output REAL, reply_input REAL, reply_output REAL,
            lookup_calls REAL, lookup_input REAL, lookup_output REAL, check_calls REAL, check_input REAL, check_output REAL,
            first_ms REAL, summary_status TEXT, hash TEXT)''')
        db.execute('CREATE INDEX IF NOT EXISTS usage_room ON events(room_id,first_ms)')
        db.execute('CREATE INDEX IF NOT EXISTS usage_project ON events(project_id,first_ms)')
        db.execute('CREATE TABLE IF NOT EXISTS consultation_rounds (id TEXT PRIMARY KEY, round_id TEXT)')
        db.execute('''CREATE TABLE IF NOT EXISTS operations (
            id TEXT PRIMARY KEY, room_id TEXT, round_id TEXT, agent_id TEXT, project_id TEXT,
            kind TEXT, provider TEXT, calls REAL, input REAL, output REAL,
            input_unknown INTEGER, output_unknown INTEGER, failed INTEGER)''')
        db.execute('CREATE INDEX IF NOT EXISTS operations_room ON operations(room_id,round_id,agent_id)')
        db.execute('CREATE TABLE IF NOT EXISTS room_limits (room_id TEXT PRIMARY KEY, revision INTEGER, calls INTEGER, input INTEGER)')
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def sync_room(self, room, full=False):
        projects = self.projects.read(); mapping = {}
        for p in projects['projects'].values():
            if p['status'] == 'forgotten': continue
            source = p['source']
            if source['room_id'] == room['id']: mapping[(source['agent_id'], source['task_id'])] = p['id']
        for agent, binding in projects['bindings'].get(room['id'], {}).items():
            if binding['project_id']: mapping[(agent, binding['task_id'])] = binding['project_id']
        task_sources = {}
        for agent in {m.get('agent_id') or 'central' for m in room['messages'] if m['role']=='assistant' and m.get('phase')=='consultation'}:
            for task in self.projects.memory.inspect(room['id'],agent)['tasks']:
                for identifier in task['message_ids']: task_sources[(agent,identifier)] = task['id']
        with self.connect() as db:
            old = db.execute('SELECT * FROM rooms WHERE id=?', (room['id'],)).fetchone()
            messages = room['messages']; start = 0
            if not full and old and old['count'] <= len(messages) and (not old['count'] or messages[old['count']-1]['id'] == old['last_id']):
                start = max(0, old['count'] - 2)
            if full:
                ids = [m['id'] for m in messages if m['role'] == 'assistant' and m.get('phase') == 'consultation']
                db.execute('CREATE TEMP TABLE current_ids (id TEXT PRIMARY KEY)')
                db.executemany('INSERT OR IGNORE INTO current_ids VALUES (?)', ((i,) for i in ids))
                db.execute('DELETE FROM events WHERE room_id=? AND NOT EXISTS (SELECT 1 FROM current_ids WHERE current_ids.id=events.id)', (room['id'],))
            columns = [row['name'] for row in db.execute('PRAGMA table_info(events)')]
            for message in messages[start:]:
                if message['role'] != 'assistant' or message.get('phase') != 'consultation' or message.get('status') not in {'completed', 'failed'}: continue
                db.execute('INSERT OR REPLACE INTO consultation_rounds VALUES (?,?)',(message['id'],message.get('round_id') or message['id']))
                usage = message.get('context_usage') or {}; enabled = bool(usage.get('enabled'))
                reply = usage.get('reply') or {}; summary = usage.get('summary') or {}
                lookup = (message.get('workflow') or {}).get('model_usage') or []
                checks = (message.get('answer_check') or {}).get('model_usage') or []
                summed = lambda items, key: sum(number(i.get(key)) or 0 for i in items) if items and all(number(i.get(key)) is not None for i in items) else (0 if not items else None)
                cached = [number(i.get('cached_tokens')) for i in [reply, summary, usage.get('preliminary_reply') or {}, *lookup, *checks]]
                timing = message.get('timing') or {}
                first = number(timing.get('request_first_text_ms'))
                payload_hash = _sha(json.dumps({'usage':usage, 'lookup':lookup, 'checks':checks, 'timing':timing, 'status':message['status']}, sort_keys=True).encode())
                agent = message.get('agent_id') or 'central'; task = usage.get('task_id') or task_sources.get((agent,message['id']))
                project = usage.get('project_id') or mapping.get((agent, task))
                values = [message['id'], room['id'], agent, task, project, message.get('created_at'), int(message['status']=='failed'), int(enabled),
                          number(usage.get('total_calls')), number(usage.get('total_input_tokens')), number(usage.get('total_output_tokens')),
                          number(usage.get('total_input_tokens_estimated')), sum(v for v in cached if v is not None) if any(v is not None for v in cached) else None,
                          number(summary.get('calls')), number(summary.get('input_tokens')), number(summary.get('output_tokens')),
                          number(reply.get('input_tokens')), number(reply.get('output_tokens')), len(lookup) if enabled else None,
                          summed(lookup,'input_tokens') if enabled else None, summed(lookup,'output_tokens') if enabled else None,
                          len(checks) if enabled else None, summed(checks,'input_tokens') if enabled else None, summed(checks,'output_tokens') if enabled else None,
                          first, summary.get('status'), payload_hash]
                # Re-importing the same reply never increments totals. Preserve its first explicit project attribution.
                updates = ','.join(c+'=excluded.'+c for c in columns if c not in {'id','project_id'})
                db.execute('INSERT INTO events VALUES ('+','.join('?' for _ in values)+') ON CONFLICT(id) DO UPDATE SET '+updates+', project_id=COALESCE(events.project_id,excluded.project_id)', values)
            for (agent, task), project in mapping.items():
                if task: db.execute('UPDATE events SET project_id=? WHERE room_id=? AND agent_id=? AND task_id=? AND project_id IS NULL', (project, room['id'], agent, task))
            db.execute('INSERT OR REPLACE INTO rooms VALUES (?,?,?)', (room['id'], len(messages), messages[-1]['id'] if messages else None))

    def totals(self, room_id=None, project_id=None):
        key, identifier = ('project_id', project_id) if project_id else ('room_id', room_id)
        with self.connect() as db:
            sums = ['calls','input','output','estimate','cached','summary_calls','summary_input','summary_output','reply_input','reply_output',
                    'lookup_calls','lookup_input','lookup_output','check_calls','check_input','check_output']
            row = dict(db.execute('SELECT COUNT(*) rounds, SUM(failed) failed_rounds, SUM(receipt) receipt_rounds, '+','.join('SUM('+c+') '+c for c in sums)+
                                  ', SUM(input IS NULL) input_unknown_rounds, SUM(output IS NULL) output_unknown_rounds, SUM(calls IS NULL) calls_unknown_rounds, '+
                                  "SUM(summary_status='failed_using_previous_and_originals') summary_failures FROM events WHERE "+key+'=?', (identifier,)).fetchone())
            n = db.execute('SELECT COUNT(*) FROM events WHERE '+key+'=? AND first_ms IS NOT NULL', (identifier,)).fetchone()[0]
            latency = {}
            for label, fraction in [('p50',.5),('p95',.95)]:
                latency[label] = db.execute('SELECT first_ms FROM events WHERE '+key+'=? AND first_ms IS NOT NULL ORDER BY first_ms LIMIT 1 OFFSET ?',
                                          (identifier,max(0,math.ceil(n*fraction)-1))).fetchone()[0] if n else None
            breakdown = [dict(r) for r in db.execute('SELECT agent_id, COUNT(*) rounds, SUM(input) input, SUM(output) output, SUM(calls) calls FROM events WHERE '+key+'=? GROUP BY agent_id', (identifier,))]
        return {'scope': 'project' if project_id else 'room', 'id':identifier, **row, 'first_text_ms': {'samples':n, **latency}, 'agents':breakdown,
                'notice':'仅统计已保存的普通咨询回执；计数缺失不视为零。分类小计仅含已返回计数，失败请求可能没有完整用量。token 与等待时间不等于 GPU 消耗或货币费用。'}

    def _operation(self, identifier, room_id, round_id, agent, project, kind, provider, calls, input_tokens, output_tokens, unknown_in, unknown_out, failed):
        with self.connect() as db:
            db.execute('INSERT INTO operations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET '
                       'calls=excluded.calls,input=excluded.input,output=excluded.output,input_unknown=excluded.input_unknown,'
                       'output_unknown=excluded.output_unknown,failed=excluded.failed,project_id=COALESCE(operations.project_id,excluded.project_id)',
                       (identifier,room_id,round_id,agent,project,kind,provider,number(calls),number(input_tokens),number(output_tokens),unknown_in,unknown_out,int(failed)))

    def record_router(self, room_id, receipt, project_id=None):
        identifier = receipt.get('usage_event_id')
        if not identifier or not receipt.get('calls'): return
        usage = receipt.get('usage') or {}
        incoming, outgoing = number(usage.get('input_tokens')), number(usage.get('output_tokens'))
        self._operation('route:'+identifier,room_id,None,'central',project_id,'routing','Jev AI',receipt['calls'],incoming,outgoing,
                        int(incoming is None),int(outgoing is None),receipt.get('status')=='unavailable')

    def record_summary(self, record):
        receipt = record['receipt']
        rows = record.get('model_usage') or []
        incoming, outgoing = receipt.get('input_tokens'), receipt.get('output_tokens')
        calls = receipt.get('calls')
        if rows:
            calls = len(rows)
            incoming = sum(r['input_tokens'] for r in rows) if all(number(r.get('input_tokens')) is not None for r in rows) else None
            outgoing = sum(r['output_tokens'] for r in rows) if all(number(r.get('output_tokens')) is not None for r in rows) else None
        provider = receipt.get('provider') or ','.join(sorted({r.get('provider','unknown') for r in rows})) or 'unknown'
        self._operation('memory-summary:'+record['id'], record['room_id'], None, record['agent_id'], record.get('project_id'),
                        'memory_summary', provider, number(calls),number(incoming),number(outgoing),
                        int(number(incoming) is None),int(number(outgoing) is None),
                        receipt['status'] not in {'generated','not_needed','skipped_budget','manual_correction_active','feature_disabled','deferred_for_chat'})

    def sync_job(self, job):
        legacy=job.get('structured_chat') and job.get('action')=='ask' and job.get('status') in {'completed','failed'}
        if not job.get('room_id') or not (job.get('usage_collected') or legacy): return
        rows = job.get('model_usage') or []
        known = lambda key: sum(number(r.get(key)) for r in rows if number(r.get(key)) is not None) if any(number(r.get(key)) is not None for r in rows) else None
        # Empty legacy/native receipts cannot establish zero calls or zero tokens.
        usage=job.get('context_usage') or {}
        calls = len(rows) if rows else number(usage.get('total_calls'))
        incoming, outgoing = (known('input_tokens'), known('output_tokens')) if rows else (number(usage.get('total_input_tokens')),number(usage.get('total_output_tokens')))
        self._operation('model:'+job['id'],job['room_id'],job.get('parent_job_id') or job['id'],job.get('space','central'),
                        job.get('usage_project_id') or (job.get('context_usage') or {}).get('project_id'),
                        'report' if job.get('analysis') else job.get('delegation_phase') or (job.get('action') if job.get('action') in {'learn','sync'} else 'execution'),
                        ','.join(sorted({r.get('provider','unknown') for r in rows})),calls,incoming,outgoing,
                        sum(number(r.get('input_tokens')) is None for r in rows) if rows else int(incoming is None),
                        sum(number(r.get('output_tokens')) is None for r in rows) if rows else int(outgoing is None),
                        job.get('status')=='failed' or any(r.get('status') in {'failed','interrupted','started'} for r in rows))

    def operation_totals(self, room_id=None, project_id=None):
        column, identifier = ('project_id',project_id) if project_id else ('room_id',room_id)
        with self.connect() as db:
            # Each native child is counted once, including format retries. A
            # persisted consultation receipt is only a fallback for legacy jobs.
            rows = [dict(r) for r in db.execute('SELECT kind,provider,calls,input,output,input_unknown,output_unknown,failed FROM operations WHERE '+column+'=?',(identifier,))]
            rows += [dict(r) for r in db.execute('''SELECT 'consultation_legacy' kind,'not_recorded' provider,e.calls,e.input,e.output,
                (e.input IS NULL) input_unknown,(e.output IS NULL) output_unknown,e.failed FROM events e
                WHERE e.'''+column+'''=? AND NOT EXISTS (SELECT 1 FROM operations o WHERE o.room_id=e.room_id AND o.agent_id=e.agent_id
                AND o.round_id=(SELECT round_id FROM consultation_rounds c WHERE c.id=e.id))''',(identifier,))] if self._has_round_table(db) else []
        def total(items,key):
            values=[r[key] for r in items if number(r[key]) is not None];return sum(values) if values else None
        groups=[]
        for kind in sorted({r['kind'] for r in rows}):
            items=[r for r in rows if r['kind']==kind]
            groups.append({'kind':kind,'events':len(items),**{k:total(items,k) for k in ['calls','input','output']}})
        return {'events':len(rows),**{k:total(rows,k) for k in ['calls','input','output']},
                'input_unknown':sum(r['input_unknown'] for r in rows),'output_unknown':sum(r['output_unknown'] for r in rows),
                'calls_unknown':sum(r['calls'] is None for r in rows),'failed_events':sum(r['failed'] for r in rows),'categories':groups,
                'notice':'按实际模型调用回执及路由尝试去重；原生旧任务和失败调用可能缺少计数。SDK 内部传输重试未逐次观测，已返回 token 是下限，不代表完整费用。'}

    @staticmethod
    def _has_round_table(db):
        return db.execute("SELECT 1 FROM sqlite_master WHERE name='consultation_rounds'").fetchone() is not None

    def limit_settings(self, room_id):
        with self.connect() as db:
            row = db.execute('SELECT revision,calls,input FROM room_limits WHERE room_id=?',(room_id,)).fetchone()
        return dict(row) if row else {'revision':0,'calls':0,'input':0}

    def set_limits(self, room_id, revision, calls, input_tokens):
        if any(type(v) is not int or v < 0 for v in [revision,calls,input_tokens]) or calls > 1000000000 or input_tokens > 1000000000000:
            raise ValueError('用量门槛必须为范围内的非负整数。')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT revision FROM room_limits WHERE room_id=?',(room_id,)).fetchone()
            if revision != (row['revision'] if row else 0): raise ValueError('用量设置已更新，请刷新核对；未覆盖其他修改。')
            db.execute('INSERT OR REPLACE INTO room_limits VALUES (?,?,?,?)',(room_id,revision+1,calls,input_tokens))
        return self.admission(room_id)

    def admission(self, room_id):
        totals=self.operation_totals(room_id=room_id)
        server={};settings=self.limit_settings(room_id)
        for key,name in [('calls','FEDERATION_ROOM_MODEL_CALLS_LIMIT'),('input','FEDERATION_ROOM_INPUT_TOKENS_LIMIT')]:
            raw=os.environ.get(name,'0');server[key]=int(raw) if raw.isdigit() and len(raw)<13 else 0
        limits={key:min(v for v in [server[key],settings[key]] if v>0) if server[key] or settings[key] else 0 for key in server}
        exceeded=[key for key,limit in limits.items() if limit and (totals[key] or 0)>=limit]
        near=[key for key,limit in limits.items() if limit and (totals[key] or 0)>=limit*.8 and key not in exceeded]
        return {'limits':limits,'settings':settings,'server_limits':server,'exceeded':exceeded,'near':near,'allowed':not exceeded,
                'notice':'门槛按会话累计已观测用量，达到后阻止新模型请求；当前一轮可能超过剩余额度。进行中的任务、取消和直接读取记忆继续可用。输入计数缺失时不能作为完整计费限额。'}
