/** Native consultation regressions. Fixture output is not real-model proof. */
import assert from 'node:assert/strict';
import {runNativeIntake} from '../federation/native-intake.mjs';
import {nativeAgentRuntime} from '../federation/native-agent.mjs';
import {contextConfig,estimatedTokens} from '../federation/context-budget.mjs';
const evidence={wiki:{text:'',reads:[],retrieval:{}},templates:{text:'',reads:[]},skills:{text:'',reads:[]}};
let request;
const client={chat:{completions:{async create(params){request=structuredClone(params);return (async function*(){
 yield {choices:[{delta:{content:'我是主 Agent。'},finish_reason:null}]};
 yield {choices:[{delta:{},finish_reason:'stop'}],usage:{prompt_tokens:20,completion_tokens:5}};
})();}}}};
const native=nativeAgentRuntime({provider:'openai-compatible',model:'fixture'},{client});
const configured={createModel(){throw new Error('Identity without factual claims needs no second model call');}};
const deltas=[];
const result=await runNativeIntake(native,configured,'你是主 Agent。','\n'.repeat(25000),'',evidence,[],
 'openai-compatible','fixture',{currentQuestion:'你叫什么？',speakerName:'主 Agent',onUpdate(){},onDelta:value=>deltas.push(value),
 executeTool(){throw new Error('Identity must not retrieve unrelated materials');},toolPolicy:{network_allowed:true}});
assert.equal(result.answer,'我是主 Agent。');
assert.equal(result.native_stream.responses,1);
assert.equal(result.native_stream.synthetic_initial_calls,0);
assert.equal(result.answer_check.calls,0);
assert.match(request.messages[0].content,/宿主确认你的名字/);
assert.equal(request.tools,undefined);
assert.equal(request.messages.length,2);
assert.ok(JSON.stringify(request.messages).length<1000,'Identity stays bounded, including the shared language policy, without unrelated context');
assert.equal(result.context_usage.omitted.find(value=>value.key==='templates').reason,'not_relevant_to_social_exchange');
const regular=await runNativeIntake(native,configured,'你是主 Agent。','\n'.repeat(25000),'',evidence,[],
 'openai-compatible','fixture',{currentQuestion:'请给一句回应',onUpdate(){}});
assert.equal(regular.native_stream.responses,1);
assert.doesNotMatch(request.messages[0].content,/先给.*中间回答|中间消息使用commentary/,'The prompt does not impose a fixed pre-tool reply');
assert.ok(estimatedTokens(JSON.stringify(request.messages))>contextConfig().input_budget,'Serialized overhead reproduces the 12K regression');
assert.ok(estimatedTokens(JSON.stringify(request.messages))<contextConfig().hard_input);
assert.equal(deltas.join(''),'我是主 Agent。');
assert.deepEqual(evidence.wiki.reads,[]);
const deferred=await runNativeIntake(native,configured,'你是主 Agent。','','',evidence,[],
 'openai-compatible','fixture',{currentQuestion:'解释会话摘要的用途。',contextMemory:{goal:'会话摘要',task_id:'fixture-task',revision:1,
 summary_request:{messages:[{id:'source',role:'user',content:'保留聊天原文。'}]},recent:[],pending:[]}});
assert.equal(deferred.answer,'我是主 Agent。');
assert.equal(deferred.context_usage.summary.status,'background_pending');
assert.equal(deferred.context_usage.total_calls,1);
assert.equal(deferred.memory_update,null,'A pending memory model cannot delay this answer');
const withTools=await runNativeIntake(native,configured,'你是主 Agent。','','',evidence,[],
 'openai-compatible','fixture',{currentQuestion:'说简单点，接着刚才讲。',toolPolicy:{tools_enabled:true,files:[],services:{search:'available'}}});
assert.equal(request.messages.filter(m=>m.role==='system' && m.content.includes('工具可用状态')).length,1);
assert.equal(request.messages.at(-1).content,'说简单点，接着刚才讲。','The actual question remains last even when tools are available');
assert.match(request.messages[0].content,/工具可用状态/);
assert.equal(withTools.context_usage.input_tokens_estimated,request.messages.reduce((n,m)=>n+estimatedTokens(m.content)+16,0),
 'Tool inventory instructions are included in the actual context receipt');
process.stdout.write('Native intake budget and identity regressions passed\n');
{
 const absentId='0'.repeat(32);let calls=0;const requests=[];
 const missingClient={chat:{completions:{async create(params){requests.push(params);const first=++calls===1;return (async function*(){
  if(first)yield {choices:[{delta:{tool_calls:[{index:0,id:'missing-attachment',type:'function',function:{name:'file_read',arguments:JSON.stringify({file_id:absentId,question:'请核对附件编号 '+absentId+' 并读取第一页。',start:'0',limit:'0'})}}]},finish_reason:'tool_calls'}]};
  else yield {choices:[{delta:{content:'本次未读取附件。'},finish_reason:'stop'}]};
 })();}}}};
 const missing=await runNativeIntake(nativeAgentRuntime({provider:'openai-compatible',model:'fixture'},{client:missingClient}),configured,'你是主 Agent。','','',evidence,[],'openai-compatible','fixture',{
  currentQuestion:'请核对附件编号 '+absentId+' 并读取第一页。',
  executeTool(){throw Error('Unknown objects must not reach execution or public search');},
  toolPolicy:{tools_enabled:true,network_allowed:true,default_online:true,files:[],has_attachments:false,services:{}}});
 assert.deepEqual(requests[0].tools.map(t=>t.function.name),['file_read']);
 assert.equal(missing.workflow.receipts.length,1);assert.equal(missing.workflow.receipts[0].executed,false);
 assert.equal(missing.workflow.receipts[0].failure_code,'unknown_object');assert.match(missing.answer,/未读取/);
 console.log('Native intake keeps nonexistent attachment checks in the chat object guard; no public search or read execution.');
}
