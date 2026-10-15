"""Exact read-only questions answered from host-confirmed task requirements."""
import json
import re
from pathlib import Path
from .memory_requirements import clean

SPEC = json.loads(Path(__file__).with_name('memory-read-queries.json').read_text())


def memory_read_slots(question):
    if not isinstance(question, str) or len(question) > 500: return None
    text = re.sub(r'^@[^\s]+\s+', '', question.strip())
    text = re.sub(r'\s+', '', text).strip('，,。！？?!')
    text = re.sub(r'^继续[，,]', '', text)
    text = re.sub(r'[，,](?:不推测执行状态|只复述已确认要求|不要推测执行状态)$', '', text)
    if re.fullmatch(SPEC['all'], text): return list(SPEC['slots'])
    if not re.fullmatch(SPEC['specific'], text): return None
    # Longest terms first prevent "框架版本" from becoming a framework query.
    tokens = {token:slot for slot,pattern in SPEC['slots'].items() for token in pattern.split('|')}
    found = {tokens[m.group()] for m in re.finditer('|'.join(re.escape(t) for t in sorted(tokens,key=len,reverse=True)),text)}
    return [slot for slot in SPEC['slots'] if slot in found]


def memory_read_answer(question, memory):
    slots = memory_read_slots(question)
    if slots is None or not isinstance(memory, dict): return None
    state = memory.get('requirement_state') or {}
    subjects = {r.get('subject') for r in [*(state.get('active') or []), *(state.get('conflicts') or [])] if r.get('slot') in slots}
    # A single-slot shortcut cannot choose a project. Let the normal contextual
    # path disambiguate instead of presenting unrelated projects as a conflict.
    if len(subjects) > 1: return None
    groups = {slot: [] for slot in slots}
    for record in [*(state.get('active') or []), *(state.get('conflicts') or [])]:
        slot = record.get('slot'); value = record.get('value')
        if record.get('origin') != 'host_policy' and slot in groups and isinstance(value, str) and len(value) <= 200:
            if not any(r['value'] == value for r in groups[slot]): groups[slot].append(record)
    conflicts = [slot for slot, records in groups.items() if len(records) > 1 or any(r.get('status') == 'conflict' for r in records)]
    display = lambda r:clean(SPEC['display'].get(r['value'], r['value']))
    if conflicts:
        detail = '；'.join(SPEC['labels'][slot]+'有“'+'”与“'.join(display(r) for r in groups[slot])+'”的未解决冲突' for slot in conflicts)
        answer = detail+'。请先确认采用哪条要求，可以在“记忆”中选择。'
    else:
        confirmed = [SPEC['labels'][slot]+'为 '+display(records[0]) for slot,records in groups.items() if records]
        missing = [SPEC['labels'][slot] for slot,records in groups.items() if not records]
        all_query = len(slots) == len(SPEC['slots'])
        answer = ('你当前确认的要求是：'+'；'.join(confirmed)+'。') if confirmed else ('当前任务还没有可用的已确认要求。' if all_query else '')
        if missing and not all_query: answer += '当前没有已确认的'+ '、'.join(missing)+'要求。'
    sources = list(dict.fromkeys(s for records in groups.values() for r in records for s in r.get('source_ids',[]) if isinstance(s,str)))
    return {'answer':answer,'response_origin':'host_memory_read','provider':'host','model':None,'engine':'宿主任务记忆',
            'memory_read':{'slots':slots,'source_ids':sources,'basis':'confirmed_user_requirements','conflicts':bool(conflicts)},
            'context_usage':{'enabled':True,'task_id':memory.get('task_id'),'project_id':(memory.get('project_memory') or {}).get('id'),
              'input_tokens_estimated':0,'total_input_tokens_estimated':0,'total_calls':0,'total_input_tokens':0,'total_output_tokens':0,
              'reply':{'input_tokens':0,'output_tokens':0,'cached_tokens':0},'summary':{'status':'not_needed','calls':0,'input_tokens':0,'output_tokens':0},
              'included':[{'key':'requirement_state','tokens':0,'reason':'host_memory_read_no_model'}],'omitted':[],'personal_omitted':[]},
            'timing':{'model_ms':0,'first_text_ms':0,'chunks':0,'input_chars':0},'model_usage':[],'usage_collected':True}
