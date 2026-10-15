import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from federation.app import create_app
from federation.chat import ChatStore
from federation.context_memory import ContextMemory
from federation.core import FederationStore
from federation.project_memory import ProjectMemory


@pytest.fixture
def fixture(tmp_path):
    store = FederationStore(tmp_path / 'data'); store.init()
    chat = ChatStore(store); memory = ContextMemory(store)
    projects = ProjectMemory(store, chat, memory); memory.projects = projects
    room = chat.create_room('group', ['central', 'software-frontend'], '隔离项目来源')
    return store, chat, memory, projects, room


def turn(chat, memory, room, text, agent='central'):
    rid = uuid.uuid4().hex
    chat.append_message(room, 'user', text, round_id=rid)
    context = memory.prepare(room, text, agent, rid)
    message=chat.append_message(room, 'assistant', '仅提供咨询，尚未部署。', agent_id=agent, phase='consultation', round_id=rid)
    message['context_usage']={'enabled':True,'task_id':context['task_id']}
    memory.complete_turn(room, context, rid); chat.save_room(room)
    return context


def edit(projects, room, memory, action, project=None, **extra):
    state = memory.inspect(room['id'], 'central'); listing = projects.view(room['id'], 'central')
    payload = dict(action=action, agent_id='central', project_id=project and project['id'],
                   expected_revision=project['revision'] if project else listing['revision'], expected_task_revision=state['revision'],
                   task_id=state['active_task'], binding_revision=listing['binding']['revision'], title='心跳页面项目', progress='方案待核对', next_steps='先调整曲线', allowed_agents=['central'])
    payload.update(extra)
    result = projects.edit(room, 'central', payload)
    return next((p for p in projects.view(room['id'], 'central')['projects'] if p['id'] == result['project_id']), None)


def values(context): return {r['slot']: r['value'] for r in context['requirement_state']['active']}


def test_extended_requirements_resume_and_local_correction(fixture):
    _,chat,memory,projects,source=fixture
    turn(chat,memory,source,'页面使用React。预算为500元。截止日期为2026-10-20。目标平台为Android和iOS。交付格式为PDF。')
    turn(chat,memory,source,'预算从500元改到300元。截止日期改为2026-10-25。交付格式改为Markdown。')
    project=edit(projects,source,memory,'create')
    target=chat.create_room('direct',['central'],'新会话')
    edit(projects,target,memory,'attach',project)
    resumed=turn(chat,memory,target,'继续这个项目。')
    assert values(resumed)=={'framework':'react','budget':'300元','deadline':'2026-10-25','platform':'android/ios','deliverable':'markdown'}
    local=turn(chat,memory,target,'改为只做Android，iOS暂缓。')
    assert values(local)['platform']=='android'
    assert values(local)['budget']=='300元'


def test_admission_blocks_new_model_round_without_appending_chat(tmp_path,monkeypatch):
    app=create_app(base=tmp_path/'data')
    with TestClient(app) as client:
        room=app.state.chat.primary_room();before=len(room['messages'])
        app.state.context_metrics.record_router(room['id'],{'usage_event_id':'known','calls':1,'status':'classified','usage':{'input_tokens':20,'output_tokens':3}})
        monkeypatch.setenv('FEDERATION_ROOM_MODEL_CALLS_LIMIT','1')
        response=client.post('/api/chat/rooms/'+room['id']+'/messages',json={'content':'请解释组件。'})
        assert response.status_code==429
        assert len(app.state.chat.get_room(room['id'])['messages'])==before
        usage=client.get('/api/chat/rooms/'+room['id']+'/context-usage').json()
        assert usage['operations']['calls']==1 and not usage['admission']['allowed']


def test_explicit_cross_room_resume_scope_and_boundary(fixture):
    _, chat, memory, projects, source = fixture
    original = turn(chat, memory, source, '心跳页面使用 React，必须保留原始聊天记录，不联网。')
    project = edit(projects, source, memory, 'create')
    raw = (chat.root / (source['id'] + '.json')).read_bytes()
    target = chat.create_room('group', ['central', 'software-frontend'], '隔离新会话')
    plain = turn(chat, memory, target, '这个项目用什么框架？')
    assert not plain['project_memory'] and not values(plain)
    edit(projects, target, memory, 'attach', project)
    resumed = turn(chat, memory, target, '继续这个项目，复述要求。')
    assert values(resumed) == {'framework': 'react', 'history': 'preserve', 'network': 'local_only'}
    assert resumed['project_memory']['progress'] == '方案待核对'
    other = turn(chat, memory, target, '继续这个项目。', 'software-frontend')
    assert not other['project_memory'] and not projects.view(target['id'], 'software-frontend')['projects']
    new = turn(chat, memory, target, '新话题：抖音热点数据。')
    assert not new['project_memory'] and not values(new)
    assert new['task_id'] != resumed['task_id']
    assert (chat.root / (source['id'] + '.json')).read_bytes() == raw


def test_binding_first_task_and_restart_correction_sync(fixture):
    store, chat, memory, projects, source = fixture
    turn(chat, memory, source, '页面使用 React，不联网。')
    project = edit(projects, source, memory, 'create')
    target = chat.create_room('direct', ['central'], '隔离续接')
    project = edit(projects, target, memory, 'attach', project, task_id=None)
    first = turn(chat, memory, target, '继续这个项目。')
    assert values(first)['framework'] == 'react'
    assert projects.view(target['id'], 'central')['binding']['task_id'] == first['task_id']
    changed = turn(chat, memory, target, '改用 Angular，其他要求保持。')
    assert values(changed) == {'framework': 'angular', 'network': 'local_only'}
    memory = ContextMemory(store); projects.memory = memory; memory.projects = projects
    assert values(turn(chat, memory, target, '继续这个页面。')) == values(changed)
    project = edit(projects, target, memory, 'sync', project)
    assert {r['value'] for r in project['requirements']} == {'angular','local_only'}
    assert values(turn(chat, memory, target, '继续这个页面。')) == values(changed)
    third = chat.create_room('direct', ['central'], '隔离第三个会话')
    edit(projects, third, memory, 'attach', project)
    assert values(turn(chat, memory, third, '继续这个项目。'))['framework'] == 'angular'


def test_ambiguous_imported_rule_is_reviewable(fixture):
    _, chat, memory, projects, source = fixture
    turn(chat, memory, source, '页面使用 React。'); project = edit(projects, source, memory, 'create')
    target = chat.create_room('direct', ['central'], '冲突隔离'); edit(projects, target, memory, 'attach', project)
    result = turn(chat, memory, target, '这个页面使用 Angular。')
    assert len(result['requirement_state']['conflicts']) == 2
    state = memory.view(target, 'central'); task = state['tasks'][0]
    choice = next(r for r in task['requirement_state']['conflicts'] if r['value'] == 'angular')
    memory.edit(target['id'], 'central', task['id'], state['revision'], 'resolve', room=target, requirement_id=choice['id'])
    assert values(turn(chat, memory, target, '继续这个页面。'))['framework'] == 'angular'


def test_source_changes_sync_refreshes_other_rooms_and_forget(fixture):
    _, chat, memory, projects, source = fixture
    initial = turn(chat, memory, source, '页面使用 React。'); project = edit(projects, source, memory, 'create')
    target = chat.create_room('direct', ['central'], '来源变化隔离'); edit(projects, target, memory, 'attach', project)
    assert values(turn(chat, memory, target, '继续这个项目。'))['framework'] == 'react'
    turn(chat, memory, source, '改用 Angular。')
    stale = turn(chat, memory, target, '继续这个项目。')
    assert stale['project_memory']['source_status'] == 'changed' and not values(stale)
    assert 'requirements' not in stale['project_memory']
    project = projects.view(source['id'], 'central')['projects'][0]
    project = edit(projects, source, memory, 'sync', project)
    assert values(turn(chat, memory, target, '继续这个项目。'))['framework'] == 'angular'
    state = memory.inspect(source['id'], 'central')
    memory.edit(source['id'], 'central', initial['task_id'], state['revision'], 'forget')
    assert projects.view(target['id'], 'central')['projects'][0]['source_status'] == 'forgotten'
    assert not values(turn(chat, memory, target, '继续这个项目。'))
    assert 'project_seed' not in json.dumps(memory.view(target,'central'))
    project = projects.view(target['id'], 'central')['projects'][0]
    edit(projects, target, memory, 'forget', project)
    assert not projects.view(target['id'], 'central')['projects']
    assert not turn(chat, memory, target, '继续这个项目。')['project_memory']


@pytest.mark.parametrize('field,value', [('expected_revision',-1),('expected_task_revision',-1),('binding_revision',-1),('task_id','nonexistent')])
def test_stale_or_invalid_attach_is_rejected_without_writes(fixture, field, value):
    _, chat, memory, projects, source = fixture
    turn(chat, memory, source, '页面使用 React。'); project = edit(projects, source, memory, 'create')
    before = projects.path.read_bytes()
    with pytest.raises(ValueError): edit(projects, source, memory, 'attach', project, **{field:value})
    assert projects.path.read_bytes() == before


def test_project_export_never_copies_automatic_execution_claims(fixture):
    _, chat, memory, projects, source = fixture
    ctx = turn(chat, memory, source, '页面使用 React。')
    with memory._locked(source['id'],'central') as (path,state):
        state['tasks'][0]['summary'] = {'goal':'助手称已部署','constraints':[], 'decisions':[], 'progress':[{'text':'已部署生产','source_ids':[]}], 'open_questions':[], 'source_ids':[]}
        path.write_text(json.dumps(state))
    project = edit(projects, source, memory, 'create')
    assert '已部署生产' not in json.dumps(project,ensure_ascii=False)


def test_api_busy_guards_and_usage_readback(tmp_path):
    app = create_app(base=tmp_path/'api-data'); chat=app.state.chat
    room=chat.create_room('direct',['central'],'隔离 API')
    turn(chat,app.state.context_memory,room,'页面使用 React。')
    with TestClient(app) as client:
        base='/api/chat/rooms/'+room['id']
        state=client.get(base+'/context-memory').json()
        payload={'action':'create','expected_revision':0,'expected_task_revision':state['revision'],'task_id':state['active_task'],'title':'隔离项目'}
        response=client.post(base+'/memory-projects',json=payload); assert response.status_code==200
        assert client.get(base+'/memory-projects').json()['binding']['project_id']==response.json()['project_id']
        assert client.get(base+'/context-usage').json()['room']['rounds']==1
        assert client.get(base+'/context-usage').json()['project']['rounds']==1
        # The task source links also attribute a missing receipt; missing counts
        # remain visible in project coverage rather than silently dropping it.
        room['messages'][-1].pop('context_usage');chat.save_room(room)
        stats=client.get(base+'/context-usage?refresh=true').json()['project']
        assert stats['rounds']==1 and stats['input_unknown_rounds']==1
        room.update(status='running',active_job_id=uuid.uuid4().hex);chat.save_room(room)
        assert client.post(base+'/memory-projects',json=payload).status_code==409
        assert client.get(base+'/memory-projects?agent_id=software-frontend').status_code==400
        assert client.get('/api/workspace').json()['context_policy']['usage_version']==2


def test_hundred_rounds_multiple_topics_and_late_corrections(fixture):
    store,chat,memory,projects,room=fixture
    first=turn(chat,memory,room,'心跳页面使用 Vue，不联网。')
    for i in range(100):
        if i==27: text='改用 React。'
        elif i==75: text='改用 Angular，必须保留原始聊天记录。'
        else: text=f'继续这个心跳页面，讨论第{i}个细节。'
        ctx=turn(chat,memory,room,text)
        if ctx['summary_request']:
            ids=[m['id'] for m in ctx['summary_request']['messages']]
            # Exercise actual source validation / compaction persistence without model calls.
            update={'goal':ctx['goal'],'constraints':[],'decisions':[],'progress':[],'open_questions':[],'source_ids':list(dict.fromkeys((ctx['summary'] or {}).get('source_ids',[])+ids))}
            ctx['revision']=memory.inspect(room['id'],'central')['revision']
            assert memory.commit(room,ctx,update)['status']=='saved'
    assert ctx['task_id']==first['task_id'] and values(ctx)=={'framework':'angular','history':'preserve','network':'local_only'}
    project=edit(projects,room,memory,'create')
    other=turn(chat,memory,room,'新话题：热点列表使用 React，回复用英文。')
    assert not other['project_memory'] and values(other)=={'framework':'react','language':'en'}
    target=chat.create_room('direct',['central'],'长对话之后的新会话')
    memory=ContextMemory(store);projects.memory=memory;memory.projects=projects
    edit(projects,target,memory,'attach',project)
    assert values(turn(chat,memory,target,'继续这个项目。'))=={'framework':'angular','history':'preserve','network':'local_only'}
