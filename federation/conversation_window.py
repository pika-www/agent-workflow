"""Room dialogue accumulates until the model's working context needs compaction."""
import json
from .core import _sha, _write_json
from .memory_requirements import clean
from .context_extract import literal_excerpt, rank_originals, is_literal_projection

MARKER = '\n[上下文摘录；省略部分保留在原记录]\n'


class ConversationWindow:
    def __init__(self, memory):
        self.memory = memory

    def _path(self, room_id, agent_id):
        return self.memory._path(room_id, agent_id).with_name(agent_id + '.window.json')

    def _read(self, room_id, agent_id):
        path = self._path(room_id, agent_id)
        return json.loads(path.read_text()) if path.is_file() else {'revision': 0, 'compaction_count': 0, 'records': {}}

    def prepare(self, room, agent_id, round_id):
        with self.memory._locked(room['id'], agent_id) as (_, memory):
            state = self._read(room['id'], agent_id)
            forgotten = {mid for task in memory['tasks'] if task['status'] == 'forgotten' for mid in task['message_ids']}
            messages = []
            candidates = list(self.memory.messages(room, agent_id, round_id))
            question = next((m['content'] for m in reversed(room['messages']) if m.get('round_id') == round_id and m['role'] == 'user'), '')
            # Only previously compacted, permitted, non-forgotten originals can
            # be rehydrated. Each turn selects again against the current query.
            eligible = []
            for m in candidates:
                saved = state['records'].get(m['id'])
                if m['id'] in forgotten or not saved or saved.get('content') == clean(m['content']):
                    continue
                eligible.append({**m,'content':clean(m['content'])})
            ranked=rank_originals(eligible,question,k=6)
            recalled = {mid for _,_,mid in ranked}
            excerpt_limit = 5400 // max(3,len(recalled))
            for message in candidates:
                if message['id'] in forgotten:
                    continue
                source_hash = _sha(message['content'].encode())
                saved = state['records'].get(message['id'], {})
                content = saved.get('content') if saved.get('source_hash') == source_hash else clean(message['content'])
                if message['id'] in recalled:
                    content = literal_excerpt(clean(message['content']), excerpt_limit, question)
                if content is None:
                    continue
                messages.append({'id': message['id'], 'role': message['role'],
                                 'agent_name': message.get('agent_name', '你'), 'content': content,
                                 'source_hash': source_hash, 'rehydrated': message['id'] in recalled})
            usage = [entry for message in reversed(room['messages'])
                     if message.get('agent_id') == agent_id and message.get('status') == 'completed'
                     for entry in reversed((message.get('native_stream') or {}).get('usage', []))
                     if entry.get('status') == 'completed' and entry.get('counting_model_key')][:8]
            return {'room_id': room['id'], 'agent_id': agent_id, 'revision': state['revision'], 'usage': usage,
                    'memory_revision': memory['revision'], 'compaction_count': state['compaction_count'], 'messages': messages,
                    'recall': {'method': 'scoped-original-query', 'candidate_count': len(eligible), 'selected_ids': sorted(recalled), 'max_messages': 6, 'max_chars': 5400, 'per_message_chars':excerpt_limit}}

    def commit(self, room, prepared, update):
        if not prepared or not update:
            return {'status': 'unchanged'}
        with self.memory._locked(room['id'], prepared['agent_id']) as (_, memory):
            state = self._read(room['id'], prepared['agent_id'])
            if (prepared['room_id'] != room['id'] or prepared['revision'] != state['revision']
                    or prepared['memory_revision'] != memory['revision']):
                return {'status': 'stale'}
            old = {m['id']: m for m in prepared['messages']}
            current = {m['id']: m for m in room['messages']}
            records = update.get('messages', [])
            if (update.get('revision') != state['revision'] or not isinstance(records, list)
                    or len(records) != len(old) or {m.get('id') for m in records} != set(old)
                    or type(update.get('compactions')) is not int or not 1 <= update['compactions'] <= 40):
                return {'status': 'rejected'}
            changed = {}
            for record in records:
                original = old[record['id']]
                if original['id'] not in current or _sha(current[original['id']]['content'].encode()) != original['source_hash']:
                    return {'status': 'stale'}
                before, after = original['content'], record.get('content')
                if after == before:
                    continue
                if after is not None:
                    if not isinstance(after, str) or len(after) >= len(before):
                        return {'status': 'rejected'}
                    if not is_literal_projection(before, after):
                        return {'status': 'rejected'}
                changed[original['id']] = {'source_hash': original['source_hash'], 'content': after}
            if not changed:
                return {'status': 'unchanged'}
            state['records'].update(changed)
            state['revision'] += 1
            state['compaction_count'] += update['compactions']
            _write_json(self._path(room['id'], prepared['agent_id']), state)
            return {'status': 'saved', 'revision': state['revision'], 'compaction_count': state['compaction_count']}
