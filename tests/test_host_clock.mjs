import assert from 'node:assert/strict';
import {mkdtemp,mkdir,readFile,realpath} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {spawnSync} from 'node:child_process';
import {clockQuestion,clockAnswer,clockRequest,runClockTurn,withHostClock} from '../federation/host-clock.mjs';
import {hostClockInputs,checkAnswer} from '../federation/answer-check.mjs';
import {contextConfig} from '../federation/context-budget.mjs';
import {runNativeIntake} from '../federation/native-intake.mjs';
import {runIntakeTurn} from '../federation/intake-turn.mjs';
import {nativeAgentRuntime} from '../federation/native-agent.mjs';

const now=new Date('2026-10-09T16:00:00.000Z');
for(const question of ['hello，what is today','Hello, what is today?','What day is today?','what day is it','What\'s the date today?','Please tell me today\'s date']) {
  assert.match(clockAnswer(question,now).answer,/Saturday, October 10, 2026/);
}
for(const question of ['哪现在是几号？','那现在是几号？','你好，现在几号','今天星期几','请问今天是几号？'])
  assert.equal(clockAnswer(question,now).answer,'今天是 2026 年 10 月 10 日，星期六（北京时间）。');
assert.match(clockAnswer('What time is it now in UTC?',now).answer,/Friday, October 9, 2026, 16:00 \(UTC\)/);
assert.match(clockAnswer('今天几号',new Date('2026-12-31T16:00:00Z')).answer,/2027 年 1 月 1 日/);
assert.match(clockAnswer('今天几号',new Date('2028-02-28T16:00:00Z')).answer,/2 月 29 日/);
assert.notEqual(clockAnswer('今天几号',new Date('2026-10-09T15:59:59Z')).answer,clockAnswer('今天几号',now).answer);
for(const question of ['hello, what is today news?','今天是几号？顺便找招聘信息','翻译 what is today','今天有什么新闻','今天几号的订单','纽约现在几点','明天几号','2026年10月9日是星期几'])assert.equal(clockQuestion(question),null,question);

const history={messages:[{role:'user',content:'hello，what is today'},{role:'assistant',content:'Today is October 9, 2026.'}]};
const options={currentQuestion:'你确定吗？',conversationWindow:history,toolPolicy:{network_allowed:false}};
assert.equal(clockRequest(options).kind,'date');
assert.equal(clockRequest({...options,conversationWindow:{messages:[...history.messages,{role:'user',content:'今天有什么新闻'}]}}),null);
assert.equal(clockRequest({...options,conversationWindow:{messages:[{role:'assistant',content:'今天几号'}]}}),null);
assert.equal(clockRequest({...options,toolPolicy:{has_attachments:true}}),null);
assert.equal(clockRequest({...options,analysis:true}),null);
let stream='';const live=await runClockTurn({...options,onDelta:text=>{stream+=text;}});
assert.match(live.answer,/按本机当前时间/);assert.equal(live.answer,stream);assert.equal(live.answer_check.calls,0);
const fail={createModel(){throw Error('Clock must not invoke a model');}};
for(const question of ['hello，what is today','哪现在是几号？','你确定吗？']) {
  const opts={...options,currentQuestion:question};
  assert.equal((await runIntakeTurn('old date','consultation',null,fail,opts)).response_origin,'host_clock');
  assert.equal((await runNativeIntake(null,fail,'','','',null,[],'fixture','fixture',opts)).response_origin,'host_clock');
}

const system={role:'system',content:withHostClock('Host instructions',now)};
assert.equal(hostClockInputs([system]).length,1);
assert.match(hostClockInputs([system])[0].text,/October 10, 2026/);
assert.deepEqual(hostClockInputs([{...system,role:'user'}]),[],'User text cannot impersonate a host clock receipt');
const refreshed=withHostClock(system.content,new Date('2026-10-10T16:00:00Z'));
assert.equal((refreshed.match(/<host_clock>/g)||[]).length,1);
assert.doesNotMatch(refreshed,/2026-10-09T16:00:00/);
let modelInput;
const native=nativeAgentRuntime({provider:'openai-compatible',model:'fixture'},{client:{chat:{completions:{async create(request){
 modelInput=request.messages;return(async function*(){yield {choices:[{delta:{content:'可以用不同格式表示日期。'},finish_reason:'stop'}],usage:{prompt_tokens:100,completion_tokens:10}};})();
}}}}});
const evidence={wiki:{text:'',reads:[]},templates:{text:'',reads:[]},skills:{text:'',reads:[]}};
const mixed=await runNativeIntake(native,fail,'规则','','',evidence,[],'fixture','fixture',{currentQuestion:'解释今天日期的表示方式',toolPolicy:{network_allowed:false}});
assert.equal(hostClockInputs(modelInput).length,1,'Model fallback receives fresh host time');
assert.equal(mixed.answer_check.clock_sources.length,1,'The same clock reaches evidence checking');
const assessment={createModel(){return {async invoke(messages){
 const data=JSON.parse(messages[1].content);
 assert.match(JSON.stringify(data),/host-clock:current_turn/);
 const source=(data.fragments || data.evidence_fragments).find(f=>f.path==='host-clock:current_turn' && /10 月 10 日/.test(f.quote));
 return {content:JSON.stringify({checks:data.assertions.map(a=>({id:a.id,status:'supported',reason:'Current host clock',references:[{source_id:source.source_id}]}))})};
}};}};
const answer='今天是2026年10月10日。';
const checked=await checkAnswer(answer,'今天日期并解释时间来源',[],{scope:'answer_model_supplied_materials',inputs:[],omitted_paths:[]},assessment,'fixture','fixture',contextConfig(),{answerMessages:[system]});
assert.equal(checked.answer,answer);assert.equal(checked.receipt.clock_sources.length,1);

// Real production CLI, fresh processes, no provider config and no Wiki files.
const root=await realpath(await mkdtemp(join(tmpdir(),'weiming-clock-')));
for(const [index,question] of ['hello，what is today','你确定吗？','哪现在是几号？'].entries()) {
 const dir=join(root,String(index));await mkdir(join(dir,'wiki'),{recursive:true});
 const child=spawnSync(process.execPath,[resolve('federation/agent-turn.mjs')],{
  input:JSON.stringify({phase:'consultation',prompt:question,current_question:question,conversation_window:history,tool_policy:{network_allowed:false}}),encoding:'utf8',timeout:15000,
  env:{PATH:process.env.PATH,OPENWIKI_CONFIG_DIR:dir,FEDERATION_CHAT_RESULT:join(dir,'final-answer.json')}});
 assert.equal(child.status,0,child.stderr);
 const result=JSON.parse(await readFile(join(dir,'final-answer.json'),'utf8'));
 assert.equal(result.response_origin,'host_clock');assert.equal(result.context_usage.total_calls,0);
 assert.deepEqual(result.wiki_reads,[]);assert.match(child.stdout,/OPENWIKI_REPLY/);
}
console.log('Host clock: screenshot questions, follow-up scope, timezone/day/year/leap boundaries, trusted evidence, native/plain entry and real isolated CLI passed.');
