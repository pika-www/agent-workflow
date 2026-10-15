import assert from 'node:assert/strict';
import {assembleContext,contextConfig} from '../federation/context-budget.mjs';
import {runNativeIntake} from '../federation/native-intake.mjs';
import {nativeAgentRuntime} from '../federation/native-agent.mjs';
import {personalIdentityQuestion} from '../federation/personal-profile.mjs';
const evidence={wiki:{text:'',reads:[]},templates:{text:'',reads:[]},skills:{text:'',reads:[]}};
const selected=assembleContext('规则','<available_roles>'+'角色目录。'.repeat(10000)+'</available_roles>',evidence,'解释一下',null,null,contextConfig());
assert.equal(selected.compaction,null);
assert.ok(selected.receipt.selection.before_tokens>selected.receipt.selection.after_tokens);
assert.ok(selected.receipt.selection.after_tokens<=selected.receipt.selection.budget_tokens);
assert.equal(selected.receipt.selection.after_tokens,selected.receipt.input_tokens_estimated);
for(const q of ['我是谁？我叫什么？','我叫什么名字','我的姓名是什么','你还记得我的名字吗'])assert.ok(personalIdentityQuestion(q),q);
for(const q of ['你是谁','我是谁？帮我搜索岗位','我叫测试王，帮我改简历'])assert.equal(personalIdentityQuestion(q),false,q);
let request;const events=[];
const native=nativeAgentRuntime({provider:'openai-compatible',model:'fixture'},{client:{chat:{completions:{async create(params){request=structuredClone(params);return(async function*(){yield{choices:[{delta:{content:'你叫测试林。'},finish_reason:'stop'}],usage:{prompt_tokens:500,completion_tokens:8}}})();}}}}});
const configured={createModel(){throw new Error('Simple personal name recall needs no assessment call');}};
const profile={sections:[{label:'关于我',text:'我叫测试林，从事前端开发。'}],source_status:'user_provided'};
const result=await runNativeIntake(native,configured,'不相关的大量系统规则。'.repeat(10000),'<available_roles>'+'无关角色目录'.repeat(10000)+'</available_roles>','',evidence,[],
 'openai-compatible','fixture',{currentQuestion:'我是谁？我叫什么？',memoryContext:{entries:[],profile},
 contextMemory:{goal:'无关旧项目',recent:[{id:'old-assistant',role:'assistant',content:'你叫错误姓名。'},
 {id:'latest',role:'user',content:'我现在改名叫测试王，请叫我测试王。',created_at:'2026-10-09T08:00:00Z'}]},
 toolPolicy:{default_online:true,network_allowed:true,tools_enabled:true},onAgentEvent:event=>events.push(event),executeTool(){throw Error('No public tools for identity');}});
assert.equal(result.response_origin,'personal_identity_model');
assert.ok(result.context_usage.input_tokens_estimated<2000);
assert.equal(request.tools,undefined);
assert.equal(request.messages.at(-1).content,'我是谁？我叫什么？');
assert.match(JSON.stringify(request.messages),/测试林/);assert.match(JSON.stringify(request.messages),/测试王/);
assert.doesNotMatch(JSON.stringify(request.messages),/无关角色目录|无关旧项目|错误姓名/);
assert.ok(result.context_usage.included.some(i=>i.key==='user_profile'));
assert.equal(events.some(e=>e.type==='agent.context.compacted'),false);
for (const question of ['hello Do you know me?','What do you know about me?','你好，你认识我吗？']) {
 const recall=await runNativeIntake(native,configured,'规则','','',evidence,[],'openai-compatible','fixture',{
  currentQuestion:question,memoryContext:{entries:[],profile},
  toolPolicy:{default_online:true,network_allowed:true,tools_enabled:true},
  executeTool(){throw new Error('Personal recognition must not use public tools');}});
 assert.equal(recall.response_origin,'personal_identity_model');
 assert.equal(request.messages.at(-1).content,question);
 assert.equal(request.tools,undefined);
 assert.match(JSON.stringify(request.messages),/测试林/);
}
const regularEvents=[];
await runNativeIntake(native,configured,'规则','<available_roles>'+'角色目录。'.repeat(10000)+'</available_roles>','',evidence,[],
 'openai-compatible','fixture',{currentQuestion:'请给一句回应',onAgentEvent:event=>regularEvents.push(event)});
assert.equal(regularEvents.some(e=>e.type==='agent.context.compacted'),false,'Initial source selection must not emit runtime compaction');
console.log('Selection vs compaction, consistent token accounting, bounded personal identity input and mixed-task routing passed.');

const window={revision:4,compaction_count:2,messages:[
 ...Array.from({length:200},(_,i)=>({id:'old-'+i,role:'assistant',content:'OLD_ASSISTANT_GUESS I do not know your name. '.repeat(100)})),
 {id:'correction',role:'user',content:'My name is Test Lin. Call me Test Lin.'}]};
const originalWindow=JSON.stringify(window);
const identity=await runNativeIntake(native,configured,'Unrelated rules','','',evidence,[],'openai-compatible','fixture',{
 currentQuestion:'hello Do you know me？',memoryContext:{entries:[],profile},conversationWindow:window,
 toolPolicy:{default_online:true,network_allowed:true},executeTool(){throw Error('No public identity search');}});
assert.ok(identity.context_usage.input_tokens_estimated<2000);
assert.match(JSON.stringify(request.messages),/Test Lin/);
assert.doesNotMatch(JSON.stringify(request.messages),/OLD_ASSISTANT_GUESS/);
assert.equal(identity.conversation_window_update,undefined,'An identity projection never deletes unrelated conversation history');
assert.equal(JSON.stringify(window),originalWindow);
console.log('English identity isolates explicit personal facts and corrections from old assistant guesses without rewriting history.');
