import assert from 'node:assert/strict';
import {appendConversation,conversationResult,conversationOnlyScope} from '../federation/conversation-context.mjs';
import {compactNativeContext,nativeContextSize} from '../federation/native-context.mjs';
import {runNativeIntake} from '../federation/native-intake.mjs';
import {nativeAgentRuntime} from '../federation/native-agent.mjs';
import {contextTokenCounter} from '../federation/context-token-counter.mjs';
import {userContextInputs} from '../federation/answer-check.mjs';

const base=[{role:'system',content:'当前用户要求优先。'},{role:'user',content:'资料。'},{role:'user',content:'继续这个对话。'}];
const window={revision:0,compaction_count:0,messages:[]};
for(let i=0;i<4;i++) {
 window.messages.push({id:String(i),role:i%2?'assistant':'user',content:'第'+i+'条完整原话。'.repeat(75)});
 const input=appendConversation(base,window),size=nativeContextSize(input).tokens;
 assert.equal(compactNativeContext(input,{maxTokens:size+1,materialIndex:1}).receipt,null,'Even 99.9% of available input is retained');
 assert.match(input[1].content,/第0/);
}
const long={revision:0,compaction_count:0,messages:Array.from({length:25},(_,i)=>({id:String(i),role:i%2?'assistant':'user',content:'第'+i+'条：'+'完整的原始会话信息。'.repeat(150)}))};
const raw=JSON.stringify(long),compacted=compactNativeContext(appendConversation(base,long),{maxTokens:9000,materialIndex:1});
assert.ok(compacted.receipt);assert.ok(compacted.receipt.before_tokens>9000);
const projection=conversationResult(long,compacted.input,[compacted.receipt]);
const next={revision:1,compaction_count:1,messages:projection.update.messages.filter(m=>m.content!==null).map(m=>({...long.messages.find(old=>old.id===m.id),...m}))};
next.messages.push({id:'new-user',role:'user',content:'接着聊。'},{id:'new-answer',role:'assistant',content:'继续。'});
assert.equal(compactNativeContext(appendConversation(base,next),{maxTokens:9000,materialIndex:1}).receipt,null,'Next turn reuses the projection instead of expanding and recompacting old originals');
assert.equal(JSON.stringify(long),raw,'Never rewrite original chat');
const sources=userContextInputs('继续这个对话。',compacted.input);
assert.ok(sources.some(s=>s.path.startsWith('user-context:conversation:')));
assert.ok(sources.filter(s=>s.path.startsWith('user-context:conversation:')).every(s=>Number(s.path.split(':').at(-1))%2===0),'Previous assistant prose cannot become user evidence');

let request;const events=[];
const runtime=nativeAgentRuntime({provider:'openai-compatible',model:'fixture'},{client:{chat:{completions:{async create(params){request=structuredClone(params);return(async function*(){yield{choices:[{delta:{content:'已收到。'},finish_reason:'stop'}],usage:{prompt_tokens:1800,completion_tokens:4}}})();}}}}});
const evidence={wiki:{text:'',reads:[]},templates:{text:'',reads:[]},skills:{text:'',reads:[]}};
const configured={createModel(){throw Error('No assessment needed');}};
const history={revision:0,compaction_count:0,messages:[{id:'full',role:'user',content:'开头'+'中段原文'.repeat(400)+'最后的标记 KEEP_FULL'}]};
for(const question of ['请继续回应','我是谁？我叫什么？','你好']) {
 const identity=question==='我是谁？我叫什么？';
 const currentHistory=identity?{...history,messages:[...history.messages,{id:'name',role:'user',content:'我叫老王。'}]}:history;
 const result=await runNativeIntake(runtime,configured,'规则','资料','',evidence,[],'openai-compatible','fixture',{
  currentQuestion:question,conversationWindow:currentHistory,onAgentEvent:e=>events.push(e),
  contextMemory:{recent:[{id:'old',role:'user',content:'无关的裁切副本'}],summary_request:{messages:[{id:'old',content:'不应按消息数摘要'}]}}});
 if(question==='你好'){
  assert.ok(!JSON.stringify(request.messages).includes(history.messages[0].content));
  assert.equal(result.context_usage.conversation.message_count,0);
  assert.equal(result.conversation_window_update,null);
 }else if(identity){
  assert.ok(!JSON.stringify(request.messages).includes(history.messages[0].content));
  assert.ok(JSON.stringify(request.messages).includes('我叫老王。'));
  assert.equal(result.response_origin,'personal_identity_model');
  assert.equal(result.conversation_window_update,undefined);
 }else{
  assert.ok(JSON.stringify(request.messages).includes(history.messages[0].content),question);
  assert.equal(result.context_usage.conversation.message_count,1);
 }
 assert.equal(result.context_usage.summary.status,'not_needed');
 assert.equal(result.context_usage.compactions.length,0);
 assert.equal(request.messages.at(-1).content,question);
}
assert.equal(events.some(e=>e.type==='agent.context.compacted'),false);
const historyQuery='只依据本会话已有内容，归档暗号是什么？不要联网，不运行命令，不修改文件。';
assert.equal(conversationOnlyScope({currentQuestion:historyQuery}),true);
for(const extra of ['，再搜索网页','，调用工具核对','，读取文件'])assert.equal(conversationOnlyScope({currentQuestion:historyQuery+extra}),false);
assert.equal(conversationOnlyScope({currentQuestion:historyQuery,toolPolicy:{has_attachments:true}}),false);
const recalled={...long,messages:[...long.messages,{id:'key-source',role:'user',content:'背景。'.repeat(1000)+'归档暗号是 ZX-12345。'+'背景。'.repeat(1000)}]};
const scoped=await runNativeIntake(runtime,configured,'规则','资料','',evidence,[],'openai-compatible','fixture',{
 currentQuestion:historyQuery,conversationWindow:recalled,toolPolicy:{network_allowed:true,tools_enabled:true},
 executeTool(){throw Error('Conversation-only recall must not execute tools');}});
assert.equal(request.tools,undefined);
assert.ok(scoped.context_usage.compactions.length);
assert.ok(scoped.context_usage.compactions.at(-1).after_tokens<=12000);
assert.ok(JSON.stringify(request.messages).includes('ZX-12345'),'Query-focused original excerpt retains the middle fact');
const pinnedLarge=appendConversation([{role:'system',content:'必要规则'.repeat(1800)},
 {role:'user',content:'\n<material kind="task_goal">\n'+JSON.stringify({goal:'必须保留原始任务'})+'\n</material>'},
 {role:'user',content:'当前问题不可裁切'}],long);
const adaptive=compactNativeContext(pinnedLarge,{maxTokens:28000,softTokens:4000,materialIndex:1});
assert.ok(adaptive.receipt.after_tokens>4000 && adaptive.receipt.after_tokens<=28000,'Soft recall target must not reject required rules below the real model limit');
assert.equal(adaptive.input[0].content,pinnedLarge[0].content);
assert.equal(adaptive.input.at(-1).content,'当前问题不可裁切');
const larger=await runNativeIntake(runtime,configured,'必要规则。'.repeat(1500),'资料','',evidence,[],'openai-compatible','fixture',{
 currentQuestion:'继续回应',conversationWindow:{revision:0,compaction_count:0,messages:[]}});
assert.equal(larger.context_usage.budget,32768-4096-512,'Continuous chat is not rejected at the old 12K selection target');
const config={provider:'openai-compatible',model:'gpt-5.6-sol',base_url:'https://example.invalid/v1',protocol:'responses'};
const plain=contextTokenCounter(config),encoded=JSON.stringify(base)+'[]';
const calibrated=contextTokenCounter(config,[{counting_model_key:plain.key,local_input_tokens_estimated:plain.local(encoded),input_tokens:plain.local(encoded)+4200}]);
assert.equal(calibrated.count(encoded),plain.local(encoded)+4200,'Observed provider overhead is counted once for the whole request');
assert.equal(calibrated.method,'o200k_base_with_provider_receipt');
assert.equal(compactNativeContext(base,{maxTokens:calibrated.count(encoded)+1,materialIndex:1,countTokens:calibrated.count}).receipt,null);
assert.equal(contextTokenCounter({...config,model:'gpt-different'},[{counting_model_key:plain.key,local_input_tokens_estimated:1,input_tokens:9000}]).method,'o200k_base_estimate','Never borrow another model/provider calibration');
console.log('Conversation continuity: full chronological history, no early compaction, persisted projection reuse, and ordinary/identity continuity and scoped greetings passed.');

const tiny=contextTokenCounter(config,[],'你好🙂');
assert.equal(tiny.method,'utf8_byte_upper_bound');
assert.ok(tiny.count('你好🙂')>=plain.local('你好🙂'));
const tinyReceipt={counting_model_key:tiny.key,context_counting:tiny.method,local_input_tokens_estimated:tiny.local('你好🙂'),input_tokens:9999};
assert.equal(contextTokenCounter(config,[tinyReceipt]).method,'o200k_base_estimate','Byte estimates cannot calibrate tokenizer estimates');
assert.equal(contextTokenCounter(config,[],'字'.repeat(2100)).method,'o200k_base_estimate','Long identities keep the normal tokenizer');
console.log('Tiny-request byte bound, large workspace fallback and counting-method isolation passed.');
