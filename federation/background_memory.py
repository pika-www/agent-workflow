"""Idle continuation summaries. Never change a chat reply or its running state."""
import asyncio
import json
import os
import signal
import time
import uuid
from contextlib import asynccontextmanager, suppress, nullcontext
from .core import _now, _write_json
from .context_memory import enabled as memory_enabled


class BackgroundSummaries:
    def __init__(self, store, chat, memory, metrics, idle, runner=None, idle_seconds=5):
        self.store, self.chat, self.memory, self.metrics = store, chat, memory, metrics
        self.idle, self.runner, self.delay = idle, runner or self.run_node, idle_seconds
        self.directory = store._safe(store.base, 'metadata/context-summaries')
        self.pending, self.active, self.current = {}, None, None
        # Python 3.9 binds Event to its creation loop. Application construction
        # can happen outside the serving loop, so create it during lifespan.
        self.wake, self.task = None, None
        self.not_before, self.closing = 0, False
        self.foreground_requests = 0
        self.release_fence = None

    def save(self, entry):
        _write_json(self.directory / (entry['id'] + '.json'), entry)

    def enqueue(self, room, context, message_id):
        context = self.memory.background_context(room, context)
        if not context: return False
        key = context['room_id'] + ':' + context['agent_id']
        previous = self.pending.get(key)
        if previous:
            previous.update(status='superseded', context=None)
            self.save(previous)
        entry = {'id': uuid.uuid4().hex, 'key': key, 'context': context, 'message_id': message_id,
                 'status': 'queued', 'created_at': _now(), 'attempts': []}
        self.pending[key] = entry
        self.save(entry)
        self.not_before = time.monotonic() + self.delay
        if self.wake: self.wake.set()
        return True

    def start(self):
        self.closing = False
        self.wake = asyncio.Event()
        if self.directory.is_dir():
            for path in sorted(self.directory.glob('*.json')):
                if path.is_symlink() or path.stat().st_size > 400000: continue
                try:
                    entry = json.loads(path.read_text())
                    if entry.get('status') not in {'queued','running','deferred_for_chat'} or not entry.get('context'): continue
                    if path.stem != entry['id'] or entry['key'] != entry['context']['room_id']+':'+entry['context']['agent_id']: continue
                    if not self.memory.summary_current(entry['context']):
                        entry.update(status='stale', context=None)
                        self.save(entry)
                        continue
                    old = self.pending.get(entry['key'])
                    if not old or old['created_at'] < entry['created_at']: self.pending[entry['key']] = entry
                except (ValueError, KeyError, TypeError, AttributeError, OSError): continue
        self.not_before = time.monotonic() + self.delay
        self.task = asyncio.create_task(self.loop())
        if self.pending: self.wake.set()

    async def preempt(self):
        self.not_before = time.monotonic() + self.delay
        if self.active and not self.active.done():
            self.active.cancel()
            with suppress(asyncio.CancelledError): await self.active
        if self.wake: self.wake.set()

    @asynccontextmanager
    async def foreground_request(self):
        # Routing/admission may await an external service before a job exists.
        # Keep memory idle throughout that request, not just for a short delay.
        self.foreground_requests += 1
        try:
            await self.preempt()
            yield
        finally:
            self.foreground_requests -= 1
            self.not_before = time.monotonic() + self.delay
            if self.wake: self.wake.set()

    async def close(self):
        self.closing = True
        await self.preempt()
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError): await self.task

    async def loop(self):
        # wait_for on Python 3.9 can finish a ready wake at the same time as
        # cancellation. Honour closing even if that cancellation is consumed.
        while not self.closing:
            if not self.pending:
                self.wake.clear()
                await self.wake.wait()
            remaining = max(0, self.not_before - time.monotonic())
            if remaining or self.foreground_requests or not self.idle() or (self.release_fence and self.release_fence.closed()):
                self.wake.clear()
                with suppress(asyncio.TimeoutError): await asyncio.wait_for(self.wake.wait(), max(.05, remaining) if remaining else .2)
                continue
            key = next(iter(self.pending))
            entry = self.pending.pop(key)
            if not self.memory.summary_current(entry['context']):
                entry.update(status='stale', context=None)
                self.save(entry)
                continue
            self.current = entry
            self.active = asyncio.create_task(self.execute(entry))
            try: await self.active
            except asyncio.CancelledError:
                if self.closing: raise
            finally: self.active, self.current = None, None

    async def execute(self, entry):
        with (self.release_fence.background() if self.release_fence else nullcontext(True)) as allowed:
            if not allowed:
                self.pending[entry["key"]] = entry
                return
            await self.execute_admitted(entry)

    async def execute_admitted(self, entry):
        attempt = uuid.uuid4().hex
        started = time.monotonic()
        entry.update(status='running', attempt_id=attempt)
        self.save(entry)
        receipt, persistence = {}, None
        project_id = (entry['context'].get('project_memory') or {}).get('id')
        try:
            if not memory_enabled():
                result = {'receipt':{'status':'feature_disabled','calls':0,'input_tokens':0,'output_tokens':0}}
            elif self.metrics.admission(entry['context']['room_id'])['allowed']:
                result = await self.runner(entry, self.store)
            else:
                result = {'receipt':{'status':'skipped_budget','calls':0,'input_tokens':0,'output_tokens':0}}
            receipt = result['receipt']
            if result.get('update'):
                room = self.chat.get_room(entry['context']['room_id'])
                persistence = self.memory.commit(room, entry['context'], result['update'])
            else:
                self.memory.record_summary_attempt(entry['context'], receipt)
            entry.update(status=(persistence or {}).get('status') or receipt['status'], context=None)
        except asyncio.CancelledError:
            # Originals remain the source of truth. A newer completed turn can
            # replace this request; never put an old snapshot over a newer one.
            receipt = {'status':'deferred_for_chat','calls':None,'input_tokens':None,'output_tokens':None}
            entry['status'] = 'deferred_for_chat'
            if entry['key'] not in self.pending: self.pending[entry['key']] = entry
            raise
        except Exception as exc:
            receipt = {'status':'failed_using_previous_and_originals','reason':type(exc).__name__,
                       'calls':None,'input_tokens':None,'output_tokens':None}
            self.memory.record_summary_attempt(entry['context'], receipt)
            entry.update(status=receipt['status'], context=None)
        finally:
            record = {'id':attempt,'room_id':entry['key'].split(':')[0],'agent_id':entry['key'].split(':')[1],
                      'message_id':entry['message_id'],'receipt':receipt,'persistence':persistence,
                      'project_id':project_id,
                      'elapsed_ms':round((time.monotonic()-started)*1000),'finished_at':_now()}
            usage = self.directory / (attempt + '.usage.jsonl')
            if usage.is_file() and not usage.is_symlink() and usage.stat().st_size <= 100000:
                with suppress(ValueError, OSError):
                    records = {r['id']:r for r in map(json.loads, usage.read_text().splitlines())}
                    record['model_usage'] = list(records.values())
            _write_json(self.directory / 'attempts' / (attempt+'.json'), record)
            entry['attempts'] = (entry['attempts']+[attempt])[-20:]
            self.save(entry)
            try: self.metrics.record_summary(record)
            except Exception: pass  # Derived metrics cannot invalidate memory or a reply.

    async def run_node(self, entry, store):
        environment = store.env_native(entry['context']['agent_id'])
        environment['FEDERATION_MODEL_USAGE_FILE'] = str(self.directory / (entry['attempt_id']+'.usage.jsonl'))
        process = await asyncio.create_subprocess_exec(store.node, str(store.project_root/'federation/summary-turn.mjs'),
            cwd=str(store.project_root), env=environment, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True)
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(json.dumps(entry['context'],ensure_ascii=False).encode()),45)
            if process.returncode or len(stdout)>400000: raise ValueError('后台摘要进程未完成')
            return json.loads(stdout)
        finally:
            if process.returncode is None:
                with suppress(ProcessLookupError): os.killpg(process.pid, signal.SIGTERM)
                try: await asyncio.wait_for(process.wait(), .5)
                except asyncio.TimeoutError:
                    with suppress(ProcessLookupError): os.killpg(process.pid, signal.SIGKILL)
                    await process.wait()
