import json
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient
import pytest
from federation.chat_stream import ReplyStreams
from federation.app import create_app
from tests.test_reply_recovery import wait


def test_retry_replaces_only_interrupted_response_and_preserves_tools():
    hub = ReplyStreams(); hub.start('room', 'job', native_protocol='responses')
    text = {'origin':'provider','protocol':'responses','type':'response.output_text.delta','item_id':'message',
            'phase':'commentary','update_id':'saved-native-1','delta':'已完整读取的答复'}
    hub.native_event('room','job',text)
    hub.update('room','job',{'id':'saved-native-1','title':'Agent 回复','text':text['delta'],'status':'completed'})
    tool={'origin':'host_tool','protocol':'responses','type':'agent.tool.completed','call_id':'once','name':'profit_calculate','status':'completed'}
    hub.native_event('room','job',tool)
    partial={**text,'phase':'final_answer','update_id':'saved-native-2','delta':'中断片段'}
    hub.native_event('room','job',partial);hub.append('room','job','中断片段')
    retry={'origin':'host_transport','protocol':'responses','type':'agent.transport.retrying','attempt':1,'max_attempts':5,
           'delay_ms':1000,'replace_ids':['saved-native-2'],'replace_answer':True}
    hub.native_event('room','job',retry)
    snapshot=hub.snapshot('room','job')
    assert snapshot['text']=='' and snapshot['updates'][0]['text']==text['delta']
    assert snapshot['operations'][0]['call_id']=='once'
    assert snapshot['transport_retry']['status']=='retrying'
    assert [entry['kind'] for entry in snapshot['timeline']]==['text','tools']
    restored={k:v for k,v in retry.items() if k not in {'replace_ids','replace_answer','delay_ms'}}
    restored['type']='agent.transport.restored';hub.native_event('room','job',restored)
    assert hub.snapshot('room','job')['transport_retry']['status']=='restored'
    for bad in [{**retry,'origin':'provider'},{**retry,'attempt':6},{**retry,'attempt':True},
                {**retry,'max_attempts':True},{**retry,'replace_ids':['secret\x00']},{**retry,'replace_answer':'yes'}]:
        with pytest.raises(ValueError):hub.native_event('room','job',bad)


def test_budget_failure_is_not_presented_as_recoverable_connection():
    async def runner(turn,store):
        raise ValueError('当前完整问题与必要规则超过上下文预算，没有截断问题。')
    with tempfile.TemporaryDirectory() as root:
        app=create_app(base=Path(root)/'data',runner=runner)
        with TestClient(app) as client:
            room=client.post('/api/chat/primary',json={}).json();url='/api/chat/rooms/'+room['id']
            sent=client.post(url+'/messages',json={'content':'什么是上下文？'}).json();job=sent['job']['id']
            assert wait(client,job)['status']=='failed'
            message=client.get(url).json()['messages'][-1]
            assert message['recoverable_job_id'] is None
            assert client.post(url+'/jobs/'+job+'/resume',json={}).status_code==409


def test_continuous_waiting_retries_preserve_strict_event_validation():
    hub = ReplyStreams(); hub.start('room','job',native_protocol='responses')
    event = {'origin':'host_transport','protocol':'responses','type':'agent.transport.retrying',
             'attempt':42,'max_attempts':None,'retry_policy':'until_cancelled',
             'delay_ms':30000,'replace_ids':[],'replace_answer':False}
    hub.native_event('room','job',event)
    assert hub.snapshot('room','job')['transport_retry'] == {
        'attempt':42,'max_attempts':None,'retry_policy':'until_cancelled','status':'retrying'}
    for patch in ({'max_attempts':5},{'retry_policy':'forever'},{'attempt':True},{'delay_ms':30001},{'origin':'provider'}):
        with pytest.raises(ValueError):hub.native_event('room','job',{**event,**patch})


def test_sse_reconnect_cursor_and_exhausted_failure_metadata():
    async def runner(turn,store):
        hub=app.state.reply_streams
        for attempt in range(1,6):
            hub.native_event(turn['room_id'],turn['parent_job_id'],{'origin':'host_transport','protocol':'responses',
                'type':'agent.transport.retrying','attempt':attempt,'max_attempts':5,'replace_ids':[],'replace_answer':False,'delay_ms':1000})
        raise ValueError('自动重连 5 次仍失败，请稍后再试。')
    with tempfile.TemporaryDirectory() as root:
        app=create_app(base=Path(root)/'data',runner=runner)
        with TestClient(app) as client:
            room=client.post('/api/chat/primary',json={}).json();url='/api/chat/rooms/'+room['id']
            sent=client.post(url+'/messages',json={'content':'解释模型连接。'}).json();job=sent['job']['id']
            assert wait(client,job)['status']=='failed'
            message=client.get(url).json()['messages'][-1]
            assert message['transport_retry']=={'attempt':5,'max_attempts':5,'status':'exhausted'}
            stream=client.get(url+'/events',params={'job_id':job,'after':3}).text
            assert 'id: 4\n' in stream and 'id: 5\n' in stream
            assert 'id: 1\n' not in stream and 'id: 3\n' not in stream
            assert 'event: done' in stream
