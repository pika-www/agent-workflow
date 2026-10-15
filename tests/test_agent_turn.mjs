/** Native bridge checks: no model calls, no writes outside temporary fixtures. */
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, readFile, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { extractFinalAnswer, prefetchWiki, delegatedInput, recordDelegationUsage, originalDelegationTask, effectiveDelegationTask } from '../federation/agent-turn.mjs';
import {outputContract} from '../federation/delegation-output.mjs';

const fullRequest='后端自行选一个 WM- 加四位数字的标识，返回包含 acceptance_code 的极简 JSON。前端必须依赖后端任务完成，收到实际产物后原样引用标识并说明一种展示方式，不得猜测。运维独立给出两条回滚检查，可与后端同时执行，必须保留“人工确认后才回滚”和“不得覆盖历史”。每名成员最多80字；软件 Agent 和主 Agent 的汇总各最多150字。';
const rolePrompt=(name,id,assignment)=>'你是'+name+' Agent（agent_id='+id+'）。\n本轮用户原始请求（完整保留）：\n'+JSON.stringify(fullRequest)+'\n<conversation_history>\n'+JSON.stringify([{role:'user',content:assignment}])+'\n</conversation_history>\n';
const backPrompt=rolePrompt('后端','software-backend','生成包含 WM-0001 标识的验收代码');
assert.equal(effectiveDelegationTask(backPrompt,'execute'),fullRequest.split('。')[0]+'。');
assert(!effectiveDelegationTask(backPrompt,'execute').includes('WM-0001'));
const opsPrompt=rolePrompt('运维','software-devops','提供两条回滚检查方案：人工确认才执行、不得覆盖历史');
assert.deepEqual(outputContract(effectiveDelegationTask(opsPrompt,'execute'),'execute',fullRequest).required_literals,['人工确认后才回滚','不得覆盖历史']);
assert.equal(effectiveDelegationTask(backPrompt,'summary'),'生成包含 WM-0001 标识的验收代码');
assert.equal(effectiveDelegationTask(rolePrompt('审计','audit','核对三个成员结果'),'execute'),'核对三个成员结果');
const semicolonRequest='请主 Agent 交给软件 Agent，再分给后端、前端和运维成员：后端输出严格 JSON {"acceptance_code":"WM-1024"}；前端必须等后端完成后读取并引用实际 acceptance_code，用一句话描述确认页面；运维独立给出两项发布前检查，必须包含“人工确认后才回滚”和“不得覆盖历史；保留原件”。成员各最多80字。';
const semicolonPrompt=(name,id,assignment)=>rolePrompt(name,id,assignment).replace(JSON.stringify(fullRequest),JSON.stringify(semicolonRequest));
assert.equal(effectiveDelegationTask(semicolonPrompt('后端','software-backend','输出严格 JSON {'),'execute'),'后端输出严格 JSON {"acceptance_code":"WM-1024"}。');
const semicolonOps=effectiveDelegationTask(semicolonPrompt('运维','software-devops','独立给出两项发布前检查，必须包含'),'execute');
assert(semicolonOps.includes('“不得覆盖历史；保留原件”'));
assert.deepEqual(outputContract(semicolonOps,'execute',semicolonRequest).required_literals,['人工确认后才回滚','不得覆盖历史；保留原件']);

// Reproduce the real delegation failure: a large role template followed the
// assigned task and the model returned only an introduction. Keep the task last,
// retain original dependency evidence, and budget optional material separately.
const assigned = '原样展示实际后端标识 WM-7391，80字内。人工确认后才回滚，不得覆盖历史。';
const reference = '/_delegation_results/backend-result.json';
const prompt = '用户原始要求：只委派软件三个成员。\n前置任务回执：{"acceptance_code":"WM-7391"}\n原件：'
  + reference + '\n<conversation_history>\n' + JSON.stringify([{role:'user',content:assigned}]) + '\n</conversation_history>\n';
const evidence = {wiki:{text:''},skills:{text:''},templates:{text:'<verified_template_reads>'
  + JSON.stringify({templates:[{id:'generic',text:'角色介绍与模板资料。'.repeat(5000)}]}) + '</verified_template_reads>'}};
for (const phase of ['execute','summary']) {
  const built = delegatedInput(prompt,phase,evidence);
  assert(built.userMessage.includes(reference));
  assert(built.userMessage.includes('前置任务回执：{"acceptance_code":"WM-7391"}'));
  assert(built.userMessage.includes(JSON.stringify(assigned)));
  assert(built.userMessage.lastIndexOf(assigned)>built.userMessage.indexOf('角色介绍与模板资料'));
  assert(built.userMessage.endsWith(phase==='summary'
    ? '仅按实际成员结果汇总，保留失败、标识、限制和原件引用。' : '只交付本节点结果，不代替其他成员完成任务。'));
  assert.equal(built.receipt.scope,'delegation_user_payload');
  assert(built.receipt.input_tokens_estimated<=built.receipt.budget);
  assert(built.receipt.included.some(item=>item.key==='templates:generic' && item.truncated));
  assert(built.receipt.selection.before_tokens>built.receipt.selection.after_tokens);
}
assert.equal(delegatedInput(prompt,'consultation',evidence),null);
assert.equal(originalDelegationTask(prompt),assigned);
assert.equal(originalDelegationTask('本轮用户原始请求（完整保留）：\n'+JSON.stringify('每名成员最多80字。')+'\n'+prompt),'每名成员最多80字。');
assert.throws(()=>delegatedInput(prompt+'不可丢失的任务约束。'.repeat(10000),'execute',evidence),/没有截断问题/);

assert.equal(extractFinalAnswer([{ type: 'human', content: 'question' },
  { type: 'ai', content: 'intermediate', tool_calls: [{ name: 'read_file' }] },
  { type: 'tool', content: 'secret tool output' }, { type: 'ai', content: 'Final answer.' }]), 'Final answer.');
assert.equal(extractFinalAnswer([{ type: 'ai', content: [
  { type: 'reasoning', text: 'Do not show this.' }, { type: 'text', text: 'Visible answer.' }],
}]), 'Visible answer.');
for (const messages of [[], [{ type: 'tool', content: 'not an answer' }],
  [{ type: 'ai', content: '', tool_calls: [] }],
  [{ type: 'ai', content: 'unfinished', tool_calls: [{ id: '1' }] }],
  [{ type: 'ai', content: 'truncated', response_metadata: { finish_reason: 'length' } }]]) {
  assert.throws(() => extractFinalAnswer(messages));
}

const root = await mkdtemp(path.join(os.tmpdir(), 'openwiki-chat-native-'));
try {
  const ledgerPath=path.join(root,'model-usage.jsonl');
  const usages=recordDelegationUsage([{provider:'native',model:'fixture',status:'completed',input_tokens:120,output_tokens:20}],ledgerPath);
  const ledger=(await readFile(ledgerPath,'utf8')).trim().split('\n').map(JSON.parse);
  assert.equal(ledger.length,2);
  assert.equal(ledger[0].id,ledger[1].id);
  assert.deepEqual(ledger[1],usages[0]);
  assert.equal(usages[0].input_tokens,120);
  assert.equal(usages[0].calls,1);
  await writeFile(path.join(root, 'index.md'), '# 测试\n[当前行业](topic.md)\n');
  const source = '# 虚构验收\n软件代号 SW-482，负责人林岚。\n';
  await writeFile(path.join(root, 'topic.md'), source);
  const prefetched = await prefetchWiki(root, '报告演示代号和负责人');
  assert(prefetched.wholeWiki);
  assert(prefetched.text.includes('SW-482'));
  assert(prefetched.text.includes('林岚'));
  assert.equal(prefetched.reads.length, 2);
  const receipt = prefetched.reads.find(read => read.path === '/topic.md');
  assert.equal(receipt.hash_scope, 'provided_excerpt');
  assert.equal(receipt.sha256, createHash('sha256').update(source).digest('hex'));
  assert.equal(receipt.truncated, false);
  assert.equal(await readFile(path.join(root, 'topic.md'), 'utf8'), source);

  const lengthy = '# 大页面\n' + '填充内容。\n'.repeat(400) + 'RareTarget 是 RT-739，负责人周舟。\n' + '其他内容。\n'.repeat(1500);
  await writeFile(path.join(root, 'large.md'), lengthy);
  const bounded = await prefetchWiki(root, '请查询 RareTarget');
  assert(!bounded.wholeWiki);
  assert(bounded.text.includes('RT-739'));
  assert(bounded.reads.some(read => read.truncated));
  assert(bounded.reads.reduce((sum, read) => sum + read.excerpt_chars, 0) <= 8000);
  assert.equal(await readFile(path.join(root, 'large.md'), 'utf8'), lengthy);
  const lesson = '# 学习目标案例\nAI 产品思维要围绕学习者理解安排对话。\n';
  await writeFile(path.join(root, 'khanmigo-learning.md'), lesson);
  const teaching = await prefetchWiki(root, '教我 AI 产品思维', null, { compact: true, teaching: true });
  assert(teaching.reads.some(read => read.path === '/khanmigo-learning.md' && read.start_line === 1));
  assert(teaching.text.includes('学习者理解'));
  assert.equal(await readFile(path.join(root, 'khanmigo-learning.md'), 'utf8'), lesson);
  const caseBody='# 实际案例机制\nFIRST_BODY_MECHANISM 按解决结果收费。\n'+'说明行。\n'.repeat(30)+'来源：Intercom Fin 文档。\n';
  await writeFile(path.join(root,'intercom-fin.md'),caseBody);
  const requested=await prefetchWiki(root,'/intercom-fin.md 收费方式',null,{compact:true,teaching:true});
  assert(requested.text.includes('FIRST_BODY_MECHANISM'),'A page requested by a real scoped path must include its mechanism, not only a matching footnote');
  assert.equal(requested.reads.find(r=>r.path==='/intercom-fin.md').start_line,1);
  const mentioned=await prefetchWiki(root,'@AI 产品思维 Agent Intercom 的收费方式',null,{compact:true,teaching:true});
  assert(mentioned.text.includes('FIRST_BODY_MECHANISM'));
  process.stdout.write('Native bridge: final-answer filtering, native Wiki reads, receipt hashes, bounded retrieval and source immutability passed.\n');
} finally {
  await rm(root, { recursive: true, force: true });
}
