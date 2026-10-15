import assert from 'node:assert/strict';
import {conversationIntent} from '../federation/conversation-intent.mjs';
import {defaultOnlineLookup} from '../federation/default-online.mjs';
import {nativeAgentRuntime,runNativeAgent} from '../federation/native-agent.mjs';
import {runNativeIntake} from '../federation/native-intake.mjs';
const memory={goal:'找招聘软件的信息',recent:[{id:'u2',role:'user',content:'我说的是软件功能，不是招聘岗位'},{id:'a2',role:'assistant',content:'错误猜测：请查北京岗位'}]};
const policy={default_online:true,network_allowed:true,tools_enabled:true,files:[],services:{search:{enabled:true}}};
const intent=conversationIntent('它们有什么区别？',memory);
assert.ok(intent.followup&&intent.hasTopic);assert.match(intent.question,/招聘软件/);assert.match(intent.question,/不是招聘岗位/);assert.doesNotMatch(intent.question,/北京/);
assert.equal(conversationIntent('换个话题，它们是什么？',memory).followup,false);
assert.equal(conversationIntent('解释数据库索引',memory).question,'解释数据库索引');
assert.equal(conversationIntent('说简单点',memory).rephrase,true);
assert.equal(conversationIntent('具体一点',memory).rephrase,true);
const personal={goal:'旧 Cephalon 产品任务',turn_focus:{source_message_id:'personal',question:'分析我的性格'},recent:[
 {id:'old',role:'user',content:'分析 Cephalon'}, {id:'personal',role:'user',content:'分析我的性格'},
 {id:'reply',role:'assistant',content:'旧回复可能错误，推荐 Cephalon'}]};
const advice=conversationIntent('给我一点建议',personal);
assert.ok(advice.followup && advice.hasTopic);
assert.match(advice.question,/分析我的性格/);assert.doesNotMatch(advice.question,/Cephalon/);
assert.equal(conversationIntent('给我一点数据库索引的建议',personal).followup,false);
const flow=defaultOnlineLookup('它们有什么区别？',policy,{},intent);
assert.equal(flow.coverageTarget,3);
const initial=flow.next({receipts:[],observations:[],allowed:['web_search']});
assert.equal(initial.requireModelQuery,true);
assert.doesNotMatch(initial.args.query,/招聘软件|岗位/,'Do not send context or corrections directly to search');
assert.equal(defaultOnlineLookup('找招聘软件的信息',policy).coverageTarget,3);
assert.equal(defaultOnlineLookup('说简单点',policy,{},conversationIntent('说简单点',memory)),null);
assert.equal(defaultOnlineLookup('不联网，它们有什么区别', {...policy,network_allowed:false},{},intent),null);

// The first native model request plans a contextual query; subsequent body
// reads still run through the bounded host workflow with honest receipts.
const order=[],requests=[];
const client={chat:{completions:{async create(params){requests.push(structuredClone(params));order.push('model');return (async function*(){
 if(requests.length===1)yield {choices:[{delta:{tool_calls:[{index:0,id:'query-1',function:{name:'web_search',arguments:JSON.stringify({query:'招聘软件 平台 功能 区别 适用人群'})}}]},finish_reason:'tool_calls'}]};
 else yield {choices:[{delta:{content:'可以按功能与使用场景比较。'},finish_reason:'stop'}]};
})();}}}};
const config={provider:'openai-compatible',model:'fixture'};
const native=nativeAgentRuntime(config,{client});
const result=await runNativeAgent(native,[{role:'system',content:JSON.stringify(memory)},{role:'user',content:'它们有什么区别？'}],async(tool,args)=>{
 order.push(tool);
 if(tool==='web_search'){assert.equal(args.query,'招聘软件 平台 功能 区别 适用人群');return {status:'completed',sources:[1,2,3].map(i=>({url:'https://source'+i+'.example/features',title:'产品功能介绍'}))};}
 return {status:'completed',sources:[{url:args.url,excerpt:'提供简历解析、沟通和招聘管理功能。',read_method:'http_text'}]};
},{tools:['web_search','web_read'],publicReadAhead:true,planPublicQuery:true,nextRequiredTool:flow.next,maxActions:6,maxTurns:6});
assert.deepEqual(order,['model','web_search','web_read','web_read','web_read','model']);
assert.equal(result.workflow.receipts[0].call_id,'query-1');assert.equal(result.workflow.receipts[0].origin,undefined);
assert.ok(result.workflow.receipts.slice(1).every(r=>r.origin==='host_workflow'));
assert.ok(requests[1].messages.some(m=>m.role==='tool'&&m.tool_call_id==='query-1'));
let refusedCalls=0;
const refusesQuery=nativeAgentRuntime(config,{client:{chat:{completions:{async create(){refusedCalls++;return (async function*(){
 yield {choices:[{delta:{content:'未提供查询。'},finish_reason:'stop'}]};
})();}}}}});
await assert.rejects(runNativeAgent(refusesQuery,[{role:'user',content:'它们有什么区别？'}],()=>{throw new Error('Bare followup must not reach search');},
 {tools:['web_search'],publicReadAhead:true,planPublicQuery:true,nextRequiredTool:()=>initial,maxActions:2,maxTurns:4}),/未能将当前追问解析/);
assert.equal(refusedCalls,2,'One bounded model repair, never a pronoun fallback search');
let rewriteRequest;
const rewriter=nativeAgentRuntime(config,{client:{chat:{completions:{async create(params){rewriteRequest=structuredClone(params);return (async function*(){yield {choices:[{delta:{content:'先看用途，再比较功能。'},finish_reason:'stop'}]};})();}}}}});
const evidence={wiki:{text:'',reads:[],retrieval:{}},templates:{text:'',reads:[]},skills:{text:'',reads:[]}};
const rewritten=await runNativeIntake(rewriter,{createModel(){throw new Error('No factual assertion needs checking');}},'系统','','',evidence,[],'openai-compatible','fixture',
 {currentQuestion:'说简单点',contextMemory:memory,toolPolicy:policy,executeTool(){throw new Error('Rephrasing cannot invoke search');}});
assert.equal(rewritten.answer,'先看用途，再比较功能。');assert.equal(rewriteRequest.tools,undefined);
assert.equal(rewriteRequest.messages.at(-1).content,'说简单点');
assert.match(JSON.stringify(rewriteRequest.messages),/招聘软件/);
console.log('Conversation intent: topic, corrections, model-planned query, multi-source reads, native call IDs and rephrase without tools passed.');

assert.equal(conversationIntent('这个月失业的人数有多少？',memory).followup,false);
assert.equal(conversationIntent('这个月失业的人数有多少？',memory).question,'这个月失业的人数有多少？');
assert.equal(conversationIntent('这个数据怎么算的？',memory).followup,true);
