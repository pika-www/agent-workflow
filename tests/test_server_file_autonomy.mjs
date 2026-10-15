import assert from 'node:assert/strict';
import {serverFileLookup,serverReadAheadAllowed} from '../federation/server-file-autonomy.mjs';
import {runNativeAgent,nativeAgentRuntime} from '../federation/native-agent.mjs';
const policy={tools_enabled:true,services:{server_files:{configured:true,runtime_location:'server'}}};
const state={receipts:[],observations:[],allowed:['server_files']};
for(const question of ['服务器上有什么东西？','看看服务器上的目录'])
 assert.equal(serverFileLookup(question,policy).next(state).args.action,'discover');
for(const question of ['服务器上有个视频，发给我','你能把服务器上的视频发给我吗？','帮我找服务器上的视频'])
 assert.deepEqual(JSON.parse(serverFileLookup(question,policy).next(state).args.parameters),{kind:'video'});
for(const question of ['你好','不要搜索服务器视频','只解释服务器怎么存储视频','如何配置视频服务器','设计一个服务器视频功能','删除服务器上的视频','你能读取服务器文件吗？'])
 assert.equal(serverFileLookup(question,policy),null,question);
assert.equal(serverFileLookup('服务器有什么',{}),null);
assert.equal(serverFileLookup('服务器有什么',{...policy,tools_enabled:false}),null);
assert.equal(serverFileLookup('服务器有什么',{...policy,services:{server_files:{configured:true,runtime_location:'local'}}}),null);
const lookup=serverFileLookup('服务器上有个视频，发给我',policy);
assert.equal(lookup.next({...state,allowed:['web_search']}),null);
assert.equal(lookup.next({...state,receipts:[{tool:'server_files',args:{action:'find'},status:'failed'}]}),null,'Failure must not loop forever');
for(const action of ['exec','delete','write','move','attach'])
 assert.equal(serverReadAheadAllowed({tool:'server_files',args:{action}}),false);
let modelCalls=0;const executions=[],visible=[],requests=[];
const client={chat:{completions:{async create(params){
 modelCalls++;requests.push(structuredClone(params));
 assert(executions.length===1);
 assert(params.messages.some(m=>m.role==='system'&&m.content?.includes('/srv/uploads/actual.mp4')));
 return (async function*(){
  yield {choices:[{delta:{content:'找到 actual.mp4，大小 123 字节。'},finish_reason:null}]};
  yield {choices:[{delta:{},finish_reason:'stop'}]};
 })();
}}}};
const messages=[{role:'user',content:'服务器上有个视频，发给我'}];
const options={tools:['server_files'],hostServerReadAhead:true,nextRequiredTool:lookup.next,
 toolPolicyKey:lookup.key,maxActions:4,onDelta:text=>visible.push(text)};
let checkpoint;
await assert.rejects(()=>runNativeAgent(nativeAgentRuntime({provider:'openai-compatible',model:'fixture'},{client}),
 messages,async(tool,args)=>{
 executions.push({tool,args});return {status:'completed',matches:['/srv/uploads/actual.mp4'],entries:[{path:'/srv/uploads/actual.mp4',bytes:123}]};
 },{...options,onCheckpoint:value=>{checkpoint=structuredClone(value);throw new Error('fixture pause');}}),/fixture pause/);
assert.equal(modelCalls,0,'Discovery runs before a model can ask for a path');
const result=await runNativeAgent(nativeAgentRuntime({provider:'openai-compatible',model:'fixture'},{client}),
 messages,()=>{throw new Error('Lookup must not replay');},{...options,resumeCheckpoint:checkpoint});
assert.equal(executions.length,1);assert.equal(result.native_stream.resumed,true);
assert.equal(result.workflow.receipts[0].origin,'host_workflow');
assert.equal(result.native_stream.tool_calls.length,0);assert.equal(result.native_stream.host_tool_calls.length,1);
assert(!requests[0].messages.some(m=>m.role==='tool'||m.tool_calls),'Host reads never fabricate native calls');
assert.doesNotMatch(visible.join(''),/请.*路径|授权/);
console.log('Server discovery before model, current request scope, failure bounds, no mutations, real receipts and checkpoint resume passed.');
