"""Conservative, source-linked requirement changes; never creates permissions."""
import re
import json
import calendar
from pathlib import Path
from .core import _sha

SPEC = json.loads(Path(__file__).with_name('requirement-rules.json').read_text())
LABELS = {rule['slot']: rule['label'] for rule in SPEC['rules']}
CHANGE = re.compile(SPEC['change'], re.I)
SUGGESTION = re.compile(SPEC['hypothetical'], re.I)
RULES = [(rule, re.compile(rule['pattern'], re.I)) for rule in SPEC['rules']]


def named_subjects(messages):
    """Explicit project names only; do not infer identity from model output."""
    names = set()
    for message in messages:
        if message.get('role') != 'user': continue
        for match in re.finditer(r'(?:^|[\s，,。；;：:\n])(?:关于|对于|另一个)?([\w\-\u3400-\u9fff]{1,24})项目', message['content']):
            name = match.group(1)
            if name not in {'这个', '那个', '当前', '本', '该', '新', '一个', '另一个', '我的', '其他', '其它'}:
                names.add(name)
    return names


def claim_subject(text, names, value=None):
    # Prefer the subject before the actual value: an exclusion such as
    # "南岬预算99000元，与岚桥无关" must not move the claim to 岚桥.
    before = text.split(value, 1)[0] if value and value in text else text
    found = [(before.rfind(name), name) for name in names if name in before]
    if not found: return None
    return max(found, key=lambda item: (item[0], len(item[1])))[1]


def clean(text):
    return re.sub(r'(?:sk[-_][A-Za-z0-9_-]{12,}|Bearer\s+\S+|(?:api[_ -]?key|密钥|密码)\s*[:：=]\s*\S+)', '[已隐藏私密配置]', text, flags=re.I)


def claims(text):
    """Known slots only; free prose remains available as ordinary user material."""
    result = []
    for sentence in re.split(r'(?<=[。！？；\n])', clean(text)):
        sentence = sentence.strip()
        if not sentence or SUGGESTION.search(sentence): continue
        found = []
        for rule, pattern in RULES:
            for match in pattern.finditer(sentence):
                if rule.get('negation') and re.search(r'不要|不能|禁止|别再|不再|不是|不$', sentence[max(0,match.start()-4):match.start()]): continue
                value = rule.get('value')
                if value is None:
                    value = match.group(1); mode = rule.get('normalize')
                    if mode == 'compact_lower': value = re.sub(r'\s+', '', value).lower()
                    elif mode == 'trim_lower': value = value.strip().lower()
                    elif mode == 'set': value = '/'.join(sorted(set(re.split(r'\s*(?:和|及|、|/)\s*',value.lower()))))
                    elif mode == 'date':
                        year,month,day = map(int,re.findall(r'\d+',value))
                        if not 1 <= month <= 12 or not 1 <= day <= calendar.monthrange(year,month)[1]: continue
                        value = f'{year:04}-{month:02}-{day:02}'
                    else: value = value.strip()
                start=max(sentence.rfind('，',0,match.start()),sentence.rfind(',',0,match.start()))+1
                ends=[i for i in (sentence.find('，',match.end()),sentence.find(',',match.end())) if i>=0]
                clause=sentence[start:min(ends) if ends else len(sentence)]
                found.append((rule['slot'],value,sentence,bool(CHANGE.search(clause))))
        corrected={item[0]:item for item in found if item[3]}
        result.extend(item[:3] for item in found if (item[0] not in corrected or item==corrected[item[0]]) and item[:3] not in result)
    return result


def is_correction(slot, value, text):
    return any(CHANGE.search(clause) and any(s==slot and v==value for s,v,_ in claims(clause)) for clause in re.split(r'[，,]',text))


def requirement_ledger(messages, resolutions=None):
    records = []
    identifiers=set()
    groups={}
    applied = set()
    subjects = named_subjects(messages)
    def apply_resolutions():
        for slot, saved in (resolutions or {}).items():
            history = saved if isinstance(saved, list) else [saved]
            for index, resolution in enumerate(history):
                if (slot,index) in applied: continue
                candidates = []
                group_key = None
                for key, values in groups.items():
                    possible = [item for items in values.values() for item in items]
                    if key[0] == slot and set(resolution.get('candidate_ids', [])) == {item['id'] for item in possible}:
                        candidates, group_key = possible, key
                        break
                if not candidates: continue
                for item in candidates:
                    if item['id'] == resolution['selected_id']:
                        item.update(status='active', resolution_origin='explicit_memory_management')
                    else:
                        item.update(status='superseded', replaced_by=resolution['selected_id'], reason='explicit_memory_management')
                selected=next((item for item in candidates if item['id']==resolution['selected_id']),None)
                groups[group_key]={selected['value']:[selected]} if selected else {}
                applied.add((slot,index))
    for message in messages:
        if message.get('role') != 'user': continue
        for slot, value, text in claims(message['content']):
            identifier = _sha((message['id'] + slot + value + text).encode())[:20]
            if identifier in identifiers: continue
            identifiers.add(identifier)
            subject = claim_subject(text, subjects, value)
            ambiguous_subject = False
            # Unnamed corrections can inherit a unique known subject for this
            # slot; multiple projects require clarification, never a mass overwrite.
            if subject is None:
                existing = {key[1] for key in groups if key[0] == slot}
                if len(existing) == 1: subject = next(iter(existing))
                elif len(existing) > 1: ambiguous_subject = True
            values=groups.setdefault((slot,subject),{})
            record = {'id': identifier, 'slot': slot, 'label': LABELS[slot], 'value': value, 'text': text,
                      'source_ids': [message['id']], 'status': 'active', 'origin': 'user_message'}
            if subject is not None: record['subject'] = subject
            if ambiguous_subject:
                record.update(status='conflict', reason='ambiguous_project_subject')
            if values and any(previous!=value for previous in values):
                if is_correction(slot,value,text):
                    for item in (item for items in values.values() for item in items):
                        item.update(status='superseded', replaced_by=identifier, reason='explicit_user_correction')
                    values.clear()
                else:
                    record['status'] = 'conflict'
                    for items in values.values():
                        if items[0]['status']!='conflict':
                            for item in items:item['status']='conflict'
            records.append(record)
            values.setdefault(value,[]).append(record)
            # Replay reviewed selections at the point their original candidates
            # become available; later input can conflict without resurrecting old choices.
            apply_resolutions()
    return {'records': records, 'active': [item for item in records if item['status'] == 'active'],
            'conflicts': [item for item in records if item['status'] == 'conflict'],
            'notice': '只标注已识别的用户要求；冲突需澄清，联网或删除要求仍受宿主权限检查。'}


def filter_summary(summary, ledger):
    """Exclude stale rule claims from prompts, while keeping persisted versions."""
    if not summary: return None
    current = {}
    for item in ledger.get('active', []):
        current.setdefault((item['slot'],item.get('subject')),set()).add(item['value'])
    conflicts = {(item['slot'],item.get('subject')) for item in ledger.get('conflicts', [])}
    subjects = {item['subject'] for item in ledger.get('records', []) if item.get('subject')}
    result = dict(summary)
    for field in ('constraints', 'decisions'):
        kept = []
        for item in summary.get(field, []):
            parsed = claims(item['text'])
            stale = False
            for slot, value, text in parsed:
                subject = claim_subject(text, subjects, value)
                keys = [(slot,subject)] if subject else [key for key in set(current) | conflicts if key[0] == slot]
                allowed = set().union(*(current.get(key,set()) for key in keys))
                if any(key in conflicts for key in keys) or (allowed and value not in allowed): stale = True
            if stale: continue
            kept.append(item)
        result[field] = kept
    return result


def summary_grounding_error(update, context, room_messages):
    """Catch known-slot contradiction, unsupported claims and invented completion."""
    sources = {message['id']: message for message in room_messages}
    for field in ('constraints', 'decisions', 'progress', 'open_questions'):
        for item in update.get(field, []):
            originals = [sources[i] for i in item['source_ids'] if i in sources]
            text = item['text']
            if field in {'constraints', 'decisions'}:
                source_claims = {(slot, value) for source in originals if source['role'] == 'user' for slot, value, _ in claims(source['content'])}
                parsed = {(slot, value) for slot, value, _ in claims(text)}
                if parsed - source_claims: return 'unsupported_requirement'
            if field == 'progress' and re.search(r'已(?:经)?(?:执行|完成|部署|发布|修复)', text) and not re.search(r'未|尚|没有|待|不代表|未核实', text):
                if not any(source['role'] == 'user' and re.search(r'已(?:经)?(?:执行|完成|部署|发布|修复)', source['content']) and not re.search(r'尚未|未执行|未完成|没有执行|待执行', source['content']) for source in originals):
                    return 'unsupported_completion'
    return None
