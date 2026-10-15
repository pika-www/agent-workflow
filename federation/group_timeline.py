"""Persist live hierarchy handoffs and real member replies in one room timeline.

Host lifecycle events are explicitly system messages. Only a completed/partially
completed task's actual result becomes that member's assistant message. This
module never invokes an Agent or backfills an old, unenabled delegation round.
"""
from __future__ import annotations

import copy
import json
import uuid

from .core import _now
from .skill_context import skill_receipt
from .template_context import template_receipt

SCHEMA_VERSION = 1
EVENT_KINDS = {'group_started', 'member_joined', 'delegation', 'work_started', 'result', 'error'}
HOST_CONTENT_LIMIT = 6000
RESULT_CONTENT_LIMIT = 60000
MAX_EVENTS_PER_ROUND = 128  # Existing orchestration is bounded to 16 tasks.
RECEIPT_BYTE_LIMIT = 96000
RECEIPT_ITEM_LIMIT = 128
RECEIPT_FIELDS = (
    'wiki_reads', 'wiki_citation_check', 'wiki_citation_checks',
    'template_reads', 'template_selection', 'template_notices',
    'skill_reads', 'skill_selection', 'skill_notices', 'web_learning',
)


def _event_key(round_id, task_id, kind, phase=None):
    return 'gt1:' + round_id + ':' + task_id + ':' + kind + (':' + phase if kind == 'work_started' else '')


def _clip(text, limit, marker='\n[完整内容保留在任务详情中]'):
    if len(text) <= limit:
        return text
    return text[:limit - len(marker)] + marker


def _result_text(task):
    text = task.get('result') or ''
    # Strip only a host-generated suffix that can be reconstructed exactly from
    # this same task's receipts. Quoted headings or model prose are never stripped.
    try:
        suffix = template_receipt(task) + skill_receipt(task)
    except (KeyError, TypeError, ValueError):
        suffix = ''
    if suffix and text.endswith(suffix) and text[:-len(suffix)].strip():
        text = text[:-len(suffix)]
    return _clip(text, RESULT_CONTENT_LIMIT)


def _encoded_bytes(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8'))


def _receipt_copy(task):
    """Copy JSON evidence without inventing truncated entries or hashes."""
    result, omitted = {}, []
    for field in RECEIPT_FIELDS:
        value = task.get(field)
        if value is None:
            continue
        try:
            value = json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
            if isinstance(value, list):
                kept = []
                for item in value[:RECEIPT_ITEM_LIMIT]:
                    if _encoded_bytes({**result, field: kept + [item]}) > RECEIPT_BYTE_LIMIT:
                        break
                    kept.append(item)
                result[field] = kept
                if len(kept) != len(value):
                    omitted.append({'field': field, 'total_items': len(value), 'copied_items': len(kept)})
            elif _encoded_bytes({**result, field: value}) <= RECEIPT_BYTE_LIMIT:
                result[field] = value
            else:
                omitted.append({'field': field, 'reason': 'receipt_size_limit'})
        except (TypeError, ValueError, OverflowError):
            omitted.append({'field': field, 'reason': 'invalid_json_receipt'})
    if omitted:
        result['receipt_truncation'] = omitted
        result['receipt_notice'] = '部分读取回执超过群聊展示上限；完整回执保留在对应任务详情。'
    return result


def _message(room, task, parent, kind, content, phase=None):
    is_result = kind == 'result'
    parent_agent = parent.get('agent_id') if parent else None
    actor = parent_agent if kind in {'delegation', 'member_joined'} else task['agent_id']
    key = _event_key(task['round_id'], task['id'], kind, phase)
    message = {
        'id': uuid.uuid5(uuid.NAMESPACE_URL, 'openwiki-group-timeline:' + room['id'] + ':' + key).hex,
        'role': 'assistant' if is_result else 'system',
        'agent_id': task['agent_id'] if is_result else None,
        'agent_name': task['agent_name'] if is_result else '系统调度',
        'content': content, 'status': 'failed' if kind == 'error' or (is_result and task['status'] == 'failed') else 'completed',
        'created_at': _now(), 'phase': phase or task['phase'],
        'round_id': task['round_id'], 'delegation_task_id': task['id'],
        'parent_task_id': task.get('parent_task_id'), 'parent_agent_id': parent_agent,
        'actor_agent_id': actor, 'recipient_agent_id': parent_agent if is_result else task['agent_id'],
        'event_key': key, 'event_kind': kind, 'event_origin': 'agent' if is_result else 'host',
    }
    if is_result:
        message['result_scope'] = 'partial' if task['status'] == 'failed' else 'complete'
        message.update(_receipt_copy(task))
    return message


def _events(room, task, parent):
    if parent:
        text = f"{parent['agent_name']} 已将任务分派给 {task['agent_name']}。\n\n任务：{task['instruction']}"
        yield _message(room, task, parent, 'delegation', _clip(text, HOST_CONTENT_LIMIT))
    if task['status'] == 'running':
        planning = '正在分析任务并选择模块' if task['agent_id'] == 'central' else '正在安排专业成员'
        action = {'plan': planning, 'execute': '开始处理任务', 'summary': '开始汇总直属成员的结果',
                  'review': '开始检查结果完整性'}[task['phase']]
        yield _message(room, task, parent, 'work_started', task['agent_name'] + ' ' + action + '。（系统执行状态）', task['phase'])
    if task['status'] in {'completed', 'failed'} and parent and task.get('result'):
        yield _message(room, task, parent, 'result', _result_text(task))
    if task['status'] == 'failed':
        detail = task.get('error') or '该任务未完整完成，请查看任务详情。'
        text = task['agent_name'] + ' 的任务未完整完成。\n原因：' + detail
        if parent and task.get('result'):
            text += '\n已保留该成员返回的部分结果，不能视为任务全部完成。'
        yield _message(room, task, parent, 'error', _clip(text, HOST_CONTENT_LIMIT))


def sync_group_timeline(chat, room, round_id):
    """Persist this live round's task state and newly observable group messages.

    Caller: invoke at every orchestration persist after active_job_id is set.
    A new round enables only at its first root-only queued state. Existing rounds
    with a persisted marker deduplicate by stable keys across polling/restarts;
    an old round without a marker is a strict no-op, including its room file.
    """
    chat._identifier(round_id)
    if room.get('mode') != 'orchestrated':
        return []
    with chat._lock:
        tasks = [task for task in room.get('delegations', []) if task.get('round_id') == round_id]
        timeline = room.get('group_timeline')
        if timeline is not None and (not isinstance(timeline, dict) or timeline.get('schema_version') != SCHEMA_VERSION or not isinstance(timeline.get('rounds'), dict)):
            raise ValueError('群聊事件登记格式无效。')
        rounds = timeline.get('rounds', {}) if timeline else {}
        marker = rounds.get(round_id)
        if marker is not None and room.get('active_job_id') != round_id:
            return []
        if marker is None:
            if not (len(tasks) == 1 and tasks[0].get('parent_task_id') is None and
                    tasks[0].get('agent_id') == 'central' and tasks[0].get('status') == 'queued' and
                    not tasks[0].get('result') and room.get('active_job_id') == round_id and
                    room.get('status') in {'queued', 'running'}):
                return []
        # Validate before deriving messages so no malformed parent/speaker can
        # cause a partially persisted or falsely attributed timeline event.
        chat._validate(room)
        previous_timeline = copy.deepcopy(timeline)
        previous_groups = copy.deepcopy(room.get('task_groups'))
        previous_current_group = room.get('current_task_group_id')
        previous_updated = room.get('updated_at')
        message_count = len(room['messages'])
        if timeline is None:
            timeline = {'schema_version': SCHEMA_VERSION, 'rounds': {}}
            room['group_timeline'] = timeline
        if marker is None:
            marker = {'enabled_at': _now(), 'root_task_id': tasks[0]['id'], 'event_keys': [], 'task_group_schema_version': 1}
            timeline['rounds'][round_id] = marker
        if (not isinstance(marker, dict) or not isinstance(marker.get('event_keys'), list) or
                not all(isinstance(key, str) for key in marker.get('event_keys', []))):
            raise ValueError('本轮群聊事件登记无效。')
        known = set(marker['event_keys'])
        # Reading message keys also protects a room whose marker was restored
        # from an older snapshot, without replaying any existing message.
        known.update(message.get('event_key') for message in room['messages']
                     if message.get('round_id') == round_id and message.get('event_key'))
        by_id = {task['id']: task for task in tasks}
        added = []

        def emit(message):
            key = message['event_key']
            if key in known:
                return
            if len(known) >= MAX_EVENTS_PER_ROUND:
                marker['notice'] = '群聊事件达到展示上限；完整状态与结果保留在任务详情。'
                return
            room['messages'].append(message)
            added.append(message)
            known.add(key)

        try:
            group = None
            if marker.get('task_group_schema_version') == 1:
                groups = room.setdefault('task_groups', [])
                group = next((item for item in groups if item['id'] == round_id), None)
                root_task = by_id[marker['root_task_id']]
                if group is None:
                    group = {'id': round_id, 'round_id': round_id,
                             'title': root_task['instruction'].strip().splitlines()[0][:100],
                             'status': root_task['status'], 'members': ['central'],
                             'created_at': root_task['created_at'], 'updated_at': _now()}
                    approved = next((proposal for proposal in room.get('proposals', []) if
                                     proposal.get('status') == 'confirmed' and proposal.get('confirmed_job_id') == round_id), None)
                    if approved:
                        group['proposal_id'] = approved['id']
                    groups.append(group)
                group['status'] = root_task['status']
                group['updated_at'] = _now()
                room['current_task_group_id'] = round_id
                emit(_message(room, root_task, None, 'group_started', '主 Agent 正在组建任务群。'))
            for task in tasks:
                parent = by_id.get(task.get('parent_task_id'))
                if group is not None and parent and task['agent_id'] not in group['members']:
                    group['members'].append(task['agent_id'])
                    joined = _message(room, task, parent, 'member_joined',
                                      parent['agent_name'] + ' 已将 ' + task['agent_name'] + ' 加入本轮任务群。（系统成员记录）')
                    emit(joined)
                for message in _events(room, task, parent):
                    emit(message)
            marker['event_keys'] = sorted(known)
            # Task changes and keys/messages are committed together in one atomic
            # room replacement, including persists with no new visible events.
            chat.save_room(room)
        except BaseException:
            del room['messages'][message_count:]
            if previous_timeline is None:
                room.pop('group_timeline', None)
            else:
                room['group_timeline'] = previous_timeline
            if previous_groups is None:
                room.pop('task_groups', None)
            else:
                room['task_groups'] = previous_groups
            if previous_current_group is None:
                room.pop('current_task_group_id', None)
            else:
                room['current_task_group_id'] = previous_current_group
            room['updated_at'] = previous_updated
            raise
        return added
