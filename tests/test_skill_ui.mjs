/** Skill library/receipt DOM behavior; no model, remote app or skill execution. */
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const source = fs.readFileSync(new URL('../federation/web/agent-chat.js', import.meta.url), 'utf8');
function extractFunction(name) {
  const start = source.search(new RegExp(`  (?:async )?function ${name}\\(`));
  assert.ok(start >= 0, name);
  return source.slice(start, source.indexOf('\n  }', start) + 4);
}
class Element {
  constructor(tag = 'div') {
    this.tagName = tag; this.children = []; this.dataset = {}; this.listeners = {}; this.attributes = {};
    this.value = ''; this.hidden = false; this.disabled = false; this.open = false; this._text = '';
    const classes = new Set();
    this.classList = { add: (s) => classes.add(s), remove: (s) => classes.delete(s), contains: (s) => classes.has(s) };
  }
  set textContent(value) { this.children = []; this._text = String(value); }
  get textContent() { return this._text + this.children.map((child) => child.textContent).join(''); }
  set innerHTML(_) { throw new Error('Dynamic HTML is prohibited'); }
  append(...children) { this.children.push(...children); }
  prepend(...children) { this.children.unshift(...children); }
  replaceChildren(...children) { this._text = ''; this.children = children; }
  addEventListener(type, callback) { this.listeners[type] = callback; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  get childNodes() { return this.children; }
  get childElementCount() { return this.children.length; }
  querySelectorAll() { return []; }
}
const nodes = new Map();
const $ = (id) => { if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id); };
const make = (tag, className, text) => { const item = new Element(tag); item.className = className || ''; if (text !== undefined) item.textContent = text; return item; };
const walk = (item) => [item, ...item.children.flatMap(walk)];
const agents = [
  { id: 'central', name: '主 Agent', breadcrumb: ['主 Agent'] },
  { id: 'software', name: '软件 Agent', parent_id: 'central', breadcrumb: ['主 Agent', '软件 Agent'] },
  { id: 'software-uiux', name: 'UI/UX 设计师', parent_id: 'software', breadcrumb: ['主 Agent', '软件 Agent', 'UI/UX 设计师'] },
  { id: 'commerce', name: '电商 Agent', parent_id: 'central', breadcrumb: ['主 Agent', '电商 Agent'] },
];
const state = { agents, graphSpace: 'software-uiux', view: 'new', room: null, skillSpace: null, skillEpoch: 0,
  taskExpanded: new Map(), selectedAgents: new Set(), listRevision: 0 };
const pending = [], fetches = [];
let fetched = { ok: true, headers: { get: () => '30' }, text: async () => '<script>unsafe()</script>\n真实规范示例' };
const sandbox = { window: new EventTarget(), Event,
  state, $, make, URL, JSON, Number, String, Set, Boolean, AbortController, setTimeout, clearTimeout, encodeURIComponent,
  agent: (id) => state.agents.find((item) => item.id === id), agentName: (id) => state.agents.find((item) => item.id === id)?.name || id,
  breadcrumb: (item) => item.breadcrumb.join(' › '), date: String, persistView() {},
  count: (value) => Number.isFinite(Number(value)) ? Number(value) : 0,
  depth: (item) => item?.id === 'central' ? 0 : item?.parent_id === 'central' ? 1 : 2,
  document: { activeElement: null, createDocumentFragment: () => new Element('fragment') },
  api: (path) => new Promise((resolve, reject) => pending.push({ path, resolve, reject })),
  fetch: async (url, options) => { fetches.push({ url, options }); return fetched; },
  renderRooms() {}, renderPicker() {}, renderMembers() {}, renderComposer() {},
};
vm.createContext(sandbox);
vm.runInContext(source.match(/^  const active = .*$/m)[0], sandbox);
vm.runInContext(['markdownBody', 'orderedAgents', 'defaultTemplateSpace', 'renderTemplatePicker', 'loadTemplates',
  'skillFileURL', 'renderSkillPicker', 'renderSkillList', 'loadSkills', 'previewTemplateFile',
  'rememberDetails', 'renderSkillReads', 'renderTemplateReads', 'publicSourceURL', 'renderLearningReceipt',
  'taskStatus', 'renderDelegations', 'renderReportArtifacts', 'validInterimReplies', 'renderInterimReplies', 'renderReportCheck', 'renderContextUsage', 'mergeReplyMessages', 'questionLanguage','turnLanguage','conversationMessages', 'operationTarget','operationReadFailure','operationFailureDetail','replyOperations','renderOperations','validReplyTimeline','replyTimeline','recordReplyTimeline','renderUnplacedOperations','replyStageLabel', 'isNativeReply', 'contextAdjustment','renderReplyBody', 'renderMessages', 'refreshDirectory'].map(extractFunction).join('\n'), sandbox);
const call = (name, ...args) => sandbox[name](...args);

call('renderSkillPicker');
assert.equal(state.skillSpace, 'software-uiux');
assert.equal($('skill-agent').value, 'software-uiux');
assert.match($('skill-agent').textContent, /UI\/UX 设计师/);
state.skillSpace = 'commerce'; state.graphSpace = 'central'; call('renderSkillPicker');
assert.equal($('skill-agent').value, 'commerce', 'A valid intentional choice survives picker refresh');
assert.equal(call('skillFileURL', 'software-uiux', 'figma-use', 'SKILL.md'), '/api/spaces/software-uiux/skills/figma-use/files/SKILL.md');
assert.equal(call('skillFileURL', '软件', '图形 技能', 'references/交接 规范.md'), '/api/spaces/%E8%BD%AF%E4%BB%B6/skills/%E5%9B%BE%E5%BD%A2%20%E6%8A%80%E8%83%BD/files/references/%E4%BA%A4%E6%8E%A5%20%E8%A7%84%E8%8C%83.md');
for (const path of ['../secret', '/etc/passwd', 'references/../secret', 'a//b', 'a/\\b', 'a/\u0000b']) assert.equal(call('skillFileURL', 'central', 'skill', path), null, path);
assert.equal(call('skillFileURL', '../central', 'skill', 'SKILL.md'), null);

const skill = { id: 'figma-use', name: 'figma-use', display_name: 'Figma 设计操作', description: '<img src=x onerror=unsafe()>',
  version: 'imported-r1', source_path: '/local/figma/SKILL.md', source_kind: 'installed-skill', execution_status: 'reference_only',
  dependencies: ['Figma MCP', '<script>connection</script>'], keywords: ['组件', '变量'],
  files: { 'references/规范.md': 'a'.repeat(64), 'SKILL.md': 'b'.repeat(64), '../secret': 'c'.repeat(64) } };
const data = { automatic_read: true, skills: [skill], selection: '按当前任务匹配本Agent技能，每轮最多3个' };
call('renderSkillList', data, 'software-uiux');
assert.match($('skill-list').textContent, /Figma 设计操作.*技能标识：figma-use.*imported-r1/);
assert.match($('skill-list').textContent, /已导入 · 可读取规范 · 执行工具尚未接入/);
assert.match($('skill-list').textContent, /来源：\/local\/figma\/SKILL.md.*installed-skill/);
assert.match($('skill-list').textContent, /依赖：Figma MCP、<script>connection<\/script>/);
assert.match($('skill-list').textContent, /<img src=x onerror=unsafe\(\)>/);
assert.match($('skill-list').textContent, /文件路径无效/);
assert.match($('skill-policy').textContent, /每轮最多读取 3 个.*不代表已执行工具/);
assert.ok(!walk($('skill-list')).some((item) => ['script', 'img', 'iframe'].includes(item.tagName)));
const links = walk($('skill-list')).filter((item) => item.tagName === 'a');
assert.equal(links.length, 2);
assert.ok(links.every((item) => item.href.startsWith('/api/spaces/software-uiux/skills/figma-use/files/')));
const buttons = walk($('skill-list')).filter((item) => item.tagName === 'button');
assert.equal(buttons[0].attributes['aria-label'], '查看技能文件 SKILL.md');
await buttons[0].listeners.click();
const preview = walk($('skill-list')).find((item) => item.tagName === 'pre' && item.dataset.loaded === 'true');
assert.equal(preview.textContent, '<script>unsafe()</script>\n真实规范示例');
assert.equal(fetches[0].options.method, undefined, 'Source preview is a GET, never a tool execution');
await buttons[0].listeners.click(); assert.equal(preview.hidden, true); assert.equal(fetches.length, 1);
$('skill-search').value = 'figma'; call('renderSkillList', data, 'software-uiux');
assert.match($('skill-status').textContent, /匹配 1 \/ 1/);
$('skill-search').value = '组件'; call('renderSkillList', data, 'software-uiux');
assert.match($('skill-status').textContent, /匹配 1 \/ 1/);
$('skill-search').value = '不存在'; call('renderSkillList', data, 'software-uiux');
assert.match($('skill-list').textContent, /没有匹配/);
$('skill-search').value = ''; call('renderSkillList', { automatic_read: false, skills: [] }, 'commerce');
assert.match($('skill-list').textContent, /还没有已导入/);
assert.match($('skill-policy').textContent, /状态尚未确认/);
call('renderSkillList', { automatic_read: true, skills: [{ ...skill, status: 'conflict', error: '人工修改 <script>保留原文</script>' }] }, 'software-uiux');
assert.match($('skill-list').textContent, /需处理.*校验失败 · 保留人工修改 · 暂不自动读取.*人工修改 <script>保留原文<\/script>/);
assert.doesNotMatch($('skill-list').textContent, /已导入 · 可读取规范/);
assert.equal(walk($('skill-list')).filter((item) => ['a', 'button', 'script'].includes(item.tagName)).length, 0, 'A conflicted package is never offered for reading, even if stale files were provided');
call('renderSkillList', { automatic_read: true, skills: [{ ...skill, version: 'e'.repeat(64) }] }, 'software-uiux');
const versionLabel = walk($('skill-list')).find((item) => item.className === 'ag-template-version');
assert.equal(versionLabel.textContent, 'sha256:' + 'e'.repeat(12));
assert.equal(versionLabel.title, 'e'.repeat(64));
assert.match($('skill-list').textContent, /完整版本 SHA-256：e{64}/);

$('skills-dialog').open = true;
const oldLoad = call('loadSkills', 'software'), newLoad = call('loadSkills', 'software-uiux');
assert.deepEqual(pending.map((item) => item.path), ['/api/spaces/software/skills', '/api/spaces/software-uiux/skills']);
pending[1].resolve(data); await newLoad;
pending[0].resolve({ skills: [{ ...skill, display_name: '过期的软件技能' }] }); await oldLoad;
assert.match($('skill-list').textContent, /Figma 设计操作/);
assert.doesNotMatch($('skill-list').textContent, /过期的软件技能/);
assert.equal($('skills-refresh').disabled, false);
const failed = call('loadSkills', 'software-uiux'); pending[2].reject(new Error('原文件变动，校验失败')); await failed;
assert.match($('skill-status').textContent, /校验失败/);
assert.equal($('skill-status').classList.contains('ag-template-error'), true);
assert.equal($('skills-refresh').disabled, false);
const closed = call('loadSkills', 'software-uiux'); $('skills-dialog').open = false;
pending[3].resolve(data); await closed;
assert.equal($('skill-list').children.length, 0, 'A closed panel receives no stale response');

// Open before the directory arrives, then preserve user selection/filter across refresh.
Object.assign(state, { agents: [], skillSpace: null, skillEpoch: 0, graphSpace: 'software-uiux', view: 'new', listRevision: 0 });
pending.length = 0; $('skills-dialog').open = true; $('skill-search').value = 'Figma';
const directory = call('refreshDirectory'); call('renderSkillPicker'); await call('loadSkills');
assert.equal(pending.length, 3); assert.equal($('skill-agent').disabled, true);
pending[0].resolve({ agents }); pending[1].resolve({ rooms: [] }); pending[2].resolve({ enabled: true }); await directory;
assert.equal(state.skillSpace, 'software-uiux'); assert.equal($('skill-agent').value, 'software-uiux');
assert.equal($('skill-search').value, 'Figma');
assert.equal(pending.length, 4); assert.equal(pending[3].path, '/api/spaces/software-uiux/skills');
const repeatDirectory = call('refreshDirectory');
pending[4].resolve({ agents }); pending[5].resolve({ rooms: [] }); pending[6].resolve({ enabled: true }); await repeatDirectory;
assert.equal(pending.length, 7, 'Directory refresh does not start a duplicate skill request');
pending[3].resolve(data); await new Promise((resolve) => setImmediate(resolve));
assert.match($('skill-list').textContent, /Figma 设计操作/);
state.skillSpace = 'commerce'; $('skill-agent').value = 'commerce'; $('skill-search').value = '订单';
const intentionalDirectory = call('refreshDirectory');
pending[7].resolve({ agents }); pending[8].resolve({ rooms: [] }); pending[9].resolve({ enabled: true }); await intentionalDirectory;
assert.equal($('skill-agent').value, 'commerce'); assert.equal($('skill-search').value, '订单'); assert.equal(pending.length, 10);

assert.equal(call('renderSkillReads', {}, 'legacy'), null);
assert.equal(call('renderSkillReads', { skill_selection: 'bad', skill_reads: [null, {}, []] }, 'invalid'), null);
const fields = {
  skill_selection: [{ agent_id: 'software-uiux', id: 'figma-use', display_name: 'Figma 设计操作', version: 'r1', selection_reason: '页面组件任务匹配' },
    { agent_id: 'commerce', id: 'figma-use', display_name: 'Figma 设计操作', version: 'r2' }],
  skill_reads: [{ agent_id: 'software-uiux', skill_id: 'figma-use', path: 'SKILL.md', full_sha256: 'a'.repeat(64), sha256: 'a'.repeat(64), excerpt_sha256: 'b'.repeat(64), truncated: true },
    { agent_id: 'commerce', skill_id: 'figma-use', path: 'references/other.md', sha256: 'c'.repeat(64) }],
};
const receipt = call('renderSkillReads', fields, 'receipt');
assert.equal(receipt.open, false);
const groups = walk(receipt).filter((item) => item.className === 'ag-skill-read-group');
assert.equal(groups.length, 2);
assert.match(groups[0].textContent, /UI\/UX 设计师.*Figma 设计操作.*figma-use.*r1.*页面组件任务匹配.*SKILL.md/);
assert.doesNotMatch(groups[0].textContent, /other.md|r2/);
assert.match(groups[0].textContent, /完整文件 SHA-256：a{64}.*模型所见摘录 SHA-256：b{64}.*未收到文件全文/);
assert.match(groups[1].textContent, /电商 Agent.*r2.*other.md.*读取回执 SHA-256：c{64}/);
assert.match(receipt.textContent, /不代表已经调用技能依赖的外部工具/);
receipt.isConnected = true; receipt.open = true; receipt.listeners.toggle();
assert.equal(call('renderSkillReads', fields, 'receipt').open, true);
assert.equal(call('renderSkillReads', fields, 'other-receipt').open, false);
assert.match(call('renderSkillReads', { skill_selection: [{ id: 'figma-use' }] }, 'selection').textContent, /只有技能选择，没有实际文件读取回执/);
const notice = call('renderSkillReads', { skill_notices: [{ agent_id: 'software-uiux', text: '<img src=x> 依赖未连接' }, '规范缺失'] }, 'notice');
assert.match(notice.textContent, /UI\/UX 设计师：<img src=x> 依赖未连接.*规范缺失/);
assert.ok(!walk(notice).some((item) => item.tagName === 'img'));

call('renderMessages', { id: 'room', mode: 'orchestrated', messages: [
  { id: 'user', role: 'user', content: '需求', ...fields },
  { id: 'summary', role: 'assistant', agent_id: 'central', content: '汇总', ...fields },
  { id: 'old', role: 'assistant', agent_id: 'software', content: '历史记录' },
] }, true);
const messages = walk($('feed')).filter((item) => /^ag-message(?: |$)/.test(item.className));
assert.equal(messages.length, 3);
assert.doesNotMatch(messages[0].textContent, /本轮读取的技能规范/);
assert.match(messages[1].textContent, /汇总/);
assert.doesNotMatch(messages[1].textContent, /本轮读取的技能规范/);
assert.doesNotMatch(messages[2].textContent, /本轮读取的技能规范/);
const delegated = call('renderDelegations', { id: 'room', delegations: [{ id: 'task', round_id: 'r', agent_id: 'software-uiux', title: '设计任务', status: 'completed', phase: 'execute', ...fields }] }, 'r');
assert.doesNotMatch(delegated.textContent, /本轮读取的技能规范|Figma 设计操作/);
console.log('Skill UI checks passed: library search/provenance/dependencies, safe previews, empty/errors, request races, directory-selection preservation, Agent-scoped actual reads and hashes, truncation, direct/summary/task receipts and legacy compatibility.');
