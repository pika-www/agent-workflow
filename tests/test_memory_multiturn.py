"""Fixed conversation regressions against actual persisted memory, not user data."""
import json
import uuid
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from federation.app import create_app
from federation.chat import ChatStore
from federation.context_memory import ContextMemory
from federation.core import FederationStore
from federation.memory_requirements import requirement_ledger, summary_grounding_error


@pytest.fixture
def conversation(tmp_path):
    store = FederationStore(tmp_path / 'data'); store.init()
    chat = ChatStore(store); room = chat.create_room('group', ['central', 'software-frontend'], '隔离多轮评估')
    return store, chat, room, ContextMemory(store)


def turn(chat, room, manager, question, agent='central'):
    rid = uuid.uuid4().hex
    chat.append_message(room, 'user', question, round_id=rid)
    context = manager.prepare(room, question, agent, rid)
    chat.append_message(room, 'assistant', '仅提供咨询；尚未执行。', agent_id=agent, phase='consultation', round_id=rid)
    manager.complete_turn(room, context, rid); chat.save_room(room)
    return context


def test_correction_survives_restart_and_later_followups(conversation):
    store, chat, room, manager = conversation
    first = turn(chat, room, manager, '心跳页面使用 Vue，必须保留原始聊天记录，不联网。')
    changed = turn(chat, room, manager, '改用 React，其他要求继续保留。')
    assert changed['task_id'] == first['task_id']
    active = {r['slot']: r['value'] for r in changed['requirement_state']['active']}
    assert active == {'framework': 'react', 'history': 'preserve', 'network': 'local_only'}
    assert any(r['value'] == 'vue' and r['status'] == 'superseded' for r in changed['requirement_state']['records'])
    restored = ContextMemory(store)
    for _ in range(12):
        followup = turn(chat, room, restored, '继续解释这个心跳页面。')
        assert {r['value'] for r in followup['requirement_state']['active'] if r['slot'] == 'framework'} == {'react'}
    assert len(room['messages']) == 28


def test_ambiguous_conflict_requires_explicit_resolution_and_new_changes_invalidate_it(conversation):
    _, chat, room, manager = conversation
    first = turn(chat, room, manager, '页面使用 Vue。')
    second = turn(chat, room, manager, '这个页面使用 React。')
    assert first['task_id'] == second['task_id']
    state = manager.view(room, 'central'); ledger = state['tasks'][0]['requirement_state']
    assert len(ledger['conflicts']) == 2
    chosen = next(r for r in ledger['conflicts'] if r['value'] == 'react')
    manager.edit(room['id'], 'central', first['task_id'], state['revision'], 'resolve', room=room, requirement_id=chosen['id'])
    result = turn(chat, room, manager, '继续这个页面。')
    assert not result['requirement_state']['conflicts']
    assert {r['value'] for r in result['requirement_state']['active']} == {'react'}
    newest = turn(chat, room, manager, '这个页面使用 Angular。')
    assert newest['task_id'] == first['task_id']
    assert newest['requirement_state']['conflicts']  # old selection cannot silently resolve new input
    assert {r['value'] for r in newest['requirement_state']['conflicts']} == {'react','angular'}
    state=manager.view(room,'central')
    chosen=next(r for r in state['tasks'][0]['requirement_state']['conflicts'] if r['value']=='angular')
    manager.edit(room['id'],'central',first['task_id'],state['revision'],'resolve',room=room,requirement_id=chosen['id'])
    final=turn(chat,room,manager,'继续这个页面。')
    assert {r['value'] for r in final['requirement_state']['active']} == {'angular'}


def test_summary_cannot_invent_rule_or_completion(conversation):
    _, chat, room, manager = conversation
    for i in range(10):turn(chat, room, manager, f'页面第{i}轮：使用 React，不联网；尚未部署。')
    context = manager.prepare(room, '继续这个页面。', round_id=uuid.uuid4().hex)
    assert context['summary_request']
    ids = [m['id'] for m in context['summary_request']['messages']]
    user_id = next(m['id'] for m in context['summary_request']['messages'] if m['role'] == 'user')
    summary = {'goal': context['goal'], 'constraints': [{'text': '使用 React，不联网。', 'source_ids': [user_id]}],
               'decisions': [], 'progress': [], 'open_questions': [], 'source_ids': ids}
    bad = deepcopy(summary); bad['constraints'][0]['text'] = '使用 Vue，允许联网。'
    assert manager.commit(room, context, bad)['reason'] == 'unsupported_requirement'
    bad = deepcopy(summary); bad['progress'] = [{'text': '已部署页面。', 'source_ids': [user_id]}]
    assert manager.commit(room, context, bad)['reason'] == 'unsupported_completion'
    assert manager.commit(room, context, summary)['status'] == 'saved'
    for i in range(10):turn(chat, room, manager, f'继续页面第{i}轮，必须保留原始聊天记录。')
    context = manager.prepare(room, '继续这个页面。', round_id=uuid.uuid4().hex)
    assert context['summary_request'] and context['summary']
    ids = list(dict.fromkeys(context['summary']['source_ids'] + [m['id'] for m in context['summary_request']['messages']]))
    next_summary = {**summary, 'source_ids': ids}
    assert manager.commit(room, context, next_summary)['status'] == 'saved'
    assert len(manager.inspect(room['id'], 'central')['tasks'][0]['versions']) == 2


@pytest.mark.parametrize('text', ['比如使用 Vue，有什么区别？', '如果改用 React 会怎样？', '是否允许联网？', '可以联网吗？', '改用 React 好吗？'])
def test_hypothetical_question_does_not_replace_requirements(text):
    ledger = requirement_ledger([{'id':'original','role':'user','content':'页面使用 Vue，不联网。'}, {'id':'question','role':'user','content':text}])
    assert {r['value'] for r in ledger['active']} == {'vue','local_only'}
    assert not ledger['conflicts']


def test_requirement_sources_hide_private_configuration(conversation):
    _, chat, room, manager = conversation
    fake_key = 'sk_test_only_12345678901234567890'
    context = turn(chat, room, manager, '页面使用 Vue，密钥：' + fake_key + ' 。必须保留原始聊天记录。')
    assert fake_key not in json.dumps(context, ensure_ascii=False)
    assert fake_key not in json.dumps(manager.view(room, 'central'), ensure_ascii=False)
    assert fake_key not in json.dumps(manager.inspect(room['id'], 'central'), ensure_ascii=False)
    assert '[已隐藏私密配置]' in json.dumps(context['requirement_state'], ensure_ascii=False)
    assert fake_key in room['messages'][0]['content']  # original chat is not rewritten
    with manager._locked(room['id'], 'central') as (path, state):
        state['tasks'][0]['terms'].append(fake_key)
        path.write_text(json.dumps(state))
    assert fake_key not in json.dumps(manager.view(room, 'central'), ensure_ascii=False)
    turn(chat, room, manager, '继续这个页面。')
    assert fake_key not in json.dumps(manager.inspect(room['id'], 'central'), ensure_ascii=False)


def test_manual_correction_pauses_summary_calls_until_removed(conversation):
    _, chat, room, manager = conversation
    initial = turn(chat, room, manager, '页面使用 React，不联网。')
    state = manager.inspect(room['id'], 'central')
    manager.edit(room['id'], 'central', initial['task_id'], state['revision'], 'correct_summary', '只有方案，尚未部署。')
    for i in range(12):
        context = turn(chat, room, manager, f'继续这个页面第{i}轮。')
        assert context['summary_request'] is None
    state = manager.inspect(room['id'], 'central')
    manager.edit(room['id'], 'central', initial['task_id'], state['revision'], 'clear_summary_correction')
    restored = turn(chat, room, manager, '继续这个页面。')
    assert restored['summary_request']
    assert restored['pending']  # unprocessed originals are still available


def test_alias_recall_keeps_topic_and_forgotten_boundaries(conversation):
    _,chat,room,manager=conversation
    login=turn(chat,room,manager,'登录入口使用React。')
    turn(chat,room,manager,'新话题：天气页面使用Vue。')
    recalled=turn(chat,room,manager,'账号认证入口用的是什么框架？')
    assert recalled['task_id']==login['task_id']
    assert {r['value'] for r in recalled['requirement_state']['active']}=={'react'}
    state=manager.inspect(room['id'],'central');manager.edit(room['id'],'central',login['task_id'],state['revision'],'forget')
    forgotten=turn(chat,room,manager,'账号认证入口用的是什么框架？')
    assert forgotten['task_id']!=login['task_id'] and not forgotten['requirement_state']['active']
    new=turn(chat,room,manager,'新话题：登录入口使用Angular。')
    assert {r['value'] for r in new['requirement_state']['active']}=={'angular'}


def test_topic_member_forget_and_manual_summary_boundaries(conversation):
    store, chat, room, manager = conversation
    original = turn(chat, room, manager, '页面使用 Vue，不联网。')
    state=manager.inspect(room['id'],'central')
    manager.edit(room['id'],'central',original['task_id'],state['revision'],'correct_summary','实际只有方案，尚未部署。')
    followup=turn(chat,room,ContextMemory(store),'继续这个页面。')
    assert followup['manual_summary']['text']=='实际只有方案，尚未部署。'
    member=turn(chat,room,manager,'新话题：页面使用 Angular。','software-frontend')
    assert {r['value'] for r in member['requirement_state']['active']}=={'angular'}
    other=turn(chat,room,manager,'新话题：讨论抖音热点。')
    assert other['task_id']!=original['task_id'] and not other['requirement_state']['records']
    state=manager.inspect(room['id'],'central')
    manager.edit(room['id'],'central',original['task_id'],state['revision'],'forget')
    assert not turn(chat,room,manager,'页面使用 Vue。')['manual_summary']


def test_sources_conflict_actions_and_busy_guards(tmp_path):
    app=create_app(base=tmp_path/'data')
    with TestClient(app) as client:
        room=app.state.chat.create_room('direct',['central'],'来源隔离')
        # Use the real store and manager; no model or remote router is called.
        manager=ContextMemory(app.state.store)
        ctx=turn(app.state.chat,room,manager,'页面使用 Vue。')
        turn(app.state.chat,room,manager,'这个页面使用 React。')
        state=client.get(f"/api/chat/rooms/{room['id']}/context-memory").json()
        source_id=state['tasks'][0]['message_ids'][0]
        source=client.get(f"/api/chat/rooms/{room['id']}/context-memory/sources/{source_id}")
        assert source.status_code==200 and 'Vue' in source.json()['content']
        assert client.get(f"/api/chat/rooms/{room['id']}/context-memory/sources/missing").status_code==404
        assert client.get(f"/api/chat/rooms/{room['id']}/context-memory/sources/{source_id}?agent_id=software").status_code==400
        selected=next(r for r in state['tasks'][0]['requirement_state']['conflicts'] if r['value']=='react')
        payload={'task_id':ctx['task_id'],'expected_revision':state['revision'],'action':'resolve','requirement_id':selected['id']}
        assert client.post(f"/api/chat/rooms/{room['id']}/context-memory",json=payload).status_code==200
        assert client.post(f"/api/chat/rooms/{room['id']}/context-memory",json=payload).status_code==400
        state=client.get(f"/api/chat/rooms/{room['id']}/context-memory").json()
        room.update(status='running',active_job_id=uuid.uuid4().hex);app.state.chat.save_room(room)
        payload.update(expected_revision=state['revision'],action='archive')
        assert client.post(f"/api/chat/rooms/{room['id']}/context-memory",json=payload).status_code==409
