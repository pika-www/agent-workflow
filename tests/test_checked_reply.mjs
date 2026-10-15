/** Draft visibility is checked at the delivery boundary, including native SSE. */
import assert from 'node:assert/strict';
import {checkedReply} from '../federation/checked-reply.mjs';
import {runIntakeTurn} from '../federation/intake-turn.mjs';
import {nativeAgentRuntime} from '../federation/native-agent.mjs';
import {conversationIntent} from '../federation/conversation-intent.mjs';

const text=[],updates=[],events=[],progress=[];
const gate=checkedReply({onDelta:v=>text.push(v),onUpdate:v=>updates.push(v),onAgentEvent:v=>events.push(v),onProgress:v=>progress.push(v)});
await gate.options.onDelta('未核对草稿：99元');
await gate.options.onUpdate({id:'before-check',text:'未核对草稿：99元'});
await gate.options.onAgentEvent({origin:'provider',type:'response.output_item.done',item:{content:[{text:'未核对草稿：99元'}]}});
await gate.options.onAgentEvent({origin:'host_tool',type:'agent.tool.completed',name:'web_read'});
await gate.options.onProgress({stage:'checking_evidence',detail:'正在核对依据'});
assert.deepEqual(text,[]);assert.deepEqual(updates,[]);assert.equal(events.length,1);
assert.equal(progress.at(-1).stage,'checking_evidence');
const published=await gate.publish({answer:'实际来源标明20元。',initial_reply:{text:'99元'},preliminary_reply:{text:'99元'},answer_check:{status:'corrected_with_limits'}});
assert.deepEqual(text,['实际来源标明20元。']);assert.equal(published.initial_reply,null);assert.equal(published.preliminary_reply,null);
assert.equal(published.reply_delivery.draft_visible,false);assert.equal(published.reply_delivery.check_status,'corrected_with_limits');
await assert.rejects(gate.publish({answer:'重复'}),/已发布/);
const abort=new AbortController(),cancelled=[];
const interrupted=checkedReply({signal:abort.signal,onDelta:t=>cancelled.push(t)});
await interrupted.options.onDelta('半截草稿');abort.abort();
await assert.rejects(interrupted.publish({answer:'不能发布'}));assert.deepEqual(cancelled,[]);

// Integrate the public intake entrypoint with a genuinely delayed checker.
const evidence={wiki:{text:'',reads:[],retrieval:{}},templates:{text:'',reads:[]},skills:{text:'',reads:[]}};
let calls=0,release,checking;const checkerStarted=new Promise(resolve=>checking=resolve),waitForCheck=new Promise(resolve=>release=resolve);
let social=false,providerDone=false,socialWasImmediate=false;
const client={chat:{completions:{async create(){calls++;return (async function*(){
 yield {choices:[{delta:{content:social?'你好！':'这个月失业人数为99万人。'},finish_reason:null}]};
 if(social) socialWasImmediate=shown.includes('你好！');
 yield {choices:[{delta:{},finish_reason:'stop'}],usage:{prompt_tokens:20,completion_tokens:10}};
 providerDone=true;
})();}}}};
const runtime={async loadOpenWikiEnv(){},resolveConfiguredProvider(){return 'openai-compatible';},resolveModelId(){return 'fixture';},resolveProviderRetryAttempts(){return 0;},
 createNativeAgent(){return nativeAgentRuntime({provider:'openai-compatible',model:'fixture'},{client});},
 createModel(){return {async invoke(messages){checking();await waitForCheck;const payload=JSON.parse(messages.at(-1).content);
  if(!payload.assertions)return {content:'来源未提供当月失业人数，目前无法确认。'};
  return {content:JSON.stringify({checks:payload.assertions.map(a=>({id:a.id,status:'insufficient',reason:'所引资料没有这个人数',references:[]}))})};
 }}}};
const shown=[],nativeEvents=[],stages=[],tools=[];let savedCheckpoint;
const question='这个月失业的人数有多少？';
const memory={goal:'最近有没有趣事？',recent:[]};
assert.equal(conversationIntent(question,memory).followup,false);
const consultationOptions={currentQuestion:question,contextMemory:memory,onCheckpoint:value=>{savedCheckpoint=structuredClone(value);},
 toolPolicy:{default_online:true,network_allowed:true,tools_enabled:true},
 onDelta:t=>shown.push(t),onUpdate:v=>shown.push(v.text),onAgentEvent:v=>nativeEvents.push(v),onProgress:v=>stages.push(v.stage),
 async executeTool(name,args){tools.push(name);if(name==='web_search')assert.doesNotMatch(args.query,/趣事|这个月/);
 return {status:'completed',sources:[{url:'https://example.com/statistics',excerpt:'统计范围说明：月度报告公布调查失业率，不提供当月失业人数。',read_method:name==='web_search'?'search_result_snippet':'http_text'}]};}};
const running=runIntakeTurn(question,'consultation',evidence,runtime,consultationOptions);
await checkerStarted;
assert.equal(providerDone,true);assert.deepEqual(shown,[],'Completed provider draft stays private while checking is blocked');
assert.deepEqual(tools,['web_search','web_read']);assert.equal(calls,1,'Explicit dated question needs one answer generation, no model query planning');
assert.ok(stages.includes('checking_evidence'));assert.ok(!JSON.stringify(nativeEvents).includes('99万人'));
release();const result=await running;
assert.equal(result.answer_check.calls,2);assert.equal(result.answer_check.repair_count,1);assert.equal(result.reply_delivery.mode,'after_checks');
assert.equal(shown.length,1);assert.equal(shown[0],result.answer);assert.doesNotMatch(result.answer,/99万人/);
assert.equal(result.initial_reply,null);
const previousCalls=calls;shown.length=0;
await runIntakeTurn(question,'consultation',evidence,runtime,{...consultationOptions,resumeCheckpoint:savedCheckpoint});
assert.equal(calls,previousCalls,'Resume reuses the saved draft without regenerating it');
assert.equal(shown.length,1);assert.doesNotMatch(shown[0],/99万人/,'Saved unverified draft stays private on resume');
// A provider failure after its first chunk cannot preserve that private draft
// as the visible failed reply, on either text channel or native SSE.
shown.length=0;const failedEvents=[];
const failing={...runtime,createNativeAgent(){return nativeAgentRuntime({provider:'openai-compatible',model:'fixture'},{client:{chat:{completions:{async create(){return (async function*(){
 yield {choices:[{delta:{content:'PRIVATE_FAILED_DRAFT'},finish_reason:null}]};throw new Error('fixture permanent failure');
})();}}}}});}};
await assert.rejects(runIntakeTurn('解释工作流程','consultation',evidence,failing,{currentQuestion:'解释工作流程',onDelta:t=>shown.push(t),onUpdate:v=>shown.push(v.text),onAgentEvent:v=>failedEvents.push(v)}),/fixture permanent failure/);
assert.deepEqual(shown,[]);assert.doesNotMatch(JSON.stringify(failedEvents),/PRIVATE_FAILED_DRAFT/);
// Social exchanges still arrive as actual model chunks before provider completion.
social=true;shown.length=0;providerDone=false;
const hello=await runIntakeTurn('你好','consultation',evidence,runtime,{currentQuestion:'你好',onUpdate:v=>shown.push(v.text),onDelta:t=>shown.push(t)});
assert.equal(hello.answer,'你好！');assert.equal(socialWasImmediate,true);assert.equal(hello.answer_check.calls,0);
console.log('Checked delivery: no draft on three channels; no aborted publication; one checked result; public read-ahead uses one generation; invalid facts still checked and repaired; social streaming remains immediate.');
