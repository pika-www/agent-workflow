import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {checkAnswer,riskyAssertions} from '../federation/answer-check.mjs';
import {contextConfig} from '../federation/context-budget.mjs';
import {runIntakeTurn} from '../federation/intake-turn.mjs';
import {nativeAgentRuntime} from '../federation/native-agent.mjs';

const fixture=JSON.parse(await readFile(new URL('./fixtures/answer-check-completeness.json',import.meta.url),'utf8'));
const hash=s=>createHash('sha256').update(s).digest('hex');
const noModel={createModel(){throw new Error('Ordinary explanations require no evidence model');}};
const empty={scope:'answer_model_supplied_materials',inputs:[],omitted_paths:[]};
const unrelated={...empty,inputs:[{path:'/film.md',origin:'wiki:/film.md',text:'影视内容策划资料，列出了选题和脚本撰写步骤。',claims:[],provided_sha256:hash('影视内容策划资料，列出了选题和脚本撰写步骤。')}]};
assert.equal(hash(fixture.draft),fixture.raw_sha256,'Replay the saved provider output, including its unwanted suffix');
for(const supplied of [empty,unrelated]) {
 const result=await checkAnswer(fixture.draft,fixture.question,[],supplied,noModel,'fixture','fixture',contextConfig());
 assert.equal(result.answer,fixture.expected,'Preserve both removed explanatory sentences verbatim');
 assert.equal(result.receipt.assertion_total,0);
 assert.equal(result.receipt.calls,0);
 assert.equal(result.receipt.original_answer_sha256,fixture.raw_sha256);
 assert.equal(result.receipt.final_answer_sha256,hash(fixture.expected));
 assert.equal(result.receipt.content_cleanup.edits.length,1);
 const edit=result.receipt.content_cleanup.edits[0];
 assert.equal(fixture.draft.slice(edit.start,edit.end),edit.text,'Cleanup has an exact auditable range');
}
for(const answer of [
 '模型本身没有被改造成另一个模型，而是被输入绕过部分约束。',
 '从安全研究角度，可以用测试来评估模型的防护能力。',
 '实验设计是一种安排变量和观察步骤的方法。',
 '用户调查可以先从开放式访谈开始。',
 '如果绕过平台规则并获取隐私，就可能造成安全风险。',
 '不正确地处理敏感信息，可能导致隐私风险。']) {
 const result=await checkAnswer(answer,'解释这个概念',[],unrelated,noModel,'fixture','fixture',contextConfig());
 assert.equal(result.answer,answer);assert.equal(result.receipt.calls,0);
}
for(const answer of [
 '研究发现这种方式有效。','研究人员表示这种方法有效。','研究认为这种方式有效。',
 '这项调查采用问卷收集用户信息。','该实验采用双盲方式。',
 '实验结果说明该方法有用。','报告指出这种方式有效。',
 '这个系统已被改造成自动执行工具的模型。',
 '该功能造成请求失败。','该产品可能造成安全风险。',
 '研究发现攻击可能造成20%的损失。','实验证明这种做法不会造成风险。']) {
 assert.ok(riskyAssertions(answer).assertions.length,`Still verify concrete claims: ${answer}`);
}
assert.ok(riskyAssertions(fixture.expected,{sourceOnly:true}).assertions.length,'Explicit evidence-only explanations stay bounded');
const mixed=await checkAnswer(fixture.expected+'\n\n这款产品的价格是99元。','解释这个概念',[],empty,noModel,'fixture','fixture',contextConfig());
assert.equal(mixed.answer,fixture.expected,'Withdraw only an unsupported price, preserving the complete concept explanation');
assert.equal(mixed.receipt.assertion_total,1);

// Related discussion, literal transcription, code, and legitimate short endings
// must not be shortened by the promotional-suffix guard.
for(const [question,answer] of [
 ['请解释彩票注册是什么意思',fixture.draft],
 ['请逐字转写这段内容',fixture.draft],
 ['请翻译这段文字',fixture.draft],
 ['解释这个概念',fixture.expected+'谢谢'],
 ['解释这个概念',fixture.expected+'下一步'],
 ['解释这个概念',fixture.expected+'“彩票注册”'],
 ['解释这个概念',fixture.expected+'\n\n```text\n彩票注册\n```'],
 ['解释这个概念',fixture.expected+'这段讨论涉及彩票。彩票注册']]) {
 const result=await checkAnswer(answer,question,[],empty,noModel,'fixture','fixture',contextConfig());
 assert.equal(result.answer,answer,'Retain relevant or literal text without guessing at completion');
 assert.equal(result.receipt.content_cleanup,undefined);
}
const native=nativeAgentRuntime({provider:'openai-compatible',model:'fixture'},{client:{chat:{completions:{
 async create(){return (async function*(){
  for(const part of [fixture.draft.slice(0,180),fixture.draft.slice(180)])
   yield {choices:[{delta:{content:part},finish_reason:null}]};
  yield {choices:[{delta:{},finish_reason:'stop'}],usage:{prompt_tokens:200,completion_tokens:222}};
 })();}
}}}});
const runtime={...noModel,async loadOpenWikiEnv(){},resolveConfiguredProvider(){return 'openai-compatible';},
 resolveModelId(){return 'fixture';},resolveProviderRetryAttempts(){return 0;},async createNativeAgent(){return native;}};
const visible=[];let rawCheckpoint;
const delivered=await runIntakeTurn(fixture.question,'consultation',
 {wiki:{text:'',reads:[]},templates:{text:'',reads:[]},skills:{text:'',reads:[]}},runtime,{
  currentQuestion:fixture.question,toolPolicy:{network_allowed:false,tools_enabled:false},
  onDelta:text=>visible.push(text),onCheckpoint:checkpoint=>{rawCheckpoint=checkpoint;},
  onUpdate:()=>{throw new Error('Do not expose unchecked output');}});
assert.equal(rawCheckpoint.answer,fixture.draft,'Keep the original provider output for diagnosis');
assert.equal(delivered.answer,fixture.expected);
assert.equal(visible.join(''),fixture.expected,'Visible delivery and saved final answer must agree after checks');
assert.equal(delivered.reply_delivery.mode,'after_checks');
assert.equal(delivered.answer_check.calls,0);
console.log('Reply completeness passed: exact incident replay, unrelated Wiki, definitions, cautions, mixed claims, source scope, suffix boundaries and native visible delivery.');
