import assert from 'node:assert/strict';
import {outputContract, outputViolations, enforceOutputContract,unsupportedExecutionClaims} from '../federation/delegation-output.mjs';
import {outputRepairRequest,structuredResponseOptions,OUTPUT_REPAIR_SCHEMA,parseOutputRepair,answerSchema,runDelegatedTextTurn,appendHostSuffix} from '../federation/planner-turn.mjs';

assert.equal(answerSchema(53).properties.answer.maxLength,53);
assert.equal(answerSchema(null).properties.answer.maxLength,undefined);
const textOnly='仅输出聊天方案，不联网、不运行命令、不修改文件、不部署。汇总最多150字。';
assert.deepEqual(unsupportedExecutionClaims('后端 WM-1024 完成。前后端共四步验证通过。'),['前后端共四步验证通过']);
assert.deepEqual(unsupportedExecutionClaims('建议测试通过后再部署；没有实际执行回滚；方案已完成。'),[]);
assert.deepEqual(unsupportedExecutionClaims('前端依据后端 WM-1024 代码确认页面加载成功，无额外执行或验证操作。'),['前端依据后端 WM-1024 代码确认页面加载成功，无额外执行或验证操作']);
assert.deepEqual(unsupportedExecutionClaims('后端 WM-1024 产出，前端加载确认页成功。'),['后端 WM-1024 产出，前端加载确认页成功']);
assert.deepEqual(unsupportedExecutionClaims('建议在加载成功后显示编号；如果启动成功再验收。'),[]);
assert.deepEqual(unsupportedExecutionClaims('页面仅显示状态码 WM-1024 与加载完成指示，避免断言通过或部署。'),[]);
assert.deepEqual(unsupportedExecutionClaims('页面加载完成。'),['页面加载完成']);
assert(outputViolations('前后端共四步验证通过。',outputContract('汇总最多150字','summary',textOnly)).length);
const correctedClaim=await enforceOutputContract('汇总最多150字','summary','后端 WM-1024 完成。前后端共四步验证通过。',async input=>{
 assert(input.violations.some(v=>v.includes('无实际操作回执')));return '后端交付 WM-1024；本轮仅交付文字方案。';
},textOnly);
assert.equal(correctedClaim.receipt.status,'repaired');
assert.match(correctedClaim.receipt.original_answer,/四步验证通过/);
await assert.rejects(()=>enforceOutputContract('汇总最多150字','summary','后端 WM-1024 完成。前后端共四步验证通过。',async input=>input.answer,textOnly),/仍未通过/);
assert(outputViolations('前端依赖后端，不',{max_characters:80,required_literals:[]}).some(issue=>issue.includes('中途结束')));
assert(outputViolations('核对目标，不得\n约束：不得覆盖历史。',{max_characters:80,required_literals:['不得覆盖历史']}).some(issue=>issue.includes('中途结束')));
const bounded=await runDelegatedTextTurn('根据原件回答。',{max_characters:80,required_literals:['不得覆盖历史']},async(prompt,system,schema)=>{
  assert(schema.properties.answer.maxLength<80);
  assert.match(system,/没有工具/);
  return {answer:'{"answer":"核对备份版本。"}',model:'controlled'};
});
assert.equal(bounded.answer,'核对备份版本。\n约束：不得覆盖历史。');
const jsonContract=outputContract('后端自行选择一个标识，返回包含 acceptance_code 的极简 JSON。','execute');
assert.equal(outputContract('后端返回包含 acceptance_code 的 JSON。主 Agent 汇总最多150字。','summary').json_fields,undefined);
assert.deepEqual(jsonContract.json_fields,['acceptance_code']);
assert(outputViolations('接受任务，标识 WM-0001。',jsonContract).length);
assert(outputViolations('{"wrong":"WM-0001"}',jsonContract).length);
assert.deepEqual(outputViolations('{"acceptance_code":"WM-7192"}',jsonContract),[]);
const actualJSON=await runDelegatedTextTurn('后端自行选标识。',jsonContract,async(prompt,system,schema)=>{
  assert.deepEqual(schema.required,['acceptance_code']);
  assert.equal(schema.properties.acceptance_code.type,'string');
  return {answer:'{"acceptance_code":"WM-7192"}',model:'controlled'};
});
assert.equal(actualJSON.answer,'{"acceptance_code":"WM-7192"}');
const literalContract=outputContract('后端输出严格 JSON {"acceptance_code":"WM-1024"}。','execute');
assert.deepEqual(literalContract.json_constants,{acceptance_code:'WM-1024'});
assert.deepEqual(outputViolations('{"acceptance_code":"WM-1024"}',literalContract),[]);
assert(outputViolations('{"acceptance_code":"WM-9999"}',literalContract).length);
assert(outputViolations('{"acceptance_code":"WM-1024","extra":1}',literalContract).length);
await runDelegatedTextTurn('真实请求',literalContract,async(prompt,system,schema)=>{
  assert.equal(schema.properties.acceptance_code.const,'WM-1024');
  return {answer:'{"acceptance_code":"WM-1024"}'};
});
await assert.rejects(()=>runDelegatedTextTurn('真实请求',literalContract,async()=>({answer:'{"acceptance_code":"WM-9999"}'})),/JSON 产物字段无效/);
const numeric=await runDelegatedTextTurn('返回数值 count。',outputContract('返回包含 count 的 JSON','execute'),async()=>({answer:'{"count":3}'}));
assert.equal(numeric.answer,'{"count":3}');
const leaked='引用 WM-1024 产物。展示：JSON 卡片直接显示 acceptance_code字段内容。”}';
assert(outputViolations(leaked,{max_characters:80,required_literals:[]}).some(issue=>issue.includes('包装残片')));
assert.deepEqual(outputViolations('展示 JSON：{"acceptance_code":"WM-1024"}',{max_characters:80,required_literals:[]}),[]);
const cleaned=await enforceOutputContract('80字内原样引用标识','execute',leaked,async()=>{throw Error('Exact unmatched wrapper needs no model');});
assert.equal(cleaned.receipt.calls,0);
assert.equal(cleaned.answer,'引用 WM-1024 产物。展示：JSON 卡片直接显示 acceptance_code字段内容。');
assert.equal(cleaned.receipt.original_answer,leaked);
const suffix='\n约束：不得覆盖历史。';
assert.equal(appendHostSuffix('实际结果。'+suffix+suffix,suffix),'实际结果。'+suffix);
assert.equal(appendHostSuffix('正文中提到约束：不得覆盖历史。',suffix),'正文中提到约束：不得覆盖历史。'+suffix);

for (const provider of ['openai-compatible','openai']) {
  assert.deepEqual(structuredResponseOptions(provider),{response_format:{type:'json_object'}});
  const schema=structuredResponseOptions(provider,OUTPUT_REPAIR_SCHEMA).response_format;
  assert.equal(schema.type,'json_schema');
  assert.equal(schema.json_schema.strict,true);
  assert.equal(schema.json_schema.schema.additionalProperties,false);
  assert.deepEqual(schema.json_schema.schema.required,['answer']);
}
assert.deepEqual(structuredResponseOptions('anthropic',OUTPUT_REPAIR_SCHEMA),{});
assert.equal(parseOutputRepair('{"answer":" WM-0523 原样展示。 "}'),'WM-0523 原样展示。');
for(const malformed of ['{"response":"WM-0523"}','{"answer":{"text":"WM-0523"}}','{"answer":"WM-0523","other":1}','{"answer":" "}','```json\n{"answer":"WM-0523"}\n```'])
  assert.throws(()=>parseOutputRepair(malformed));

const task = '独立给出两条回滚检查措施，必须包含‘人工确认后才回滚’和‘不得覆盖历史’，字数限制在80字以内。';
const observed = '1. 检查 Deployment 是否存在 `ProgressDeadlineExceeded` 状态并确认失败原因；人工评估影响域后由值班负责人书面批准再触发回滚命令。2. 提取历史 Revision 版本哈希与滚动日志基线，比对当前版本差异；仅当新版本不可用且差异确为破坏性故障时方可执行回滚，严禁直接覆盖上次成功发布的资源清单。';
const contract = outputContract(task,'execute');
assert.equal(contract.max_characters,80);
assert.deepEqual(contract.required_literals,['人工确认后才回滚','不得覆盖历史']);
assert.equal(outputViolations(observed,contract).length,3);
const original='运维必须保留“人工确认后才回滚”和“不得覆盖历史”。每名成员最多80字；软件 Agent 汇总各最多150字。';
const rewritten='独立给出两条回滚检查：1. 人工确认后才回滚；2. 不得覆盖历史。';
assert.deepEqual(outputContract(rewritten,'execute',original),contract);
assert.equal(outputContract('生成一个标识','execute',original).max_characters,80);
const aliasOriginal='本轮仅做文字方案，不联网、不调用外部工具、不写文件、不执行部署。成员各最多80字，两级汇总各最多150字。';
assert.equal(outputContract('生成一个标识','execute',aliasOriginal).max_characters,80);
assert.equal(outputContract('汇总已完成成员','summary',aliasOriginal).max_characters,150);
assert.equal(outputContract('给出两项发布前检查','execute',aliasOriginal).check_items,2);
assert(outputViolations('已经部署。',outputContract('汇总已完成成员','summary',aliasOriginal)).length);
assert(outputViolations('甲'.repeat(81),outputContract('给出两项发布前检查','execute',aliasOriginal)).some(v=>v.includes('超过')));
assert.deepEqual(outputContract('生成一个标识','execute',original).required_literals,[]);
assert.equal(outputContract('前端展示方式','execute','后端最多20字。'),null);
const repairRequest=outputRepairRequest({task,answer:observed,contract});
assert(repairRequest.suffix.includes('人工确认后才回滚'));
assert(repairRequest.suffix.includes('不得覆盖历史'));
assert.deepEqual(repairRequest.request.contract.required_literals,[]);
assert.equal(repairRequest.request.contract.max_characters+[...repairRequest.suffix].length,80);
assert.throws(()=>outputRepairRequest({contract:{max_characters:2,required_literals:['不得覆盖历史']}}),/占满正文上限/);
const hostRestored=await enforceOutputContract(task,'execute',observed,async input=>{
  const prepared=outputRepairRequest(input);
  // Reproduce a provider rewrite that paraphrases and omits both literal rules.
  return '1. 核对回滚目标。\n2. 核对备份可读。'+prepared.suffix;
});
assert.deepEqual(outputViolations(hostRestored.answer,contract),[]);
let calls=0;
const corrected = await enforceOutputContract(task,'execute',observed,async input=>{
  calls++; assert.equal(input.answer,observed);
  return '1. 人工确认后才回滚。\n2. 核对备份版本，不得覆盖历史。';
});
assert.equal(calls,1);assert.equal(corrected.receipt.status,'repaired');
assert.equal(corrected.receipt.original_answer,observed);
await enforceOutputContract(task,'execute',corrected.answer,()=>{throw Error('No call for an already valid answer');});
assert.equal(outputContract('每名成员最多80字，软件 Agent 和主 Agent 的汇总各最多150字，并保留实际标识。','summary').max_characters,150);
assert.equal(outputContract('无需字数限制，也不要包含“机密”。','execute'),null);
assert.equal(outputContract(task,'plan'),null);
assert.equal(outputContract('必须在20字内回答。','execute').max_characters,20);
assert.equal(outputContract('字数 ≤ 80。','execute').max_characters,80);
assert.deepEqual(outputViolations('😀😀',{max_characters:2,required_literals:[]}),[]);
await assert.rejects(()=>enforceOutputContract(task,'execute',observed,async()=>observed),/仍未通过/);
await assert.rejects(()=>enforceOutputContract('必须保留“不得覆盖历史”。','execute','实际标识 WM-0419',async()=> '不得覆盖历史。'),/丢失了实际标识/);
await assert.rejects(()=>enforceOutputContract('必须保留“不得覆盖历史”。','execute','实际标识 WM-0419',async()=> 'WM-0419、WM-9999，不得覆盖历史。'),/新增了没有依据的标识/);
await assert.rejects(()=>enforceOutputContract(task,'execute',observed,async()=>''),/没有返回正文/);
process.stdout.write('Delegated output: real overlong draft, literal constraints, role-specific limits, single repair, identifier retention and fail-closed checks passed.\n');

const checks=await runDelegatedTextTurn('两条回滚检查',contract,async(prompt,system,schema)=>{
 assert.equal(schema.properties.checks.minItems,2);
 assert.equal(schema.properties.checks.maxItems,2);
 return {answer:JSON.stringify({checks:[{target:'目标版本',expected:'可用'},{target:'备份',expected:'可读'}]})};
});
// The observed independent ops task drifted to another member's WM identifier.
// Keep its assignment explicit after global task/evidence, without removing either.
const scopedChecks=await runDelegatedTextTurn('后端生成 WM- 标识；运维独立检查回滚。',contract,async(prompt,system)=>{
 assert(prompt.includes('后端生成 WM- 标识'));
 assert(prompt.endsWith(JSON.stringify('1.检查回滚预案需人工确认。\n2.核备日志策略禁覆盖历史。')));
 assert(system.includes('不把其他成员的编号生成'));
 return {answer:JSON.stringify({checks:[{target:'回滚预案',expected:'已获授权'},{target:'日志策略',expected:'保留原件'}]})};
},'1.检查回滚预案需人工确认。\n2.核备日志策略禁覆盖历史。');
assert(scopedChecks.answer.includes('回滚预案'));
assert.deepEqual(outputViolations(checks.answer,contract),[]);
assert(outputViolations('回滚检查1：仅执行一次。\n约束：人工确认后才回滚；不得覆盖历史。',contract).some(issue=>issue.includes('逐项交付')));
await assert.rejects(()=>runDelegatedTextTurn('两条检查',contract,async()=>({answer:'{"checks":["仅一条检查"]}'})),/项数/);
