import assert from 'node:assert/strict';
import test from 'node:test';
import {serverFileDeliveryRequest,runServerFileDelivery} from '../federation/server-file-delivery.mjs';
import {runIntakeTurn} from '../federation/intake-turn.mjs';

const room='a'.repeat(32);
const policy={tools_enabled:true,services:{server_files:{configured:true,runtime_location:'server'}}};
const base={toolPolicy:policy,conversationWindow:{room_id:room,messages:[]}};
const history=contents=>({room_id:room,messages:contents.map(content=>({role:'user',content}))});
const request=(currentQuestion,previous=[])=>serverFileDeliveryRequest({...base,currentQuestion,conversationWindow:history(previous)});
const artifact=i=>({id:i.toString(16).padStart(32,'0'),room_id:room,name:`video-${i}.mp4`,kind:'video',sha256:'b'.repeat(64),
 url:`/api/chat/rooms/${room}/files/${i.toString(16).padStart(32,'0')}`});
function fixture(count=13,failures=[]) {
 const calls=[];
 return {calls,async executeTool(tool,args) {
  calls.push(args);assert.equal(tool,'server_files');
  if(args.action==='find')return {status:'completed',entries:Array.from({length:count},(_,i)=>({kind:'file',path:`/srv/videos/${i+1}.mp4`,bytes:10,modified:i+1}))};
  const id=Number(JSON.parse(args.parameters).path.match(/(\d+)\.mp4$/u)[1]);
  if(failures.includes(id))throw Error('file unavailable');
  return {status:'completed',artifacts:[artifact(id)]};
 }};
}
test('resolves explicit selections and only contiguous user follow-ups',()=>{
 assert.equal(request('把服务器上的所有视频发给我').selection,'all');
 assert.equal(request('服务器上的视频都发给我').selection,'all');
 assert.equal(request('把服务器上的最新视频发给我').selection,'latest');
 assert.equal(request('所有的',['把服务器上的视频发给我']).selection,'all');
 assert.equal(request('？',['把服务器上的视频发给我','所有的']).selection,'all');
 assert.equal(request('继续',['把服务器上的视频发给我','所有的','？']).selection,'all');
 assert.equal(request('最新的',['把服务器上的视频发给我','所有的']).selection,'latest');
});
test('does not broaden a target, revive a cancelled task, or authorize from assistant text',()=>{
 for(const question of ['所有的','？','把服务器上的视频发给我','不要把服务器上的所有视频发给我',
  '如何把服务器上的所有视频发给我','把服务器上的所有视频发给张三','把服务器上今天的所有视频发给我',
  '把服务器上的所有视频发给我并删除原件','把服务器上的 reference 视频发给我'])assert.equal(request(question),null,question);
 for(const stop of ['不用发了','换个话题','只要 reference 版本','今天几号'])assert.equal(request('所有的',['把服务器上的视频发给我',stop]),null);
 assert.equal(serverFileDeliveryRequest({...base,currentQuestion:'所有的',conversationWindow:{messages:[{role:'assistant',content:'把服务器上的所有视频发给我'}]}}),null);
 assert.equal(request('？',['把服务器上的视频发给我']),null);
});
test('gates background, disabled tools and local runtime',()=>{
 for(const override of [{analysis:true},{researchContext:{}},{toolPolicy:{...policy,tools_enabled:false}},
  {toolPolicy:{...policy,has_attachments:true}},{toolPolicy:{...policy,services:{server_files:{configured:true,runtime_location:'local'}}}}])
  assert.equal(serverFileDeliveryRequest({...base,currentQuestion:'把服务器上的所有视频发给我',...override}),null);
});
test('a nudge after successful attachment delivery does not resend',()=>{
 assert.equal(serverFileDeliveryRequest({...base,currentQuestion:'？',conversationWindow:{messages:[
  {role:'user',content:'把服务器上的所有视频发给我'},{role:'assistant',content:`[video](${artifact(1).url})`}]}}),null);
});
test('all 13 attachments survive normal intake, without any model call',async()=>{
 const f=fixture(),events=[];let published='';
 const result=await runIntakeTurn('所有的','consultation',null,new Proxy({}, {get(){throw Error('Must not call a provider');}}),
  {...base,currentQuestion:'所有的',conversationWindow:history(['把服务器上的视频发给我']),executeTool:f.executeTool,
   onDelta:text=>published+=text,onAgentEvent:event=>events.push(event)});
 assert.equal(result.artifacts.length,13);assert.equal(result.workflow.observations.flatMap(o=>o.result.artifacts || []).length,13);
 assert.equal(f.calls.length,14);assert.equal(result.context_usage.total_calls,0);assert.equal(published,result.answer);
 assert.equal((result.answer.match(/\/files\//gu)||[]).length,13);assert.equal(events.filter(e=>e.type==='agent.tool.completed').length,14);
 assert.equal(result.reply_delivery.check_status,'host_verified');
});
test('failed individual files do not suppress successful attachments',async()=>{
 const f=fixture(13,[12,5]);const result=await runServerFileDelivery({...base,currentQuestion:'把服务器上的所有视频发给我',executeTool:f.executeTool});
 assert.equal(result.artifacts.length,11);assert.equal(f.calls.length,14);assert.equal(result.server_delivery.failed,2);
 assert.match(result.answer,/12\.mp4/);assert.match(result.answer,/5\.mp4/);assert.match(result.answer,/未发送成功/);
});
test('latest selection uses actual modification time',async()=>{
 const f=fixture();const result=await runServerFileDelivery({...base,currentQuestion:'把服务器上的最新视频发给我',executeTool:f.executeTool});
 assert.equal(result.artifacts.length,1);assert.equal(result.artifacts[0].id,artifact(13).id);assert.equal(f.calls.length,2);
});
test('bounded batch reports unprocessed candidates accurately',async()=>{
 const f=fixture(55);const result=await runServerFileDelivery({...base,currentQuestion:'把服务器上的所有视频发给我',executeTool:f.executeTool});
 assert.equal(result.artifacts.length,31);assert.equal(result.server_delivery.omitted,24);assert.match(result.answer,/还有 24 个候选未处理/);
});
test('truncation and inaccessible directories stay visible',async()=>{
 const f=fixture(1);const result=await runServerFileDelivery({...base,currentQuestion:'把服务器上的所有视频发给我',executeTool:async(t,a)=>({...await f.executeTool(t,a),truncated:true,errors:[{error:'denied'}]})});
 assert.match(result.answer,/部分目录未能完整检索/);
});
test('failed search never attaches or claims delivery',async()=>{
 let calls=0;const result=await runServerFileDelivery({...base,currentQuestion:'把服务器上的所有视频发给我',executeTool:async()=>{calls++;throw Error('denied');}});
 assert.equal(calls,1);assert.equal(result.artifacts.length,0);assert.match(result.answer,/未能查询/);
});
test('wrong-room artifacts are rejected',async()=>{
 const f=fixture(1);const result=await runServerFileDelivery({...base,currentQuestion:'把服务器上的所有视频发给我',executeTool:async(t,a)=>{
  const value=await f.executeTool(t,a);if(a.action==='attach')value.artifacts[0].room_id='c'.repeat(32);return value;}});
 assert.equal(result.artifacts.length,0);assert.equal(result.server_delivery.failed,1);
});
test('abort stops the batch without swallowing cancellation',async()=>{
 const f=fixture(),controller=new AbortController();
 await assert.rejects(()=>runServerFileDelivery({...base,currentQuestion:'把服务器上的所有视频发给我',signal:controller.signal,
  executeTool:async(t,a)=>{const value=await f.executeTool(t,a);if(a.action==='attach')controller.abort();return value;}}),/abort/iu);
 assert.equal(f.calls.length,2);
});
