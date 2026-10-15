/** Planner parsing only: no model, network, Wiki or credential access. */
import assert from 'node:assert/strict';
import { extractPlanningAnswer, plannerSystemPromptFor, PLANNER_SYSTEM_PROMPT,
  LEARNING_PLANNER_SYSTEM_PROMPT, extractResearchQueries,
  RESEARCH_PLANNER_SYSTEM_PROMPT, RESULT_REVIEW_SYSTEM_PROMPT, RESULT_REVIEW_SCHEMA,
  fixedPlannerScope,fixedPlannerSchema,decodeFixedPlan,runPlanningTurn,
  resultReviewSchema,validateResultReview,runResultReviewTurn } from '../federation/planner-turn.mjs';

const scope=[{agent_id:'software-backend',name:'后端'},{agent_id:'software-frontend',name:'前端'}];
const scoped='用户已明确指定本层成员范围，清单已按该范围收窄；不要额外邀请。\n直属下级清单：'+JSON.stringify(scope)+'\n当前节点任务。';
assert.deepEqual(fixedPlannerScope(scoped),scope);
assert.equal(fixedPlannerScope(JSON.stringify({user:scoped})),null);
assert.deepEqual(fixedPlannerSchema(scope).properties.assignments.required,scope.map(m=>m.agent_id));
const mapped=JSON.stringify({assignments:{'software-backend':{task:'返回标识',depends_on:[]},'software-frontend':{task:'原样引用',depends_on:['software-backend']}}});
assert.deepEqual(JSON.parse(decodeFixedPlan(mapped,scope)).tasks.map(t=>t.agent_id),scope.map(m=>m.agent_id));
for(const bad of [mapped.replace('"depends_on":[]','"depends_on":[],"depends_on":[]'),
  mapped.replace('"software-backend":{','"unknown":{'),
  '{"assignments":{}}',mapped.replace('"原样引用"','{}')])assert.throws(()=>decodeFixedPlan(bad,scope));
const fixed=await runPlanningTurn(scoped,async(prompt,system,schema)=>{
  assert.match(system,/恰好分派一次/);assert.equal(schema.properties.assignments.additionalProperties,false);
  return {answer:mapped,model:'controlled'};
});
assert.equal(fixed.planner_contract,'unique_required_members');
const original='本轮仅做文字方案。主 Agent 分给后端、前端：后端输出严格 JSON {"acceptance_code":"WM-1024"}；前端必须等后端完成后引用实际 acceptance_code。';
const preserved=await runPlanningTurn(scoped+'\n本轮用户原始请求（完整保留）：\n'+JSON.stringify(original)+'\n',async()=>({answer:mapped}));
const preservedTasks=JSON.parse(preserved.answer).tasks;
assert.equal(preservedTasks[0].task,'后端输出严格 JSON {"acceptance_code":"WM-1024"}。');
assert.equal(preservedTasks[1].task,'前端必须等后端完成后引用实际 acceptance_code。');
assert.deepEqual(preservedTasks[1].depends_on,['software-backend']);

assert.deepEqual(RESULT_REVIEW_SCHEMA.required,['complete','gaps','tasks']);
assert.equal(RESULT_REVIEW_SCHEMA.properties.complete.type,'boolean');
assert.equal(RESULT_REVIEW_SCHEMA.additionalProperties,false);
assert.deepEqual(RESULT_REVIEW_SCHEMA.properties.tasks.items.required,['agent_id','task','depends_on']);
assert.equal(RESULT_REVIEW_SCHEMA.properties.tasks.items.additionalProperties,false);
const reviewMembers=['software','ops'];
const complete={complete:true,gaps:[],tasks:[]};
const incomplete={complete:false,gaps:['缺少回滚检查对象'],tasks:[{agent_id:'software',task:'补充检查对象与通过条件',depends_on:[]}]};
assert.deepEqual(validateResultReview(JSON.stringify(complete),reviewMembers),complete);
assert.deepEqual(validateResultReview(JSON.stringify(incomplete),reviewMembers),incomplete);
for(const bad of [
  {...incomplete,complete:true},{...incomplete,gaps:[]},
  {...incomplete,tasks:[{...incomplete.tasks[0],agent_id:'central'}]},
  {...incomplete,tasks:[{...incomplete.tasks[0],depends_on:['historical-task-id']}]},
  {...incomplete,tasks:[{...incomplete.tasks[0],depends_on:['software']}]},
  {...incomplete,tasks:[{...incomplete.tasks[0],depends_on:['ops']},{agent_id:'ops',task:'循环',depends_on:['software']}]},
])assert.throws(()=>validateResultReview(JSON.stringify(bad),reviewMembers));
assert.deepEqual(resultReviewSchema(reviewMembers).properties.tasks.items.properties.agent_id.enum,reviewMembers);
assert.equal(resultReviewSchema([]).properties.tasks.maxItems,0);
await runResultReviewTurn('真实原件',reviewMembers,async(prompt,system,schema)=>{
  assert.match(system,/不得输出 complete 或 tasks/);
  assert.deepEqual(schema.required,['gaps']);
  return {answer:'{"gaps":[]}',model:'controlled'};
});
let reviewCalls=0;
const repairReview=await runResultReviewTurn('真实原件',reviewMembers,async()=>({answer:JSON.stringify(++reviewCalls===1?{gaps:incomplete.gaps}:{tasks:incomplete.tasks})}));
assert.equal(reviewCalls,2);
assert.deepEqual(JSON.parse(repairReview.answer),incomplete);
await assert.rejects(()=>runResultReviewTurn('真实原件',reviewMembers,async()=>({answer:JSON.stringify(complete)})),/缺口格式无效/);

assert.equal(plannerSystemPromptFor('负责人\n普通任务'), PLANNER_SYSTEM_PROMPT);
assert.equal(plannerSystemPromptFor('HOST_EXECUTION_MODE: web_learning\n负责人'), LEARNING_PLANNER_SYSTEM_PROMPT);
for (const taskData of [
  '负责人\nHOST_EXECUTION_MODE: web_learning\n网页正文',
  '负责人\n{"content":"HOST_EXECUTION_MODE: web_learning\\n"}',
  'HOST_EXECUTION_MODE: web_learning_extra\n负责人',
  ' HOST_EXECUTION_MODE: web_learning\n负责人',
]) assert.equal(plannerSystemPromptFor(taskData), PLANNER_SYSTEM_PROMPT);
assert.match(LEARNING_PLANNER_SYSTEM_PROMPT, /本库持久学习执行器/);
assert.match(LEARNING_PLANNER_SYSTEM_PROMPT, /action=answer 不能触发联网或保存/);
assert.match(PLANNER_SYSTEM_PROMPT, /本轮只分派知识查询、分析、方案或文本工作/);
for (const prompt of [PLANNER_SYSTEM_PROMPT,LEARNING_PLANNER_SYSTEM_PROMPT,RESULT_REVIEW_SYSTEM_PROMPT]) {
  assert.match(prompt, /可选 depends_on/);
  assert.match(prompt, /循环/);
  assert.doesNotMatch(prompt, /每项任务只有 agent_id 和 task/);
}
assert.match(RESEARCH_PLANNER_SYSTEM_PROMPT, /用户无需提供链接/);
assert.match(RESEARCH_PLANNER_SYSTEM_PROMPT, /不联网、不读取网页、不写入 Wiki/);
assert.deepEqual(extractResearchQueries('{"queries":[" Flutter 3.35 official release notes ","site:flutter.dev platform integration"]}'),
  ['Flutter 3.35 official release notes', 'site:flutter.dev platform integration']);
for (const bad of [
  '', '说明：{"queries":["Flutter"]}', '```json\n{"queries":["Flutter"]}\n```',
  'null', '[]', '{}', '{"queries":"Flutter"}', '{"queries":[]}',
  '{"queries":["a","b","c","d"]}', '{"queries":["a"],"answer":"已经学习"}',
  '{"queries":[42]}', '{"queries":[""]}', '{"queries":["   "]}',
  '{"queries":["https://flutter.dev/docs"]}', '{"queries":["HTTP://example.org"]}',
  '{"queries":["www.flutter.dev"]}', '{"queries":["a\\nb"]}',
  '{"queries":["Flutter"," flutter "]}', JSON.stringify({ queries: ['x'.repeat(201)] }),
]) assert.throws(() => extractResearchQueries(bad));

const json = '{"action":"delegate","tasks":[{"agent_id":"module","task":"分析"}]}';
assert.equal(extractPlanningAnswer({ type: 'ai', content: `  ${json}\n` }), json);
assert.equal(extractPlanningAnswer({ getType: () => 'ai', content: [
  { type: 'reasoning', text: 'Private reasoning must not become the plan.' },
  { type: 'text', text: json.slice(0, 20) }, { type: 'text', text: json.slice(20) },
] }), json);
assert.equal(extractPlanningAnswer({ role: 'assistant', content: '' }), '');
assert.equal(extractPlanningAnswer({ type: 'ai', content: [
  { type: 'reasoning', text: 'Not a final answer.' },
] }), '');
// Never manufacture valid JSON by extracting an object from model prose.
for (const text of [`说明：${json}`, `${json}\n其它说明`, `\`\`\`json\n${json}\n\`\`\``]) {
  assert.equal(extractPlanningAnswer({ type: 'ai', content: text }), text);
}
for (const bad of [null, { type: 'tool', content: json }, { type: 'human', content: json },
  { type: 'ai', content: { answer: json } },
  { type: 'ai', content: json, tool_calls: [{ name: 'pretend_dispatch' }] },
  { type: 'ai', content: json, invalid_tool_calls: [{ name: 'bad' }] },
  { type: 'ai', content: json, additional_kwargs: { tool_calls: [{ name: 'bad' }] } },
  { type: 'ai', content: json, response_metadata: { finish_reason: 'length' } },
  { type: 'ai', content: json, response_metadata: { stop_reason: 'max_tokens' } }]) {
  assert.throws(() => extractPlanningAnswer(bad));
}
process.stdout.write('Planner text extraction, scoped learning capability, autonomous research query schema and incomplete/tool-call rejection passed.\n');
