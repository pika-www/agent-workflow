/** Template library DOM regression: read-only fixtures, no browser or model. */
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const source = fs.readFileSync(new URL('../federation/web/agent-chat.js', import.meta.url), 'utf8');
function extractFunction(name) {
  const start = source.search(new RegExp(`  (?:async )?function ${name}\\(`));
  assert.ok(start >= 0, name);
  const end = source.indexOf('\n  }', start) + 4;
  return source.slice(start, end);
}
class Element {
  constructor(tag = 'div') {
    this.tagName = tag; this.children = []; this.dataset = {}; this.listeners = {}; this.attributes = {};
    this.value = ''; this.hidden = false; this.disabled = false; this.open = false; this._text = '';
    const classes = new Set();
    this.classList = { add: (value) => classes.add(value), remove: (value) => classes.delete(value), contains: (value) => classes.has(value) };
  }
  set textContent(value) { this.children = []; this._text = String(value); }
  get textContent() { return this._text + this.children.map((child) => child.textContent).join(''); }
  set innerHTML(_) { throw new Error('Dynamic markup is prohibited'); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this._text = ''; this.children = children; }
  addEventListener(type, fn) { this.listeners[type] = fn; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  get childNodes() { return this.children; }
  get childElementCount() { return this.children.length; }
  querySelectorAll() { return []; }
}
const elements = new Map();
const $ = (id) => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
const make = (tag, cls, text) => { const node = new Element(tag); node.className = cls || ''; if (text !== undefined) node.textContent = String(text); return node; };
const agents = [
  { id: 'central', name: '主 Agent', breadcrumb: ['主 Agent'] },
  { id: 'software', name: '软件 Agent', parent_id: 'central', breadcrumb: ['主 Agent', '软件 Agent'] },
  { id: 'software-frontend', name: '前端 Agent', parent_id: 'software', breadcrumb: ['主 Agent', '软件 Agent', '前端 Agent'] },
  { id: 'commerce', name: '电商 Agent', parent_id: 'central', breadcrumb: ['主 Agent', '电商 Agent'] },
];
const state = { agents, view: 'room', room: { mode: 'direct', participants: ['software-frontend'] }, graphSpace: 'commerce', templateEpoch: 0, taskExpanded: new Map() };
const pending = [], fetches = [];
let fetchResult = { ok: true, headers: { get: () => '35' }, text: async () => '<script>unsafe()</script>\n规范正文' };
const sandbox = {
  window: new EventTarget(), Event,
  state, $, make, URL, JSON, Number, String, Set, Boolean, AbortController, setTimeout, clearTimeout, encodeURIComponent,
  agent: (id) => state.agents.find((item) => item.id === id), agentName: (id) => state.agents.find((item) => item.id === id)?.name || id,
  breadcrumb: (item) => item.breadcrumb.join(' › '), date: (value) => String(value), persistView() {},
  count: (value) => Number.isFinite(Number(value)) ? Number(value) : 0,
  depth: (item) => item?.id === 'central' ? 0 : item?.parent_id === 'central' ? 1 : 2,
  document: { activeElement: null, createDocumentFragment: () => new Element('fragment') },
  api: (path) => new Promise((resolve, reject) => pending.push({ path, resolve, reject })),
  fetch: async (url, options) => { fetches.push({ url, options }); return fetchResult; },
};
vm.createContext(sandbox);
vm.runInContext(source.match(/^  const active = .*$/m)[0], sandbox);
vm.runInContext(['markdownBody', 'orderedAgents', 'templateFileURL', 'defaultTemplateSpace', 'renderTemplatePicker', 'previewTemplateFile', 'renderTemplateList', 'loadTemplates', 'rememberDetails', 'publicSourceURL', 'renderTemplateReads', 'renderLearningReceipt', 'taskStatus', 'renderDelegations', 'renderReportArtifacts', 'validInterimReplies', 'renderInterimReplies', 'renderReportCheck', 'renderContextUsage', 'mergeReplyMessages', 'questionLanguage','turnLanguage','conversationMessages', 'operationTarget','operationReadFailure','operationFailureDetail','replyOperations','renderOperations','validReplyTimeline','replyTimeline','recordReplyTimeline','renderUnplacedOperations','replyStageLabel', 'isNativeReply', 'contextAdjustment','renderReplyBody', 'renderMessages'].map(extractFunction).join('\n'), sandbox);
const call = (name, ...args) => sandbox[name](...args);
const walk = (element) => [element, ...element.children.flatMap(walk)];

assert.equal(call('defaultTemplateSpace'), 'software-frontend', 'Direct chat chooses its own Agent');
state.room.mode = 'orchestrated';
assert.equal(call('defaultTemplateSpace'), 'commerce', 'Main chat respects the selected galaxy branch');
state.graphSpace = 'missing';
assert.equal(call('defaultTemplateSpace'), 'central');
call('renderTemplatePicker');
assert.deepEqual($('template-agent').children.map((option) => option.value), ['central', 'software', 'software-frontend', 'commerce']);
assert.equal($('template-agent').value, 'central');
assert.equal(call('templateFileURL', 'software-frontend', 'react-ts', 'template/src/App.tsx'), '/api/spaces/software-frontend/templates/react-ts/files/template/src/App.tsx');
assert.equal(call('templateFileURL', 'commerce', '订单 表', 'template/每日 订单.csv'), '/api/spaces/commerce/templates/%E8%AE%A2%E5%8D%95%20%E8%A1%A8/files/template/%E6%AF%8F%E6%97%A5%20%E8%AE%A2%E5%8D%95.csv');
for (const path of ['../secret', '/etc/passwd', 'template/../secret', 'template//a', 'template/\\file', 'template/\u0000x']) assert.equal(call('templateFileURL', 'central', 'pack', path), null, path);
assert.equal(call('templateFileURL', '..', 'pack', 'safe.md'), null);
assert.equal(call('templateFileURL', 'central', '../pack', 'safe.md'), null);

const manifest = { id: 'standard', name: '<img src=x onerror=unsafe()>', kind: 'agent-standard', framework: 'general', source_version: 'local-policy-v1.r2', source_url: 'local-agent-policy', updated_at: '2026-10-04', files: { 'template/岗位表.csv': 'a', 'GUIDELINES.md': 'b', 'template/policy.yaml': 'c', '../secret': 'd' } };
call('renderTemplateList', { automatic_read: true, templates: [manifest, { id: 'react-ts', framework: 'React', source_version: '8.0.0', upstream_commit: 'abc123456789abcdef', source_url: 'https://github.com/vitejs/vite', files: { 'template/src/App.tsx': 'e' } }] }, 'software-frontend');
assert.match($('template-policy').textContent, /自动读取.*普通聊天不会升级/);
assert.equal($('template-list').children.length, 2);
assert.equal($('template-list').children[0].open, true, 'The Agent standard is immediately visible');
assert.match($('template-list').textContent, /<img src=x onerror=unsafe\(\)>/);
assert.match($('template-list').textContent, /local-policy-v1.r2/);
assert.match($('template-list').textContent, /abc123456789abcdef/);
assert.match($('template-list').textContent, /文件路径无效/);
const links = walk($('template-list')).filter((node) => node.tagName === 'a');
assert.equal(links.length, 4);
assert.ok(links.every((node) => node.href.startsWith('/api/spaces/software-frontend/templates/')), 'Every rendered download is same-origin and scoped');
assert.ok(!walk($('template-list')).some((node) => node.tagName === 'img' || node.tagName === 'script'));
const previews = walk($('template-list')).filter((node) => node.tagName === 'button');
assert.equal(previews.length, 4, 'Markdown, CSV, YAML and source code are inspectable');
await previews[0].listeners.click();
assert.equal(fetches.length, 1);
assert.equal(fetches[0].options.method, undefined, 'Preview is a GET and cannot upgrade templates');
const preview = walk($('template-list')).find((node) => node.tagName === 'pre' && node.dataset.loaded === 'true');
assert.equal(preview.textContent, '<script>unsafe()</script>\n规范正文');
await previews[0].listeners.click();
assert.equal(preview.hidden, true);
assert.equal(fetches.length, 1, 'Closing a preview does not reread or mutate the file');
call('renderTemplateList', { automatic_read: true, templates: [{ id: 'mobile', kind: 'specialist',
  files: Object.fromEntries(['dart', 'swift', 'kt', 'py', 'less', 'scss', 'sass', 'wxss', 'wxml', 'svelte', 'astro'].map((ext) => [`template/example.${ext}`, 'a'])) }] }, 'software-app');
assert.equal(walk($('template-list')).filter((node) => node.tagName === 'button').length, 11,
  'Mobile, stylesheet and component sources have safe text previews');
$('template-search').value = 'wxml';
call('renderTemplateList', state.templateData.data, 'software-app');
assert.match($('template-status').textContent, /匹配 1 \/ 1/);
$('template-search').value = 'does-not-exist';
call('renderTemplateList', state.templateData.data, 'software-app');
assert.match($('template-list').textContent, /没有匹配/);
$('template-search').value = '';
const largeButton = new Element('button'), largeOutput = new Element('pre');
fetchResult = { ok: true, headers: { get: () => '262145' }, text: async () => { throw new Error('Must not read large body'); } };
await call('previewTemplateFile', '/api/spaces/central/templates/pack/files/a.txt', largeButton, largeOutput);
assert.match(largeOutput.textContent, /文件较大/);
assert.equal(largeButton.disabled, false);

call('renderTemplateList', { automatic_read: false, templates: [] }, 'commerce');
assert.match($('template-policy').textContent, /状态尚未确认/);
assert.match($('template-list').textContent, /还没有已保存的模板/);
$('templates-dialog').open = true;
const oldLoad = call('loadTemplates', 'software'), newLoad = call('loadTemplates', 'commerce');
assert.equal(pending[0].path, '/api/spaces/software/templates');
assert.equal(pending[1].path, '/api/spaces/commerce/templates');
pending[1].resolve({ automatic_read: true, templates: [{ ...manifest, name: '电商工作表' }] }); await newLoad;
pending[0].resolve({ automatic_read: true, templates: [{ ...manifest, name: '旧的软件列表' }] }); await oldLoad;
assert.match($('template-list').textContent, /电商工作表/);
assert.doesNotMatch($('template-list').textContent, /旧的软件列表/);
assert.equal($('templates-refresh').disabled, false);
const failedLoad = call('loadTemplates', 'commerce'); pending[2].reject(new Error('当前模板有用户修改，请先保留冲突')); await failedLoad;
assert.match($('template-status').textContent, /用户修改/);
assert.equal($('template-status').classList.contains('ag-template-error'), true);

const receipt = call('renderLearningReceipt', { kind: 'web_learning', web_learning: { status: 'failed', templates: [
  { id: 'agent-standard', status: 'updated', source_version: 'local-policy-v1.r3' },
  { id: 'react-ts', status: 'unchanged', source_version: '8.0.0', upstream_commit: 'abcdef0123456789' },
  { id: 'agent-sheet', status: 'conflict', error: '<script>keep original</script>' },
], template_errors: [{ id: 'agent-sheet', code: 'template_conflict', error: '用户修改未覆盖' }, '网络连接失败'] } }, 'round:task');
assert.match(receipt.textContent, /规范与模板维护 · 3/);
assert.match(receipt.textContent, /agent-standard · 已更新 · local-policy-v1.r3/);
assert.match(receipt.textContent, /react-ts · 版本未变化 · 8.0.0 · abcdef012345/);
assert.match(receipt.textContent, /存在冲突，保留原版本/);
assert.match(receipt.textContent, /模板维护未完成.*用户修改未覆盖.*网络连接失败/);
assert.match(receipt.textContent, /<script>keep original<\/script>/);
assert.equal(call('renderLearningReceipt', { kind: 'ordinary' }, 'none'), null);

const readFields = {
  template_selection: [
    { agent_id: 'software-frontend', id: 'agent-standard', framework: 'general', source_version: 'front-v2' },
    { agent_id: 'commerce', id: 'agent-standard', framework: 'general', source_version: 'commerce-v5' },
  ],
  template_reads: [
    { agent_id: 'software-frontend', template_id: 'agent-standard', path: 'GUIDELINES.md', sha256: 'a'.repeat(64) },
    { agent_id: 'commerce', template_id: 'agent-standard', path: 'template/每日订单.csv', sha256: 'b'.repeat(64) },
  ],
};
assert.equal(call('renderTemplateReads', {}, 'legacy'), null, 'Older rooms do not gain invented receipts');
assert.equal(call('renderTemplateReads', { template_reads: [null, {}, []], template_selection: 'bad' }, 'bad'), null);
const reads = call('renderTemplateReads', readFields, 'room:message:summary');
assert.equal(reads.open, false, 'Receipt is collapsed by default');
assert.equal(reads.children[0].textContent, '本轮读取的规范与模板');
const groups = walk(reads).filter((node) => node.className === 'ag-template-read-group');
assert.equal(groups.length, 2, 'Same template ID in different Agent libraries remains separate');
assert.match(groups[0].textContent, /前端 Agent · agent-standard.*已选模板版本：front-v2.*GUIDELINES.md/);
assert.doesNotMatch(groups[0].textContent, /commerce-v5|每日订单/);
assert.match(groups[1].textContent, /电商 Agent · agent-standard.*已选模板版本：commerce-v5.*每日订单/);
assert.doesNotMatch(groups[1].textContent, /front-v2|GUIDELINES/);
reads.isConnected = true; reads.open = true; reads.listeners.toggle();
assert.equal(call('renderTemplateReads', readFields, 'room:message:summary').open, true, 'Refresh preserves this receipt expansion');
assert.equal(call('renderTemplateReads', readFields, 'room:message:other').open, false, 'Other replies remain collapsed');
const localRead = call('renderTemplateReads', { agent_id: 'software', template_selection: [{ id: 'agent-standard', source_version: 'v1' }] }, 'task:software');
assert.match(localRead.textContent, /软件 Agent · agent-standard.*v1.*没有实际文件读取回执/);
const injected = call('renderTemplateReads', { agent_id: 'commerce', template_reads: [{ template_id: '<script>x()</script>', path: '<img src=x>', sha256: 'literal hash' }] }, 'safe');
assert.match(injected.textContent, /<script>x\(\)<\/script>.*<img src=x>/);
assert.ok(!walk(injected).some((node) => ['script', 'img'].includes(node.tagName)));

const messages = [
  { id: 'u1', role: 'user', content: '我的需求', ...readFields },
  { id: 'a1', role: 'assistant', agent_id: 'central', content: '汇总结果', ...readFields },
  { id: 'a2', role: 'assistant', agent_id: 'software', content: '历史回复没有回执' },
];
call('renderMessages', { id: 'room-a', mode: 'orchestrated', messages }, true);
const renderedMessages = walk($('feed')).filter((node) => node.className?.startsWith('ag-message ') || node.className === 'ag-message');
assert.equal(renderedMessages.length, 3);
assert.doesNotMatch(renderedMessages[0].textContent, /本轮读取的规范与模板/, 'Receipt never attaches to the user message');
assert.match(renderedMessages[1].textContent, /汇总结果/);
assert.doesNotMatch(renderedMessages[1].textContent, /本轮读取的规范与模板/);
assert.doesNotMatch(renderedMessages[2].textContent, /本轮读取的规范与模板/);
const taskReceipt = call('renderDelegations', { id: 'room-a', delegations: [{ id: 't1', round_id: 'r1', agent_id: 'commerce', title: '研究', status: 'completed', phase: 'execute', result: '任务结果', template_reads: [{ template_id: 'agent-standard', path: 'GUIDELINES.md' }] }] }, 'r1');
assert.match(taskReceipt.textContent, /任务结果/);
assert.doesNotMatch(taskReceipt.textContent, /本轮读取的规范与模板|GUIDELINES.md/);
console.log('Template UI DOM checks passed: library browsing, safe same-origin previews/downloads, request races, maintenance receipts, collapsed reply/task reads, Agent-specific versions, expansion isolation and legacy compatibility.');
const noticeReceipt = call('renderTemplateReads', {template_notices:[{agent_id:'software-frontend',text:'未读取：<missing>；React Native 不使用 DOM 样式'}]}, 'notice-only');
assert.ok(noticeReceipt);
assert.match(noticeReceipt.textContent, /前端 Agent.*<missing>/);
assert.match(noticeReceipt.textContent, /React Native/);

// A user can open templates before the directory request from opening chat
// completes. The late result must repair that same open panel exactly once.
Object.assign(sandbox, { renderRooms() {}, renderPicker() {}, renderMembers() {}, renderComposer() {} });
vm.runInContext(extractFunction('refreshDirectory'), sandbox);
Object.assign(state, { agents: [], templateSpace: null, loaded: false, listRevision: 0, selectedAgents: new Set(),
  view: 'new', room: null, graphSpace: 'software-frontend' });
pending.length = 0;
$('templates-dialog').open = true;
$('template-search').value = 'SCSS';
const lateDirectory = call('refreshDirectory');
call('renderTemplatePicker');
await call('loadTemplates');
assert.equal($('template-agent').disabled, true);
assert.equal(pending.length, 3, 'No template API call is possible before Agents arrive');
assert.deepEqual(pending.map((request) => request.path), ['/api/agents', '/api/chat/rooms', '/api/web-learning/status']);
pending[0].resolve({ agents }); pending[1].resolve({ rooms: [] }); pending[2].resolve({ enabled: true });
await lateDirectory;
assert.equal(state.templateSpace, 'software-frontend');
assert.equal($('template-agent').value, 'software-frontend');
assert.equal($('template-agent').disabled, false);
assert.equal($('template-search').value, 'SCSS', 'Late directory does not clear an entered filter');
assert.equal(pending.length, 4);
assert.equal(pending[3].path, '/api/spaces/software-frontend/templates');
const refreshWhileLoading = call('refreshDirectory');
pending[4].resolve({ agents }); pending[5].resolve({ rooms: [] }); pending[6].resolve({ enabled: true });
await refreshWhileLoading;
assert.equal(pending.length, 7, 'A valid selected Agent keeps its already running template request');
pending[3].resolve({ automatic_read: true, templates: [{ ...manifest, name: 'SCSS 规范' }] });
await new Promise((resolve) => setImmediate(resolve));
assert.match($('template-list').textContent, /SCSS 规范/);
assert.equal($('template-status').classList.contains('ag-template-error'), false);
assert.equal($('templates-refresh').disabled, false);

// Updating the directory must not replace an intentional valid selection or
// its loaded results with the current galaxy branch's default.
state.templateSpace = 'commerce'; $('template-agent').value = 'commerce';
$('template-search').value = '订单';
const selectedDirectory = call('refreshDirectory');
pending[7].resolve({ agents }); pending[8].resolve({ rooms: [] }); pending[9].resolve({ enabled: true });
await selectedDirectory;
assert.equal(state.templateSpace, 'commerce');
assert.equal($('template-agent').value, 'commerce');
assert.equal($('template-search').value, '订单');
assert.equal(pending.length, 10, 'A valid choice is not reloaded during directory refresh');

state.agents = []; state.templateSpace = null;
const closedDirectory = call('refreshDirectory');
$('templates-dialog').open = false;
pending[10].resolve({ agents }); pending[11].resolve({ rooms: [] }); pending[12].resolve({ enabled: true });
await closedDirectory;
assert.equal(state.templateSpace, null);
assert.equal(pending.length, 13, 'Closing the panel before Agents arrive does not trigger a template load');
console.log('Template directory race passed: late initialization, one request, filter/selection preservation and closed-panel guard.');
