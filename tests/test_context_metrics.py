import uuid

import pytest
from federation.chat import ChatStore
from federation.context_memory import ContextMemory
from federation.context_metrics import ContextMetrics, number
from federation.core import FederationStore
from federation.project_memory import ProjectMemory


@pytest.fixture
def fixture(tmp_path):
    store=FederationStore(tmp_path/'data');store.init();chat=ChatStore(store)
    memory=ContextMemory(store);projects=ProjectMemory(store,chat,memory);memory.projects=projects
    return chat,chat.create_room('direct',['central'],'隔离用量统计'),ContextMetrics(store,projects)


def receipt(chat,room,usage=None,**extra):
    message=chat.append_message(room,'assistant','隔离咨询回执',phase='consultation',agent_id='central',round_id=uuid.uuid4().hex,status=extra.pop('status','completed'))
    message.update(extra)
    if usage is not None: message['context_usage']=usage
    return message


def usage(**extra):
    return dict(enabled=True,task_id='task',total_calls=4,total_input_tokens=150,total_output_tokens=40,total_input_tokens_estimated=170,
                reply={'input_tokens':100,'output_tokens':20,'cached_tokens':30},summary={'status':'generated','calls':1,'input_tokens':20,'output_tokens':10},**extra)


def test_totals_dedup_categories_cached_latency_and_restart(fixture):
    chat,room,metrics=fixture
    msg=receipt(chat,room,usage(),workflow={'model_usage':[{'input_tokens':10,'output_tokens':5}]},answer_check={'model_usage':[{'input_tokens':20,'output_tokens':5}]},timing={'request_first_text_ms':1200,'first_text_ms':300})
    metrics.sync_room(room);metrics.sync_room(room);metrics.sync_room(room,full=True)
    result=metrics.totals(room_id=room['id'])
    assert (result['rounds'],result['calls'],result['input'],result['output'])==(1,4,150,40)
    assert (result['reply_input'],result['summary_input'],result['lookup_input'],result['check_input'])==(100,20,10,20)
    assert result['cached']==30 and result['first_text_ms']=={'samples':1,'p50':1200,'p95':1200}
    assert ContextMetrics(chat.store,metrics.projects).totals(room_id=room['id'])==result
    msg['context_usage']['total_input_tokens']=180; metrics.sync_room(room)
    assert metrics.totals(room_id=room['id'])['input']==180


def test_missing_usage_and_failed_request_do_not_become_zero(fixture):
    chat,room,metrics=fixture
    receipt(chat,room,None,timing={'first_text_ms':1})
    receipt(chat,room,{'enabled':True,'total_calls':1,'reply':{}},status='failed')
    metrics.sync_room(room)
    totals=metrics.totals(room_id=room['id'])
    assert totals['input'] is None and totals['output'] is None and totals['calls']==1
    assert totals['input_unknown_rounds']==2 and totals['calls_unknown_rounds']==1 and totals['failed_rounds']==1
    assert totals['first_text_ms']['samples']==0
    receipt(chat,room,dict(enabled=True,total_calls=0,total_input_tokens=0,total_output_tokens=0,reply={'input_tokens':0,'output_tokens':0},summary={'calls':0,'input_tokens':0,'output_tokens':0}),timing={'request_first_text_ms':0})
    metrics.sync_room(room);totals=metrics.totals(room_id=room['id'])
    assert totals['input']==0 and totals['input_unknown_rounds']==2 and totals['first_text_ms']['samples']==1


def test_incremental_and_full_refresh_large_history(fixture):
    chat,room,metrics=fixture
    for i in range(1205): receipt(chat,room,usage(),timing={'request_first_text_ms':i})
    metrics.sync_room(room,full=True);assert metrics.totals(room_id=room['id'])['rounds']==1205
    # Change an older receipt: incremental intentionally rechecks only the tail.
    room['messages'][0]['context_usage']['total_input_tokens']=160
    metrics.sync_room(room);assert metrics.totals(room_id=room['id'])['input']==1205*150
    metrics.sync_room(room,full=True);assert metrics.totals(room_id=room['id'])['input']==1205*150+10
    room['messages']=room['messages'][5:];metrics.sync_room(room,full=True)
    assert metrics.totals(room_id=room['id'])['rounds']==1200


def test_project_attribution_across_rooms_and_agent_counts(fixture):
    chat,room,metrics=fixture
    projects=metrics.projects;identifier=uuid.uuid4().hex
    state=projects.read();state['projects'][identifier]={'id':identifier,'status':'active','source':{'room_id':room['id'],'agent_id':'central','task_id':'task'}}
    projects.path.parent.mkdir(parents=True,exist_ok=True)
    from federation.core import _write_json
    _write_json(projects.path,state)
    receipt(chat,room,usage());metrics.sync_room(room)
    other=chat.create_room('direct',['central'],'隔离另一个会话')
    receipt(chat,other,usage(project_id=identifier));metrics.sync_room(other)
    assert metrics.totals(project_id=identifier)['input']==300
    # Removing the current association does not rewrite historical receipts.
    state['projects'][identifier]['status']='forgotten';_write_json(projects.path,state)
    metrics.sync_room(room,full=True)
    assert metrics.totals(project_id=identifier)['rounds']==2
    assert metrics.totals(room_id=other['id'])['agents'][0]['rounds']==1


@pytest.mark.parametrize('value',[True,False,-1,float('nan'),float('inf'),'100',None])
def test_invalid_provider_counters_stay_missing(value): assert number(value) is None

def test_all_operations_failed_route_child_retry_and_legacy_dedup(fixture,monkeypatch):
    chat,room,metrics=fixture
    message=receipt(chat,room,usage());message['round_id']='round'
    metrics.sync_room(room)
    assert metrics.operation_totals(room_id=room['id'])['input']==150
    route={'usage_event_id':'route','provider':'Jev AI','calls':1,'status':'unavailable'}
    metrics.record_router(room['id'],route);metrics.record_router(room['id'],route)
    job={'id':'child','room_id':room['id'],'parent_job_id':'round','space':'central','delegation_phase':'consultation','status':'completed','usage_collected':True,
         'model_usage':[{'provider':'local','status':'completed','input_tokens':100,'output_tokens':20},{'provider':'local','status':'failed','input_tokens':None,'output_tokens':None}]}
    metrics.sync_job(job);metrics.sync_job(job)
    result=metrics.operation_totals(room_id=room['id'])
    assert (result['calls'],result['input'],result['output'])==(3,100,20)
    assert result['input_unknown']==2 and result['failed_events']==2
    assert {r['kind'] for r in result['categories']}=={'routing','consultation'}
    retry={**job,'id':'format-retry','model_usage':[{'provider':'local','status':'completed','input_tokens':80,'output_tokens':5}]}
    metrics.sync_job(retry);assert metrics.operation_totals(room_id=room['id'])['input']==180
    monkeypatch.setenv('FEDERATION_ROOM_MODEL_CALLS_LIMIT','4')
    assert not metrics.admission(room['id'])['allowed']
    monkeypatch.setenv('FEDERATION_ROOM_MODEL_CALLS_LIMIT','0');assert metrics.admission(room['id'])['allowed']

def test_execution_unknown_report_and_explicit_project(fixture):
    chat,room,metrics=fixture
    job={'id':'native','room_id':room['id'],'space':'central','usage_collected':True,'status':'failed'}
    metrics.sync_job(job)
    result=metrics.operation_totals(room_id=room['id']);assert result['calls'] is None and result['calls_unknown']==1 and result['input_unknown']==1
    report={**job,'id':'report','status':'completed','analysis':True,'delegation_phase':'consultation','usage_project_id':'p','model_usage':[{'provider':'local','status':'completed','input_tokens':50,'output_tokens':10}]}
    metrics.sync_job(report)
    project=metrics.operation_totals(project_id='p');assert project['input']==50 and project['categories'][0]['kind']=='report'


def test_host_zero_and_legacy_known_receipt_survive_restart(fixture):
    chat,room,metrics=fixture
    host={'id':'zero','room_id':room['id'],'space':'central','action':'ask','structured_chat':True,'status':'completed',
          'context_usage':{'total_calls':0,'total_input_tokens':0,'total_output_tokens':0}}
    metrics.sync_job(host)
    value=metrics.operation_totals(room_id=room['id']);assert value['calls']==0 and value['input']==0 and value['input_unknown']==0
    older={**host,'id':'old','context_usage':{'total_calls':2,'total_input_tokens':120,'total_output_tokens':20}}
    metrics.sync_job(older);metrics.sync_job(older)
    restored=ContextMetrics(chat.store,metrics.projects)
    value=restored.operation_totals(room_id=room['id']);assert value['calls']==2 and value['input']==120 and value['output_unknown']==0


def test_background_summary_usage_is_separate_deduplicated_and_project_scoped(fixture):
    chat,room,metrics=fixture
    record={'id':'summary-attempt','room_id':room['id'],'agent_id':'central','project_id':'p',
            'receipt':{'status':'generated','calls':1,'input_tokens':100,'output_tokens':20,'provider':'local'}}
    metrics.record_summary(record);metrics.record_summary(record)
    value=metrics.operation_totals(room_id=room['id'])
    assert value['calls']==1 and value['input']==100 and value['output']==20
    assert value['categories'][0]['kind']=='memory_summary'
    assert metrics.operation_totals(project_id='p')['calls']==1
    metrics.record_summary({**record,'id':'interrupted-attempt','receipt':{'status':'deferred_for_chat'},
                            'model_usage':[{'id':'call','provider':'local','status':'started','input_tokens':None,'output_tokens':None}]})
    value=metrics.operation_totals(room_id=room['id'])
    assert value['calls']==2 and value['input_unknown']==1 and value['failed_events']==0
