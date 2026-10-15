import asyncio
import json
import uuid
import pytest
from federation.orchestration import run_orchestration, _parse_plan, PlanError
from federation.delegation_artifacts import DelegationArtifacts


def test_rejects_cycles_and_missing_dependencies():
    for needs in (['missing'],['b']):
        tasks=[{'agent_id':'a','task':'a','depends_on':needs},{'agent_id':'b','task':'b','depends_on':['a']}]
        with pytest.raises(PlanError):
            _parse_plan(json.dumps({'action':'delegate','tasks':tasks}),{'a','b'},10,0)


@pytest.mark.parametrize('fail_first',[False,True])
def test_parallel_limit_dependency_handoff_and_failure(tmp_path,fail_first):
    async def scenario():
        room={'participants':['central'],'delegations':[],'messages':[]}
        agents=[{'id':'central','name':'central','parent_id':None}]+[{'id':k,'name':k,'parent_id':'central'} for k in 'abcd']
        artifacts=DelegationArtifacts(tmp_path,uuid.uuid4().hex,uuid.uuid4().hex)
        active=0;peak=0;finished=set();executed=[]
        both=asyncio.Event()
        async def invoke(agent,prompt,phase,tid):
            nonlocal active,peak
            if phase=='plan':
                # The host example must permit the same dependency key that
                # the validator and scheduler accept, including learning mode.
                assert '"depends_on":[]' in prompt
                assert '不要增加任何字段' not in prompt
                return json.dumps({'action':'delegate','tasks':[{'agent_id':k,'task':'预算检查','depends_on':['a'] if k=='c' else []} for k in 'abcd']})
            if phase=='summary':
                assert '/_delegation_results/' in prompt
                return '汇总'
            active+=1;peak=max(peak,active);executed.append(agent)
            try:
                if active==2:both.set()
                if agent in 'ab':await asyncio.wait_for(both.wait(),1)
                await asyncio.sleep(.01)
                if agent=='a' and fail_first:raise ValueError('fixture failure')
                if agent=='c':assert 'a' in finished and '前置任务回执' in prompt
                finished.add(agent)
                return '一般材料。'*1000+'预算必须保留 37 元。'+'一般材料。'*1000
            finally:active-=1
        result=await run_orchestration(room,agents,'预算检查',[],invoke,lambda:None,uuid.uuid4().hex,concurrency=2,archive_result=artifacts.save)
        assert peak==2
        assert result['failed']==fail_first
        assert ('c' in executed)!=fail_first
        for task in room['delegations']:
            if task.get('result_artifact'):
                full=artifacts.read(task['result_artifact'])
                assert len(full)==task['result_characters']
        assert room['current_agent'] is None
    asyncio.run(scenario())


def test_artifact_version_mismatch_and_scope(tmp_path):
    store=DelegationArtifacts(tmp_path,uuid.uuid4().hex,uuid.uuid4().hex)
    ref=store.save(uuid.uuid4().hex,'完整原件')
    assert store.read(ref)=='完整原件'
    (store.root/ref['path'].split('/')[-1]).write_text('changed')
    with pytest.raises(ValueError):store.read(ref)


def test_ready_dependency_does_not_wait_for_unrelated_sibling():
    async def scenario():
        room={'participants':['central'],'delegations':[],'messages':[]}
        agents=[{'id':'central','name':'central','parent_id':None}]+[{'id':k,'name':k,'parent_id':'central'} for k in 'abc']
        c_started=asyncio.Event()
        async def invoke(agent,prompt,phase,tid):
            if phase=='plan':
                return json.dumps({'action':'delegate','tasks':[
                    {'agent_id':'a','task':'先产出输入'}, {'agent_id':'b','task':'独立慢任务'},
                    {'agent_id':'c','task':'消费输入','depends_on':['a']}]})
            if phase=='summary':return '完成'
            if agent=='b':await asyncio.wait_for(c_started.wait(),.4)
            if agent=='c':c_started.set()
            return agent+'完成'
        result=await run_orchestration(room,agents,'测试就绪调度',[],invoke,lambda:None,uuid.uuid4().hex,concurrency=2)
        assert not result['failed'], result
        assert c_started.is_set()
    asyncio.run(scenario())


def test_dependency_originals_reach_nested_executor(tmp_path):
    async def scenario():
        room={'participants':['central'],'delegations':[],'messages':[]}
        agents=[{'id':'central','name':'central','parent_id':None},
                {'id':'a','name':'a','parent_id':'central'},
                {'id':'b','name':'b','parent_id':'central'},
                {'id':'leaf','name':'leaf','parent_id':'b'}]
        artifacts=DelegationArtifacts(tmp_path,uuid.uuid4().hex,uuid.uuid4().hex)
        async def invoke(agent,prompt,phase,tid):
            if phase=='plan':
                if agent=='central':tasks=[{'agent_id':'a','task':'给出依据'}, {'agent_id':'b','task':'依据上游写说明','depends_on':['a']}]
                else:tasks=[{'agent_id':'leaf','task':'整理上游依据'}]
                return json.dumps({'action':'delegate','tasks':tasks})
            if phase=='summary':return '汇总完成'
            if agent=='a':return '原始回滚标签是琥珀-621；必须人工确认。'
            assert '琥珀-621' in prompt
            leaf=next(t for t in room['delegations'] if t['id']==tid)
            assert len(leaf['input_artifacts'])==1
            assert '琥珀-621' in artifacts.read(leaf['input_artifacts'][0])
            return '已核对原件'
        result=await run_orchestration(room,agents,'整理回滚说明',[],invoke,lambda:None,uuid.uuid4().hex,archive_result=artifacts.save)
        assert not result['failed'], result
    asyncio.run(scenario())


def test_explicit_members_cannot_expand_to_unrequested_reviewers():
    from federation.orchestration import _explicit_member_scope
    candidates=[{'id':'software','name':'互联网与软件'}, {'id':'business','name':'经营'}, {'id':'custom','name':'AI 产品思维'}]
    question='请主 Agent 委派给软件 Agent，再由软件 Agent 分配给后端、前端和运维三个成员。'
    assert _explicit_member_scope(question,candidates)=={'software'}
    assert _explicit_member_scope('请委派给软件Agent。',candidates)=={'software'}
    leaves=[{'id':'software-'+key,'name':name} for key,name in [('backend','后端'),('frontend','前端'),('devops','运维'),('testing','测试')]]
    assert _explicit_member_scope(question,leaves)=={'software-backend','software-frontend','software-devops'}
    for text in ['介绍软件与经营的区别','不要委派给软件 Agent。','请委派给软件 Agent 和其他合适成员。']:
        assert _explicit_member_scope(text,candidates) is None
    async def scenario():
        room={'participants':['central'],'delegations':[],'messages':[]};attempts=0;executed=[]
        agents=[{'id':'central','name':'主 Agent','parent_id':None}]+[dict(c,parent_id='central') for c in candidates]
        async def invoke(agent,prompt,phase,tid):
            nonlocal attempts
            if phase=='plan':
                attempts+=1
                assert '用户已明确指定本层成员范围' in prompt
                assert '"agent_id": "business"' not in prompt
                return json.dumps({'action':'delegate','tasks':[{'agent_id':'business' if attempts==1 else 'software','task':'短方案'}]})
            if phase=='execute':executed.append(agent)
            return '只读短方案。'
        result=await run_orchestration(room,agents,question,[],invoke,lambda:None,uuid.uuid4().hex)
        assert not result['failed'] and attempts==0 and executed==['software']
        assert room['delegations'][0]['plan_origin']=='explicit_single_recipient'
        assert room['delegations'][1]['instruction']==question
    asyncio.run(scenario())


def test_explicit_hierarchy_cannot_be_replaced_by_a_direct_answer():
    async def scenario():
        room={'participants':['central'],'delegations':[],'messages':[]}
        agents=[{'id':'central','name':'主 Agent','parent_id':None},
                {'id':'software','name':'软件 Agent','parent_id':'central'}]+[
                {'id':key,'name':name+' Agent','parent_id':'software'}
                for key,name in [('back','后端'),('front','前端'),('ops','运维')]]
        question='MULTI-01 复验：主 Agent 委派给软件 Agent，由软件 Agent 分配给后端、前端和运维。后端选 WM- 加四位数字的标识。'
        attempts=0;executed=[]
        async def invoke(agent,prompt,phase,tid):
            nonlocal attempts
            if phase=='plan':
                assert agent=='software','The explicit single-recipient route needs no model decision'
                assert room['delegations'][0]['status']=='running'
                attempts+=1
                if attempts==1:return json.dumps({'action':'answer','answer':'本层无法越级调用，因此不能委派。'})
                assert 'action=answer 不会调用成员' in prompt
                return json.dumps({'action':'delegate','tasks':[
                    {'agent_id':'back','task':'选取 WM- 加四位数字的标识'},
                    {'agent_id':'front','task':'引用后端产物','depends_on':['back']},
                    {'agent_id':'ops','task':'独立给出限制'}]})
            if phase=='execute':executed.append(agent)
            return 'WM-7391，人工确认后才回滚，不得覆盖历史。'
        result=await run_orchestration(room,agents,question,[],invoke,lambda:None,uuid.uuid4().hex)
        assert not result['failed'] and attempts==2
        assert set(executed)=={'back','front','ops'}
    asyncio.run(scenario())


def test_explicit_identifier_prefix_survives_plan_rewriting():
    source='自行选一个 WM- 加四位数字的验收标识。'
    def plan(text):return json.dumps({'action':'delegate','tasks':[{'agent_id':'a','task':text}]})
    with pytest.raises(PlanError,match='标识前缀'):
        _parse_plan(plan("选一个'MM-0000'格式的验收标识"),{'a'},4,0,source_question=source)
    assert _parse_plan(plan("选一个'WM-0000'格式的验收标识"),{'a'},4,0,source_question=source)['action']=='delegate'
    assert _parse_plan(plan('选一个验收标识，遵循用户原始格式'),{'a'},4,0,source_question=source)['action']=='delegate'
    assert _parse_plan(plan('解释编号 AB-1234'),{'a'},4,0,source_question='解释编号的用途')['action']=='delegate'


def test_user_dependency_cannot_exist_only_in_task_prose():
    from federation.orchestration import _explicit_dependencies
    members=[{'id':'back','name':'后端 Agent'},{'id':'front','name':'前端 Agent'},{'id':'ops','name':'运维 Agent'}]
    question='请分配给后端、前端和运维三个成员。前端必须依赖后端任务完成，收到其产物后原样引用。运维独立。'
    assert _explicit_dependencies(question,members)=={'front':{'back'}}
    for text in ['前端不依赖后端','不要让前端等待后端','前端等待后端或运维','front 等待 background']:
        assert not _explicit_dependencies(text,members)
    async def scenario():
        room={'participants':['central'],'delegations':[],'messages':[]};attempts=0;done=set()
        agents=[{'id':'central','name':'主 Agent','parent_id':None}]+[dict(m,parent_id='central') for m in members]
        async def invoke(agent,prompt,phase,tid):
            nonlocal attempts
            if phase=='plan':
                attempts+=1
                assert '宿主从用户原话确认的必需依赖' in prompt
                tasks=[{'agent_id':'back','task':'选取随机标识'},
                       {'agent_id':'front','task':'依赖后端完成后引用实际产物'},
                       {'agent_id':'ops','task':'独立检查'}]
                if attempts==2:
                    assert 'depends_on 必须包含 back' in prompt
                    tasks[1]['depends_on']=['back']
                return json.dumps({'action':'delegate','tasks':tasks})
            if phase=='summary':return '已汇总实际结果'
            if agent=='front':
                assert 'back' in done
                assert 'WM-1936' in prompt
            done.add(agent)
            return 'WM-1936'
        result=await run_orchestration(room,agents,question,[],invoke,lambda:None,uuid.uuid4().hex)
        assert not result['failed'] and attempts==2 and done=={'back','front','ops'}
        assert len(room['delegations'])==4,'The invalid plan must create no tasks'
    asyncio.run(scenario())
