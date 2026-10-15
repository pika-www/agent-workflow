/** Latency regressions use controlled tools/models, not external research proof. */
import assert from 'node:assert/strict';
import {compactNativeContext,nativeContextSize} from '../federation/native-context.mjs';
import {runNativeAgent,nativeAgentRuntime} from '../federation/native-agent.mjs';
import {defaultOnlineLookup} from '../federation/default-online.mjs';
import {conversationIntent} from '../federation/conversation-intent.mjs';
import {checkAnswer} from '../federation/answer-check.mjs';
import {contextConfig} from '../federation/context-budget.mjs';
const material=(key,value)=>`\n<material kind="${key}">\n${JSON.stringify(value)}\n</material>`;
const history=Array.from({length:240},(_,i)=>material('conversation:'+i,{id:String(i),role:i%2?'assistant':'user',content:'虚构历史信息。'.repeat(80)})).join('');
const pinned=material('requirement_state',{active:[{value:'保留当前要求'}]});
const input=[{role:'system',content:'必要规则。'},{role:'user',content:pinned+history},{role:'user',content:'当前完整问题。'}];
const original=JSON.stringify(input);let tokenCalls=0;
const reduced=compactNativeContext(input,{maxTokens:14000,materialIndex:1,countTokens:text=>{tokenCalls++;return Math.ceil(text.length/2);}});
assert.ok(tokenCalls<40,`Full-context tokenizations must not grow per message: ${tokenCalls}`);
assert.equal(JSON.stringify(input),original);assert.ok(reduced.input[1].content.includes(pinned));
assert.equal(reduced.input.at(-1).content,input.at(-1).content);
assert.ok(reduced.receipt.after_tokens<=14000);

const policy={default_online:true,network_allowed:true,services:{search:{enabled:true}}};
const question='查找 Python 列表使用说明。',flow=defaultOnlineLookup(question,policy,{},conversationIntent(question));
assert.equal(flow.next({receipts:[],allowed:['web_search']}).hostQueryReady,true);
for(const q of ['它们有什么区别？','搜索刚才那个产品','继续查找']){
 const f=defaultOnlineLookup(q,policy,{},conversationIntent(q,{goal:'产品比较'}));
 assert.notEqual(f?.next({receipts:[],allowed:['web_search']})?.hostQueryReady,true);
}
const official=defaultOnlineLookup('查找 Python 官方文档，解释 list 和 tuple 的区别。',policy);
assert.equal(official.coverageTarget,1);
assert.equal(official.next({receipts:[],allowed:['web_search']}).hostQueryReady,false);
assert.equal(defaultOnlineLookup('解释 list 和 tuple 的区别。',policy),null,'Ordinary concept explanations do not require a search');
assert.equal(defaultOnlineLookup('介绍招聘平台的区别。',policy).coverageTarget,3);
const order=[];let pastTerminal=false,closed=false;
const client={responses:{async create(){order.push('model');return(async function*(){try{
 const item={id:'final',type:'message',role:'assistant',phase:'final_answer',content:[{type:'output_text',text:'请先明确问题，再记录观察。'}]};
 yield {type:'response.output_item.added',item};yield {type:'response.output_text.delta',item_id:item.id,delta:item.content[0].text};
 yield {type:'response.output_item.done',item};yield {type:'response.completed',response:{output:[item],usage:{input_tokens:100,output_tokens:10}}};
 pastTerminal=true;throw new Error('Do not wait for delayed EOF after terminal receipt');
 }finally{closed=true;}})();}}};
const runtime=nativeAgentRuntime({provider:'openai-compatible',model:'fixture',responses_api:true},{client});
const result=await runNativeAgent(runtime,[{role:'system',content:'规则'},{role:'user',content:question}],async(tool,args)=>{
 order.push(tool);return {status:'completed',sources:[{url:'https://docs.python.org/3/tutorial/datastructures.html',title:'Python 说明',excerpt:'提供列表操作说明，建议结合示例阅读。',read_method:tool==='web_search'?'search_result_snippet':'http_text'}]};
},{tools:['web_search','web_read'],publicReadAhead:true,planPublicQuery:true,nextRequiredTool:flow.next,maxActions:4});
assert.deepEqual(order,['web_search','web_read','model']);assert.equal(result.native_stream.usage.length,1);
assert.ok(result.workflow.receipts.every(r=>r.origin==='host_workflow'));
assert.equal(pastTerminal,false);assert.equal(closed,true);assert.equal(result.native_stream.reconnects,0);
assert.equal(result.native_stream.usage[0].input_tokens,100);
assert.ok(Number.isFinite(result.timing.context_preparation_ms));

// Independent batches overlap, while evidence validation, ordering and failure
// withdrawal still apply after all in-flight batches have settled.
const fact='METR 测量的是开发任务完成时间，不是学习掌握速度。';
let active=0,peak=0,finished=0;
const supplied={inputs:[{path:'/a.md',text:fact,claims:[],provided_sha256:'a'.repeat(64),truncated:false}],omitted_paths:[]};
const configured={createModel(p,m,r,max){assert.equal(max,1600);return {async invoke(messages){
 active++;peak=Math.max(peak,active);const data=JSON.parse(messages[1].content);
 await new Promise(resolve=>setTimeout(resolve,data.assertions[0].id==='assertion-1'?50:10));
 active--;finished++;
 return {content:JSON.stringify({checks:data.assertions.map(a=>({id:a.id,status:'supported',reason:'实际提供的原句',references:[{source_id:data.fragments[0].source_id}]}))})};
}};}};
const checked=await checkAnswer(Array.from({length:14},()=>fact).join('\n'),'解释该研究',[],supplied,configured,'fixture','fixture',contextConfig());
assert.equal(peak,2);assert.equal(finished,3);assert.equal(active,0);assert.equal(checked.receipt.assessed_assertions,14);
assert.deepEqual(checked.receipt.model_usage.map(u=>u.batch_start),[0,6,12]);
assert.deepEqual(checked.receipt.checks.map(c=>c.id),Array.from({length:14},(_,i)=>'assertion-'+(i+1)));
assert.ok(checked.receipt.checks.every(c=>c.status==='supported'));
console.log('Conversation speed: bounded exact context counts, full-query read-ahead, reference guard, terminal stream exit and bounded parallel evidence checks passed.');
let settled=0;
const partiallyFailed={createModel(){return {async invoke(messages){
 const data=JSON.parse(messages[1].content);
 await new Promise(resolve=>setTimeout(resolve,data.assertions[0].id==='assertion-1'?5:15));
 settled++;
 if(data.assertions[0].id==='assertion-1')throw Error('controlled verification failure');
 return {content:JSON.stringify({checks:data.assertions.map(a=>({id:a.id,status:'supported',reason:'原句匹配',references:[{source_id:data.fragments[0].source_id}]}))})};
}};}};
const partial=await checkAnswer(Array.from({length:8},()=>fact).join('\n'),'解释该研究',[],supplied,partiallyFailed,'fixture','fixture',contextConfig());
assert.equal(settled,2);assert.equal(partial.receipt.calls,2);assert.equal(partial.receipt.assessed_assertions,2);
assert.equal(partial.receipt.failure,'invalid_or_failed_assessment');
assert.ok(partial.receipt.checks.filter(c=>c.status==='supported').every(c=>['assertion-7','assertion-8'].includes(c.id)));
assert.ok(partial.receipt.checks.filter(c=>Number(c.id.split('-')[1])<=6).every(c=>c.status==='insufficient'));
let nativeAssessmentRequests=0;
const nativeChecker={async createNativeAgent(){return nativeAgentRuntime({provider:'openai-compatible',model:'fixture',responses_api:true},{client:{responses:{async create(params){
 nativeAssessmentRequests++;
 assert.equal(params.text.format.type,'json_schema');assert.equal(params.text.format.strict,true);assert.equal(params.text.format.name,'answer_evidence_checks');
 assert.equal(params.response_format,undefined);assert.deepEqual(params.tools,[]);
 const data=JSON.parse(params.input[1].content);
 const text=JSON.stringify({checks:data.assertions.map(a=>({id:a.id,status:'supported',reason:'实际原句',references:[{source_id:data.fragments[0].source_id}]}))});
 return(async function*(){const item={id:'json-result',type:'message',role:'assistant',phase:'final_answer',content:[{type:'output_text',text}]};
 yield {type:'response.output_item.added',item};yield {type:'response.output_text.delta',item_id:item.id,delta:text};yield {type:'response.output_item.done',item};
 yield {type:'response.completed',response:{output:[item],usage:{input_tokens:80,output_tokens:20,input_tokens_details:{cached_tokens:0}}}};
 throw Error('Terminal JSON receipt must end stream consumption');})();
}}}});},createModel(){throw Error('Do not drop structured native output through the legacy adapter');}};
const nativeChecked=await checkAnswer(fact,'解释该研究',[],supplied,nativeChecker,'openai-compatible','fixture',contextConfig());
assert.equal(nativeAssessmentRequests,1);assert.equal(nativeChecked.receipt.assessed_assertions,1);assert.equal(nativeChecked.receipt.checks[0].status,'supported');
assert.equal(nativeChecked.receipt.model_usage[0].protocol,'native_responses');assert.equal(nativeChecked.receipt.model_usage[0].input_tokens,80);
assert.equal(nativeChecked.receipt.calls,1);
console.log('Structured native evidence output and usage passed.');
