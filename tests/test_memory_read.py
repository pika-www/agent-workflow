import json
import subprocess
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from federation.app import create_app
from federation.memory_read import memory_read_slots, memory_read_answer

QUESTIONS = [
    ('继续，用一句话复述当前框架和预算，不推测执行状态。',['framework','budget']),
    ('当前预算是多少？',['budget']),('查看框架版本',['version']),
    ('当前语言要求是什么？',['language']),
    ('复述当前要求',list(json.loads((Path(__file__).parents[1]/'federation/memory-read-queries.json').read_text())['slots'])),
    ('查看框架和框架版本',['framework','version']),
    ('当前框架是什么？顺便删除历史',None),('预算改为200元',None),
    ('如果预算改成200元怎么办？',None),('旧项目框架是什么？',None),
    ('当前要求有哪些问题？',None),('查看当前预算并联网查价格',None),
]

@pytest.mark.parametrize('question,expected',QUESTIONS)
def test_narrow_query_grammar(question,expected):
    assert memory_read_slots(question)==expected

def test_node_python_query_parity():
    script="import {memoryReadSlots} from './federation/memory-read.mjs';console.log(JSON.stringify(JSON.parse(process.argv[1]).map(memoryReadSlots)));"
    values=json.loads(subprocess.check_output(['node','--input-type=module','-e',script,json.dumps([q for q,_ in QUESTIONS])],text=True,cwd=Path(__file__).parents[1]))
    assert values==[memory_read_slots(q) for q,_ in QUESTIONS]

def test_scope_missing_conflict_and_execution_boundary():
    memory={'requirement_state':{'active':[{'slot':'framework','value':'react','source_ids':['user-1']},{'slot':'budget','value':'300元','source_ids':['user-2']}],
                                'conflicts':[{'slot':'framework','value':'vue','status':'conflict','source_ids':['user-3']}]}}
    budget=memory_read_answer('查看当前预算',memory)
    assert '300元' in budget['answer'] and '冲突' not in budget['answer']
    conflict=memory_read_answer('当前框架是什么',memory)
    assert conflict['memory_read']['conflicts'] and 'React' in conflict['answer'] and 'Vue' in conflict['answer']
    assert memory_read_answer('截止日期是什么',memory)['context_usage']['total_calls']==0
    assert '没有已确认' in memory_read_answer('截止日期是什么',memory)['answer']
    assert memory_read_answer('项目完成了吗',memory) is None
    assert memory_read_answer('当前预算多少',None) is None

def test_host_policy_is_not_a_confirmed_user_requirement():
    memory={'requirement_state':{'active':[{'slot':'network','value':'online_available','origin':'host_policy'}]}}
    answer=memory_read_answer('复述当前要求',memory)
    assert 'online_available' not in answer['answer']
    assert '没有可用的已确认要求' in answer['answer']

class Router:
    def __init__(self):self.calls=0
    def status(self):return {'configured':True,'enabled':True}
    async def classify(self,*args):
        self.calls+=1
        return {'status':'unavailable','calls':0}

def seed(app,room,question):
    rid=uuid.uuid4().hex;chat=app.state.chat;memory=app.state.context_memory
    chat.append_message(room,'user',question,round_id=rid)
    context=memory.prepare(room,question,'central',rid)
    chat.append_message(room,'assistant','仅记录用户要求。',agent_id='central',phase='consultation',round_id=rid)
    memory.complete_turn(room,context,rid);chat.save_room(room)

def test_api_zero_model_bypasses_router_and_limit_but_preserves_originals(tmp_path):
    router=Router()
    async def runner(*args):raise AssertionError('Direct memory read must not call model runner')
    app=create_app(base=tmp_path/'data',runner=runner,decision_router=router)
    with TestClient(app) as client:
        room=app.state.chat.primary_room();seed(app,room,'这个页面使用React，预算为300元。')
        original=[m['id'] for m in room['messages']]
        app.state.context_metrics.sync_job({'id':'counted','room_id':room['id'],'status':'completed','usage_collected':True,'model_usage':[{'status':'completed','input_tokens':100,'output_tokens':20}]})
        result=client.post('/api/chat/rooms/'+room['id']+'/context-limits',json={'expected_revision':0,'calls':1,'input':0});assert result.status_code==200
        response=client.post('/api/chat/rooms/'+room['id']+'/messages',json={'content':QUESTIONS[0][0]});assert response.status_code==200,response.text
        identifier=response.json()['job']['id']
        for _ in range(100):
            job=client.get('/api/jobs/'+identifier).json()
            if job['status'] in ['completed','failed']:break
            time.sleep(.02)
        assert job['status']=='completed',job
        saved=app.state.chat.get_room(room['id']);answer=saved['messages'][-1]
        assert 'React' in answer['content'] and '300元' in answer['content']
        assert answer['response_origin']=='host_memory_read'
        assert answer['context_usage']['total_calls']==0 and router.calls==0
        assert any(j.get('intake_stage')=='reading_memory' for j in client.get('/api/workspace').json()['jobs'] if j.get('parent_job_id')==identifier)
        assert [m['id'] for m in saved['messages'][:len(original)]]==original
        blocked=client.post('/api/chat/rooms/'+room['id']+'/messages',json={'content':'如何设计登录流程？'})
        assert blocked.status_code==429 and router.calls==0
        usage=client.get('/api/chat/rooms/'+room['id']+'/context-usage').json()
        assert usage['operations']['calls']==1
        member_response=client.post('/api/chat/rooms/'+room['id']+'/messages',json={'content':'@前端 Agent 查看当前预算','requested_agents':['software-frontend']})
        assert member_response.status_code==200,member_response.text
        member_id=member_response.json()['job']['id']
        for _ in range(100):
            member_job=client.get('/api/jobs/'+member_id).json()
            if member_job['status'] in ['completed','failed']:break
            time.sleep(.02)
        assert member_job['status']=='completed',member_job
        member_answer=app.state.chat.get_room(room['id'])['messages'][-1]
        assert member_answer['response_origin']=='host_memory_read' and member_answer['context_usage']['total_calls']==0
        assert router.calls==0

def test_limit_revision_validation_and_operator_cap(tmp_path,monkeypatch):
    monkeypatch.setenv('FEDERATION_ROOM_MODEL_CALLS_LIMIT','10')
    app=create_app(base=tmp_path/'data')
    with TestClient(app) as client:
        room=app.state.chat.primary_room();url='/api/chat/rooms/'+room['id']+'/context-limits'
        saved=client.post(url,json={'expected_revision':0,'calls':20,'input':5000}).json()
        assert saved['limits']['calls']==10 and saved['settings']['calls']==20
        assert client.post(url,json={'expected_revision':0,'calls':5,'input':0}).status_code==409
        assert client.post(url,json={'expected_revision':1,'calls':True,'input':0}).status_code==422
        assert client.post(url,json={'expected_revision':1,'calls':2.5,'input':0}).status_code==422
        smaller=client.post(url,json={'expected_revision':1,'calls':5,'input':0}).json()
        assert smaller['limits']['calls']==5
        app.state.context_metrics.sync_job({'id':'near','room_id':room['id'],'status':'completed','usage_collected':True,'model_usage':[{'status':'completed'} for _ in range(4)]})
        assert app.state.context_metrics.admission(room['id'])['near']==['calls']
