import json
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from federation.app import create_app, isolated_ask_environment
from federation.chat import ChatStore
from federation.context_memory import ContextMemory, select_personal_memory
from federation.core import FederationStore
from federation.knowledge_lifecycle import remember, user_memory
from federation.agent_templates import initialize_standards


@pytest.fixture
def setup():
    with tempfile.TemporaryDirectory() as root:
        store = FederationStore(Path(root) / 'data'); store.init()
        chat = ChatStore(store)
        room = chat.create_room('direct', ['central'], '上下文隔离测试')
        yield store, chat, room, ContextMemory(store)


def add(chat, room, text, role='user', agent='central', status='completed'):
    message = chat.append_message(room, role, text, agent_id=agent if role == 'assistant' else None,
                                  phase='consultation', round_id=uuid.uuid4().hex, status=status)
    chat.save_room(room)
    return message


def long_history(chat, room):
    for i in range(12):
        add(chat, room, f'心跳界面第{i}轮：依据真实回复字符跳动，必须保留历史，不联网。')
        add(chat, room, f'心跳界面第{i}轮建议，尚未执行修改。', 'assistant')


def test_native_config_path_is_canonical_and_symlink_parent_rejected(setup,tmp_path):
    store,_,_,_=setup
    initialize_standards(store)
    job={'id':uuid.uuid4().hex,'space':'central','action':'ask','question':'只复述记录。','delegation_phase':'consultation'}
    environment=isolated_ask_environment(store,job)
    assert Path(environment['OPENWIKI_CONFIG_DIR'])==Path(environment['OPENWIKI_CONFIG_DIR']).resolve()
    parent=store.base/'ask-runs';outside=tmp_path/'outside';outside.mkdir()
    (parent/'blocked').symlink_to(outside,target_is_directory=True)
    with pytest.raises(ValueError,match='符号链接'):
        isolated_ask_environment(store,{**job,'id':'blocked'})


def test_many_summary_updates_keep_coverage_without_growing_prompt_ids(setup):
    _,chat,room,memory=setup
    for i in range(200):
        chat.append_message(room,'user',f'页面讨论第{i}轮。',round_id=uuid.uuid4().hex)
    chat.save_room(room)
    for _ in range(20):
        context=memory.prepare(room,'继续这个页面。',round_id=uuid.uuid4().hex)
        request=context['summary_request'];assert request
        ids=list(dict.fromkeys((request['previous'] or {}).get('source_ids',[])+[m['id'] for m in request['messages']]))
        update={'goal':context['goal'],'constraints':[],'decisions':[],'progress':[],'open_questions':[],'source_ids':ids}
        assert memory.commit(room,context,update)['status']=='saved'
        task=memory.inspect(room['id'],'central')['tasks'][0]
        assert len(task['summary']['source_ids'])<=8
    assert len(task['covered_ids'])==160
    assert len(task['message_ids'])==200


def summary(context):
    ids = [m['id'] for m in context['summary_request']['messages']]
    return {'goal': '心跳界面调整', 'constraints': [{'text': '用户要求保留历史，不联网。', 'source_ids': [ids[0]]}],
            'decisions': [], 'progress': [], 'open_questions': [], 'source_ids': ids}


def test_summary_bootstrap_sources_originals_and_restart(setup):
    store, chat, room, manager = setup
    long_history(chat, room)
    raw = (chat.root / (room['id'] + '.json')).read_bytes()
    context = manager.prepare(room, '心跳界面继续调整', round_id=uuid.uuid4().hex)
    assert len(context['recent']) == 8 and len(context['recall']) <= 3
    assert context['requirements'] and context['summary_request']
    assert manager.commit(room, context, summary(context))['status'] == 'saved'
    restored = ContextMemory(store).inspect(room['id'], 'central')
    assert restored['tasks'][0]['summary']['constraints'][0]['source_ids']
    assert restored['tasks'][0]['covered_ids']
    assert (chat.root / (room['id'] + '.json')).read_bytes() == raw


def test_stale_update_and_edited_sources_cannot_overwrite(setup):
    _, chat, room, manager = setup
    long_history(chat, room)
    context = manager.prepare(room, '心跳界面', round_id=uuid.uuid4().hex)
    newer = manager.prepare(room, '继续心跳界面', round_id=uuid.uuid4().hex)
    assert manager.commit(room, context, summary(context))['status'] == 'stale'
    room['messages'][0]['content'] += '已修正'
    assert manager.commit(room, newer, summary(newer))['reason'] == 'source_changed'


def test_failed_summary_does_not_retry_the_same_batch_each_turn(setup):
    _, chat, room, manager = setup
    long_history(chat, room)
    context = manager.prepare(room, '心跳界面', round_id=uuid.uuid4().hex)
    manager.record_summary_attempt(context, {'status':'failed_using_previous_and_originals','reason':'invalid_json'})
    next_context = manager.prepare(room, '继续心跳界面', round_id=uuid.uuid4().hex)
    assert next_context['summary_request'] is None and next_context['summary_cooldown']
    assert next_context['pending']
    retried = manager.prepare(room, '重新生成摘要', round_id=uuid.uuid4().hex)
    assert retried['task_id'] == context['task_id'] and retried['summary_request']


@pytest.mark.parametrize('bad', [None, 'not-an-array', [{}], ['invented-id']])
def test_invalid_worker_sources_rejected(setup, bad):
    _, chat, room, manager = setup
    long_history(chat, room)
    context = manager.prepare(room, '心跳界面', round_id=uuid.uuid4().hex)
    value = summary(context); value['source_ids'] = bad
    assert manager.commit(room, context, value)['status'] == 'rejected'


def test_new_topic_agent_room_and_failed_reply_isolation(setup):
    store, chat, room, manager = setup
    long_history(chat, room)
    add(chat, room, 'PRIVATE_FAILED_REPLY 心跳', 'assistant', status='failed')
    context = manager.prepare(room, '心跳界面', round_id=uuid.uuid4().hex)
    assert 'PRIVATE_FAILED_REPLY' not in json.dumps(context)
    other = manager.prepare(room, '新话题：讨论抖音热点采集', round_id=uuid.uuid4().hex)
    assert other['task_id'] != context['task_id'] and not other['recent'] and not other['requirements']
    new_room = chat.create_room('direct', ['central'], '另一个房间')
    assert not manager.prepare(new_room, '心跳界面', round_id=uuid.uuid4().hex)['recent']
    member = manager.prepare(room, '心跳界面', 'software-frontend', uuid.uuid4().hex)
    assert member['agent_id'] == 'software-frontend'
    assert manager.inspect(room['id'], 'central')['tasks'][0]['summary'] is None


def test_conversational_followups_keep_recent_dialogue_and_explicit_topic_reset(setup):
    _, chat, room, manager = setup
    original = add(chat, room, '我每天收藏一堆文章，最后都没看。你觉得问题出在哪？')
    context = manager.prepare(room, original['content'], round_id=original['round_id'])
    task_id = context['task_id']
    for question in ['说简单点，我今晚该干什么？', '好的', '再短一点', '没明白', '然后呢？']:
        answer = add(chat, room, '今晚挑一篇和手头问题相关的文章，读完写下一句话。', 'assistant')
        manager.complete_turn(room, context, answer['round_id'])
        current = add(chat, room, question)
        context = manager.prepare(room, question, round_id=current['round_id'])
        assert context['task_id'] == task_id
        assert context['goal'] == original['content']
        assert context['recent'][-1]['id'] == answer['id']
    current = add(chat, room, '换个话题，讲简单点：烤面包怎么做？')
    changed = manager.prepare(room, current['content'], round_id=current['round_id'])
    assert changed['task_id'] != task_id
    assert not changed['recent']


def test_late_constraints_are_not_first_550_character_clipped(setup):
    _, chat, room, manager = setup
    add(chat, room, '心跳界面：' + '背景信息。' * 250 + '必须保留尾部要求 MARKER_TAIL，不联网。')
    result = manager.prepare(room, '继续心跳界面', round_id=uuid.uuid4().hex)
    assert 'MARKER_TAIL' in json.dumps(result, ensure_ascii=False)


def test_edit_forget_and_revision_tombstone(setup):
    _, chat, room, manager = setup
    long_history(chat, room)
    context = manager.prepare(room, '心跳界面', round_id=uuid.uuid4().hex)
    manager.edit(room['id'], 'central', context['task_id'], context['revision'], 'update', '心跳界面：改为绿色曲线')
    with pytest.raises(ValueError, match='版本'):
        manager.edit(room['id'], 'central', context['task_id'], context['revision'], 'forget')
    state = manager.inspect(room['id'], 'central')
    manager.edit(room['id'], 'central', context['task_id'], state['revision'], 'forget')
    forgotten = manager.inspect(room['id'], 'central')
    with pytest.raises(ValueError, match='已忘记'):
        manager.edit(room['id'], 'central', context['task_id'], forgotten['revision'], 'update', '恢复旧目标')
    new = manager.prepare(room, '心跳界面', round_id=uuid.uuid4().hex)
    assert not new['recent'] and not new['requirements']
    assert len(room['messages']) == 24


def test_personal_memory_relevance_scope_expiry_versions_and_forget(setup):
    store, _, _, _ = setup
    reply = remember(store, '回复用中文，直接表达')
    remember(store, '心跳界面采用青色', scope='software-frontend')
    remember(store, '抖音热点今天优先', expires_at='2020-01-01T00:00:00+00:00')
    remember(store, '只讨论微信小程序')
    picked = select_personal_memory(user_memory(store), '心跳界面', 'central')
    assert len(picked['entries']) == 1
    assert {o['reason'] for o in picked['omitted']} == {'scope', 'expired', 'unrelated'}
    remember(store, '回复用中文，语气温和', memory_id=reply['key'], expected_revision=1)
    entry = user_memory(store)['preferences'][reply['key']]
    assert entry['revision'] == 2 and entry['versions'][0]['text'] == '回复用中文，直接表达'
    with pytest.raises(ValueError, match='版本'):
        remember(store, '再次修正', memory_id=reply['key'], expected_revision=1)
    remember(store, '回复用中文，语气温和', forget=True, memory_id=reply['key'], expected_revision=2)
    assert reply['key'] not in user_memory(store)['preferences']


def test_feature_off_is_read_only(setup):
    store, _, room, manager = setup
    with patch.dict('os.environ', {'FEDERATION_CONTEXT_ENABLED': 'false'}):
        assert manager.prepare(room, '心跳') is None
    assert not (store.base / 'metadata/context-memory').exists()


class NoRemote:
    def status(self): return {'enabled': False}
    async def classify(self, *args): return {'status': 'disabled'}


def test_api_persists_turn_receipt_and_task_memory_in_scoped_file(tmp_path):
    import time
    captured = []
    async def runner(job, store):
        captured.append(job)
        job['answer'] = '心跳依据实际回复字符变化。'
        job['context_usage'] = {'enabled': True, 'budget': 12000, 'reply': {'input_tokens': 321}}
    app = create_app(base=tmp_path / 'data', runner=runner, decision_router=NoRemote())
    with TestClient(app) as client:
        room = client.post('/api/chat/primary', json={}).json()
        response = client.post('/api/chat/rooms/' + room['id'] + '/messages', json={'content':'心跳的跳动依据是什么？'}).json()
        for _ in range(150):
            job = client.get('/api/jobs/' + response['job']['id']).json()
            if job['status'] not in {'queued','running'}: break
            time.sleep(.01)
        assert job['status'] == 'completed', job.get('error')
        assert captured[-1]['context_memory']['room_id'] == room['id']
        saved = client.get('/api/chat/rooms/' + room['id']).json()
        assert saved['messages'][-1]['context_usage']['reply']['input_tokens'] == 321
        state = client.get('/api/chat/rooms/' + room['id'] + '/context-memory').json()
        assert len(state['tasks'][0]['message_ids']) == 2
        assert client.get('/api/chat/rooms/' + room['id'] + '/context-memory?agent_id=software').status_code == 400
        assert client.post('/api/chat/rooms/' + room['id'] + '/context-memory', json={'task_id':state['active_task'],'expected_revision':state['revision'],'action':'update','text':'心跳界面调整曲线'}).status_code == 200
