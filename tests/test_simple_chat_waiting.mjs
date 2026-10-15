import assert from 'node:assert/strict';
import {nativeAgentRuntime,runNativeAgent} from '../federation/native-agent.mjs';
const config={provider:'openai-compatible',model:'fixture',responses_api:true};
const input=[{role:'system',content:'名称：未明；称呼：老王；记忆：测试项目。'},{role:'user',content:'你好'}];
const item={id:'final',type:'message',role:'assistant',phase:'final_answer',content:[{type:'output_text',text:'你好，老王。'}]};
let calls=0;const events=[],checkpoints=[],inputs=[],delays=[];
const client={responses:{async create(params){
 calls++;inputs.push(JSON.stringify(params.input));
 if(calls<=42)throw Object.assign(new Error('controlled timeout'),{name:'APIConnectionTimeoutError'});
 return (async function*(){
  yield {type:'response.output_item.added',item:{...item,content:[]}};
  yield {type:'response.output_text.delta',item_id:item.id,delta:item.content[0].text};
  yield {type:'response.output_item.done',item};
  yield {type:'response.completed',response:{output:[item],usage:{input_tokens:20,output_tokens:5}}};
 })();
}}};
const options={waitForModel:true,shortTextBudget:true,maxActions:0,tools:[],retryWait:ms=>delays.push(ms),
 onAgentEvent:e=>events.push(e),onCheckpoint:c=>checkpoints.push(c)};
const result=await runNativeAgent(nativeAgentRuntime(config,{client}),input,undefined,options);
assert.equal(result.answer,'你好，老王。');assert.equal(calls,43);
assert.equal(new Set(inputs).size,1,'Identity and memory are identical on every retry');
assert.equal(result.native_stream.reconnect_limit,null);assert.equal(result.native_stream.retry_policy,'until_cancelled');
assert.equal(result.native_stream.usage.length,43,'All attempted calls remain in usage');
assert.equal(checkpoints[0].usage.length,40,'The resumable checkpoint stays within its existing limit');
assert.deepEqual(delays.slice(0,6),[2000,4000,8000,16000,30000,30000]);
assert.ok(events.filter(e=>e.origin==='host_transport').every(e=>e.max_attempts===null&&e.retry_policy==='until_cancelled'));
// The explicit stop wins even after more than five timeouts.
let cancelledCalls=0;const controller=new AbortController();
const unavailable={responses:{async create(){cancelledCalls++;throw Object.assign(new Error('controlled outage'),{status:503});}}};
await assert.rejects(runNativeAgent(nativeAgentRuntime(config,{client:unavailable}),input,undefined,
 {...options,signal:controller.signal,retryWait:()=>{if(cancelledCalls===7)controller.abort(new Error('user stopped'));}}),/user stopped/);
assert.equal(cancelledCalls,7);
// Never apply continuous retries to a tool-capable operation.
let boundedCalls=0;
await assert.rejects(runNativeAgent(nativeAgentRuntime(config,{client:{responses:{async create(){boundedCalls++;throw Object.assign(new Error('outage'),{status:503});}}}}),input,undefined,
 {...options,maxActions:1,tools:['wiki_search']}),e=>e.code==='reconnect_exhausted');
assert.equal(boundedCalls,6);
console.log('Continuous greeting recovery: 42 timeouts then live answer, stable identity/memory, bounded backoff/checkpoint, explicit cancellation and tool-scope guard passed.');
