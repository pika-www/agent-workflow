import assert from 'node:assert/strict';
import http from 'node:http';
import {nativeAgentRuntime,runNativeAgent} from '../federation/native-agent.mjs';
import {retryableTransport} from '../federation/native-retry.mjs';
const config={provider:'openai-compatible',model:'controlled-fixture',responses_api:true};
const messages=[{role:'user',content:'计算一个明确的假设'}];
const final={id:'final',type:'message',role:'assistant',phase:'final_answer',content:[{type:'output_text',text:'假设利润为 1000。'}]};
const commentary={...final,id:'intro',phase:'commentary',content:[{type:'output_text',text:'先计算假设。'}]};
const call={id:'tool-item',type:'function_call',name:'profit_calculate',call_id:'call-once',arguments:JSON.stringify({price:'50',unit_cost:'20',fixed_cost:'2000',units:'100',discount:'1'})};
function* frames(items) {
  for(const item of items){yield {type:'response.output_item.added',item};
    if(item.type==='message')yield {type:'response.output_text.delta',item_id:item.id,delta:item.content[0].text};
    yield {type:'response.output_item.done',item};}
  yield {type:'response.completed',response:{output:items,usage:{input_tokens:100,output_tokens:10}}};
}
for(const status of [400,401,403,422])assert.equal(retryableTransport({status}),false);
for(const status of [408,409,429,500,503])assert.equal(retryableTransport({status}),true);
assert.equal(retryableTransport({code:'ECONNRESET'}, {aborted:true}),false);
assert.equal(retryableTransport(new Error('上下文预算超限')),false);
let socketRequests=0; const delays=[], events=[];
const server=http.createServer(async(req,res)=>{for await(const _ of req){}socketRequests++;
  res.writeHead(503,{'content-type':'application/json'});res.end(JSON.stringify({error:{message:'controlled outage',type:'server_error',code:'server_error'}}));});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
try {
  const runtime=nativeAgentRuntime({...config,base_url:`http://127.0.0.1:${server.address().port}/v1`,api_key:'isolated-test-only'});
  await assert.rejects(runNativeAgent(runtime,messages,()=>{}, {retryWait:ms=>delays.push(ms),onAgentEvent:event=>events.push(event)}),error=>error.code==='reconnect_exhausted');
  assert.equal(socketRequests,6,'Real SDK makes one initial request and exactly five reconnections');
  assert.deepEqual(delays,[1000,2000,4000,8000,8000]);
  assert.deepEqual(events.map(event=>event.attempt),[1,2,3,4,5]);
}finally{await new Promise(resolve=>server.close(resolve));}
let requests=0,tools=0;const inputs=[],deltas=[],retries=[];
const client={responses:{async create(params){inputs.push(structuredClone(params.input));requests++;
  return (async function*(){if(requests===1){yield*frames([commentary,call]);return;}
    if(requests===2){yield {type:'response.output_item.added',item:final};yield {type:'response.output_text.delta',item_id:final.id,delta:'未完整接收的片段'};throw Object.assign(new Error('socket lost'),{code:'ECONNRESET'});}
    yield*frames([final]);})();}}};
const result=await runNativeAgent(nativeAgentRuntime(config,{client}),messages,async()=>{tools++;return {status:'completed',profit:'1000'};},
  {tools:['profit_calculate'],maxActions:1,retryWait:()=>{},onDelta:delta=>deltas.push(delta),onAgentEvent:event=>{if(event.origin==='host_transport')retries.push(event);}});
assert.equal(requests,3);assert.equal(tools,1);assert.deepEqual(inputs[1],inputs[2]);
assert.equal(inputs[2].find(item=>item.type==='function_call_output').call_id,'call-once');
assert.equal(result.answer,'假设利润为 1000。');assert.equal(result.native_stream.reconnects,1);
assert.equal(result.native_stream.message_items.length,2,'Interrupted messages never become retained chain items');
assert.equal(result.native_stream.usage.length,3,'The interrupted model attempt stays in usage evidence');
assert.deepEqual(retries[0].replace_ids,['native-2']);assert.equal(retries[0].replace_answer,true);
assert.equal(retries[1].type,'agent.transport.restored');
let chatCalls=0;const chatEvents=[];
const chat={chat:{completions:{async create(){chatCalls++;return (async function*(){yield {choices:[{delta:{content:chatCalls===1?'中断片段':'完整回答'}}]};
  if(chatCalls===1)return;yield {choices:[{delta:{},finish_reason:'stop'}]};})();}}}};
const chatResult=await runNativeAgent(nativeAgentRuntime({...config,responses_api:false},{client:chat}),messages,()=>{},
 {retryWait:()=>{},onAgentEvent:event=>chatEvents.push(event)});
assert.equal(chatCalls,2);assert.equal(chatResult.answer,'完整回答');
assert.equal(chatEvents.filter(event=>event.type==='agent.transport.retrying').length,1);
assert.equal(chatResult.native_stream.phase_source,'not_available');
let lastCalls=0;
const last={responses:{async create(){lastCalls++;if(lastCalls<=5)throw Object.assign(new Error('temporary'),{status:429});return (async function*(){yield*frames([final]);})();}}};
const lastResult=await runNativeAgent(nativeAgentRuntime(config,{client:last}),messages,()=>{}, {retryWait:()=>{}});
assert.equal(lastCalls,6);assert.equal(lastResult.native_stream.reconnects,5);
let budgetCalls=0;
await assert.rejects(runNativeAgent(nativeAgentRuntime(config,{client:{responses:{create(){budgetCalls++;}}}}),messages,()=>{}, {maxInputTokens:1,retryWait:()=>{}}),/自动压缩后/);
assert.equal(budgetCalls,0);
console.log('Native reconnect passed: real SDK six-request limit, backoff, stream interruption in both protocols, same call-ID/tool reuse, final-attempt success and permanent/aborted failure exclusion.');
