/** Minimal DOM regression: no browser, network, model or knowledge writes. */
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
    this.tagName = tag; this.children = []; this.dataset = {}; this._text = ''; this.open = false;
    this.scrollTop = 0; this.scrollHeight = 1000;
    this.value = ''; this.checked = false; this.disabled = false; this.hidden = false;
    this.listeners = {}; this.classList = { toggle() {} };
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map((item) => item.textContent).join(''); }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; this._text = ''; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  focus() { this.focused = true; }
}
const elements = new Map();
const $ = (name) => {
  if (!elements.has(name)) elements.set(name, new Element());
  return elements.get(name);
};
const state = {
  room: { id: 'room', mode: 'orchestrated', status: 'idle' }, roomId: 'room', view: 'room',
  rooms: [], sending: new Set(), submissions: new Map(), unconfirmed: new Map(), drafts: new Map(), feedPositions: new Map(), taskExpanded: new Map(), epoch: 0, listRevision: 0,
  learningStatus: { enabled: true, search_available: false, default_provider: 'official-sites',
    max_pages_per_agent: 5, max_pages_per_round: 8, requires_user_urls: false },
};
const posts = [], notices = [];
const make = (tag, cls, text) => { const node = new Element(tag); node.className = cls || ''; if (text !== undefined) node.textContent = text; return node; };
const walk = (node) => [node, ...node.children.flatMap(walk)];
let rejectPost = false, holdPost = false, finishPost, failPost;
const sandbox = {
  window: {},
  state, $, make, Set, Number, Boolean, JSON, URL, date: String,
  active: (status) => ['queued', 'running'].includes(status),
  count: (value) => Number.isFinite(Number(value)) ? Number(value) : 0,
  persistView() {}, upsertRoom() {}, schedulePoll() {}, renderRooms() {}, renderMessages() {},
  notice(text) { notices.push(text); },
  renderRoom(room) { state.room = room; sandbox.renderComposer(); },
  async api(path, options) {
    posts.push(JSON.parse(options.body));
    if (rejectPost) throw new Error('受控连接失败');
    if (holdPost) await new Promise((resolve,reject) => { finishPost = resolve; failPost=reject; });
    return { room: { ...state.room, status: 'idle' } };
  },
  renderComposerContext() {},
};
vm.createContext(sandbox);
vm.runInContext(source.match(/^  const hasLearningPrefix = .*$/m)[0] + '\n'
  + ['stopRoomStream', 'saveDraft', 'resetLearningControls', 'researchRequested', 'learningRequested', 'renderLearningControls', 'renderComposer', 'selectRoom', 'rememberDetails', 'publicSourceURL', 'renderResearchReceipt']
    .map(extractFunction).join('\n'), sandbox);
const evaluate = (text) => vm.runInContext(text, sandbox);
const handlerStart = source.indexOf('  $("message").addEventListener("input"');
const handlerEnd = source.indexOf('\n  window.addEventListener("pagehide"', handlerStart);
assert.ok(handlerStart > 0 && handlerEnd > handlerStart);
vm.runInContext(source.slice(handlerStart, handlerEnd), sandbox);
const submit = () => $('message-form').listeners.submit({ preventDefault() {} });
const change = (name, checked) => { $(name).checked = checked; $(name).listeners.change(); };

evaluate('resetLearningControls(); renderComposer();');
assert.match(source, /id="ag-research" type="checkbox" aria-describedby="ag-research-description"/);
assert.equal($('research-controls').hidden, true, 'Legacy rooms do not offer the primary query action');
assert.equal($('learning').checked, false);
assert.equal($('learning').disabled, false, 'No search API key must not disable official discovery');
assert.equal($('learning-pages').value, '2');
$('message').value = '让 App Agent 自主学习 Flutter';
$('learning').checked = true; $('learning-pages').value = '3';
evaluate('renderComposer()');
assert.equal($('send').disabled, false, 'Enabled official discovery must permit learning POST');
assert.equal($('send').textContent, '开始学习');
assert.match($('learning-provider').textContent, /官方资料自主发现 · 无需提供链接/);
assert.doesNotMatch($('learning-provider').textContent, /不可用|未启用/);
await submit();
assert.deepEqual(posts.at(-1), { content: '让 App Agent 自主学习 Flutter', learning: true, research: false, max_pages: 3, file_ids:[] });
assert.equal($('learning').checked, false);
assert.equal($('learning-pages').value, '2');
assert.equal($('message').value, '');
$('message').value = '解释学习结果';
await submit();
assert.deepEqual(posts.at(-1), { content: '解释学习结果', learning: false, research: false, max_pages: 2, file_ids:[] });
$('message').value = '/学习 Flutter';
evaluate('renderComposer()');
assert.equal($('learning-prefix').hidden, false);
assert.equal($('send').disabled, false);
await submit();
assert.equal(posts.at(-1).learning, true);

state.learningStatus.enabled = false;
$('message').value = '/学习 Flutter';
evaluate('renderComposer()');
assert.equal($('learning').disabled, true);
assert.equal($('send').disabled, true);
assert.match($('learning-provider').textContent, /未启用/);
const before = posts.length;
await submit();
assert.equal(posts.length, before);
assert.match(notices.at(-1), /未启用/);

state.learningStatus.enabled = true;
state.learningStatus.search_available = true;
evaluate('renderComposer()');
assert.equal($('send').disabled, false);
assert.match($('learning-provider').textContent, /已配置搜索服务，具体采集方式以回执为准/);
state.room.mode = 'group';
evaluate('renderComposer()');
assert.equal($('learning-controls').hidden, true);
await submit();
assert.equal(posts.length, before);
assert.match(notices.at(-1), /主 Agent 自动协作/);
state.room.mode = 'orchestrated'; state.room.purpose = 'primary'; state.room.status = 'idle';
$('learning').checked = true;
evaluate('renderComposer()');
assert.equal($('send').textContent, '生成学习方案');
assert.match($('compose-hint').textContent, /先生成待确认的学习方案，确认后才采集并更新草稿/);
delete state.room.purpose;
evaluate('renderComposer()');
assert.equal($('send').textContent, '开始学习', 'Legacy rooms keep their existing explicit learning action');
assert.match($('compose-hint').textContent, /本轮会采集公开资料/);

// Primary query and learning controls are independent choices with distinct effects.
state.room.purpose = 'primary';
$('message').value = 'Flutter 当前有哪些新变化？';
change('research', true);
assert.equal($('research-controls').hidden, false);
assert.equal($('learning').checked, false);
assert.equal($('learning-pages').disabled, true);
assert.equal($('send').textContent, '查询并回答');
assert.match($('research-description').textContent, /只查阅公开资料并回答，不写入知识库/);
assert.equal($('learning-description').hidden, false, 'The difference remains explained before selecting learning');
assert.match($('learning-description').textContent, /你确认后才采集资料并更新知识草稿/);
assert.match($('compose-hint').textContent, /查询公开资料.*明确要求不更新时保留原文/);
change('learning', true);
assert.equal($('research').checked, false);
assert.equal($('send').textContent, '生成学习方案');
change('research', true);
assert.equal($('learning').checked, false);
state.learningStatus.enabled = false;
evaluate('renderComposer()');
assert.equal($('research').disabled, false, 'Disabling knowledge learning does not disable a read-only query');
assert.equal($('send').disabled, false);
await submit();
assert.deepEqual(posts.at(-1), { content: 'Flutter 当前有哪些新变化？', learning: false, research: true, max_pages: 2, file_ids:[] });
assert.equal($('research').checked, false);
assert.equal($('learning').checked, false);
$('message').value = '继续解释刚才的回答';
await submit();
assert.equal(posts.at(-1).research, false, 'An ordinary follow-up does not silently repeat query mode');
state.learningStatus.enabled = true;

// The explicit learning command wins over a previously selected query, without both modes being submitted.
change('research', true);
$('message').value = '/学习 Flutter'; $('message').listeners.input();
assert.equal($('research').checked, false);
assert.equal($('research').disabled, true);
assert.equal($('learning-prefix').hidden, false);
assert.match($('research-description').textContent, /移除指令后可选择只查询/);
assert.equal($('send').textContent, '生成学习方案');
await submit();
assert.equal(posts.at(-1).learning, true);
assert.equal(posts.at(-1).research, false);

// Both queued work and an in-flight POST disable mode changes and duplicate sends.
$('message').value = '查一下 Flutter 文档'; change('research', true);
state.room.status = 'running'; evaluate('renderComposer()');
assert.equal($('research').disabled, true); assert.equal($('learning').disabled, true);
assert.equal($('learning-pages').disabled, true); assert.equal($('send').disabled, true);
assert.equal($('message').disabled, false, 'The next draft remains editable while a turn runs');
let postCount = posts.length;
await submit(); assert.equal(posts.length, postCount);
state.room.status = 'idle'; evaluate('renderComposer()');
holdPost = true;
const pending = submit();
assert.equal($('research').disabled, true); assert.equal($('learning').disabled, true);
assert.equal($('message').disabled, false); assert.equal($('send').textContent, '发送');
assert.equal($('message').value, '', 'Move the submitted text out of the composer before awaiting HTTP');
assert.equal(state.drafts.has('room'),false);
assert.equal(state.submissions.get('room').content,'查一下 Flutter 文档');
$('message').value='下一条草稿'; $('message').listeners.input();
postCount = posts.length; await submit(); assert.equal(posts.length, postCount);
finishPost(); await pending; holdPost = false;
assert.equal($('message').value,'下一条草稿','A late acknowledgement must not clear the next draft');
assert.equal(state.drafts.get('room'),'下一条草稿');
assert.equal($('research').checked, false); assert.equal($('research').disabled, false);

// A failed delayed POST preserves both the submitted message and the new draft.
$('message').value='原消息';holdPost=true;
const failed=submit();
$('message').value='新的草稿不能覆盖';$('message').listeners.input();
failPost(new Error('受控连接失败'));await failed;holdPost=false;
assert.equal($('message').value,'新的草稿不能覆盖');
assert.equal(state.drafts.get('room'),'新的草稿不能覆盖');
assert.equal(state.unconfirmed.get('room').at(-1).content,'原消息');

// Even a new draft with identical text is a new draft, not the acknowledged input.
$('message').value='同一句话';holdPost=true;
const repeated=submit();$('message').value='同一句话';$('message').listeners.input();
finishPost();await repeated;holdPost=false;
assert.equal($('message').value,'同一句话');assert.equal(state.drafts.get('room'),'同一句话');

// A failed request keeps its draft and explicit choice available for review/retry.
$('message').value = '待重试的资料查询'; change('research', true); rejectPost = true;
await submit(); rejectPost = false;
assert.equal($('message').value, '待重试的资料查询'); assert.equal($('research').checked, true);
assert.equal(state.drafts.get('room'), '待重试的资料查询');
assert.match(notices.at(-1), /消息未确认发送.*受控连接失败/);

// Actual room-selection code resets mode choices while preserving each room's text and position.
const primary = { ...state.room }, legacy = { id: 'legacy', mode: 'orchestrated', status: 'idle' };
state.rooms = [primary, legacy]; state.primaryRoomId = primary.id;
state.drafts.set('legacy', '历史会话草稿'); state.feedPositions.set('legacy', 71);
$('feed').scrollTop = 42; state.taskExpanded.set('history:detail', true);
await sandbox.selectRoom('legacy', legacy);
assert.equal($('research').checked, false); assert.equal($('learning').checked, false);
assert.equal($('research-controls').hidden, true); assert.equal($('message').value, '历史会话草稿');
assert.equal($('feed').scrollTop, 71); assert.equal(state.drafts.get(primary.id), '待重试的资料查询');
change('learning', true); $('message').value = '历史群下一轮草稿';
await sandbox.selectRoom(primary.id, primary);
assert.equal($('learning').checked, false); assert.equal($('research').checked, false);
assert.equal($('message').value, '待重试的资料查询'); assert.equal($('feed').scrollTop, 42);
assert.equal(state.drafts.get('legacy'), '历史群下一轮草稿'); assert.equal(state.taskExpanded.get('history:detail'), true);
delete state.room.purpose; evaluate('renderComposer()');
assert.equal($('research-controls').hidden, false, 'A primary room remains recognized by its known ID');
await sandbox.selectRoom('legacy', legacy);
$('message').value = '旧群普通问题'; $('research').checked = true;
await submit(); assert.equal(posts.at(-1).research, false, 'A stale hidden checkbox never enables queries in old rooms');

// Query receipts are factual, readable, and distinct from persisted proposal research.
const receipt = { status: 'completed', scope: 'proposal-only', query: 'Flutter 文档', note: '实际读取了以下网页。',
  sources: [{ title: '官方文档', url: 'https://example.com/flutter', truncated: true, fetched_at: '2026-10-03T12:00:00Z' }] };
const queryReceipt = sandbox.renderResearchReceipt({ phase: 'consultation', research: receipt }, 'query');
assert.match(queryReceipt.children[0].textContent, /本轮联网查询.*公开资料读取完成.*1 项来源/);
assert.match(queryReceipt.textContent, /查询内容：Flutter 文档.*本次回答依据的是网页摘录/s);
assert.match(queryReceipt.textContent, /没有写入知识库/);
assert.doesNotMatch(queryReceipt.textContent, /方案|市场调研/);
assert.equal(walk(queryReceipt).find((node) => node.tagName === 'a').href, 'https://example.com/flutter');
const flagReceipt = sandbox.renderResearchReceipt({ research_only: true, research: receipt }, 'flag-query');
assert.match(flagReceipt.children[0].textContent, /本轮联网查询/);
for (const [searchStatus, label, note] of [
  ['not_configured', '未配置搜索服务', '尚未配置通用搜索服务，也没有可匹配的官方资料入口。'],
  ['no_results', '未找到查询结果', '没有找到与本次问题匹配的公开资料。'],
  ['failed', '查询服务调用失败', '查询服务调用失败，本轮没有取得公开资料。'],
]) {
  const unavailable = sandbox.renderResearchReceipt({ phase: 'consultation', research: { status: 'not_researched', search_status: searchStatus, note, sources: [] } }, searchStatus);
  assert.match(unavailable.children[0].textContent, new RegExp(`本轮联网查询.*${label}.*0 项来源`));
  assert.ok(unavailable.textContent.includes(note));
  assert.doesNotMatch(unavailable.children[0].textContent, /读取完成|读取成功/);
  assert.match(unavailable.textContent, /没有成功读取并记录的网页来源/);
  const withSource = sandbox.renderResearchReceipt({ phase: 'consultation', research: { ...receipt, status: 'partial', search_status: searchStatus } }, `${searchStatus}-with-source`);
  assert.match(withSource.children[0].textContent, /本轮联网查询.*部分资料读取成功.*1 项来源/);
  assert.ok(!withSource.children[0].textContent.includes(label), 'Recorded sources take precedence over search service availability');
}
for (const searchStatus of ['not_requested', 'completed']) {
  const noSource = sandbox.renderResearchReceipt({ phase: 'consultation', research: { status: 'not_researched', search_status: searchStatus, sources: [] } }, searchStatus);
  assert.match(noSource.children[0].textContent, /本轮联网查询.*未取得查询资料.*0 项来源/);
}
const emptySuccess = sandbox.renderResearchReceipt({ phase: 'consultation', research: { status: 'completed', sources: [] } }, 'empty');
assert.match(emptySuccess.children[0].textContent, /未成功读取资料.*0 项来源/);
const proposalReceipt = sandbox.renderResearchReceipt({ phase: 'proposal', research: receipt }, 'proposal');
assert.match(proposalReceipt.children[0].textContent, /本轮调研来源/);
assert.match(proposalReceipt.textContent, /不代表方案每条结论都获得支持/);
console.log('Learning and research UI DOM checks passed: mutually exclusive choices, primary/legacy isolation, honest receipts, query POST, per-turn reset, busy/failure handling, and preserved room drafts/history.');
