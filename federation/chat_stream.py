"""Reply previews and private stage journals; final validation remains separate."""
import json
import time
import re
import os
import hashlib
import uuid
from pathlib import Path
from datetime import datetime, timezone

PREFIX = 'OPENWIKI_REPLY '
UPDATE_PREFIX = 'OPENWIKI_UPDATE '
CHECKPOINT_PREFIX = 'OPENWIKI_CHECKPOINT '
AGENT_PREFIX = 'OPENWIKI_AGENT_EVENT '
MAX_REPLY_CHARS = 64000


class ReplyStreams:
    def __init__(self, root=None):
        self.replies = {}
        self.finished_native = {}
        self.root = Path(root) if root is not None else None
        if self.root:
            if self.root.is_symlink():
                raise ValueError('处理阶段目录不能是符号链接。')
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    @staticmethod
    def resumable(job):
        return (job.get('action') == 'chat' and job.get('intake_kind') == 'answer'
                and not re.search(r'完整问题.*预算|完整要求.*预算|必要规则仍超过|未获授权|401|403', str(job.get('error', '')))
                and not any(job.get(k) for k in ('parent_job_id', 'dispatch_confirmed', 'requested_agents', 'learning', 'social_data_only', 'social_status_only'))
                and not (job.get('execution_options') or {}).get('learning'))

    def _path(self, job_id):
        if self.root.is_symlink():
            raise ValueError('处理阶段目录不能是符号链接。')
        if not isinstance(job_id, str) or not re.fullmatch(r'[a-f0-9]{32}', job_id):
            raise ValueError('处理阶段标识无效。')
        target = self.root / (job_id + '.json')
        if target.is_symlink():
            raise ValueError('处理阶段文件不能是符号链接。')
        return target

    @staticmethod
    def _encoded(value):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')

    @staticmethod
    def _validate_checkpoint(value):
        if (not isinstance(value, dict) or value.get('schema_version') != 1
                or value.get('kind') not in {'consultation', 'report', 'native_agent'}
                or not isinstance(value.get('fingerprint'), str) or not re.fullmatch(r'[a-f0-9]{64}', value['fingerprint'])):
            raise ValueError('续接记录格式无效。')
        allowed = {'schema_version', 'kind', 'fingerprint', 'preliminary_reply'} if value['kind'] == 'consultation' else {
            'schema_version', 'kind', 'fingerprint', 'sections', 'prepared', 'initial_reply', 'sources', 'workflow',
            'calculation', 'ledger', 'reviewed_answer', 'reviewed_draft_sha256'}
        if value['kind'] == 'native_agent':
            allowed = {'schema_version', 'kind', 'fingerprint', 'protocol', 'input', 'turn_index', 'visible_count',
                       'answer', 'observations', 'receipts', 'message_items', 'usage', 'completed'}
        optional = {'context_compactions'} if value['kind'] == 'native_agent' else set()
        if set(value) - allowed - optional or len(ReplyStreams._encoded(value)) > 700000:
            raise ValueError('续接记录超出范围。')
        if value['kind'] == 'native_agent':
            if (set(value) - optional != allowed or value['protocol'] not in {'responses', 'chat_completions'}
                    or type(value['turn_index']) is not int or not 0 <= value['turn_index'] <= 34
                    or type(value['visible_count']) is not int or not 0 <= value['visible_count'] <= 32
                    or not isinstance(value['answer'], str) or len(value['answer']) > 64000
                    or type(value['completed']) is not bool):
                raise ValueError('原生Agent续接状态无效。')
            compactions = value.get('context_compactions', [])
            if not isinstance(compactions, list) or len(compactions) > 40:
                raise ValueError('上下文压缩记录无效。')
            for record in compactions:
                if (not isinstance(record, dict) or record.get('method') != 'extractive' or record.get('history_preserved') is not True
                        or set(record) - {'stage'} != {'method','history_preserved','before_tokens','after_tokens','budget_tokens','before_sha256','after_sha256'}
                        or ('stage' in record and record['stage'] != 'runtime')
                        or any(type(record.get(k)) is not int or not 0 < record[k] <= 10000000 for k in ('before_tokens','after_tokens','budget_tokens'))
                        or not record['after_tokens'] < record['before_tokens'] or record['after_tokens'] > record['budget_tokens']
                        or any(not re.fullmatch(r'[a-f0-9]{64}',str(record.get(k,''))) for k in ('before_sha256','after_sha256'))):
                    raise ValueError('上下文压缩记录无效。')
            for field, limit in [('input', 240), ('observations', 32), ('receipts', 32), ('message_items', 32), ('usage', 40)]:
                if not isinstance(value[field], list) or len(value[field]) > limit or any(not isinstance(v, dict) for v in value[field]):
                    raise ValueError('原生Agent续接列表无效。')
            for item in value['input']:
                if item.get('role') not in {'system', 'developer', 'user', 'assistant', 'tool'} and item.get('type') not in {'message', 'reasoning', 'function_call', 'function_call_output'}:
                    raise ValueError('原生Agent续接消息类型无效。')
                if item.get('phase') is not None and (item.get('role') != 'assistant' or item['phase'] not in {'commentary', 'final_answer'}):
                    raise ValueError('原生Agent续接消息phase无效。')
        elif value['kind'] == 'consultation':
            reply = value.get('preliminary_reply')
            if not isinstance(reply, dict) or not isinstance(reply.get('text'), str) or len(reply['text']) > 1800 or not isinstance(reply.get('receipt'), dict):
                raise ValueError('初答续接记录无效。')
        else:
            sections = value.get('sections')
            if not isinstance(sections, list) or len(sections) > 3:
                raise ValueError('报告续接章节无效。')
            for section in sections:
                if (not isinstance(section, dict) or set(section) != {'name', 'text', 'sha256'} or not isinstance(section['name'], str)
                        or not isinstance(section['text'], str) or len(section['text']) > 16000
                        or hashlib.sha256(section['text'].encode()).hexdigest() != section['sha256']):
                    raise ValueError('报告续接章节校验失败。')
            sources = value.get('sources', [])
            if not isinstance(sources, list) or len(sources) > 12 or any(not isinstance(s, dict)
                    or not isinstance(s.get('excerpt'), str) or len(s['excerpt']) > 6500
                    or not isinstance(s.get('url'), str) or not re.match(r'^https?://', s['url']) for s in sources):
                raise ValueError('报告续接来源无效。')
            for key, limit in [('initial_reply', 5000), ('reviewed_answer', 40000)]:
                if key in value and (not isinstance(value[key], str) or len(value[key]) > limit):
                    raise ValueError('报告续接正文超出范围。')

    def _persist(self, reply, force=False, active=True):
        if not self.root:
            return
        if not force and time.monotonic() - reply.get('_persisted', 0) < .5:
            return
        payload = {'schema_version': 1, 'room_id': reply['room_id'], 'job_id': reply['job_id'], 'active': active,
                   'saved_at': datetime.now(timezone.utc).isoformat(), 'preview': self.snapshot(reply['room_id'], reply['job_id']),
                   'checkpoint': reply.get('checkpoint'), 'processing_stage': reply.get('processing_stage')}
        encoded = self._encoded(payload)
        if len(encoded) > 1100000:
            raise ValueError('处理阶段记录超过长度上限。')
        data = self._encoded({'payload': payload, 'sha256': hashlib.sha256(encoded).hexdigest()})
        target = self._path(reply['job_id']); temp = self.root / ('.' + uuid.uuid4().hex + '.tmp')
        try:
            with temp.open('xb') as stream:
                os.chmod(temp, 0o600); stream.write(data); stream.flush(); os.fsync(stream.fileno())
            os.replace(temp, target)
            fd = os.open(self.root, os.O_RDONLY)
            try: os.fsync(fd)
            finally: os.close(fd)
            reply['_persisted'] = time.monotonic()
        finally:
            if temp.exists(): temp.unlink()

    def load_saved(self, job_id):
        if not self.root: return None
        try:
            target = self._path(job_id)
            if target.stat().st_size > 1101000: return None
            data = json.loads(target.read_text('utf-8')); payload = data['payload']
            if (hashlib.sha256(self._encoded(payload)).hexdigest() != data['sha256'] or payload.get('schema_version') != 1
                    or payload.get('job_id') != job_id or not re.fullmatch(r'[a-f0-9]{32}', payload.get('room_id', ''))):
                return None
            if payload.get('checkpoint'): self._validate_checkpoint(payload['checkpoint'])
            return payload
        except (OSError, ValueError, TypeError, KeyError): return None

    def checkpoint(self, room_id, job_id, value):
        reply = self.replies.get(room_id)
        if not reply or reply['job_id'] != job_id: return
        self._validate_checkpoint(value)
        reply['checkpoint'] = json.loads(self._encoded(value)); self._persist(reply, force=True)

    def progress(self, room_id, job_id, stage, detail):
        reply = self.replies.get(room_id)
        if not reply or reply['job_id'] != job_id: return
        value = {'stage': str(stage)[:80], 'detail': str(detail)[:300]}
        if reply.get('processing_stage') == value: return
        reply['processing_stage'] = value
        reply['revision'] += 1
        self._persist(reply, force=True)

    def recover(self, chat, load_job, append_message):
        if not self.root: return
        for path in self.root.glob('*.json'):
            saved = self.load_saved(path.stem)
            if not saved or not saved.get('active'): continue
            job = load_job(path.stem)
            if not job: continue
            try: room = chat.get_room(saved['room_id'])
            except (ValueError, FileNotFoundError): continue
            if job.get('room_id') != room['id']: continue
            existing = any(m.get('round_id') == job['id'] and m['role'] == 'assistant' and m.get('phase') == 'consultation'
                           and m.get('status') in {'completed', 'failed'} for m in room['messages'])
            if job.get('status') == 'failed' and not existing:
                preview = saved['preview'] or {}; partial = preview.get('text', '')[:58000]
                append_message(room, 'assistant', (partial + '\n\n以上内容未完成。' if partial else '') +
                               '上次处理被中断，已保留先发的回答与完成的阶段。', job['id'], 'consultation', status='failed',
                               interim_replies=preview.get('updates', []), acceptance_reply=preview.get('acknowledgement'),
                               operations=self.settled_operations(preview.get('operations', []), interrupted=True),
                               reply_timeline=preview.get('timeline', []),
                               processing_stage=saved.get('processing_stage'),
                               recoverable_job_id=job['id'] if self.resumable(job) and room.get('purpose') == 'primary' else None)
                chat.save_room(room)
            # Recovery is recorded once, with no automatic execution.
            saved['active'] = False
            encoded = self._encoded(saved)
            target = self._path(job['id']); temp = target.with_suffix('.recovered.tmp')
            if temp.is_symlink(): raise ValueError('恢复记录临时文件无效。')
            with temp.open('w', encoding='utf-8') as stream:
                os.chmod(temp, 0o600); json.dump({'payload': saved, 'sha256': hashlib.sha256(encoded).hexdigest()}, stream, ensure_ascii=False)
                stream.flush(); os.fsync(stream.fileno())
            os.replace(temp, target)

    def start(self, room_id, job_id, *, agent_id='central', agent_name='主 Agent', turn_id=None, received_at=None, acknowledgement=None, native_protocol=None):
        previous = self.replies.get(room_id)
        revision = previous['revision'] + 1 if previous and previous['job_id'] == job_id else 0
        self.replies[room_id] = {'room_id': room_id, 'job_id': job_id, 'agent_id': agent_id, 'agent_name': agent_name,
                                 'turn_id': turn_id, 'text': '', 'revision': revision,
                                 'started': time.monotonic(), 'first_text_ms': None,
                                 'received_at': received_at, 'request_first_text_ms': None,
                                 'acknowledgement': acknowledgement or (previous.get('acknowledgement') if previous and previous['job_id'] == job_id else None),
                                 'updates': previous.get('updates', []) if previous and previous['job_id'] == job_id
                                 and previous.get('turn_id') == turn_id else [], 'operations': [], 'timeline': [], 'native_seq': 0, '_native_events': [], 'native_protocol': native_protocol}
        if previous and previous['job_id'] == job_id:
            for key in ('checkpoint', 'processing_stage', 'native_seq', '_native_events', 'native_protocol'): self.replies[room_id][key] = previous.get(key)
            if previous['agent_id'] == agent_id and previous.get('turn_id') in {None, turn_id}:
                if previous.get('context_compaction'): self.replies[room_id]['context_compaction'] = dict(previous['context_compaction'])
                self.replies[room_id]['operations'] = [dict(item) for item in previous.get('operations', [])]
                self.replies[room_id]['timeline'] = json.loads(self._encoded(previous.get('timeline', [])))
        self._persist(self.replies[room_id], force=True)

    def update(self, room_id, job_id, event):
        reply = self.replies.get(room_id)
        if not reply or reply['job_id'] != job_id:
            return
        if (not isinstance(event, dict) or set(event) != {'id', 'title', 'text', 'status'}
                or not isinstance(event['id'], str) or not re.fullmatch(r'[a-z0-9-]{1,32}', event['id'])
                or not isinstance(event['title'], str) or not 1 <= len(event['title']) <= 100
                or not isinstance(event['text'], str) or '\0' in event['text']
                or not isinstance(event['status'], str) or event['status'] not in {'streaming', 'completed'}):
            raise ValueError('分段回复事件格式无效。')
        updates = reply['updates']
        if sum(len(item['text']) for item in updates) + len(event['text']) > 40000:
            raise ValueError('分段回复超过长度上限。')
        item = next((item for item in updates if item['id'] == event['id']), None)
        if item is None:
            if len(updates) >= 32:
                raise ValueError('分段回复数量超过上限。')
            item = {'id': event['id'], 'title': event['title'], 'text': '',
                    'created_at': datetime.now(timezone.utc).isoformat()}
            updates.append(item)
        elif item['title'] != event['title'] or item['status'] == 'completed':
            raise ValueError('分段回复已经结束或标题发生变化。')
        item['text'] += event['text']
        item['status'] = event['status']
        reply['revision'] += 1
        first = bool(event['text']) and reply['first_text_ms'] is None
        if event['text'] and reply['first_text_ms'] is None:
            self._first_text(reply)
        self._persist(reply, force=event['status'] == 'completed' or first)

    def _first_text(self, reply):
        reply['first_text_ms'] = round((time.monotonic() - reply['started']) * 1000)
        if reply.get('received_at'):
            try:
                received = datetime.fromisoformat(reply['received_at'])
                reply['request_first_text_ms'] = max(0, round((datetime.now(timezone.utc) - received).total_seconds() * 1000))
            except (TypeError, ValueError):
                pass

    def append(self, room_id, job_id, text):
        reply = self.replies.get(room_id)
        if not reply or reply['job_id'] != job_id:
            return
        if not isinstance(text, str) or '\0' in text or len(reply['text']) + len(text) > MAX_REPLY_CHARS:
            raise ValueError('流式回复无效或超过长度上限。')
        if text:
            first = reply['first_text_ms'] is None
            if reply['first_text_ms'] is None:
                self._first_text(reply)
            reply['text'] += text
            if reply.get('native_protocol') == 'chat_completions' and reply.get('updates'):
                last = reply['updates'][-1]
                if reply['text'] == last['text']:
                    for entry in reply.get('timeline', []):
                        if entry.get('source') == 'update' and entry.get('id') == last['id']:
                            entry.update(source='answer', id='answer')
            reply['revision'] += 1
            self._persist(reply, force=first)

    def accept_line(self, room_id, job_id, line):
        if line.startswith(AGENT_PREFIX):
            self.native_event(room_id, job_id, json.loads(line[len(AGENT_PREFIX):]))
            return True
        if line.startswith(CHECKPOINT_PREFIX):
            self.checkpoint(room_id, job_id, json.loads(line[len(CHECKPOINT_PREFIX):]))
            return True
        if line.startswith(UPDATE_PREFIX):
            self.update(room_id, job_id, json.loads(line[len(UPDATE_PREFIX):]))
            return True
        if not line.startswith(PREFIX):
            return False
        event = json.loads(line[len(PREFIX):])
        if not isinstance(event, dict) or set(event) != {'text'}:
            raise ValueError('流式回复事件格式无效。')
        self.append(room_id, job_id, event['text'])
        return True

    def native_event(self, room_id, job_id, event):
        reply = self.replies.get(room_id)
        if not reply or reply['job_id'] != job_id:
            return
        fields = {'origin', 'protocol', 'type', 'response_id', 'item_id', 'item_type', 'phase', 'call_id', 'name', 'update_id', 'delta', 'status', 'output_sha256', 'target', 'failure_detail', 'elapsed_ms', 'attempt', 'max_attempts', 'delay_ms', 'replace_ids', 'replace_answer'}
        provider_types = {'response.output_item.added', 'response.output_item.done', 'response.output_text.delta', 'response.completed', 'chat.completion.content.delta'}
        tool_types = {'agent.tool.started', 'agent.tool.completed'}
        transport_types = {'agent.transport.retrying', 'agent.transport.restored'}
        context_fields = {'before_tokens', 'after_tokens', 'budget_tokens'}
        fields |= context_fields | {'stage', 'retry_policy'}
        if (not isinstance(event, dict) or set(event) - fields or event.get('protocol') not in {'responses', 'chat_completions'}
                or not (event.get('origin') == 'provider' and event.get('type') in provider_types
                        or event.get('origin') == 'host_tool' and event.get('type') in tool_types
                        or event.get('origin') == 'host_transport' and event.get('type') in transport_types
                        or event.get('origin') == 'host_context' and event.get('type') == 'agent.context.compacted')):
            raise ValueError('原生Agent事件未获授权。')
        transport_fields = {'attempt', 'max_attempts', 'delay_ms', 'replace_ids', 'replace_answer', 'retry_policy'}
        for key in fields - {'phase', 'elapsed_ms'} - transport_fields - context_fields:
            if key in event and (not isinstance(event[key], str) or '\0' in event[key] or len(event[key]) > (4096 if key == 'delta' else 200)):
                raise ValueError('原生Agent事件字段无效。')
        if event.get('phase') not in {None, 'commentary', 'final_answer'}:
            raise ValueError('原生Agent消息phase无效。')
        if event['type'] == 'response.output_text.delta' and (event.get('phase') not in {'commentary', 'final_answer'} or not event.get('item_id') or 'delta' not in event):
            raise ValueError('原生Agent文本缺少对应消息。')
        if 'update_id' in event and not re.fullmatch(r'[a-z0-9-]{1,32}', event['update_id']):
            raise ValueError('原生Agent消息标识无效。')
        if event['origin'] == 'host_tool' and (event.get('name') not in {'server_files', 'wiki_search', 'web_read', 'web_search', 'research_review', 'visual_browser', 'profit_calculate', 'file_search','file_read','audio_transcribe','video_analyze', 'code_interpreter', 'image_analyze', 'image_generate', 'connector_search', 'connector_read', 'platform_tools', 'platform_read'} or not event.get('call_id')):
            raise ValueError('原生Agent工具未获授权。')
        if 'elapsed_ms' in event and (type(event['elapsed_ms']) is not int or not 0 <= event['elapsed_ms'] <= 86400000):
            raise ValueError('工具耗时无效。')
        if event['origin'] != 'host_tool' and {'target', 'failure_detail', 'elapsed_ms'} & set(event):
            raise ValueError('工具记录必须来自实际宿主执行。')
        if event['origin'] != 'host_transport' and transport_fields & set(event):
            raise ValueError('重连记录必须来自宿主传输。')
        if event['origin'] != 'host_context' and (context_fields | {'stage'}) & set(event):
            raise ValueError('压缩记录必须来自宿主上下文处理。')
        if event['origin'] == 'host_context':
            if (set(event) - {'stage'} != {'origin','protocol','type'} | context_fields
                    or ('stage' in event and event['stage'] != 'runtime')
                    or any(type(event.get(k)) is not int or not 0 < event[k] <= 10000000 for k in context_fields)
                    or not event['after_tokens'] < event['before_tokens'] or event['after_tokens'] > event['budget_tokens']):
                raise ValueError('上下文压缩事件无效。')
            reply['context_compaction'] = {k:event[k] for k in context_fields | {'stage'} if k in event}
        if event['origin'] == 'host_transport':
            waiting = event.get('retry_policy') == 'until_cancelled' and 'max_attempts' in event and event['max_attempts'] is None
            bounded = 'retry_policy' not in event and type(event.get('max_attempts')) is int and event['max_attempts'] == 5
            if (type(event.get('attempt')) is not int or not 1 <= event['attempt'] <= (9007199254740991 if waiting else 5)
                    or not (waiting or bounded)
                    or set(event) - ({'origin','protocol','type'} | transport_fields)):
                raise ValueError('重连次数或事件字段无效。')
            ids = event.get('replace_ids', [])
            if (not isinstance(ids, list) or len(ids) > 32 or any(not isinstance(value, str) or not re.fullmatch(r'[a-z0-9-]{1,32}', value) for value in ids)
                    or type(event.get('replace_answer', False)) is not bool
                    or type(event.get('delay_ms', 0)) is not int or not 0 <= event.get('delay_ms', 0) <= (30000 if waiting else 8000)):
                raise ValueError('重连替换范围无效。')
            retrying = event['type'] == 'agent.transport.retrying'
            reply['transport_retry'] = {'attempt':event['attempt'], 'max_attempts':event['max_attempts'],
                                        **({'retry_policy':'until_cancelled'} if waiting else {}), 'status':'retrying' if retrying else 'restored'}
            if retrying:
                # Remove only the interrupted provider response, retaining all
                # previously completed responses and actual tool receipts.
                reply['updates'] = [item for item in reply['updates'] if item['id'] not in ids]
                if event.get('replace_answer'): reply['text'] = ''
                reply['timeline'] = [entry for entry in reply.get('timeline', []) if not (entry.get('source') == 'update' and entry.get('id') in ids
                    or event.get('replace_answer') and entry.get('source') == 'answer')]
        if event['origin'] == 'host_tool':
            operations = reply.setdefault('operations', [])
            operation = next((item for item in operations if item['call_id'] == event['call_id']), None)
            if operation and operation['name'] != event['name']:
                raise ValueError('工具记录标识与名称不一致。')
            if operation is None:
                if len(operations) >= 32: raise ValueError('工具记录超过本轮上限。')
                operation = {'call_id': event['call_id'], 'name': event['name'], 'status': 'running'}
                operations.append(operation)
            if event.get('target'): operation['target'] = event['target']
            if event['type'] == 'agent.tool.started':
                operation.setdefault('started_at', datetime.now(timezone.utc).isoformat())
            else:
                operation.update(status=event.get('status') or 'unknown', finished_at=datetime.now(timezone.utc).isoformat())
                for key in ('elapsed_ms', 'output_sha256', 'failure_detail'):
                    if key in event: operation[key] = event[key]
            self._timeline_tool(reply, event['call_id'])
        elif event['type'] in {'response.output_text.delta', 'chat.completion.content.delta'} and event.get('delta'):
            source = 'answer' if event.get('phase') == 'final_answer' else 'update'
            identifier = 'answer' if source == 'answer' else event.get('update_id')
            if identifier: self._timeline_text(reply, source, identifier)
        reply['native_seq'] = (reply.get('native_seq') or 0) + 1
        reply['revision'] += 1
        reply['native_protocol'] = event['protocol']
        frame = {**event, 'job_id': job_id, 'agent_id': reply['agent_id'], 'agent_name': reply['agent_name'],
                 'turn_id': reply['turn_id'], 'seq': reply['native_seq'], 'revision': reply['revision']}
        queue = reply.setdefault('_native_events', [])
        queue.append(frame)
        # Raw deltas are an active transport buffer. Snapshots/journals hold the
        # canonical text and native checkpoint, never hidden reasoning events.
        if len(queue) > 2000:
            del queue[:len(queue)-2000]
        if event['origin'] in {'host_tool','host_transport','host_context'}: self._persist(reply, force=True)

    def native_events(self, room_id, job_id, after=0):
        reply = self.replies.get(room_id)
        if not reply or reply['job_id'] != job_id:
            reply = self.finished_native.get((room_id, job_id))
            if not reply:
                return []
        return [dict(event) for event in reply.get('_native_events', []) if event['seq'] > after]

    def snapshot(self, room_id, job_id):
        reply = self.replies.get(room_id)
        if reply and reply['job_id'] == job_id:
            result = {**{key: reply[key] for key in ('job_id', 'agent_id', 'agent_name', 'turn_id', 'text', 'revision', 'first_text_ms', 'request_first_text_ms')},
                    'updates': [dict(item) for item in reply['updates']],
                    'operations': [dict(item) for item in reply.get('operations', [])],
                    'timeline': json.loads(self._encoded(reply.get('timeline', [])))}
            if reply.get('processing_stage'):
                result['processing_stage'] = dict(reply['processing_stage'])
            if reply.get('native_protocol'):
                result.update(native_seq=reply.get('native_seq') or 0, native_protocol=reply['native_protocol'])
            if reply.get('acknowledgement'):
                result['acknowledgement'] = dict(reply['acknowledgement'])
            if reply.get('transport_retry'):
                result['transport_retry'] = dict(reply['transport_retry'])
            if reply.get('context_compaction'):
                result['context_compaction'] = dict(reply['context_compaction'])
            return result
        return None

    @staticmethod
    def settled_operations(operations, interrupted=False):
        # A started event is proof of an attempted call, not proof of completion.
        # Keep completed receipts and mark unfinished calls honestly on failure.
        return [{**item, 'status': 'interrupted' if interrupted else 'unknown'}
                if item.get('status') == 'running' else dict(item) for item in operations]

    @staticmethod
    def _timeline_text(reply, source, identifier):
        timeline = reply.setdefault('timeline', [])
        if any(item.get('kind') == 'text' and item.get('source') == source and item.get('id') == identifier for item in timeline): return
        if len(timeline) >= 32: raise ValueError('回复顺序记录超过上限。')
        timeline.append({'kind': 'text', 'source': source, 'id': identifier})

    @staticmethod
    def _timeline_tool(reply, call_id):
        timeline = reply.setdefault('timeline', [])
        if any(call_id in item.get('call_ids', []) for item in timeline): return
        if timeline and timeline[-1]['kind'] == 'tools': timeline[-1]['call_ids'].append(call_id)
        else:
            if len(timeline) >= 32: raise ValueError('回复顺序记录超过上限。')
            timeline.append({'kind': 'tools', 'id': 'tools-' + str(len(timeline)), 'call_ids': [call_id]})

    def clear(self, room_id, job_id):
        if self.snapshot(room_id, job_id) is not None:
            self._persist(self.replies[room_id], force=True, active=False)
            reply = self.replies[room_id]
            if reply.get('_native_events'):
                self.finished_native[(room_id, job_id)] = {'job_id': job_id, '_native_events': reply['_native_events']}
                while len(self.finished_native) > 8:
                    self.finished_native.pop(next(iter(self.finished_native)))
            self.replies.pop(room_id, None)


def sse_event(name, value):
    return 'event: ' + name + '\ndata: ' + json.dumps(value, ensure_ascii=False) + '\n\n'
