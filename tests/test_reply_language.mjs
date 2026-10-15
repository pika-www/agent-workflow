/** Verify policy reaches real request boundaries; fixtures do not prove fluency. */
import assert from 'node:assert/strict';
import {runIntakeTurn,intakeSystemPrompt} from '../federation/intake-turn.mjs';
import {runPersonalIdentityTurn} from '../federation/personal-identity-turn.mjs';
import {nativeAgentRuntime} from '../federation/native-agent.mjs';
import {replyLanguagePolicy,withReplyLanguage} from '../federation/reply-language.mjs';

const evidence={wiki:{text:'',reads:[]},templates:{text:'',reads:[]},skills:{text:'',reads:[]}};
const requests=[];
const client={chat:{completions:{async create(request){requests.push(structuredClone(request));return (async function*(){
  yield {choices:[{delta:{content:'Hello!'},finish_reason:null}]};
  yield {choices:[{delta:{},finish_reason:'stop'}],usage:{prompt_tokens:40,completion_tokens:3}};
})();}}}};
const native=nativeAgentRuntime({provider:'openai-compatible',model:'fixture'},{client});
const runtime={async loadOpenWikiEnv(){},resolveConfiguredProvider(){return 'openai-compatible';},resolveModelId(){return 'fixture';},
  resolveProviderRetryAttempts(){return 0;},
  createNativeAgent(){return native;},createModel(){return {async invoke(messages){requests.push(structuredClone({messages}));return {content:'Hello!'};}};}};
for(const phase of ['consultation','proposal'])assert.ok(intakeSystemPrompt(phase).includes(replyLanguagePolicy));
assert.equal(withReplyLanguage(withReplyLanguage('Rules')),withReplyLanguage('Rules'));
const window={messages:[{id:'old-user',role:'user',content:'你好'},{id:'old-reply',role:'assistant',content:'你好。'}],revision:1,compaction_count:0};
for(const question of ['Hello!','Explain how to plan a small task.','请解释 React hooks。','Please answer in Chinese: how should I plan?']) {
  const result=await runIntakeTurn('当前接待任务','consultation',evidence,runtime,{currentQuestion:question,conversationWindow:window,onUpdate(){}});
  const messages=requests.at(-1).messages;
  assert.ok(messages[0].content.includes(replyLanguagePolicy));
  assert.doesNotMatch(messages[0].content,/用一句简短中文|用简体中文/);
  assert.equal(messages.at(-1).content,question,'The latest user language remains visible, separate from Chinese history');
  assert.equal(result.answer,'Hello!','No host-side translation of the model reply');
}
await runIntakeTurn('当前接待任务','consultation',evidence,{...runtime,createNativeAgent:undefined},{currentQuestion:'Explain task planning.'});
assert.ok(requests.at(-1).messages[0].content.includes(replyLanguagePolicy),'Plain-model fallback has the same policy');
await runPersonalIdentityTurn(native,runtime,'openai-compatible','fixture',{currentQuestion:'我叫什么？用英文回答。'});
assert.ok(requests.at(-1).messages[0].content.includes(replyLanguagePolicy),'Personal recall keeps the requested language');
console.log('Reply language: simple, native, compatibility, identity, latest question and explicit-language instruction boundaries passed.');

const {checkAnswer}=await import('../federation/answer-check.mjs');
const {contextConfig}=await import('../federation/context-budget.mjs');
const {publicEvidenceFallback}=await import('../federation/public-evidence.mjs');
const {isEnglishReply}=await import('../federation/reply-language.mjs');
assert.ok(isEnglishReply('Your name is 吴锋, and you work on frontend development.'));
assert.equal(isEnglishReply('你熟悉 React、Vue 和 TypeScript 开发。'),false);
const archive={inputs:[{path:'/example.md',text:'A recorded feature.',claims:[{kind:'fact',text:'A recorded feature.',semantic_review:'pending',status:'current',references:[{freshness:'local_only'}]}],citation_label:'[Wiki: /example.md]'}],omitted_paths:[]};
const checked=await checkAnswer('This page describes a recorded feature. [Wiki: /example.md]','Explain this archived page.',[{path:'/example.md',citation_label:'[Wiki: /example.md]'}],archive,
 {createModel(){return {async invoke(){throw new Error('Simulate unavailable auxiliary check');}};}},'fixture','fixture',contextConfig());
assert.doesNotMatch(checked.answer,/[\u3400-\u9fff]/);
assert.match(checked.answer,/archived material/);
const excerpt=publicEvidenceFallback([{source_url:'https://example.com',source_title:'Example',source_excerpt:'A recorded feature is described on this page.',citation_label:'来源：<https://example.com>'}],{question:'Describe the feature',language:'en'});
assert.match(excerpt,/Source: <https:\/\/example.com>/);assert.doesNotMatch(excerpt,/[\u3400-\u9fff]/);
console.log('English host-generated archive notices, source labels and evidence fallback passed.');
