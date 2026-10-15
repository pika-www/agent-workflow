"""Short natural turns retain topic/explicit corrections without new write scope."""
import json
import uuid
from fastapi.testclient import TestClient
from federation.app import create_app, isolated_ask_environment
from federation.conversation_intent import conversational_followup, latest_dialogue
from tests.test_reply_recovery import wait
from tests.test_context_memory import setup, add


def test_topic_correction_references_and_reset(setup):
    _, chat, room, manager = setup
    original = add(chat, room, '找招聘软件的信息')
    context = manager.prepare(room, original['content'], round_id=original['round_id'])
    task = context['task_id']
    for question in ['它们有什么区别？', '我说的是软件功能，不是招聘岗位', '主要看功能和适用人群', '再找找呢', '哪个适合我？', '用表格', '说简单点']:
        answer = add(chat, room, '可按求职者使用的平台与企业管理招聘流程的软件区分。', 'assistant')
        manager.complete_turn(room, context, answer['round_id'])
        current = add(chat, room, question)
        context = manager.prepare(room, question, round_id=current['round_id'])
        assert context['task_id'] == task, question
        assert context['goal'] == original['content']
    assert '主要看功能和适用人群' in json.dumps(context, ensure_ascii=False)
    for _ in range(12):
        current = add(chat, room, '它们还有什么区别？')
        context = manager.prepare(room, current['content'], round_id=current['round_id'])
    assert '主要看功能和适用人群' not in json.dumps(context['recent'], ensure_ascii=False)
    assert '主要看功能和适用人群' in json.dumps(context['intent_clarifications'], ensure_ascii=False)
    current = add(chat, room, '换个话题，今天有什么新闻？')
    changed = manager.prepare(room, current['content'], round_id=current['round_id'])
    assert changed['task_id'] != task
    assert not changed['recent']


def test_legacy_bootstrap_uses_latest_user_topic_and_respects_forget(setup):
    _, chat, room, manager = setup
    add(chat, room, '旧项目：做一个招聘网站')
    original = add(chat, room, '找记账软件的信息')
    add(chat, room, '不可靠的助手判断', 'assistant', status='failed')
    add(chat, room, '主要看家庭记账')
    current = add(chat, room, '它们有什么区别？')
    context = manager.prepare(room, current['content'], round_id=current['round_id'])
    assert context['goal'] == original['content']
    assert '旧项目' not in json.dumps(context, ensure_ascii=False)
    assert '不可靠的助手判断' not in json.dumps(context, ensure_ascii=False)
    manager.edit(room['id'], 'central', context['task_id'], context['revision'], 'forget')
    next_turn = add(chat, room, '再找找呢')
    fresh = manager.prepare(room, next_turn['content'], round_id=next_turn['round_id'])
    assert '记账软件' not in json.dumps(fresh, ensure_ascii=False)


def test_followup_api_keeps_actual_question_and_context(tmp_path):
    turns = []
    async def runner(turn, store):
        isolated_ask_environment(store, turn)
        turns.append(json.loads(json.dumps(turn)))
        turn['answer'] = '可以按用途、功能和适用场景比较。'
    class Router:
        def status(self): return {'configured': False, 'enabled': False}
        async def classify(self, *args): return {'provider': 'host-rules', 'status': 'bypassed'}
    app = create_app(base=tmp_path/'data', runner=runner, decision_router=Router())
    with TestClient(app) as client:
        room = client.post('/api/chat/primary', json={}).json()
        path = '/api/chat/rooms/'+room['id']
        for question in ['找招聘软件的信息', '它们有什么区别？', '我说的是功能，不是岗位', '再找找呢']:
            sent = client.post(path+'/messages', json={'content': question})
            assert sent.status_code == 200, sent.text
            job = wait(client, sent.json()['job']['id'])
            assert job['status'] == 'completed', job.get('error')
            assert turns[-1]['current_question'] == question
            assert turns[-1]['context_memory']['goal'] == '找招聘软件的信息'
        assert '招聘软件' in turns[-1]['retrieval_query']
        assert '招聘软件' in job['research_goal']
        assert '我说的是功能，不是岗位' in job['research_goal']
        stored = client.get(path).json()
        assert not stored.get('proposals')
        assert app.state.store.space('central')['knowledge_count'] == 0


def test_named_new_subject_and_confirmation_are_not_references():
    for question in ['查一下数据库索引', '今天有什么热点', '换个话题，它们是什么', '帮我找北京招聘岗位']:
        assert not conversational_followup(question)
    assert latest_dialogue([{'role': 'user', 'content': '确认', 'phase': 'confirmation'}]) == []


def test_advice_follows_recovered_personality_turn_not_stale_task(setup):
    _, chat, room, manager = setup
    old = add(chat, room, '分析 https://cephalon.cloud/aigc 这个产品')
    stale = manager.prepare(room, old['content'], round_id=old['round_id'])
    answer = add(chat, room, 'Cephalon 的建议：先验证 AIGC 功能。', 'assistant')
    manager.complete_turn(room, stale, answer['round_id'])
    source = add(chat, room, '分析我的性格')
    add(chat, room, '上下文超出预算', 'assistant', status='failed')
    # Recovery may have no fresh user turn/task index. Recency must win over
    # the stale active product task and its summary in that case as well.
    answer = add(chat, room, '从你的表达看比较直接，但性格判断需要更多具体经历。', 'assistant')
    for question in ['给我一点建议', '具体一点', '那我该怎么做呢？', '展开说说', '再找找呢']:
        current = add(chat, room, question)
        context = manager.prepare(room, question, round_id=current['round_id'])
        assert context['goal'] == source['content']
        assert context['turn_focus']['source_message_id'] == source['id']
        assert context['turn_focus']['previous_reply_id'] == answer['id']
        assert answer['id'] in [m['id'] for m in context['recent']]
        assert 'cephalon' not in json.dumps(context, ensure_ascii=False).lower()
        assert '上下文超出预算' not in json.dumps(context, ensure_ascii=False)
        answer = add(chat, room, '先回顾一次具体的压力情境，再决定下一步。', 'assistant')
        manager.complete_turn(room, context, answer['round_id'])
    named = add(chat, room, '现在分析 Cephalon 的产品功能')
    returned = manager.prepare(room, named['content'], round_id=named['round_id'])
    assert returned['task_id'] != context['task_id']


def test_generic_assistant_words_cannot_bootstrap_new_topic(setup):
    _, chat, room, manager = setup
    add(chat, room, '分析旧产品')
    add(chat, room, '建议你建立自我观察，分析性格和求职方向。', 'assistant')
    current = add(chat, room, '分析我的性格')
    context = manager.prepare(room, current['content'], round_id=current['round_id'])
    assert not context['recent']


def test_advice_forms_do_not_swallow_named_new_subjects():
    for question in ['给我一点建议', '那你给我一些具体建议', '提几条建议', '我接下来该怎么做', '在哪里去申请呢']:
        assert conversational_followup(question), question
    for question in ['给我一点数据库索引的建议', '给我建议如何部署 Cephalon', '换个话题，给我一点建议']:
        assert not conversational_followup(question), question


def test_advice_api_carries_focus_to_retrieval_and_worker(tmp_path):
    turns = []
    async def runner(turn, store):
        isolated_ask_environment(store, turn)
        turns.append(json.loads(json.dumps(turn)))
        turn['answer'] = '先回顾一个具体经历，再考虑行动建议。'
    class Router:
        def status(self): return {'configured': False, 'enabled': False}
        async def classify(self, *args): return {'provider': 'host-rules', 'status': 'bypassed'}
    app = create_app(base=tmp_path/'data', runner=runner, decision_router=Router())
    with TestClient(app) as client:
        room = app.state.chat.primary_room()
        original = add(app.state.chat, room, '分析我的性格')
        add(app.state.chat, room, '从表达方式只能得到有限线索。', 'assistant')
        room['analysis_context'] = {'goal':'分析 https://cephalon.cloud/aigc 这个产品'}
        app.state.chat.save_room(room)
        for question in ['给我一点建议', '展开说说']:
            sent = client.post('/api/chat/rooms/'+room['id']+'/messages', json={'content':question})
            assert sent.status_code == 200, sent.text
            job = wait(client, sent.json()['job']['id'])
            assert job['status'] == 'completed', job.get('error')
            assert not job.get('analysis')
            assert job['turn_focus']['source_message_id'] == original['id']
            assert turns[-1]['current_question'] == question
            assert '分析我的性格' in turns[-1]['retrieval_query']
            assert turns[-1]['context_memory']['turn_focus']['question'] == '分析我的性格'
            assert 'cephalon' not in json.dumps(turns[-1]['context_memory'],ensure_ascii=False).lower()


def test_temporal_public_subject_is_not_a_pronoun_reference():
    assert not conversational_followup('这个月失业的人数有多少？')
    assert conversational_followup('这个数据怎么算的？')
