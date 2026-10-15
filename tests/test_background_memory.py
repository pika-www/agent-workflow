"""Real HTTP/queue/memory persistence; controlled models in disposable stores."""
import asyncio
import copy
import json
import threading
import time
import uuid
import pytest
from fastapi.testclient import TestClient
from federation.app import create_app


class NoRouter:
    def status(self): return {'enabled':False,'configured':False}
    async def classify(self, *args): return {'status':'disabled','calls':0}


def wait(check, seconds=3):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        value=check()
        if value:return value
        time.sleep(.01)
    raise AssertionError('Timed out waiting for controlled background state')


def seed(app):
    chat,memory=app.state.chat,app.state.context_memory
    room=chat.primary_room()
    for i in range(10):
        round_id=uuid.uuid4().hex
        chat.append_message(room,'user','继续会话摘要测试，保留聊天原文。',round_id=round_id)
        context=memory.prepare(room,'继续会话摘要测试，保留聊天原文。','central',round_id)
        chat.append_message(room,'assistant','会话摘要用于压缩续聊资料。',agent_id='central',phase='consultation',round_id=round_id)
        memory.complete_turn(room,context,round_id)
    chat.save_room(room)
    return room['id']


def runners(fail=False):
    entered,release,cancelled=threading.Event(),threading.Event(),threading.Event()
    async def answer(job,store):
        job['answer']='这条回答已经完成。'
        context=job.get('context_memory')
        job['context_usage']={'enabled':True,'summary':{'status':'background_pending' if context and context['summary_request'] else 'not_needed','calls':0},'total_calls':1,'total_input_tokens':20,'total_output_tokens':5}
    async def summary(entry,store):
        entered.set()
        try:
            while not release.is_set():await asyncio.sleep(.01)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        if fail:raise ValueError('Controlled summary failure')
        context=entry['context'];ids=[m['id'] for m in context['summary_request']['messages']]
        return {'update':{'goal':context['goal'],'constraints':[],'decisions':[],'progress':[],'open_questions':[],'source_ids':ids},'receipt':{'status':'generated','calls':1,'input_tokens':100,'output_tokens':20,'provider':'fixture','model':'fixture'}}
    return answer,summary,entered,release,cancelled


def post(client,room):
    accepted=client.post('/api/chat/rooms/'+room+'/messages',json={'content':'继续会话摘要测试，解释这个方案。'})
    assert accepted.status_code==200,accepted.text
    return wait(lambda: (r if (r:=client.get('/api/chat/rooms/'+room).json())['status']=='idle' else None))


def entries(app):return [json.loads(p.read_text()) for p in app.state.background_summaries.directory.glob('*.json')]


def test_reply_finishes_before_summary_and_new_message_preempts(tmp_path):
    answer,summary,entered,release,cancelled=runners()
    app=create_app(base=tmp_path,runner=answer,summary_runner=summary,summary_idle_seconds=.02,decision_router=NoRouter())
    with TestClient(app) as client:
        room=seed(app);first=post(client,room)
        assert entered.wait(2)
        assert first['active_job_id'] is None and first['messages'][-1]['status']=='completed'
        old=copy.deepcopy(first['messages'])
        start=time.monotonic();second=post(client,room)
        assert time.monotonic()-start<1 and cancelled.is_set(),'A new reply must not wait for a blocked summary'
        assert second['messages'][:len(old)]==old,'Preemption cannot change already-completed text or metadata'
        release.set()
        wait(lambda:any(e['status']=='saved' for e in entries(app)))
        final=client.get('/api/chat/rooms/'+room).json()
        assert final['messages']==second['messages'] and final['status']=='idle'
        state=app.state.context_memory.inspect(room,'central')
        assert any(t['covered_ids'] and t['summary'] for t in state['tasks'])
        attempts=list((app.state.background_summaries.directory/'attempts').glob('*.json'))
        assert len(attempts)>=2,'Cancelled and completed attempts retain separate usage receipts'


def test_summary_failure_does_not_fail_or_modify_reply(tmp_path):
    answer,summary,entered,release,_=runners(fail=True)
    app=create_app(base=tmp_path,runner=answer,summary_runner=summary,summary_idle_seconds=.01,decision_router=NoRouter())
    with TestClient(app) as client:
        room=seed(app);completed=post(client,room);assert entered.wait(2);release.set()
        wait(lambda:any(e['status']=='failed_using_previous_and_originals' for e in entries(app)))
        after=client.get('/api/chat/rooms/'+room).json()
        assert after['status']=='idle' and after['messages']==completed['messages']
        assert not app.state.context_memory.inspect(room,'central')['tasks'][-1]['covered_ids']


def test_manual_correction_invalidates_queued_summary(tmp_path):
    answer,summary,entered,release,cancelled=runners()
    app=create_app(base=tmp_path,runner=answer,summary_runner=summary,summary_idle_seconds=.01,decision_router=NoRouter())
    with TestClient(app) as client:
        room=seed(app);completed=post(client,room);assert entered.wait(2)
        state=app.state.context_memory.inspect(room,'central');task=state['tasks'][-1]
        result=client.post('/api/chat/rooms/'+room+'/context-memory',json={'agent_id':'central','task_id':task['id'],'expected_revision':state['revision'],'action':'correct_summary','text':'人工修订应保留。'})
        assert result.status_code==200,result.text
        assert cancelled.is_set();release.set()
        wait(lambda:any(e['status']=='stale' for e in entries(app)))
        current=app.state.context_memory.inspect(room,'central')['tasks'][-1]
        assert current['manual_summary']['text']=='人工修订应保留。'
        assert client.get('/api/chat/rooms/'+room).json()['messages']==completed['messages']


def test_restart_recovers_pending_memory_without_replaying_reply(tmp_path):
    answer,summary,entered,release,cancelled=runners()
    app=create_app(base=tmp_path,runner=answer,summary_runner=summary,summary_idle_seconds=.01,decision_router=NoRouter())
    with TestClient(app) as client:
        room=seed(app);completed=post(client,room);assert entered.wait(2)
    assert cancelled.is_set()
    entered.clear();release.set()
    restored=create_app(base=tmp_path,runner=answer,summary_runner=summary,summary_idle_seconds=.01,decision_router=NoRouter())
    with TestClient(restored) as client:
        wait(lambda:any(e['status']=='saved' for e in entries(restored)))
        assert entered.is_set()
        assert client.get('/api/chat/rooms/'+room).json()['messages']==completed['messages']


def test_background_summary_respects_room_model_budget(tmp_path):
    answer,summary,entered,release,_=runners()
    app=create_app(base=tmp_path,runner=answer,summary_runner=summary,summary_idle_seconds=.03,decision_router=NoRouter())
    with TestClient(app) as client:
        room=seed(app);completed=post(client,room)
        app.state.context_metrics.set_limits(room,0,1,0)
        wait(lambda:any(e['status']=='skipped_budget' for e in entries(app)))
        assert not entered.is_set(),'A memory job cannot bypass the model-call limit'
        assert client.get('/api/chat/rooms/'+room).json()['messages']==completed['messages']


def test_foreground_request_holds_priority_beyond_idle_delay(tmp_path):
    answer,summary,entered,release,cancelled=runners()
    app=create_app(base=tmp_path,runner=answer,summary_runner=summary,summary_idle_seconds=.01,decision_router=NoRouter())
    with TestClient(app) as client:
        room=seed(app);post(client,room);assert entered.wait(2)
        async def routing_wait():
            async with app.state.background_summaries.foreground_request():
                entered.clear()
                await asyncio.sleep(.1)
                assert cancelled.is_set() and not entered.is_set(),'Routing must retain priority until it returns'
            release.set()
        client.portal.call(routing_wait)
        wait(lambda:any(e['status']=='saved' for e in entries(app)))


def test_disabling_memory_does_not_run_already_queued_summary(tmp_path,monkeypatch):
    answer,summary,entered,release,_=runners()
    app=create_app(base=tmp_path,runner=answer,summary_runner=summary,summary_idle_seconds=.1,decision_router=NoRouter())
    with TestClient(app) as client:
        room=seed(app);completed=post(client,room)
        previous=copy.deepcopy(app.state.context_memory.inspect(room,'central'))
        monkeypatch.setenv('FEDERATION_CONTEXT_ENABLED','false')
        wait(lambda:any(e['status']=='feature_disabled' for e in entries(app)))
        assert not entered.is_set()
        assert app.state.context_memory.inspect(room,'central')==previous
        assert client.get('/api/chat/rooms/'+room).json()['messages']==completed['messages']
