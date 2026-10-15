import assert from 'node:assert/strict';
import {nativeAgentRuntime,runNativeAgent} from '../federation/native-agent.mjs';
import {defaultOnlineLookup} from '../federation/default-online.mjs';
import {onlineContext,serviceSummary} from '../federation/online-context.mjs';
const policy={default_online:true,network_allowed:true},url='https://example.com/docs';
const lookup=defaultOnlineLookup('查阅官方文档，解释 Locator 定位时机',policy),order=[],requests=[];
const final={id:'final',type:'message',role:'assistant',phase:'final_answer',content:[{type:'output_text',text:'定位器会重新查找元素。'}]};
const client={responses:{async create(params){order.push('model');requests.push(structuredClone(params));return (async function*(){
 yield {type:'response.output_item.added',item:{...final,content:[]}};
 yield {type:'response.output_text.delta',item_id:'final',delta:final.content[0].text};
 yield {type:'response.output_item.done',item:final};
 yield {type:'response.completed',response:{id:'response',output:[final],usage:{input_tokens:20,output_tokens:10}}};
})();}}};
const native=nativeAgentRuntime({provider:'openai-compatible',model:'fixture',responses_api:true},{client});
const execute=async name=>{order.push(name);return {status:'completed',sources:[{url,excerpt:'Actual locator documentation',read_method:name==='web_search'?'search_result_snippet':'http_text'}]};};
const options={tools:['web_search','web_read','visual_browser'],nextRequiredTool:lookup.next,publicReadAhead:true,maxActions:3,maxTurns:3};
const messages=[{role:'user',content:'解释 Locator 定位时机'}];
const result=await runNativeAgent(native,messages,execute,options);
assert.deepEqual(order,['web_search','web_read','model'],'Actual public evidence must arrive before any provider wait');
assert.equal(result.native_stream.responses,1);
assert.equal(result.native_stream.tool_calls.length,0);assert.equal(result.native_stream.host_tool_calls.length,2);
assert.ok(requests[0].input.every(i=>!['function_call','function_call_output'].includes(i.type)),'Never invent a model tool call');
assert.ok(requests[0].input.some(i=>i.content?.includes('Actual locator documentation')));
assert.ok(result.timing.first_tool_ms>=0 && result.timing.provider_ms>=0 && result.timing.tool_ms>=0);
assert.ok(result.native_stream.usage[0].elapsed_ms>=0);

let saved;order.length=0;
await assert.rejects(runNativeAgent(native,messages,execute,{...options,onCheckpoint:state=>{saved=structuredClone(state);throw new Error('interrupted after tool');}}),/interrupted after tool/);
assert.deepEqual(order,['web_search']);assert.equal(saved.turn_index,0);
order.length=0;
await runNativeAgent(native,messages,execute,{...options,resumeCheckpoint:saved});
assert.deepEqual(order,['web_read','model'],'Resuming prefetch must not repeat a completed search');
order.length=0;
await runNativeAgent(native,messages,execute,{...options,maxActions:1});
assert.deepEqual(order,['web_search','model'],'Read-ahead preserves action limits');
assert.equal(requests.at(-1).tool_choice,'none');

order.length=0;const failureEvents=[];
const fallback=await runNativeAgent(native,messages,async name=>{
 order.push(name);
 if(name==='web_read')return {status:'unavailable',errors:[{error:'未提取到足够的可读正文；页面可能需要登录或执行脚本'}]};
 return {status:'completed',sources:[{url,excerpt:'Actual locator documentation',read_method:name==='web_search'?'search_result_snippet':'visual_browser_dom'}]};
},{...options,onAgentEvent:event=>failureEvents.push(event)});
assert.deepEqual(order,['web_search','web_read','visual_browser','model']);
assert.equal(fallback.workflow.receipts[1].status,'unavailable');
assert.equal(fallback.workflow.receipts[1].failure_code,'no_readable_body');
assert.equal(failureEvents.find(e=>e.type==='agent.tool.completed'&&e.name==='web_read').status,'no_readable_body');

// After a native query refinement, the selected result also needs no separate
// provider turn merely to repeat the known read URL.
let refinements=0;const refinedOrder=[];
const refiningClient={responses:{async create(params){
 refinedOrder.push('model');const items=++refinements===1?[{type:'function_call',call_id:'refined-search',name:'web_search',arguments:JSON.stringify({query:'Locator official'})}]:[final];
 return (async function*(){
  if(refinements>1){yield {type:'response.output_item.added',item:{...final,content:[]}};yield {type:'response.output_text.delta',item_id:'final',delta:final.content[0].text};yield {type:'response.output_item.done',item:final};}
  yield {type:'response.completed',response:{output:items}};
 })();
}}};
await runNativeAgent(nativeAgentRuntime({provider:'openai-compatible',model:'fixture',responses_api:true},{client:refiningClient}),messages,async(name)=>{
 refinedOrder.push(name);return refinements===0?{status:'no_results',sources:[]}:{status:'completed',sources:[{url,excerpt:'Actual documentation',read_method:name==='web_search'?'search_result_snippet':'http_text'}]};
},{...options,maxActions:4});
assert.deepEqual(refinedOrder,['web_search','model','web_search','web_read','model']);

const memory={requirements:[{id:'old',content:'只用本库，不联网。',requirement_changes:[{slot:'network',value:'local_only'}]},
 {id:'mix',content:'React，离线',requirement_changes:[{slot:'network',value:'local_only'},{slot:'framework',value:'react'}]}],
 requirement_state:{records:[{slot:'network',value:'local_only'},{slot:'framework',value:'react'}],active:[{slot:'network',value:'local_only'},{slot:'framework',value:'react'}],conflicts:[]}};
const original=structuredClone(memory),projected=onlineContext(memory,policy);
assert.deepEqual(memory,original,'Stored requirements are never mutated');
assert.equal(projected.requirement_state.active.find(r=>r.slot==='network').value,'online_available');
assert.equal(projected.requirement_state.active.find(r=>r.slot==='framework').value,'react');
assert.equal(projected.requirements.length,1);assert.equal(projected.requirements[0].requirement_changes[0].slot,'framework');
assert.equal(onlineContext(memory,{default_online:false,network_allowed:false}),memory,'Explicit offline mode keeps its constraints');
assert.deepEqual(serviceSummary({search:{enabled:true,configured:true,last_execution:{huge:'history'},base_url:'private-address'}}),{search:{enabled:true,configured:true}});
console.log('Public read-ahead passed: zero planning calls, honest receipts, resume, action limits, timing and current network mode.');
