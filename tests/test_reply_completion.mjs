import assert from 'node:assert/strict';
import {clockQuestion,clockAnswer} from '../federation/host-clock.mjs';
import {runIntakeTurn} from '../federation/intake-turn.mjs';
import {runNativeIntake} from '../federation/native-intake.mjs';
import {checkAnswer} from '../federation/answer-check.mjs';
import {hasAnswerBody} from '../federation/public-evidence.mjs';
import {contextConfig} from '../federation/context-budget.mjs';

const date=new Date('2026-10-08T16:00:00Z');
assert.equal(clockAnswer('现在是几几年几月几号？',date).answer,'今天是 2026 年 10 月 9 日，星期五（北京时间）。');
assert.equal(clockAnswer('UTC 今天几号？',date).answer,'今天是 2026 年 10 月 8 日，星期四（UTC）。');
assert.match(clockAnswer('请问现在几点？',date).answer,/00:00/);
for (const q of ['查一下今天 X 上有什么消息','今天是几号？顺便找最新新闻','今天农历几号','纽约现在几点','2026年10月9日是星期几','今天是什么节日','明天几号']) assert.equal(clockQuestion(q),null,q);
const fail={createModel(){throw new Error('Clock reply must not need a model');}};
const evidence={wiki:{text:'',reads:[]},templates:{text:'',reads:[]},skills:{text:'',reads:[]}};
let streamed='';
const options={currentQuestion:'现在是几几年几月几号？',toolPolicy:{network_allowed:true,default_online:true},onDelta:s=>{streamed+=s;}};
const clock=await runIntakeTurn('unrelated history','consultation',evidence,fail,options);
assert.equal(clock.response_origin,'host_clock');assert.equal(clock.answer_check.calls,0);assert.equal(clock.answer,streamed);
assert.equal((await runNativeIntake(null,fail,'','','',evidence,[],'fixture','fixture',options)).response_origin,'host_clock');

const empty={scope:'answer_model_supplied_materials',inputs:[],omitted_paths:[]};
const url='https://example.com/calendar';
const publicBody=[{tool:'web_read',result:{status:'completed',sources:[{url,title:'日期',excerpt:'这个网站是用于查看日历的工具。今天是2026年10月9日，星期五（北京时间）。',read_method:'static_html'}]}}];
const original=`这个网站是用于查看日历的工具。来源：${url}`;
const timeout={createModel(){return {async invoke(){throw Object.assign(new Error('fixture timeout'),{name:'TimeoutError'});}}}};
const checked=await checkAnswer(original,'这个网站是干嘛的？',[],empty,timeout,'fixture','fixture',contextConfig(),{toolEvidence:publicBody});
assert.ok(checked.answer.includes(original),'A failed check cannot erase the streamed answer to a URL');
assert.match(checked.answer,/初步答复.*尚待核实/);
assert.equal(checked.receipt.repair_status,'preserved_with_uncertainty');
assert.equal(checked.receipt.semantic_correctness,'not_evaluated');
assert.equal(checked.receipt.unchecked_assertions_withdrawn,0);
assert.ok(hasAnswerBody(checked.answer));
for (const toolEvidence of [[],publicBody.map(o=>({...o,tool:'web_search'}))]) {
 const result=await checkAnswer(original,'日期是什么？',[],empty,timeout,'fixture','fixture',contextConfig(),{toolEvidence});
 assert.ok(!result.answer.includes(original),'Search snippets alone do not restore an unassessed answer');
 assert.ok(hasAnswerBody(result.answer),'Failure must still give a useful explanation, never only links');
}
const execution=await checkAnswer(`本项目已经部署成功。来源：${url}`,'项目情况',[],empty,timeout,'fixture','fixture',contextConfig(),{toolEvidence:publicBody});
assert.ok(!execution.answer.includes('本项目已经部署成功'),'A search source cannot restore a fabricated execution claim');
const scoped=await checkAnswer(original,'只根据本库回答日期',[],empty,timeout,'fixture','fixture',contextConfig(),{toolEvidence:publicBody});
assert.notEqual(scoped.receipt.repair_status,'preserved_with_uncertainty');
const negative={createModel(p,i,r,max){return {async invoke(messages){const data=JSON.parse(messages[1].content);return {content:max===1600?JSON.stringify({checks:data.assertions.map(a=>({id:a.id,status:'insufficient',reason:'来源未支持这个结论',references:[]}))}):'目前无法确认日期。'};}};}};
const rejected=await checkAnswer(original,'日期是什么？',[],empty,negative,'fixture','fixture',contextConfig(),{toolEvidence:publicBody});
assert.ok(!rejected.answer.includes(original),'Completed negative findings still correct the answer');
assert.ok(hasAnswerBody(rejected.answer));
console.log('Reply completion: host date/time, timezone boundary, no models/tools, exact streamed content, public-source timeout, no-link-only final, explicit scope and execution boundaries passed.');
