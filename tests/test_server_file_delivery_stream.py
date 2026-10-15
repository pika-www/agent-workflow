"""The actual JS delivery events must pass the Python stream contract."""
import json
import shutil
import subprocess
from pathlib import Path
import pytest
from federation.chat_stream import ReplyStreams

@pytest.mark.parametrize('count', [13, 40])
def test_delivery_stream_contract(tmp_path, count):
    script = '''
import {runServerFileDelivery} from './federation/server-file-delivery.mjs';
const events=[],room='a'.repeat(32),count=Number(process.argv[1]);
const result=await runServerFileDelivery({currentQuestion:'把服务器上的所有视频发给我',
 toolPolicy:{tools_enabled:true,services:{server_files:{configured:true,runtime_location:'server'}}},
 onAgentEvent:event=>events.push(event),executeTool:async(tool,args)=>{
  if(args.action==='find')return {status:'completed',entries:Array.from({length:count},(_,i)=>({kind:'file',path:'/srv/'+('long/'.repeat(45))+i+'.mp4',bytes:10,modified:i}))};
  const name=JSON.parse(args.parameters).path.split('/').at(-1),id=Number(name.split('.')[0]).toString(16).padStart(32,'0');
  return {status:'completed',artifacts:[{id,room_id:room,name,kind:'video',sha256:'b'.repeat(64),url:`/api/chat/rooms/${room}/files/${id}`}]};
 }});console.log(JSON.stringify({events,result}));
'''
    output = subprocess.run([shutil.which('node'), '--input-type=module', '-e', script, str(count)],
                            cwd=Path(__file__).resolve().parents[1], check=True, capture_output=True, text=True)
    value = json.loads(output.stdout)
    hub = ReplyStreams(tmp_path/'streams');rid='a'*32;jid='b'*32;hub.start(rid,jid)
    for event in value['events']:
        assert event['origin'] == 'host_tool'
        hub.accept_line(rid,jid,'OPENWIKI_AGENT_EVENT '+json.dumps(event))
    hub.accept_line(rid,jid,'OPENWIKI_REPLY '+json.dumps({'text':value['result']['answer']}))
    saved=hub.snapshot(rid,jid)
    assert len(saved['operations']) == min(count,31)+1
    assert all(op['status']=='completed' for op in saved['operations'])
    assert len(value['result']['artifacts'])==min(count,31)
    assert value['result']['context_usage']['total_calls']==0
