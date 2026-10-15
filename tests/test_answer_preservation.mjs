import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {riskyAssertions,checkAnswer} from '../federation/answer-check.mjs';
import {contextConfig} from '../federation/context-budget.mjs';

const empty={scope:'answer_model_supplied_materials',inputs:[],omitted_paths:[]};
const noModel={createModel(){throw new Error('General explanation must not trigger evidence or rewrite calls');}};
// Reported regression: a completed conversational reply waited for an evidence
// model solely because of “因为”, then lost its first sentence after the check.
const nicknameReply='因为“母狗”通常带有侮辱和性化意味，我不接受这种称呼。你可以叫我“主 Agent”或给我取一个尊重、友好的昵称；我也会正常叫你吴锋。';
for (const answer of [nicknameReply,
 '因为我想认真理解你的意思，所以会先听你说完。',
 '因此，你可以用自己喜欢的方式表达。',
 '由于信息还不完整，我想先听听你的想法。',
 'RAG 把检索到的资料交给模型，因此回答可以参考这些资料。']) {
 const progress=[],updates=[];
 const result=await checkAnswer(answer,'为什么不行？',[],empty,noModel,'fixture','fixture',contextConfig(),{
  answerMessages:[{role:'user',content:'为什么不行？'}],
  onProgress:event=>progress.push(event),onUpdate:event=>updates.push(event)});
 assert.equal(result.answer,answer,'Conversational wording must survive finalization verbatim');
 assert.equal(result.receipt.calls,0);assert.equal(result.receipt.repair_count,0);
 assert.equal(result.receipt.assertion_total,0);
 assert.equal(result.receipt.original_answer_sha256,result.receipt.final_answer_sha256);
 assert.deepEqual(progress,[],'Do not publish a checking stage when no check is needed');
 assert.deepEqual(updates,[]);
}
for (const answer of [
 '因为促销，这款产品价格为99元。',
 '因此，该系统采用 Redis 保存订单。',
 '由于更新，本项目已经部署成功。',
 '因为研究表明这个方法有效，我们采用它。',
 '由于这款产品的作用，效率提高了。',
 '该功能导致请求失败。',
 '因此，该平台支持免费服务。']) {
 const assertions=riskyAssertions(answer).assertions;
 assert.ok(assertions.length,answer);
 assert.ok(assertions[0].risks.includes('causal_or_result'),answer);
}
assert.ok(riskyAssertions(nicknameReply,{sourceOnly:true}).assertions.length,
 'Explicit source-only requests still require evidence for causal explanations');
const mixedConversation=await checkAnswer(nicknameReply+'因为促销，这款产品价格为99元。',
 '为什么不行？',[],empty,noModel,'fixture','fixture',contextConfig());
assert.equal(mixedConversation.answer,nicknameReply,'Withdraw the unsupported price, preserving the explanation');
assert.equal(mixedConversation.receipt.assertion_total,1);
const mixedExecution=await checkAnswer(nicknameReply+'因此，本项目已经部署成功。',
 '为什么不行？',[],empty,noModel,'fixture','fixture',contextConfig());
assert.equal(mixedExecution.answer,nicknameReply,'A factual claim in the same paragraph must not reclassify conversational prose');
assert.equal(mixedExecution.receipt.assertion_total,1);
for (const answer of ['“不能确定”是指现有信息还不足以作出肯定判断，可以继续补充信息。',
 'RAG 是检索增强生成，把查到的资料作为回答的参考。',
 '名字是一种称呼，你可以叫我未明，也可以选一个你喜欢的名字。']) {
 const result=await checkAnswer(answer,'请解释一下',[],empty,noModel,'fixture','fixture',contextConfig());
 assert.equal(result.answer,answer);assert.equal(result.receipt.calls,0);
}

const fixture=JSON.parse(await readFile(new URL('./fixtures/answer-check-dialogue.json',import.meta.url),'utf8'));
const selected=riskyAssertions(fixture.draft).assertions;
assert.equal(selected.length,1);assert.match(selected[0].text,/后来被要求删除/);
let calls=0;
const assessOnly={createModel(p,i,r,max){assert.equal(max,1600,'Retained explanation must not be sent to an all-answer rewrite');return {async invoke(messages){
 calls++;const data=JSON.parse(messages[1].content);
 return {content:JSON.stringify({checks:data.assertions.map(a=>({id:a.id,status:'insufficient',reason:'没有实际删除回执',references:[]}))})};
}};}};
const checked=await checkAnswer(fixture.draft,fixture.question,[],empty,assessOnly,'fixture','fixture',contextConfig(),
 {answerMessages:[{role:'user',content:fixture.question}]});
assert.equal(calls,1);assert.equal(checked.receipt.repair_count,0);
assert.equal(checked.receipt.repair_scope,'factual_assertions_only');
assert.match(checked.answer,/资料缺口/);assert.match(checked.answer,/简单来说/);
assert.doesNotMatch(checked.answer,/删除了相关权重|search_available|无法给出.*详细解释|资料中未提供关于/);
assert.doesNotMatch(checked.answer,/以下两种情况/,'Removing a list item does not leave an incorrect count in the introduction');

const sameParagraph='不确定是一种对信息完整性的描述。本项目已经部署成功。';
const failed=await checkAnswer(sameParagraph,'请解释不确定的意思',[],empty,{createModel(){return {async invoke(){throw new Error('fixture timeout');}}}},
 'fixture','fixture',contextConfig(),{answerMessages:[{role:'user',content:'请解释不确定的意思'}]});
assert.equal(failed.answer,'不确定是一种对信息完整性的描述。');
assert.equal(failed.receipt.fallback_basis,'preserved_general_prose_and_exact_input_quotes');

const mixedCode='不确定是一种对信息完整性的描述。\n\n```js\nconst example = "研究证明效率提高900%";\n```\n\n本项目已经部署成功。';
const codeResult=await checkAnswer(mixedCode,'解释并给代码示例',[],empty,{createModel(){return {async invoke(){throw new Error('fixture timeout');}}}},
 'fixture','fixture',contextConfig(),{answerMessages:[{role:'user',content:'解释并给代码示例'}]});
assert.match(codeResult.answer,/const example = "研究证明效率提高900%"/);
assert.doesNotMatch(codeResult.answer,/本项目已经部署成功/);

const dialogueDraft='根据你目前的表达方式，只能做初步推测：\n\n可以先记录今天的一次具体经历。\n\n目前最明显的画像是：务实、简洁、结果导向。';
let checkedUserQuestion=false;
const dialogueChecked=await checkAnswer(dialogueDraft,'分析我的性格\n用户当前追问（以此为准）：请把刚才的建议具体一点',[],empty,
 {createModel(){return {async invoke(messages){
  const data=JSON.parse(messages[1].content);
  const fragment=data.fragments.find(f=>f.path==='user-context:current_question');
  assert.equal(fragment.quote,'请把刚才的建议具体一点');checkedUserQuestion=true;
  return {content:JSON.stringify({checks:data.assertions.map((a,i)=>({id:a.id,status:i===0?'supported':'insufficient',reason:'仅有当前表达',references:i===0?[{source_id:fragment.source_id}]:[]}))})};
 }};}},'fixture','fixture',contextConfig(),{currentQuestion:'请把刚才的建议具体一点',answerMessages:[{role:'user',content:'请把刚才的建议具体一点'}]});
assert.ok(checkedUserQuestion);
assert.equal(dialogueChecked.receipt.checks[0].status,'supported');
assert.equal(dialogueChecked.receipt.repair_status,'withdrawal_fallback');
assert.match(dialogueChecked.answer,/记录今天的一次具体经历/);
assert.doesNotMatch(dialogueChecked.answer,/用户当前追问|用户要求或用户记录|不构成事实验证/);

const sourceOnly=await checkAnswer('RAG 是检索增强生成。','只用本库解释 RAG 是什么',[],empty,
 {createModel(p,i,r,max){return {async invoke(messages){const data=JSON.parse(messages[1].content);return {content:max===1600
  ?JSON.stringify({checks:data.assertions.map(a=>({id:a.id,status:'insufficient',reason:'指定资料没有定义',references:[]}))})
  :'这份资料没有 RAG 的定义。'};}};}},'fixture','fixture',contextConfig(),{answerMessages:[{role:'user',content:'只用本库解释 RAG 是什么'}]});
assert.equal(sourceOnly.receipt.source_only,true);assert.notEqual(sourceOnly.answer,'RAG 是检索增强生成。');
for (const answer of ['我会先解释：研究证明效率提高900%。','这款产品支持免费服务。','这个系统采用 Redis 保存订单。',
 '本项目已经部署成功。','某些功能后来被删除，因此现在无法确认可用。','RAG 是检索增强生成。[Wiki: /invented.md]'])
 assert.ok(riskyAssertions(answer).assertions.length>0,answer);
console.log('Answer preservation passed: exact reported draft, general knowledge and names, selective runtime withdrawal, timeout, code, source-only scope, citations and concrete claims.');
const websiteQuestion='这个网站是干嘛的 https://aiflbchengzi.com/';
assert.ok(riskyAssertions('aiflbchengzi 很可能是“AI 飞镖成子”的拼音缩写。',{question:websiteQuestion}).assertions.some(a=>a.risks.includes('website_fact')));
assert.equal(riskyAssertions('RAG 是检索增强生成。',{question:websiteQuestion}).assertions.length,0);
