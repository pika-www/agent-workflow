import json
import tempfile
from pathlib import Path
import pytest
from federation.chat_stream import ReplyStreams
from unittest.mock import AsyncMock, patch, MagicMock
import asyncio
from federation.workflow_tools import execute

def test_original_native_deltas_sequence_replay_and_snapshot():
    hub=ReplyStreams(); hub.start('room','job',turn_id='turn')
    event={'origin':'provider','protocol':'responses','type':'response.output_text.delta',
           'response_id':'response-1','item_id':'message-1','phase':'commentary','update_id':'abcd-native-1','delta':'先核对。'}
    assert hub.accept_line('room','job','OPENWIKI_AGENT_EVENT '+json.dumps(event))
    hub.update('room','job',{'id':event['update_id'],'title':'Agent 中间回答','text':event['delta'],'status':'streaming'})
    frame=hub.native_events('room','job')[0]
    assert frame['delta']==event['delta'] and frame['phase']=='commentary' and frame['seq']==1
    assert hub.native_events('room','job',1)==[]
    assert hub.snapshot('room','job')['native_seq']==1
    assert hub.snapshot('room','job')['updates'][0]['text']==event['delta']
    hub.native_event('room','other',event)
    assert len(hub.native_events('room','job'))==1
    for bad in [{**event,'type':'response.reasoning_text.delta'}, {**event,'arguments':'secret'},
                {**event,'phase':'thinking'}, {**event,'delta':'x'*4097},
                {'origin':'host_tool','protocol':'responses','type':'agent.tool.started','call_id':'x','name':'shell_execute'}]:
        with pytest.raises(ValueError): hub.native_event('room','job',bad)
    hub.start('room','job',turn_id='turn-2')
    assert hub.native_events('room','job',0)[0]['seq']==1
    hub.clear('room','job')
    assert hub.snapshot('room','job') is None
    assert hub.native_events('room','job',0)[0]['seq']==1, 'Final deltas remain drainable before done'
    hub.start('room','different')
    assert hub.native_events('room','different')==[]

def test_public_reader_failure_code_survives_existing_stream_schema():
    hub=ReplyStreams(); hub.start('room','job')
    event={'origin':'host_tool','protocol':'responses','type':'agent.tool.completed',
           'call_id':'blocked-page','name':'web_read','target':'https://example.com/',
           'status':'robots_blocked','elapsed_ms':287}
    hub.native_event('room','job',event)
    assert hub.snapshot('room','job')['operations'][0]['status']=='robots_blocked'
    assert hub.settled_operations(hub.snapshot('room','job')['operations'])[0]['status']=='robots_blocked'

def test_context_compaction_is_a_host_event_not_model_text():
    with tempfile.TemporaryDirectory() as root:
        hub=ReplyStreams(Path(root));room='a'*32;job='b'*32;hub.start(room,job,turn_id='same')
        event={'origin':'host_context','protocol':'responses','type':'agent.context.compacted',
               'before_tokens':18000,'after_tokens':6500,'budget_tokens':12000}
        hub.native_event(room,job,event)
        assert hub.snapshot(room,job)['text']==''
        assert hub.snapshot(room,job)['operations']==[]
        assert hub.snapshot(room,job)['context_compaction']['after_tokens']==6500
        assert hub.load_saved(job)['preview']['context_compaction']['before_tokens']==18000
        hub.start(room,job,turn_id='same')
        assert hub.snapshot(room,job)['context_compaction']['after_tokens']==6500
        hub.native_event(room,job,{**event,'stage':'runtime'})
        assert hub.snapshot(room,job)['context_compaction']['stage']=='runtime'
        assert hub.load_saved(job)['preview']['context_compaction']['stage']=='runtime'
        with pytest.raises(ValueError):hub.native_event(room,job,{**event,'stage':'selection'})
        for bad in [{**event,'origin':'provider'}, {**event,'after_tokens':19000}, {**event,'after_tokens':True}, {**event,'text':'invented'}]:
            with pytest.raises(ValueError): hub.native_event(room,job,bad)

def test_native_checkpoint_private_integrity_and_phase():
    with tempfile.TemporaryDirectory() as root:
        hub=ReplyStreams(Path(root));room='a'*32;job='b'*32;hub.start(room,job)
        state={'schema_version':1,'kind':'native_agent','fingerprint':'c'*64,'protocol':'responses','input':[
            {'role':'user','content':'question'},
            {'type':'message','role':'assistant','phase':'commentary','content':[]},
            {'type':'function_call','call_id':'call-1','name':'profit_calculate','arguments':'{}'},
            {'type':'function_call_output','call_id':'call-1','output':'{}'}],
            'turn_index':1,'visible_count':1,'answer':'','observations':[],'receipts':[], 'message_items':[],'usage':[],'completed':False}
        hub.checkpoint(room,job,state)
        saved=hub.load_saved(job)['checkpoint']
        assert saved==state and saved['input'][1]['phase']=='commentary'
        assert (Path(root)/(job+'.json')).stat().st_mode & 0o077 ==0
        compaction={'method':'extractive','stage':'runtime','history_preserved':True,
                    'before_tokens':18000,'after_tokens':6500,'budget_tokens':8000,
                    'before_sha256':'d'*64,'after_sha256':'e'*64}
        hub.checkpoint(room,job,{**state,'context_compactions':[compaction]})
        assert hub.load_saved(job)['checkpoint']['context_compactions']==[compaction]
        with pytest.raises(ValueError):hub.checkpoint(room,job,{**state,'context_compactions':[{**compaction,'stage':'selection'}]})
        with pytest.raises(ValueError):hub.checkpoint(room,job,{**state,'extra':'arbitrary'})
        with pytest.raises(ValueError):hub.checkpoint(room,job,{**state,'input':[{'role':'user','phase':'commentary'}]})

def test_report_native_tool_retains_existing_public_reader_profile():
    context={'base':'/isolated','space':'central','network_allowed':True,'research_profile':'product-analysis'}
    reader=AsyncMock(return_value={'status':'completed','sources':[]})
    with patch('federation.workflow_tools.FederationStore',return_value=MagicMock()), patch('federation.workflow_tools.research_project',reader):
        asyncio.run(execute(context,'web_read',{'url':'https://example.com/'}))
    assert reader.call_args.kwargs['profile']=='product-analysis'
    with pytest.raises(ValueError):asyncio.run(execute({**context,'network_allowed':False},'web_read',{'url':'https://example.com/'}))

def test_tool_operations_survive_snapshot_replay_and_private_recovery():
    with tempfile.TemporaryDirectory() as root:
        hub=ReplyStreams(Path(root)); room='a'*32; job='b'*32
        hub.start(room,job,turn_id='turn',native_protocol='responses')
        start={'origin':'host_tool','protocol':'responses','type':'agent.tool.started',
               'call_id':'call-web','name':'web_read','target':'https://example.com/page'}
        hub.native_event(room,job,start)
        assert hub.snapshot(room,job)['text']==''
        assert hub.snapshot(room,job)['operations'][0]['status']=='running'
        saved=hub.load_saved(job)
        assert saved['preview']['operations'][0]['target']==start['target']
        done={**start,'type':'agent.tool.completed','status':'failed','elapsed_ms':750,'output_sha256':'f'*64}
        hub.native_event(room,job,done)
        hub.native_event(room,job,start)  # A replayed start never reverses completion.
        snapshot=hub.snapshot(room,job)
        assert len(snapshot['operations'])==1 and snapshot['operations'][0]['status']=='failed'
        assert snapshot['operations'][0]['elapsed_ms']==750
        snapshot['operations'][0]['status']='tampered'
        assert hub.snapshot(room,job)['operations'][0]['status']=='failed'
        hub.start(room,job,turn_id='turn')
        assert hub.snapshot(room,job)['operations'][0]['status']=='failed'
        hub.native_event(room,job,{**start,'call_id':'call-calc','name':'profit_calculate','target':''})
        assert hub.settled_operations(hub.snapshot(room,job)['operations'],interrupted=True)[1]['status']=='interrupted'
        assert hub.load_saved(job)['preview']['operations'][1]['status']=='running'
        hub.start(room,'c'*32)
        assert hub.snapshot(room,'c'*32)['operations']==[]
        for bad in [{**start,'elapsed_ms':True},{**start,'elapsed_ms':-1},
                    {**start,'elapsed_ms':86400001},{**start,'target':'x'*201},
                    {**start,'arguments':'PRIVATE'}, {**start,'origin':'provider'}]:
            with pytest.raises(ValueError):hub.native_event(room,'c'*32,bad)


def test_operations_are_kept_with_completed_and_failed_api_answers():
    from fastapi.testclient import TestClient
    from federation.app import create_app
    import time
    for failing in (False,True):
        with tempfile.TemporaryDirectory() as root:
            async def runner(job,store):
                stream=app.state.reply_streams
                start={'origin':'host_tool','protocol':'responses','type':'agent.tool.started',
                       'call_id':'actual-test-tool','name':'profit_calculate','target':''}
                stream.native_event(job['room_id'],job['parent_job_id'],start)
                if failing:raise ValueError('controlled interruption')
                stream.native_event(job['room_id'],job['parent_job_id'],{**start,'type':'agent.tool.completed',
                    'status':'completed','elapsed_ms':4,'output_sha256':'d'*64})
                job['answer']='计算已完成。'
            app=create_app(base=Path(root)/'data',runner=runner)
            with TestClient(app) as client:
                room=client.post('/api/chat/primary',json={}).json()
                sent=client.post('/api/chat/rooms/'+room['id']+'/messages',json={'content':'解释假设收入与成本'}).json()
                for _ in range(150):
                    job=client.get('/api/jobs/'+sent['job']['id']).json()
                    if job['status'] in {'completed','failed'}:break
                    time.sleep(.01)
                assert job['status']==('failed' if failing else 'completed')
                message=client.get('/api/chat/rooms/'+room['id']).json()['messages'][-1]
                assert message['operations'][0]['call_id']=='actual-test-tool'
                assert message['operations'][0]['status']==('interrupted' if failing else 'completed')
                assert message['reply_timeline'][0]['kind']=='tools'
                assert message['reply_timeline'][0]['call_ids']==['actual-test-tool']
                assert app.state.store.space('central')['knowledge_count']==0

def test_reply_timeline_tracks_order_without_copying_text_or_arguments():
    hub=ReplyStreams();hub.start('room','job',turn_id='turn',native_protocol='responses')
    text={'origin':'provider','protocol':'responses','type':'response.output_text.delta','item_id':'message',
          'phase':'commentary','update_id':'abcd-native-1','delta':'先读取。'}
    tool={'origin':'host_tool','protocol':'responses','type':'agent.tool.started','call_id':'web-1','name':'web_read'}
    hub.native_event('room','job',text)
    hub.native_event('room','job',text)
    hub.native_event('room','job',tool)
    hub.native_event('room','job',{**tool,'type':'agent.tool.completed','status':'completed'})
    hub.native_event('room','job',{**text,'update_id':'abcd-native-2','delta':'继续计算。'})
    hub.native_event('room','job',{**tool,'call_id':'calc-1','name':'profit_calculate'})
    hub.native_event('room','job',{**text,'phase':'final_answer','delta':'最终结果。'})
    timeline=hub.snapshot('room','job')['timeline']
    assert [entry['kind'] for entry in timeline]==['text','tools','text','tools','text']
    assert timeline[1]['call_ids']==['web-1'] and timeline[3]['call_ids']==['calc-1']
    assert timeline[-1]['source']=='answer'
    assert '先读取' not in json.dumps(timeline) and 'arguments' not in json.dumps(timeline)
    timeline[1]['call_ids'].append('tampered')
    assert hub.snapshot('room','job')['timeline'][1]['call_ids']==['web-1']
    hub.start('room','job',turn_id='turn')
    assert len(hub.snapshot('room','job')['timeline'])==5
    hub.start('room','job',agent_id='another',turn_id='other-turn')
    assert hub.snapshot('room','job')['timeline']==[]


def test_native_chat_final_text_uses_the_same_timeline_slot():
    hub=ReplyStreams();hub.start('room','job',native_protocol='chat_completions')
    event={'origin':'provider','protocol':'chat_completions','type':'chat.completion.content.delta',
           'update_id':'abcd-native-1','delta':'结果。'}
    hub.native_event('room','job',event)
    hub.update('room','job',{'id':'abcd-native-1','title':'Agent 回复','text':'结果。','status':'completed'})
    hub.append('room','job','结果。')
    assert hub.snapshot('room','job')['timeline']==[{'kind':'text','source':'answer','id':'answer'}]


def test_visual_browser_operation_stream_uses_real_host_origin():
    from federation.chat_stream import ReplyStreams
    hub=ReplyStreams();hub.start('room','job',turn_id='visual-turn',native_protocol='responses')
    event={'origin':'host_tool','protocol':'responses','type':'agent.tool.started','call_id':'visual-call','name':'visual_browser','target':'https://example.com/'}
    hub.native_event('room','job',event)
    hub.native_event('room','job',{**event,'type':'agent.tool.completed','status':'completed','elapsed_ms':1250})
    assert hub.snapshot('room','job')['operations'][0]['name']=='visual_browser'
    assert hub.snapshot('room','job')['operations'][0]['status']=='completed'


def test_parallel_public_reads_and_crosscheck_remain_distinct_operations():
    hub=ReplyStreams();hub.start('room','job')
    base={'origin':'host_tool','protocol':'responses'}
    for i in range(3):
        hub.native_event('room','job',{**base,'type':'agent.tool.started','call_id':f'read-{i}','name':'web_read','target':f'https://source{i}.example/news'})
    snapshot=hub.snapshot('room','job')
    assert len(snapshot['operations'])==3
    assert all(o['status']=='running' for o in snapshot['operations'])
    for i in [2,0,1]:
        hub.native_event('room','job',{**base,'type':'agent.tool.completed','call_id':f'read-{i}','name':'web_read','status':'completed','elapsed_ms':120})
    hub.native_event('room','job',{**base,'type':'agent.tool.started','call_id':'review-1','name':'research_review'})
    hub.native_event('room','job',{**base,'type':'agent.tool.completed','call_id':'review-1','name':'research_review','status':'completed'})
    operations=hub.snapshot('room','job')['operations']
    assert [o['call_id'] for o in operations]==['read-0','read-1','read-2','review-1']
    assert all(o['status']=='completed' for o in operations)


def test_research_progress_budget_preserves_more_than_twelve_updates():
    hub=ReplyStreams();hub.start('room','job')
    for i in range(14):
        hub.update('room','job',{'id':f'native-{i}','title':'Agent 回复','text':'核对来源。','status':'streaming'})
    assert len(hub.snapshot('room','job')['updates'])==14


def test_real_node_soft_budget_receipt_matches_host_checkpoint_contract():
    import subprocess
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    script="""import {compactNativeContext} from './federation/native-context.mjs';
const history=Array.from({length:30},(_,i)=>'\\n<material kind="conversation:'+i+'">\\n'+JSON.stringify({id:String(i),content:'合成背景。'.repeat(100)})+'\\n</material>').join('');
const input=[{role:'system',content:'保留必要规则'},{role:'system',content:history},{role:'user',content:'当前预算是多少？'}];
const result=compactNativeContext(input,{maxTokens:28160,softTokens:1200,materialIndex:1,question:'当前预算是多少？'});
process.stdout.write(JSON.stringify(result));"""
    value=json.loads(subprocess.check_output(['node','--input-type=module','-e',script],cwd=root,text=True))
    assert value['receipt'] and value['receipt']['after_tokens']<=28160
    state={'schema_version':1,'kind':'native_agent','fingerprint':'c'*64,'protocol':'responses',
           'input':value['input'],'turn_index':0,'visible_count':0,'answer':'','observations':[],
           'receipts':[],'message_items':[],'usage':[],'completed':False,'context_compactions':[value['receipt']]}
    ReplyStreams._validate_checkpoint(state)
