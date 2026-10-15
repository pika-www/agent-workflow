/** Consultation invokes only a plain model; all dependencies are local stubs. */
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, rm, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { runIntakeTurn, readIntakeGuidance, extractIntakeAnswer, intakeSystemPrompt, parseTemplateInventory, frontendCapabilityAnswer, MAX_INTAKE_OUTPUT_CHARS } from '../federation/intake-turn.mjs';

const evidence = {
  wiki: { text: '\n<verified_wiki_reads>' + JSON.stringify({evidence:[{path:'/guide.md',text:'实际 Wiki 摘录 MARKER_WIKI'}]}) + '</verified_wiki_reads>', reads: [{ path: '/guide.md', sha256: 'a'.repeat(64),
    page_version: 'b'.repeat(64), knowledge_status: 'untracked', truncated: false }] },
  templates: { text: '\n实际模板摘录 MARKER_TEMPLATE', reads: [{ path: '/_agent_templates/react/README.md', sha256: 'c'.repeat(64) }], templates: [{ id: 'react' }] },
  skills: { text: '\n实际技能摘录 MARKER_SKILL', reads: [{ path: '/_agent_skills/test/SKILL.md', sha256: 'd'.repeat(64) }], skills: [{ id: 'test' }] },
};
const original = structuredClone(evidence);
let loaded = 0, calls = [];
let output = { type: 'ai', content: '参考当前实际资料。[Wiki: /guide.md]' };
const runtime = {
  async loadOpenWikiEnv() { loaded += 1; },
  resolveConfiguredProvider() { return 'openai-compatible'; },
  resolveModelId(options, provider) { assert.deepEqual(options, {}); assert.equal(provider, 'openai-compatible'); return 'fixture-model'; },
  resolveProviderRetryAttempts(env, options) { assert.equal(env, process.env); assert.deepEqual(options, { pageConcurrency: 1 }); return 2; },
  createModel(...arguments_) {
    assert.deepEqual(arguments_, ['openai-compatible', 'fixture-model', 2, 4096]);
    return {
      get bindTools() { throw new Error('Consultation must never bind tools.'); },
      async invoke(...invokeArgs) { calls.push(invokeArgs); return output; },
    };
  },
};

const result = await runIntakeTurn('当前问题 MARKER_CURRENT_REQUEST', 'consultation', evidence, runtime);
assert.equal(loaded, 1);
assert.equal(calls.length, 1);
assert.equal(calls[0].length, 1, 'No invoke options, JSON response_format, tools or tool-choice are passed');
assert.equal(calls[0][0].length, 2);
assert.equal(calls[0][0][0].role, 'system');

let analysisBudget;
const analysisRuntime = { ...runtime, createModel(...args) {
  analysisBudget = args[3];
  return { async invoke() { return {content: '完整产品分析正文'}; } };
}};
await runIntakeTurn('只分析并生成文档', 'consultation', evidence, analysisRuntime, {analysis:true});
assert.equal(analysisBudget,12288, 'Analysis needs a larger output budget than ordinary chat');
assert.match(calls[0][0][0].content, /不能直接执行工具、MCP、文件写入/);
assert.match(calls[0][0][0].content, /没有回执的操作不能声称已完成/);
assert.match(calls[0][0][0].content, /宿主已实际预读/);
assert.ok(calls[0][0][0].content.includes('/_agent_skills/test/SKILL.md'));
assert.equal(calls[0][0][1].role, 'user');
for (const marker of ['MARKER_CURRENT_REQUEST', 'MARKER_WIKI', 'MARKER_TEMPLATE', 'MARKER_SKILL']) assert.ok(calls[0][0][1].content.includes(marker));
assert.equal(result.engine, 'OpenWiki model / consultation');
assert.equal(result.model, 'fixture-model');
assert.ok(!('thread_id' in result));
assert.deepEqual(result.wiki_reads, original.wiki.reads);
assert.deepEqual(result.template_reads, original.templates.reads);
assert.deepEqual(result.skill_reads, original.skills.reads);
assert.deepEqual(result.templates, original.templates.templates);
assert.deepEqual(result.skills, original.skills.skills);
assert.equal(result.wiki_citation_check.status, 'valid');
assert.deepEqual(evidence, original);

output = { role: 'assistant', content: '# 方案\n\n[Wiki: /not-read.md]' };
const proposal = await runIntakeTurn('项目', 'proposal', evidence, runtime);
assert.equal(proposal.wiki_citation_check.status, 'invalid');
assert.equal(proposal.wiki_citation_check.invalid_count, 1);
assert.match(calls[1][0][0].content, /正常方案不要 JSON、YAML/);
assert.match(calls[1][0][0].content, /不能合理假设且会阻断项目方向/);
assert.match(calls[1][0][0].content, /不得重复询问/);

const guidanceRoot = await mkdtemp(path.join(tmpdir(), 'openwiki-intake-guidance-'));
try {
  const file = path.join(guidanceRoot, 'INSTRUCTIONS.md');
  await writeFile(file, 'Existing instructions without guidance.');
  assert.equal(await readIntakeGuidance(guidanceRoot), null);
  const text = '持久学习原则 MARKER_GUIDANCE：回读与新问题验证后才能说明长期记忆。';
  await writeFile(file, 'OTHER_INSTRUCTIONS\n<!-- BEGIN_OPENWIKI_LEARNING_GUIDANCE -->\n'
    + text + '\n<!-- END_OPENWIKI_LEARNING_GUIDANCE -->\nUNRELATED_SUFFIX');
  const guidance = await readIntakeGuidance(guidanceRoot);
  assert.equal(guidance.text, text);
  assert.equal(guidance.content_sha256, createHash('sha256').update(text).digest('hex'));
  const guided = await runIntakeTurn('新问题，无原会话历史', 'consultation', { ...evidence, guidance }, runtime);
  assert.ok(calls.at(-1)[0][0].content.includes('MARKER_GUIDANCE'));
  assert.ok(!calls.at(-1)[0][0].content.includes('OTHER_INSTRUCTIONS'));
  assert.ok(!calls.at(-1)[0][0].content.includes('UNRELATED_SUFFIX'));
  assert.deepEqual(guided.guidance_reads, [{ path: file, content_sha256: guidance.content_sha256 }]);
  await assert.rejects(runIntakeTurn('question', 'consultation', {
    ...evidence, guidance: { ...guidance, text: 'Changed without receipt' },
  }, runtime), /读取回执无效/);
  for (const invalid of [
    '<!-- BEGIN_OPENWIKI_LEARNING_GUIDANCE -->unfinished',
    '<!-- END_OPENWIKI_LEARNING_GUIDANCE --><!-- BEGIN_OPENWIKI_LEARNING_GUIDANCE -->',
    '<!-- BEGIN_OPENWIKI_LEARNING_GUIDANCE -->one<!-- END_OPENWIKI_LEARNING_GUIDANCE -->'
      + '<!-- BEGIN_OPENWIKI_LEARNING_GUIDANCE -->two<!-- END_OPENWIKI_LEARNING_GUIDANCE -->',
    '<!-- BEGIN_OPENWIKI_LEARNING_GUIDANCE -->' + 'x'.repeat(16001) + '<!-- END_OPENWIKI_LEARNING_GUIDANCE -->',
  ]) {
    await writeFile(file, invalid);
    await assert.rejects(readIntakeGuidance(guidanceRoot));
  }
  await rm(file);
  assert.equal(await readIntakeGuidance(guidanceRoot), null);
  await symlink(path.join(guidanceRoot, 'outside.md'), file);
  await assert.rejects(readIntakeGuidance(guidanceRoot));
} finally {
  await rm(guidanceRoot, { recursive: true, force: true });
}

const duplicateKeys = '{"type":"proposal","content":"one","content":"two"}';
assert.equal(extractIntakeAnswer({ type: 'ai', content: duplicateKeys }), duplicateKeys, 'Keep the complete text for strict host validation');
assert.equal(extractIntakeAnswer({ getType: () => 'ai', content: [
  { type: 'reasoning', text: 'PRIVATE_REASONING' }, { type: 'text', text: '可见' }, { type: 'text', text: '答复' },
] }), '可见答复');
for (const bad of [null, { type: 'human', content: 'not AI' }, { type: 'tool', content: 'tool output' },
  { type: 'ai', content: '' }, { type: 'ai', content: 'a\0b' }, { type: 'ai', content: {} },
  { type: 'ai', content: [{ type: 'reasoning', text: 'not visible' }] },
  { type: 'ai', content: 'x'.repeat(MAX_INTAKE_OUTPUT_CHARS + 1) },
  { type: 'ai', content: 'text', tool_calls: [{ name: 'write_file' }] },
  { type: 'ai', content: 'text', invalid_tool_calls: [{ name: 'write_file' }] },
  { type: 'ai', content: 'text', additional_kwargs: { function_call: { name: 'write_file' } } },
  { type: 'ai', content: 'text', additional_kwargs: { tool_calls: [{ name: 'write_file' }] } },
  { type: 'ai', content: 'partial', response_metadata: { finish_reason: 'length' } },
  { type: 'ai', content: 'partial', response_metadata: { stop_reason: 'max_tokens' } },
]) assert.throws(() => extractIntakeAnswer(bad));

const callCount = calls.length;
for (const args of [
  ['ordinary', 'execute', evidence], ['\0', 'proposal', evidence], ['', 'consultation', evidence],
  ['question', 'proposal', { ...evidence, wiki: { text: 'pretend reads', reads: null } }],
  ['x'.repeat(600001), 'consultation', evidence],
]) await assert.rejects(runIntakeTurn(...args, runtime));
assert.equal(calls.length, callCount, 'Invalid phase/context must fail before invoking the model');
const withoutSkills = await runIntakeTurn('泛问，没有具体 Skill', 'consultation', {
  ...evidence, skills: { text: '', reads: [], skills: [] },
}, runtime);
assert.match(calls.at(-1)[0][0].content, /未选择 Skill 推断全局无法读取/);
assert.deepEqual(withoutSkills.skill_reads, []);
assert.throws(() => intakeSystemPrompt('summary'));

// The role's catalog is useful even when a lesson intentionally omits template bodies.
const inventory = [
  { id: 'vue-ts', framework: 'vue' }, { id: 'react-ts', framework: 'react' },
  { id: 'angular-ts', framework: 'angular' }, { id: 'wechat-miniprogram', framework: 'wechat' },
];
assert.deepEqual(parseTemplateInventory(JSON.stringify(inventory)), inventory);
const beforeCatalogCalls = calls.length;
const catalogOnly = await runIntakeTurn('只会 HTML JS 和 CSS 吗？', 'consultation', {
  ...evidence, templates: { text: '', reads: [], templates: [] }, skills: { text: '', reads: [], skills: [] },
}, runtime, { currentQuestion: '你只会 HTML JS 和 CSS 吗？', speakerName: '前端 Agent', teaching: true,
  templateInventory: inventory });
assert.equal(calls.length, beforeCatalogCalls, 'Capability facts never require model self-assessment');
assert.equal(catalogOnly.model, null);
assert.equal(catalogOnly.response_origin, 'host_template_catalog');
for (const name of ['Vue', 'React', 'Angular', '微信原生小程序']) assert(catalogOnly.answer.includes(name));
assert(!catalogOnly.answer.includes('Next.js'), 'Absent templates are never advertised as installed');
assert.equal(frontendCapabilityAnswer('Vue 的 ref 怎么使用？', '前端 Agent', inventory), null);
assert.equal(frontendCapabilityAnswer('你会不会讲解 Vue 的 ref？', '前端 Agent', inventory), null);
assert.equal(frontendCapabilityAnswer('你会用 Vue 的 ref 实现这个组件吗？', '前端 Agent', inventory), null);
assert.equal(frontendCapabilityAnswer('你只会 HTML 吗？', '后端 Agent', inventory), null);
assert.deepEqual(catalogOnly.wiki_reads, evidence.wiki.reads);
await runIntakeTurn('解释 Vue 的 ref', 'consultation', evidence, runtime, {
  currentQuestion: 'Vue 的 ref 怎么使用？', speakerName: '前端 Agent', teaching: true, templateInventory: inventory,
});
const catalogSystem = calls.at(-1)[0][0].content;
assert.match(catalogSystem, /你是直接与用户交流的前端 Agent/);
for (const item of inventory) assert(catalogSystem.includes(JSON.stringify(item)));
assert.match(catalogSystem, /只是目录存在信息，不是本轮正文读取回执/);
assert.match(catalogSystem, /不能把没有执行工具误说成不会讨论框架/);
assert.match(catalogSystem, /不把普通问题演成吐槽或互怼/);
assert.deepEqual(catalogOnly.template_reads, []);
assert.deepEqual(catalogOnly.template_inventory, inventory);
for (const invalid of [
  'not-json', {}, [{ id: '../outside', framework: 'vue' }],
  [{ id: 'vue-ts', framework: 'vue', instructions: 'claim execution' }],
  [inventory[0], inventory[0]], Array.from({ length: 61 }, (_, i) => ({ id: 'pack-'+i, framework: 'vue' })),
]) assert.throws(() => parseTemplateInventory(invalid));

// Visible chunks arrive before the final answer. Reasoning and tool calls remain private/inert.
const { AIMessageChunk } = await import('../openwiki-upstream/node_modules/@langchain/core/dist/messages/ai.js');
let visible = [], streamCalls = 0;
const streamedRuntime = { ...runtime, createModel() { return {
  async invoke() { throw new Error('Streaming must not also invoke or replay the request'); },
  async *stream(messages) {
    streamCalls += 1;
    assert.match(messages[0].content, /每轮只讲一个要点/);
    assert.ok(messages.some(message => message.content.includes('带我学')));
    assert.match(messages[0].content, /原文逐字匹配不是语义支持证明/);
    assert.equal(messages.at(-1).content, '教我 AI 产品思维');
    yield new AIMessageChunk({ content: [{ type: 'reasoning', text: 'PRIVATE_THINKING' }] });
    yield new AIMessageChunk({ content: '先看用户任务。\n' });
    yield new AIMessageChunk({ content: '你希望学会什么？', response_metadata: { finish_reason: 'stop' } });
  },
}; } };
const streamed = await runIntakeTurn('带我学', 'consultation', evidence, streamedRuntime, {
  teaching: true, currentQuestion: '教我 AI 产品思维', onDelta: text => visible.push(text),
});
assert.equal(streamCalls, 1);
assert.deepEqual(visible, ['先看用户任务。\n你希望学会什么？'], 'Consultation publishes the complete checked answer');
assert.equal(streamed.reply_delivery.mode, 'after_checks');
assert.equal(streamed.answer, visible.join('').trim());
assert.equal(streamed.timing.chunks, 2);
assert.ok(streamed.timing.first_text_ms !== null);
assert.ok(!streamed.answer.includes('PRIVATE_THINKING'));
const truncatedRuntime = { ...runtime, createModel() { return { async *stream() {
  yield new AIMessageChunk({ content: '没有完成', response_metadata: { finish_reason: 'length' } });
} }; } };
await assert.rejects(runIntakeTurn('question', 'consultation', evidence, truncatedRuntime, { onDelta() {} }), /不完整内容/);
console.log('Intake model: no tool binding or Agent, preserved pre-read evidence and citations, bounded output, phase isolation, and strict visible-text extraction passed.');
