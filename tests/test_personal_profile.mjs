import assert from 'node:assert/strict';
import {assembleContext,contextConfig} from '../federation/context-budget.mjs';
import {userContextInputs,checkAnswer} from '../federation/answer-check.mjs';
import {profileOnlyQuestion,personalIdentityQuestion} from '../federation/personal-profile.mjs';
import {defaultOnlineLookup} from '../federation/default-online.mjs';
import {runNativeIntake} from '../federation/native-intake.mjs';
import {nativeAgentRuntime,validateNativeCall} from '../federation/native-agent.mjs';
const evidence={wiki:{text:'',reads:[],retrieval:{}},templates:{text:'',reads:[]},skills:{text:'',reads:[]}};
const profile={revision:1,origin:'explicit_user_profile',source_status:'user_provided',sections:[{label:'关于我',text:'测试用户，有前端经验。'},{label:'当前目标',text:'想转向 AI 应用开发。'},{label:'简历',text:'React 和 TypeScript。'.repeat(300)}]};
const question='你了解我吗？';
const built=assembleContext('规则','',evidence,question,null,{entries:[],profile},contextConfig());
assert.equal(built.messages.at(-1).content,question);
const inputs=userContextInputs(question,built.messages);
assert.ok(inputs.some(i=>i.path==='user-context:user_profile'&&i.text.includes('前端经验')));
assert.ok(inputs.filter(i=>i.path==='user-context:user_profile').every(i=>!i.text.includes('"label"')));
assert.ok(built.receipt.included.some(i=>i.key==='user_profile'));
assert.ok(built.receipt.input_tokens_estimated<=contextConfig().input_budget);
for(const q of ['你了解我吗？','总结我的简历','我的工作经历有哪些？','我会哪些技能','帮我改简历','我是谁','帮我写一段求职自我介绍','按我的背景，给我一个求职自我介绍。'])assert.ok(profileOnlyQuestion(q),q);
assert.equal(profileOnlyQuestion('我适合什么招聘岗位'),false);
assert.equal(profileOnlyQuestion('搜索最新 React 工作行情'),false);
for(const q of ['hello Do you know me？','Who am I?',"What's my name?",'Do you remember me?','What do you know about me?']) {
 assert.ok(personalIdentityQuestion(q),q);
 assert.equal(defaultOnlineLookup(q,{default_online:true,network_allowed:true}),null);
}
for(const q of ['Do you know the song Do You Know Me?','Do you know me? Search for jobs.','hello, do you know React?'])assert.equal(personalIdentityQuestion(q),false,q);
let request;
const native=nativeAgentRuntime({provider:'openai-compatible',model:'fixture'},{client:{chat:{completions:{async create(params){request=structuredClone(params);return (async function*(){yield {choices:[{delta:{content:'可以围绕你希望转向的方向继续聊。'},finish_reason:'stop'}]};})();}}}}});
await runNativeIntake(native,{createModel(){throw new Error('No factual assessment needed');}},'系统','','',evidence,[],'openai-compatible','fixture',{
 currentQuestion:question,memoryContext:{entries:[],profile},toolPolicy:{default_online:true,network_allowed:true,tools_enabled:true,files:[]},executeTool(){throw new Error('Personal recall must not search the web');}});
assert.equal(request.tools,undefined);assert.match(JSON.stringify(request.messages),/前端经验/);
const identity=await runNativeIntake(native,{createModel(){throw new Error('No second model needed');}},'系统','','',evidence,[],'openai-compatible','fixture',{
 currentQuestion:'hello Do you know me？',memoryContext:{entries:[],profile},toolPolicy:{default_online:true,network_allowed:true,tools_enabled:true},executeTool(){throw new Error('English identity must not trigger public search');}});
assert.equal(identity.response_origin,'personal_identity_model');assert.equal(request.tools,undefined);
for(const query of ['sample@example.com 求职','13800138000 简历','310101199001011234 个人资料','/Users/demo/private-resume']){
 assert.throws(()=>validateNativeCall({type:'function_call',call_id:'q',name:'web_search',arguments:JSON.stringify({query})},['web_search']),/公开搜索不能/);
}
assert.deepEqual(validateNativeCall({type:'function_call',call_id:'q',name:'web_search',arguments:'{"query":"React AI 应用开发岗位"}'},['web_search']),{query:'React AI 应用开发岗位'});
console.log('Personal profile: bounded retained context, user-record evidence, recall without public tools and private query rejection passed.');

// A rejected fabricated experience must not turn the supported goal into a
// raw JSON quote or an internal user-record disclaimer in the final prose.
const draft='我目前希望转向 AI 应用开发。\n\n我已经部署了大型生产系统。';
const checked=await checkAnswer(draft,'按我的背景写求职自我介绍',[],{inputs:[],omitted_paths:[]},
 {createModel(){return {async invoke(messages){const data=JSON.parse(messages[1].content);
  const goal=data.fragments.find(f=>f.path==='user-context:user_profile'&&f.quote.includes('转向'));
  return {content:JSON.stringify({checks:data.assertions.map(a=>({id:a.id,status:a.text.includes('转向')?'supported':'insufficient',reason:'按用户资料核对',references:a.text.includes('转向')?[{source_id:goal.source_id}]:[]}))})};
 }}}},'fixture','fixture',contextConfig(),{answerMessages:built.messages});
assert.equal(checked.answer,'我目前希望转向 AI 应用开发。');
assert.doesNotMatch(checked.answer,/label|用户记录|大型生产系统|^>/m);
console.log('Personal introduction repair preserves supported user prose and removes fabricated experience without internal source formatting.');
