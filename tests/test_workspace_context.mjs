import assert from 'node:assert/strict';
import {runIntakeTurn} from '../federation/intake-turn.mjs';
import {chatNicknameContext} from '../federation/conversation-style.mjs';
import {workspaceReceipt,withWorkspace} from '../federation/workspace-context.mjs';

const workspace={agent_id:'central',name:'未明',identity:'名称：未明',soul:'表达直接但不说教',rules:'完成后验证',
 user:'语言：中文',profile:{},nicknames:{user_address:'老王',scope:'current_conversation'},memory:[],excerpts:[],
 reads:[{path:'central/IDENTITY.md',sha256:'fixture'}, {path:'central/USER.md',sha256:'fixture'}]};
const options={currentQuestion:'你该叫我什么',workspaceContext:workspace,
 conversationWindow:{revision:7,compaction_count:8,messages:[{role:'user',content:'叫我旧称呼'}]}};
assert.equal(chatNicknameContext(options).user_address,'老王');
assert.equal(chatNicknameContext({...options,workspaceContext:{...workspace,nicknames:null}}),null);
assert.equal(chatNicknameContext({...options,currentQuestion:'叫我小李'}).user_address,'小李');
let calls=0;
const runtime={loadOpenWikiEnv:async()=>{},resolveConfiguredProvider:()=> 'mock',resolveModelId:()=> 'mock-model',
 createModel(){return {async invoke(messages){calls++;const input=JSON.stringify(messages);
 assert.match(input,/未明/);assert.match(input,/老王/);assert.doesNotMatch(input,/旧称呼|UNRELATED/);
 assert.match(input,/不授予权限/);assert.ok(input.length<4000);
 return {content:'老王。',usage_metadata:{input_tokens:400,output_tokens:4}};}}}};
const poison={wiki:{text:'UNRELATED',reads:[]},templates:{text:'UNRELATED',reads:[]},skills:{text:'UNRELATED',reads:[]}};
const result=await runIntakeTurn('UNRELATED','consultation',poison,runtime,options);
assert.equal(result.answer,'老王。');assert.equal(calls,1);
assert.equal(result.context_usage.workspace.status,'provided_to_model');
assert.equal(result.context_usage.workspace.reads.length,2);
assert.equal(result.conversation_window_update,null);
assert.deepEqual(workspaceReceipt({response_origin:'host_clock',model:null},options).context_usage.workspace.reads,[]);
const reportReceipt=workspaceReceipt({response_origin:'local_product_analysis_model',model:'fixture'},options).context_usage.workspace;
assert.equal(reportReceipt.status,'not_used_by_this_route');assert.deepEqual(reportReceipt.reads,[]);
assert.match(withWorkspace('base',options),/完成后验证/);
console.log('Workspace context: actual simple-model input, identity, retained nickname precedence, bounded input and honest receipts passed.');

const {nativeAgentRuntime}=await import('../federation/native-agent.mjs');
const {runNativeIntake}=await import('../federation/native-intake.mjs');
let recallRequests=[];
const client={chat:{completions:{async create(request){recallRequests.push(request);return (async function*(){
 yield {choices:[{delta:{content:'项目使用 SQLite；今天完成了初始化。'},finish_reason:null}]};
 yield {choices:[{delta:{},finish_reason:'stop'}],usage:{prompt_tokens:600,completion_tokens:20}};
})();}}}};
const native=nativeAgentRuntime({provider:'openai-compatible',model:'fixture'},{client});
const recall=await runNativeIntake(native,{createModel(){throw new Error('No extra checker or summary');}},
 'UNRELATED_SYSTEM','UNRELATED_TASK','UNRELATED_INPUT',
 {...poison,skills:{text:'MEMORY_SKILL: respect recorded sources',reads:[{path:'/SKILL.md'}]}},[],
 'openai-compatible','fixture',{...options,currentQuestion:'今天的工作记录？',
 workspaceContext:{...workspace,private_recall:true,excerpts:[{path:'MEMORY.md',text:'SQLite'},
 {path:'memory/2026-10-13.md',text:'completed: 初始化'}]},
 contextMemory:{goal:'UNRELATED_GOAL',requirement_state:{active:[{value:'online_available'}]}}});
assert.equal(recallRequests.length,1);assert.equal(recallRequests[0].tools,undefined);
assert.doesNotMatch(JSON.stringify(recallRequests),/UNRELATED|online_available|旧称呼/);
assert.match(JSON.stringify(recallRequests),/SQLite/);assert.match(JSON.stringify(recallRequests),/MEMORY_SKILL/);
assert.equal(recall.skill_reads[0].path,'/SKILL.md');assert.equal(recall.response_origin,'workspace_memory_model');
assert.equal(recall.context_usage.total_calls,1);assert.equal(recall.conversation_window_update,null);
console.log('Private recall: one real native transport call, no search/check/old-task context, actual skill text and selected memory provided.');
