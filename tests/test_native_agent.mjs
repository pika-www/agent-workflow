/** SDK/SSE transport contract tests. Fixture output is not real-model proof. */
import assert from 'node:assert/strict';
import http from 'node:http';
import {nativeAgentRuntime,runNativeAgent,nativeToolTarget} from '../federation/native-agent.mjs';
const originalLocalTimeout=process.env.WEIMING_LOCAL_MODEL_TIMEOUT_SECONDS;
try {
 process.env.WEIMING_LOCAL_MODEL_TIMEOUT_SECONDS='1800';
 const local=nativeAgentRuntime({provider:'openai-compatible',model:'local',base_url:'http://127.0.0.1:11436/v1'});
 assert.equal(local.client.timeout,1800000,'CPU chat fallback must use the same timeout as learning');
 const cloud=nativeAgentRuntime({provider:'openai-compatible',model:'cloud',base_url:'https://cloud.example/v1'});
 assert.equal(cloud.client.timeout,120000,'Cloud transport keeps its original timeout');
} finally {
 if(originalLocalTimeout===undefined)delete process.env.WEIMING_LOCAL_MODEL_TIMEOUT_SECONDS;
 else process.env.WEIMING_LOCAL_MODEL_TIMEOUT_SECONDS=originalLocalTimeout;
}
assert.equal(nativeToolTarget('web_read',{url:'https://user:SECRET@example.com/page?token=SECRET#private'}),'https://example.com/page');
assert.equal(nativeToolTarget('wiki_search',{query:'RAG token=SECRET\nAPI_KEY: SECRET'}),'RAG [已隐藏] [已隐藏]');
const commentary={id:'msg-interim',type:'message',role:'assistant',phase:'commentary',status:'completed',content:[{type:'output_text',text:'先核对利润。',annotations:[]}]};
const reasoning={id:'reasoning-private',type:'reasoning',encrypted_content:'opaque-private-state',summary:[]};
const call={id:'fc-calc',type:'function_call',call_id:'call-exact-17',name:'profit_calculate',arguments:JSON.stringify({price:'25',unit_cost:'10',fixed_cost:'500',units:'100',discount:'1'}),status:'completed'};
const final={id:'msg-final',type:'message',role:'assistant',phase:'final_answer',status:'completed',content:[{type:'output_text',text:'假设利润为1000。',annotations:[]}]};
function responseEvents(id,items) {
 const events=[{type:'response.created',response:{id}}];
 for(const item of items) {
  events.push({type:'response.output_item.added',item:{...item,content:[],arguments:''}});
  if(item.type==='message') {
   const value=item.content[0]?.text || '';
   events.push({type:'response.output_text.delta',item_id:item.id,delta:value.slice(0,3)},
    {type:'response.reasoning_text.delta',item_id:'reasoning-private',delta:'PRIVATE_DO_NOT_DISPLAY'},
    {type:'response.output_text.delta',item_id:item.id,delta:value.slice(3)});
  }
  events.push({type:'response.output_item.done',item});
 }
 events.push({type:'response.completed',response:{id,output:items,usage:{input_tokens:100,output_tokens:30}}});return events;
}
const requests=[];
const server=http.createServer(async(req,res)=>{
 let body='';for await(const chunk of req)body+=chunk;
 requests.push(JSON.parse(body));assert.equal(req.url,'/v1/responses');
 res.writeHead(200,{'Content-Type':'text/event-stream'});
 for(const event of responseEvents('response-'+requests.length,requests.length===1?[reasoning,commentary,call]:[final]))
  res.write('event: '+event.type+'\ndata: '+JSON.stringify(event)+'\n\n');
 res.end();
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const config={provider:'openai-compatible',model:'fixture',api_key:'test-only',responses_api:true};
const messages=[{role:'system',content:'Scoped'}, {role:'user',content:'Calculate'}];
const updates=[],deltas=[],visible=[],tools=[];let checkpoint;
try {
 const wireConfig={...config,base_url:'http://127.0.0.1:'+server.address().port+'/v1'};
 const runtime=nativeAgentRuntime(wireConfig);
 const result=await runNativeAgent(runtime,messages,async(name,args)=>{tools.push({name,args});return {status:'completed',profit:'1000'};},
  {tools:['profit_calculate'],maxActions:1,onUpdate:v=>updates.push(v),onDelta:v=>deltas.push(v),onAgentEvent:v=>visible.push(v),onCheckpoint:v=>{checkpoint=structuredClone(v);}});
 assert.equal(requests.length,2,'One execution continues after the tool; no independent initial-answer call');
 assert.deepEqual(requests[1].input.slice(0,5),[...messages,reasoning,commentary,call],'Native phase/reasoning/call ID replayed unchanged');
 assert.equal(requests[1].input[5].call_id,call.call_id);
 assert.equal(requests[1].input[5].type,'function_call_output');
 assert.deepEqual(JSON.parse(requests[1].input[5].output),{status:'completed',profit:'1000'});
 assert.equal(requests[1].tool_choice,'none');
 assert.equal(tools.length,1);assert.equal(deltas.join(''),final.content[0].text);
 assert.equal(updates.map(v=>v.text).join(''),commentary.content[0].text);
 assert.equal(result.native_stream.synthetic_initial_calls,0);
 assert.deepEqual(result.native_stream.message_items.map(v=>v.phase),['commentary','final_answer']);
 assert.ok(visible.some(v=>v.type==='response.output_item.added' && v.phase==='commentary'));
 assert.ok(visible.some(v=>v.type==='agent.tool.completed' && v.call_id===call.call_id));
 const operation=visible.find(v=>v.type==='agent.tool.completed');
 assert.equal(operation.status,'completed');assert.ok(Number.isInteger(operation.elapsed_ms));
 assert.equal(operation.target,'');assert.equal(operation.arguments,undefined);
 assert.doesNotMatch(JSON.stringify({updates,deltas,visible,result:result.native_stream}),/PRIVATE_DO_NOT_DISPLAY|opaque-private-state/);
 assert.equal(checkpoint.kind,'native_agent');
 const resumed=[];const never={responses:{create(){throw new Error('Completed resume must not call provider');}}};
 const reused=await runNativeAgent(nativeAgentRuntime(wireConfig,{client:never}),messages,()=>{throw new Error('No repeated tool');},
  {tools:['profit_calculate'],maxActions:1,resumeCheckpoint:checkpoint,onDelta:t=>resumed.push(t)});
 assert.equal(reused.native_stream.resumed,true);assert.equal(resumed.join(''),result.answer);
} finally {await new Promise(resolve=>server.close(resolve));}

const clientFor=items=>({responses:{async create(){return (async function*(){yield*responseEvents('failure-fixture',items);})();}}});
const naturalUpdates=[];
const direct=await runNativeAgent(nativeAgentRuntime(config,{client:clientFor([final])}),messages,()=>{throw new Error('No tool needed');},
 {onUpdate:value=>naturalUpdates.push(value)});
assert.equal(direct.native_stream.responses,1);
assert.deepEqual(direct.native_stream.message_items.map(value=>value.phase),['final_answer'],'The Agent may finish directly without an interim item');
assert.equal(naturalUpdates.length,0,'No fabricated commentary when the provider emits only a final message');
let interruptedState,round=0,toolExecutions=0;
const interrupted={responses:{async create(){if(++round>1)throw new Error('Interrupted after successful tool');return (async function*(){yield*responseEvents('first-before-interruption',[reasoning,commentary,call]);})();}}};
await assert.rejects(runNativeAgent(nativeAgentRuntime(config,{client:interrupted}),messages,
 async()=>{toolExecutions++;return {status:'completed',profit:'1000'};},
 {tools:['profit_calculate'],maxActions:1,onCheckpoint:value=>{interruptedState=structuredClone(value);}}),/Interrupted after successful tool/);
let resumedInput;
const pendingResume={responses:{async create(params){resumedInput=params.input;assert.equal(params.tool_choice,'none');return (async function*(){yield*responseEvents('resumed-native-final',[final]);})();}}};
const continued=await runNativeAgent(nativeAgentRuntime(config,{client:pendingResume}),messages,()=>{throw new Error('Tool must not repeat');},
 {tools:['profit_calculate'],maxActions:1,resumeCheckpoint:interruptedState});
assert.equal(toolExecutions,1);assert.equal(continued.native_stream.resumed,true);
assert.equal(resumedInput.find(item=>item.type==='function_call_output').call_id,call.call_id);
assert.equal(resumedInput.find(item=>item.type==='message').phase,'commentary');
let executed=0;
await assert.rejects(runNativeAgent(nativeAgentRuntime(config,{client:clientFor([commentary,call,{...call,call_id:'other',name:'shell_execute'}])}),messages,
 async()=>{executed++;return {};},{tools:['profit_calculate'],maxActions:3}),/未获授权/);
assert.equal(executed,0,'Validate every native call before executing any tool in a batch');
await assert.rejects(runNativeAgent(nativeAgentRuntime(config,{client:clientFor([{...final,phase:undefined}])}),messages,()=>{},{}),/未提供原生assistant phase/);
const unphased={...final,phase:undefined};
const standardDeltas=[],standardUpdates=[];
const standard=await runNativeAgent(nativeAgentRuntime(config,{client:clientFor([unphased])}),messages,null,
 {tools:[],maxActions:0,allowUnphasedResponses:true,onDelta:text=>standardDeltas.push(text),onUpdate:item=>standardUpdates.push(item)});
assert.equal(standard.answer,final.content[0].text);
assert.equal(standard.native_stream.phase_source,'not_available');
assert.equal(standard.native_stream.commentary_count,0);
assert.deepEqual(standardDeltas,[final.content[0].text],'Publish only the verified complete unphased answer');
assert.equal(standardUpdates.length,0,'Do not manufacture native interim replies');
const prelude={id:'empty-prelude',type:'message',role:'assistant',status:'completed',content:[]};
const withPrelude=await runNativeAgent(nativeAgentRuntime(config,{client:clientFor([prelude,final])}),messages,null,
 {allowUnphasedResponses:true});
assert.equal(withPrelude.answer,final.content[0].text);
assert.equal(withPrelude.native_stream.phase_source,'provider','An empty gateway prelude does not remove the real final phase');
let standardRound=0,standardInput;const afterTool=[];
const standardTools={responses:{async create(params){standardInput=params.input;return (async function*(){
 yield* responseEvents('standard-'+standardRound,standardRound++===0?[{...commentary,phase:undefined},call]:[unphased]);
})();}}};
await runNativeAgent(nativeAgentRuntime(config,{client:standardTools}),messages,async()=>({status:'completed',profit:'1000'}),
 {tools:['profit_calculate'],maxActions:1,allowUnphasedResponses:true,onDelta:text=>afterTool.push(text)});
assert.deepEqual(afterTool,[final.content[0].text],'Tool preambles without phase stay private until a final response');
assert.deepEqual(standardInput[2],{...commentary,phase:undefined},'Replay original provider message without adding phase');
await assert.rejects(runNativeAgent(nativeAgentRuntime(config,{client:clientFor([unphased,{...unphased,id:'second'}])}),messages,null,
 {allowUnphasedResponses:true}),/多个最终消息/);
const brokenStandard={responses:{async create(){return (async function*(){yield* responseEvents('broken',[unphased]).slice(0,-1);})();}}};
const brokenVisible=[];
await assert.rejects(runNativeAgent(nativeAgentRuntime(config,{client:brokenStandard}),messages,null,
 {allowUnphasedResponses:true,maxReconnects:0,onDelta:text=>brokenVisible.push(text)}),/未收到completed/);
assert.equal(brokenVisible.length,0,'An interrupted standard response cannot publish buffered text');
await assert.rejects(runNativeAgent(nativeAgentRuntime(config,{client:{responses:{async create(){return (async function*(){yield {type:'response.incomplete'};})();}}}}),messages,()=>{},{}),/未完整完成/);
await assert.rejects(runNativeAgent(nativeAgentRuntime(config,{client:clientFor([final,call])}),messages,()=>{}, {tools:['profit_calculate']}),/与待执行工具调用冲突/);
console.log('Native Agent contracts passed: raw SDK SSE, exact phase and call-ID roundtrip, hidden reasoning exclusion, zero initial-answer calls, completed resume, batch authorization, missing phase and incomplete failure.');
