/** Host progress and real member replies share one collaboration timeline. */
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const source = fs.readFileSync(new URL('../federation/web/agent-chat.js', import.meta.url), 'utf8');
function extract(name) {
  const start = source.search(new RegExp(`  (?:async )?function ${name}\\(`));
  assert.ok(start >= 0, name);
  return source.slice(start, source.indexOf('\n  }', start) + 4);
}
class Element {
  constructor(tag = 'div') {
    this.tagName = tag; this.children = []; this.dataset = {}; this.listeners = {}; this.attributes = {}; this._text = '';
    this.open = false; this.hidden = false; this.disabled = false; this.value = ''; this.scrollTop = 0; this.scrollHeight = 1000; this.clientHeight = 400;
    this.style = { setProperty() {} }; this.replacements = 0;
    const classes = new Set();
    this.classList = { add: (key) => classes.add(key), remove: (key) => classes.delete(key), contains: (key) => classes.has(key), toggle(key, value) { if (value) classes.add(key); else classes.delete(key); } };
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map((item) => item.textContent).join(''); }
  set innerHTML(_) { throw new Error('Dynamic HTML not allowed'); }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; this._text = ''; this.replacements++; }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  get childNodes() { return this.children; }
  get childElementCount() { return this.children.length; }
  querySelectorAll(selector) {
    const children = this.children.flatMap((node) => [node, ...node.querySelectorAll('*')]);
    return selector === '*' ? children : selector === '[data-message-id]' ? children.filter((node) => node.dataset.messageId) : [];
  }
  scrollIntoView(options) { this.scrolled = options; }
  showModal() { this.open = true; }
  close() { this.open = false; }
  focus() { this.focused = true; }
}
const nodes = new Map();
const $ = (id) => { if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id); };
const make = (tag, className, text) => { const node = new Element(tag); node.className = className || ''; if (text !== undefined) node.textContent = text; return node; };
const walk = (node) => [node, ...node.children.flatMap(walk)];
const agents = [
  { id: 'central', name: '中央智能体', depth: 0, breadcrumb: ['中央智能体'] },
  { id: 'software', name: '互联网与软件 Agent', parent_id: 'central', depth: 1, breadcrumb: ['中央智能体', '互联网与软件'] },
  { id: 'software-frontend', name: '前端 Agent', parent_id: 'software', depth: 2, breadcrumb: ['中央智能体', '互联网与软件', '前端'] },
  { id: 'software-uiux', name: 'UI/UX 设计师', parent_id: 'software', depth: 2, breadcrumb: ['中央智能体', '互联网与软件', 'UI/UX'] },
];
const state = { agents, rooms: [], room: null, view: 'new', mode: 'orchestrated', selectedAgents: new Set(),
  taskExpanded: new Map(), drafts: new Map(), feedPositions: new Map(), sending: new Set(), epoch: 0,
  graphSpace: 'central', feedSignature: '', creating: false, industryFilter: 'all', loaded: true };
const sandbox = { state, $, make, Number, String, Object, Array, Set, Map, JSON, URL, window: {},
  agent: (id) => agents.find((item) => item.id === id), agentName: (id) => agents.find((item) => item.id === id)?.name || id || 'Agent',
  count: (value) => Number.isFinite(Number(value)) ? Number(value) : 0,
  depth: (item) => item?.depth || 0, breadcrumb: (item) => item?.breadcrumb?.join(' › ') || 'Agent',
  industryId: (item) => item.id === 'central' ? 'central' : 'software',
  date: String, persistView() {}, notice() {}, renderRooms() {}, resetLearningControls() {},
  active: (value) => ['running', 'queued'].includes(value), modeName: (mode) => mode === 'orchestrated' ? '主 Agent 协作群' : mode,
  document: { activeElement: null, createDocumentFragment: () => new Element('fragment') }, watchRoomStream() {},
};
vm.createContext(sandbox);
vm.runInContext(['markdownBody', 'orderedAgents', 'saveDraft',
  'currentChatContext', 'renderMembers', 'taskStatus', 'rememberDetails', 'publicSourceURL', 'renderTemplateReads', 'renderResearchReceipt', 'renderLearningReceipt',
  'renderDelegations', 'renderProgressMessage', 'renderProposal', 'confirmProposal', 'renderTaskGroup', 'renderReportArtifacts', 'validInterimReplies', 'renderInterimReplies', 'renderReportCheck', 'renderContextUsage', 'mergeReplyMessages', 'questionLanguage','turnLanguage','conversationMessages', 'operationTarget','operationReadFailure','operationFailureDetail','replyOperations','renderOperations','validReplyTimeline','replyTimeline','recordReplyTimeline','renderUnplacedOperations','processingLabel','replyStageLabel', 'isNativeReply', 'renderReplyLoading', 'contextAdjustment','renderReplyBody', 'messageDetails','renderReplyTiming','renderMessages', 'renderRoom', 'renderStreamNotice', 'stopRoomStream'].map(extract).join('\n'), sandbox);
const call = (name, ...args) => sandbox[name](...args);

// Actual interim conversation is visible while streaming; diagnostic drafts
// and historical check panels are retained in storage, outside the chat view.
const interim={id:'first-answer',title:'先回应你',text:'实际模型初步回应，尚待校对。',status:'completed'};
call('renderMessages',{id:'progressive',mode:'orchestrated',status:'running',active_job_id:'progressive-job',messages:[],
  live_reply:{job_id:'progressive-job',agent_id:'central',updates:[interim],text:'',revision:1}});
assert.ok(walk($('feed')).some(node=>node.dataset.messageId==='live-progressive-job-update-first-answer'));
assert.ok(walk($('feed')).some(node=>node.textContent.includes('先给你这部分')));
call('renderMessages',{id:'progressive',mode:'orchestrated',status:'idle',messages:[{id:'final-report',role:'assistant',agent_id:'central',content:'最终校对结果。',interim_replies:[interim]}]});
assert.equal(walk($('feed')).some(node=>node.tagName==='details' && node.className.includes('ag-interim-history')),false);
assert.equal(walk($('feed')).some(node=>node.dataset.messageId==='live-progressive-job-update-first-answer'),false);

// The normal entry contains only the main conversation, never creation or member picking.
assert.match(source, /<h2 id="ag-title">主 Agent<\/h2>/);
assert.match(source, /id="ag-history-open"/);
assert.match(source, /id="ag-history-dialog"/);
assert.match(source, /id="ag-return-primary"/);
assert.doesNotMatch(source, /id="ag-(new|create-form|room-title|mode-orchestrated|mode-group|mode-direct|agents)"/);
assert.doesNotMatch(source, /api\("\/api\/chat\/rooms", \{ method: "POST"/);
state.roomId = 'draft-room'; state.view = 'room'; $('message').value = '尚未发送的草稿'; $('feed').scrollTop = 123;
call('saveDraft');
assert.equal(state.drafts.get('draft-room'), '尚未发送的草稿'); assert.equal(state.feedPositions.get('draft-room'), 123);

const tasks = [
  { id: 'root-task', round_id: 'r1', agent_id: 'central', phase: 'plan', status: 'running', title: '处理用户需求' },
  { id: 'module-task', parent_task_id: 'root-task', round_id: 'r1', agent_id: 'software', phase: 'plan', status: 'running', title: '拆分软件任务' },
  { id: 'front-task', parent_task_id: 'module-task', round_id: 'r1', agent_id: 'software-frontend', phase: 'execute', status: 'completed', title: '实现页面', instruction: '复用 React 模板', result: '真实前端结果正文' },
];
const messages = [
  { id: 'u1', role: 'user', content: '做一个界面', round_id: 'r1' },
  { id: 'e1', role: 'system', event_origin: 'host', event_kind: 'delegation', actor_agent_id: 'central', recipient_agent_id: 'software', delegation_task_id: 'module-task', round_id: 'r1', content: '请拆分软件模块任务。' },
  { id: 'e2', role: 'system', event_origin: 'host', event_kind: 'delegation', actor_agent_id: 'software', recipient_agent_id: 'software-frontend', delegation_task_id: 'front-task', round_id: 'r1', content: '请前端完成页面实现。' },
  { id: 'e3', role: 'system', event_origin: 'host', event_kind: 'work_started', actor_agent_id: 'software-frontend', delegation_task_id: 'front-task', round_id: 'r1', content: '开始读取本库规范。' },
  { id: 'a1', role: 'assistant', agent_id: 'software-frontend', event_origin: 'agent', event_kind: 'result', round_id: 'r1', delegation_task_id: 'front-task', content: '真实前端结果正文', status: 'completed' },
  { id: 'a2', role: 'assistant', agent_id: 'software', event_origin: 'agent', event_kind: 'result', round_id: 'r1', phase: 'summary', content: '模块汇总正文' },
  { id: 'a3', role: 'assistant', agent_id: 'central', round_id: 'r1', phase: 'summary', content: '主智能体最终汇总' },
];
const room = { id: 'collaboration', mode: 'orchestrated', participants: ['central'], status: 'running', messages, delegations: tasks };
call('renderMembers', room);
assert.equal($('members').children.length, 3);
assert.match($('members').textContent, /主 Agent · 分派中.*互联网与软件 Agent · 分派中.*前端 Agent · 已完成/);
assert.doesNotMatch($('members').textContent, /UI\/UX/, 'Unassigned Agents are not invented as participants');
const tree = call('renderDelegations', room, 'r1');
assert.equal(tree.tagName, 'details'); assert.equal(tree.open, false);
assert.equal(tree.children[0].tagName, 'summary'); assert.match(tree.children[0].textContent, /分工详情/);
tree.isConnected = true; tree.open = true; tree.listeners.toggle();
assert.equal(call('renderDelegations', room, 'r1').open, true);
assert.equal(call('renderDelegations', { ...room, id: 'another-room' }, 'r1').open, false);

$('message').value = '下一轮草稿'; $('feed').scrollTop = 117;
call('renderMessages', room);
const top = $('feed').children[0].children;
assert.deepEqual(top.map((node) => node.tagName), ['article', 'details', 'article', 'article', 'article', 'article', 'article', 'article']);
assert.equal(top.filter((node) => node.className === 'ag-delegations').length, 1);
assert.match(top[2].textContent, /主 Agent → 互联网与软件 Agent.*分派任务.*系统执行记录.*拆分软件模块任务/);
assert.match(top[3].textContent, /互联网与软件 Agent → 前端 Agent.*请前端完成页面实现/);
assert.match(top[4].textContent, /前端 Agent.*开始处理.*系统执行记录/);
assert.match(top[5].textContent, /前端 Agent.*成员回复.*真实前端结果正文/);
assert.equal(top[5].tagName, 'article', 'Member reply is a visible top-level bubble, not buried in the task tree');
assert.match(top[6].textContent, /互联网与软件 Agent.*行业汇总.*模块汇总正文/);
assert.match(top[7].textContent, /主 Agent.*协作汇总.*主智能体最终汇总/);
assert.equal($('message').value, '下一轮草稿'); assert.equal($('feed').scrollTop, 117);
const replacements = $('feed').replacements; call('renderMessages', room);
assert.equal($('feed').replacements, replacements, 'Unchanged polling does not rebuild the feed');
const progressed = { ...room, messages: [...messages, { id: 'new-result', role: 'assistant', event_kind: 'result', agent_id: 'software-uiux', content: '新增设计结果' }] };
call('renderMessages', progressed);
assert.match($('feed').textContent, /新增设计结果/); assert.equal($('feed').scrollTop, 117);
$('feed').scrollTop = 590; call('renderMessages', { ...progressed, messages: [...progressed.messages, { id: 'last', role: 'assistant', agent_id: 'central', content: '完成' }] });
assert.equal($('feed').scrollTop, 1000, 'A reader near the bottom follows new replies');

const unsafe = { role: 'system', event_origin: 'host', event_kind: 'delegation', actor_agent_id: 'software', recipient_agent_id: '<img src=x>', content: '<script>任务</script>' };
const card = call('renderProgressMessage', unsafe, room);
assert.match(card.textContent, /<img src=x>.*<script>任务<\/script>/);
assert.ok(!walk(card).some((item) => ['img', 'script'].includes(item.tagName)));
assert.equal(call('renderProgressMessage', { ...unsafe, event_origin: 'agent' }, room), null);
assert.equal(call('renderProgressMessage', { ...unsafe, role: 'user' }, room), null);
call('renderMessages', { ...room, messages: [
  { role: 'system', event_origin: 'host', event_kind: 'error', actor_agent_id: 'software-frontend', content: '接口检查失败', id: 'failure' },
  { role: 'assistant', agent_id: 'software-frontend', event_kind: 'result', result_scope: 'partial', status: 'failed', content: '保留已完成部分', id: 'partial' },
] }, true);
assert.match($('feed').textContent, /前端 Agent.*未完成.*系统执行记录.*接口检查失败.*前端 Agent.*部分结果.*保留已完成部分/);

// Existing direct/manual group room behavior remains ordinary, with no invented members.
call('renderMembers', { ...room, mode: 'direct', participants: ['software-frontend'] });
assert.equal($('members').children.length, 1);
call('renderMessages', { id: 'direct', mode: 'direct', messages: [{ role: 'assistant', agent_id: 'software-frontend', content: '独立会话原回复' }] }, true);
assert.match($('feed').textContent, /独立会话原回复/);
assert.doesNotMatch($('feed').textContent, /分工详情|系统执行记录/);

// Every task is grouped inside the fixed entry. Current members never leak from earlier tasks.
const firstGroup = { id: 'r1', round_id: 'r1', title: '做一个界面', status: 'completed', members: ['central', 'software', 'software-frontend'] };
const secondGroup = { id: 'r2', round_id: 'r2', title: '<img src=x>设计任务', status: 'running', members: ['central', 'software-uiux'] };
const grouped = { ...room, purpose: 'primary', participants: ['central', 'software', 'software-frontend', 'software-uiux'],
  task_groups: [firstGroup, secondGroup], current_task_group_id: 'r2', messages: [
    ...messages, { id: 'u2', role: 'user', content: '下一项设计任务', round_id: 'r2' },
    { id: 'g2', role: 'system', event_origin: 'host', event_kind: 'group_started', actor_agent_id: 'central', recipient_agent_id: 'central', content: '主 Agent 已为这项任务创建协作群。', round_id: 'r2' },
    { id: 'j2', role: 'system', event_origin: 'host', event_kind: 'member_joined', actor_agent_id: 'central', recipient_agent_id: 'software-uiux', content: '邀请 UI/UX 设计师参与。', round_id: 'r2' },
    { id: 'd2', role: 'system', event_origin: 'host', event_kind: 'delegation', actor_agent_id: 'central', recipient_agent_id: 'software-uiux', content: '请整理交互设计规范。', round_id: 'r2' },
    { id: 'r2-result', role: 'assistant', event_origin: 'agent', event_kind: 'result', agent_id: 'software-uiux', content: '设计师的实际回复', round_id: 'r2' },
  ] };
call('renderMembers', grouped);
assert.equal($('members').children.length, 2);
assert.match($('members').textContent, /主 Agent.*UI\/UX 设计师/);
assert.doesNotMatch($('members').textContent, /前端 Agent|互联网与软件 Agent/);
call('renderMessages', grouped, true);
const taskGroups = $('feed').children[0].children;
assert.equal(taskGroups.length, 2);
assert.ok(taskGroups.every((node) => node.tagName === 'section' && node.className === 'ag-task-group'));
assert.match(taskGroups[0].children[0].textContent, /主 Agent 创建的任务群.*做一个界面.*已完成/);
assert.match(taskGroups[1].textContent, /主 Agent.*已创建任务群.*主 Agent 邀请 UI\/UX 设计师.*加入任务群.*分派任务.*设计师的实际回复/);
assert.ok(!walk(taskGroups[1]).some((node) => ['img', 'script'].includes(node.tagName)));
assert.doesNotMatch(taskGroups[1].textContent, /真实前端结果正文|主智能体最终汇总/);
const groupMessages = taskGroups[1].children[2].children;
assert.equal(groupMessages.at(-1).tagName, 'article', 'Real replies remain visible inside each task group');
assert.match(groupMessages[1].className, /ag-progress-group_started/);
assert.match(groupMessages[2].className, /ag-progress-member_joined/);
assert.match(groupMessages[3].className, /ag-progress-delegation/);
const finalJump = walk(taskGroups[0].children[0]).find((node) => node.tagName === 'button' && /最终答复/.test(node.textContent));
assert.ok(finalJump, 'A completed task group provides a direct route to the main Agent answer');
finalJump.listeners.click();
const finalAnswer = walk(taskGroups[0]).find((node) => node.dataset.messageId === 'a3');
assert.equal(finalAnswer.scrolled.block, 'start'); assert.equal(finalAnswer.focused, true);
assert.equal(finalAnswer.attributes.tabindex, '-1');
const previous = $('feed').replacements;
call('renderMessages', { ...grouped, task_groups: [firstGroup, { ...secondGroup, status: 'completed' }] });
assert.ok($('feed').replacements > previous, 'Group-only status updates re-render');
call('renderMembers', { ...grouped, task_groups: [secondGroup, firstGroup], current_task_group_id: 'r2' });
assert.equal($('members').children.length, 2, 'Explicit current group wins over list ordering');
call('renderMembers', { ...grouped, current_task_group_id: undefined, task_groups: [firstGroup, secondGroup] });
assert.equal($('members').children.length, 2, 'No explicit current ID falls back to last group');
call('renderMembers', { ...grouped, task_groups: [], messages: [] });
assert.equal($('members').textContent, '主 Agent', 'Empty primary does not show past participant union');

// The second request is queued before the worker creates its new group. Old members stay
// in the old group, while the current header must describe the newly submitted task.
const queued = { ...grouped, status: 'queued', active_job_id: 'content-round', current_task_group_id: 'r1', task_groups: [firstGroup],
  proposals: [{ id: 'queued-proposal', status: 'confirmed', title: '第二项：整理内容运营规范', confirmed_job_id: 'content-round' }],
  messages: [...messages, { id: 'next-user', role: 'user', round_id: 'content-round', phase: 'confirmation', proposal_id: 'queued-proposal', content: '第二项：整理内容运营规范' }] };
state.roomId = queued.id; state.view = 'room'; sandbox.renderComposer = () => {};
const beforeQueue = JSON.stringify(queued);
call('renderRoom', queued);
assert.equal($('conversation-title').textContent, '第二项：整理内容运营规范');
assert.equal($('conversation-mode').textContent, '方案已确认 · 等待组建任务群');
assert.equal($('members').textContent, '主 Agent · 等待组群');
assert.doesNotMatch($('members').textContent, /软件|前端|设计师|已完成|分派中/);
assert.match($('feed').textContent, /做一个界面.*真实前端结果正文.*第二项：整理内容运营规范/);
assert.equal($('feed').children[0].children.filter((node) => node.className === 'ag-task-group').length, 1);
assert.doesNotMatch($('feed').textContent, /加入任务群/, 'No invitation event is fabricated during queueing');
assert.equal(JSON.stringify(queued), beforeQueue, 'Queue display does not rewrite recorded groups or events');
call('renderRoom', { ...queued, messages, proposals: [{ id: 'queued-proposal', status: 'confirmed', confirmed_job_id: 'content-round' }] });
assert.equal($('conversation-title').textContent, '正在组建任务群', 'Missing queued message must not reuse the previous task title');
const started = { ...queued, status: 'running', current_task_group_id: 'content-round', task_groups: [firstGroup,
  { id: 'content-round', round_id: 'content-round', title: '整理内容运营规范', status: 'running', members: ['central', 'content'] }] };
call('renderRoom', started);
assert.equal($('conversation-title').textContent, '整理内容运营规范');
assert.equal($('conversation-mode').textContent, '当前任务成员');
assert.match($('members').textContent, /主 Agent.*content/);
assert.doesNotMatch($('members').textContent, /等待组群|软件|前端/);

// Ordinary questions and proposal discussion never inherit an earlier execution group's
// title or members, including the queued period immediately after a new user message.
const discussion = { ...queued, status: 'idle', active_job_id: null, proposals: [],
  messages: [...messages, { id: 'question', role: 'user', round_id: 'discussion', phase: 'consultation', content: '前端是什么？' },
    { id: 'answer', role: 'assistant', agent_id: 'central', round_id: 'discussion', phase: 'consultation', content: '前端是用户直接使用的界面部分。' }] };
call('renderRoom', discussion);
assert.equal($('conversation-title').textContent, '主 Agent');
assert.equal($('members').textContent, '主 Agent');
assert.equal($('conversation-mode').textContent, '先聊需求，方案确认后开始协作');
assert.match($('feed').textContent, /前端是用户直接使用的界面部分/);
assert.equal($('feed').children[0].children.filter((node) => node.className === 'ag-task-group').length, 1, 'Only the already-recorded previous task group remains');
call('renderRoom', { ...discussion, status: 'queued', active_job_id: 'discussion' });
assert.equal($('conversation-title').textContent, '主 Agent');
assert.equal($('members').textContent, '主 Agent · 等待回复');
assert.doesNotMatch($('members').textContent, /组群|软件|前端/);
call('renderMessages', { ...discussion, task_groups: [], delegations: [], messages: discussion.messages.slice(-2) });
assert.doesNotMatch($('feed').textContent, /任务群|分工详情|分派任务|加入任务群/);

// Proposal cards are bound to a real stored proposal and display the whole safe text.
const proposal = { id: 'proposal-one', title: '产品方案 <img src=x>', goal: '做一个项目', content: '调研依据\n第一步：核对目标。\n第二步：确认范围。\n<script>示例</script>',
  status: 'awaiting_confirmation', message_id: 'proposal-message' };
const proposalMessage = { id: 'proposal-message', role: 'assistant', agent_id: 'central', phase: 'proposal', proposal_id: proposal.id, round_id: 'discussion', content: '模型方案正文' };
const proposalRoom = { ...discussion, status: 'idle', active_proposal_id: proposal.id, proposals: [proposal], messages: [...discussion.messages.slice(0, -1), proposalMessage] };
state.roomId = proposalRoom.id; state.room = proposalRoom; state.view = 'room';
call('renderRoom', proposalRoom);
assert.equal($('conversation-title').textContent, '主 Agent'); assert.equal($('conversation-mode').textContent, '方案待确认');
let proposalCard = walk($('feed')).find((node) => node.className === 'ag-proposal-card');
assert.match(proposalCard.textContent, /待确认.*调研依据.*第一步.*第二步.*<script>示例<\/script>/s);
assert.ok(!walk(proposalCard).some((node) => ['img', 'script'].includes(node.tagName)));
let confirmButton = walk(proposalCard).find((node) => node.tagName === 'button');
assert.equal(confirmButton.textContent, '确认方案并开始协作'); assert.equal(confirmButton.disabled, false);
assert.equal($('feed').children[0].children.filter((node) => node.className === 'ag-task-group').length, 1, 'Proposal does not create a new execution group');
call('renderMessages', { ...proposalRoom, messages: [{ ...proposalMessage, id: 'forged-message' }] });
assert.ok(!walk($('feed')).some((node) => node.className === 'ag-proposal-card'), 'A mismatched message cannot expose stored proposal controls');
call('renderMessages', { ...proposalRoom, proposals: [] });
assert.ok(!walk($('feed')).some((node) => node.className === 'ag-proposal-card'), 'Model text alone is never treated as a confirmable proposal');

const confirmRequests = [], confirmNotices = []; let finishConfirmation;
Object.assign(sandbox, { notice: (text) => confirmNotices.push(text), upsertRoom() {}, schedulePoll() {},
  api: (path, options) => { confirmRequests.push({ path, body: JSON.parse(options.body) }); return new Promise((resolve) => { finishConfirmation = resolve; }); } });
state.room = proposalRoom; state.roomId = proposalRoom.id; $('message').value = '保留的修改意见草稿'; $('learning').checked = true;
call('renderRoom', proposalRoom);
const confirming = call('confirmProposal', proposal.id);
assert.equal(state.sending.has(proposalRoom.id), true);
proposalCard = walk($('feed')).find((node) => node.className === 'ag-proposal-card');
assert.equal(walk(proposalCard).find((node) => node.tagName === 'button').disabled, true);
await call('confirmProposal', proposal.id); assert.equal(confirmRequests.length, 1, 'Repeated click cannot submit twice');
assert.deepEqual(confirmRequests[0].body, { content: '确认方案并开始协作', confirm_proposal_id: proposal.id }, 'Confirmation cannot silently change approved learning options or include unsent draft text');
const confirmedRoom = { ...proposalRoom, status: 'queued', active_job_id: 'confirmed-round', proposals: [{ ...proposal, status: 'confirmed', confirmed_job_id: 'confirmed-round' }],
  messages: [...proposalRoom.messages, { id: 'confirm-message', role: 'user', phase: 'confirmation', proposal_id: proposal.id, round_id: 'confirmed-round', content: '确认方案并开始协作' }] };
finishConfirmation({ room: confirmedRoom }); await confirming;
assert.equal($('message').value, '保留的修改意见草稿');
assert.equal(state.drafts.get(proposalRoom.id), '保留的修改意见草稿');
assert.equal(state.sending.has(proposalRoom.id), false);
assert.equal($('members').textContent, '主 Agent · 等待组群');
assert.equal($('conversation-title').textContent, proposal.title);
proposalCard = walk($('feed')).find((node) => node.className === 'ag-proposal-card');
assert.match(proposalCard.textContent, /已确认/); assert.ok(!walk(proposalCard).some((node) => node.tagName === 'button'));

const supersededRoom = { ...proposalRoom, active_proposal_id: 'new-proposal', proposals: [{ ...proposal, status: 'superseded' }] };
call('renderRoom', supersededRoom);
proposalCard = walk($('feed')).find((node) => node.className === 'ag-proposal-card');
assert.match(proposalCard.textContent, /已更新.*不能再确认/s); assert.ok(!walk(proposalCard).some((node) => node.tagName === 'button'));
await call('confirmProposal', proposal.id); await call('confirmProposal', 'fabricated-proposal');
assert.equal(confirmRequests.length, 1); assert.match(confirmNotices.at(-1), /已更新或已确认/);
call('renderMessages', { ...proposalRoom, active_proposal_id: 'newer-active' });
assert.ok(!walk($('feed')).some((node) => node.tagName === 'button' && /确认方案并开始协作/.test(node.textContent)), 'A no-longer-active pending proposal is also not confirmable');

// Actual proposal research is rendered from its independent host receipt, never the
// model's claimed citations, and unavailable or skipped attempts remain visible.
const research = { run_id: 'a'.repeat(32), status: 'partial', scope: 'proposal-only', note: '只读取了本轮列出的网页，市场数据仍待核实。',
  sources: [{ title: '官方说明 <img src=x>', url: 'https://example.com/guide?q=1', sha256: 'b'.repeat(64), excerpt_sha256: 'c'.repeat(64),
    fetched_at: '2026-10-03T12:00:00Z', truncated: true, path: 'research-runs/recorded/1.md' }],
  errors: [{ url: 'https://example.com/blocked', error: 'robots 检查失败 <script>unsafe</script>' }] };
assert.equal(call('renderResearchReceipt', {}, 'absent'), null);
assert.equal(call('renderResearchReceipt', { research: {} }, 'empty-object'), null);
assert.equal(call('renderResearchReceipt', { research: [] }, 'wrong-schema'), null);
const researchReceipt = call('renderResearchReceipt', { research }, 'research-message');
assert.equal(researchReceipt.tagName, 'details'); assert.equal(researchReceipt.open, false);
assert.match(researchReceipt.children[0].textContent, /本轮调研来源.*部分资料读取成功.*1 项来源/);
assert.match(researchReceipt.textContent, /市场数据仍待核实.*官方说明.*摘录.*正文 SHA-256.*摘录 SHA-256.*记录文件.*robots 检查失败/s);
assert.match(researchReceipt.textContent, /不代表方案每条结论都获得支持/);
const actualLink = walk(researchReceipt).find((node) => node.tagName === 'a');
assert.equal(actualLink.href, 'https://example.com/guide?q=1'); assert.equal(actualLink.rel, 'noopener noreferrer');
assert.equal(actualLink.target, '_blank'); assert.equal(actualLink.textContent, actualLink.href);
assert.ok(!walk(researchReceipt).some((node) => ['img', 'script'].includes(node.tagName)));
const hashDetails = walk(researchReceipt).find((node) => node.className?.includes('ag-research-hashes'));
assert.equal(hashDetails.open, false); assert.match(hashDetails.textContent, new RegExp('b'.repeat(64)));
researchReceipt.isConnected = true; researchReceipt.open = true; researchReceipt.listeners.toggle();
assert.equal(call('renderResearchReceipt', { research }, 'research-message').open, true);
assert.equal(call('renderResearchReceipt', { research }, 'other-message').open, false);
for (const unsafeURL of ['javascript:alert(1)', 'file:///private/path', 'https://user:pass@example.com/', 'https://example.com/\nunsafe']) {
  const rendered = call('renderResearchReceipt', { research: { ...research, sources: [{ title: '不应成为链接', url: unsafeURL }] } }, 'unsafe-url');
  assert.equal(walk(rendered).filter((node) => node.tagName === 'a').length, 0);
}
const noRecordedPath = call('renderResearchReceipt', { research: { ...research, sources: [{ title: '无文件路径', url: 'https://example.com/source', sha256: 'd'.repeat(64) }] } }, 'no-path');
assert.doesNotMatch(noRecordedPath.textContent, /记录文件|research-runs|report\.json/, 'Internal paths must not be inferred from a run ID');
for (const [status, label] of [['completed', '公开资料读取完成'], ['partial', '部分资料读取成功']]) {
  assert.match(call('renderResearchReceipt', { research: { ...research, status } }, status).children[0].textContent, new RegExp(label));
}
for (const [status, label] of [['unavailable', '未成功读取资料'], ['not_researched', '未进行联网调研'], ['completed', '未成功读取资料']]) {
  const rendered = call('renderResearchReceipt', { research: { status, sources: [], errors: ['受控错误'], note: '本轮不声称已完成调研。' } }, status);
  assert.match(rendered.children[0].textContent, new RegExp(label)); assert.match(rendered.textContent, /受控错误/);
  assert.match(rendered.textContent, /没有成功读取并记录的网页来源/);
}
call('renderMessages', { ...proposalRoom, messages: [{ ...proposalMessage, research, content: '[Wiki:/index.md + run_inputs] 这是模型声称的来源。' }] });
assert.equal(walk($('feed')).filter((node) => node.className?.includes('ag-research-receipt')).length, 0);
assert.doesNotMatch($('feed').textContent, /正文 SHA-256|本轮调研来源|回复详情/);
call('renderMessages', { ...proposalRoom, messages: [{ role: 'assistant', agent_id: 'central', content: '声称已查来源 https://example.com/fake' }] });
assert.equal(walk($('feed')).filter((node) => node.className?.includes('ag-research-receipt')).length, 0);
call('renderMessages', { ...proposalRoom, messages: [{ role: 'user', content: '用户粘贴的记录', research }] });
assert.equal(walk($('feed')).filter((node) => node.className?.includes('ag-research-receipt')).length, 0);

// The confirmation card discloses only persisted learning scope, not the live checkbox.
$('learning').checked = false; $('learning-pages').value = '1';
const learningProposal = call('renderProposal', { ...proposal, execution_options: { learning: true, max_pages: 3 } }, proposalRoom);
assert.match(learningProposal.textContent, /确认后将采集资料并更新所选子库草稿；每个成员最多 3 页；不自动发布/);
$('learning').checked = true; $('learning-pages').value = '5';
const ordinaryProposal = call('renderProposal', { ...proposal, execution_options: { learning: false, max_pages: 3 } }, proposalRoom);
assert.doesNotMatch(ordinaryProposal.textContent, /每个成员最多|更新所选子库草稿/);

// POST primary is the only opening action; backend owns idempotency. No creation screen.
const requests = [], notices = [];
const primary = { id: 'fixed-primary', purpose: 'primary', title: '主 Agent', mode: 'orchestrated', status: 'idle', participants: ['central'], messages: [], task_groups: [] };
Object.assign(sandbox, { viewStorage: Promise.resolve(), refreshDirectory: async () => {}, schedulePoll() {}, notice: (message) => notices.push(message),
  upsertRoom: (value) => { if (!state.rooms.some((item) => item.id === value.id)) state.rooms.push(value); },
  renderComposer: () => { $('message').disabled = !state.room; },
  api: async (path, options) => { requests.push({ path, options }); assert.equal(path, '/api/chat/primary'); assert.equal(options.method, 'POST'); return primary; } });
vm.runInContext(['selectRoom', 'openMainChat'].map(extract).join('\n'), sandbox);
state.rooms = [{ id: 'old-direct', mode: 'direct' }, { id: 'old-auto', mode: 'orchestrated' }];
state.room = { id: 'old-direct' }; state.roomId = 'old-direct'; state.view = 'room'; state.preferredRoomId = 'old-direct';
$('message').value = '历史草稿'; $('feed').scrollTop = 72;
await call('openMainChat');
assert.equal(state.roomId, 'fixed-primary'); assert.equal(state.primaryRoomId, 'fixed-primary');
assert.equal(state.drafts.get('old-direct'), '历史草稿'); assert.equal(state.feedPositions.get('old-direct'), 72);
assert.equal($('message').disabled, false); assert.equal($('return-primary').hidden, true);
assert.equal($('conversation-mode').textContent, '先聊需求，方案确认后开始协作');
assert.match($('feed').textContent, /一次聊一个点/);
$('message').value = '固定入口草稿'; $('feed').scrollTop = 91;
await call('openMainChat');
assert.equal(state.roomId, 'fixed-primary'); assert.equal($('message').value, '固定入口草稿'); assert.equal($('feed').scrollTop, 91);
assert.equal(requests.length, 2); assert.equal(state.rooms.length, 3, 'Idempotent entry preserves all old rooms without duplicating primary');
assert.ok(notices.every((message) => !message));

// Historical direct/group conversations remain accessible, with an explicit return action.
await call('selectRoom', 'old-direct', { id: 'old-direct', mode: 'direct', title: '保留的前端会话', status: 'idle', participants: ['software-frontend'], messages: [{ role: 'assistant', agent_id: 'software-frontend', content: '原来的回复' }] });
assert.equal($('return-primary').hidden, false); assert.equal($('message').value, '历史草稿');
assert.match($('conversation-mode').textContent, /历史记录/); assert.match($('feed').textContent, /原来的回复/);
await call('openMainChat'); assert.equal($('message').value, '固定入口草稿');

// A closed dialog or newer entry invalidates a delayed POST result.
let resolveDelayed;
sandbox.api = () => new Promise((resolve) => { resolveDelayed = resolve; });
const pending = call('openMainChat');
await new Promise(resolve => setImmediate(resolve)); // Hydrate server drafts before the primary-room POST.
$('dialog').close(); state.epoch++;
resolveDelayed({ ...primary, id: 'must-not-adopt' }); await pending;
assert.notEqual(state.primaryRoomId, 'must-not-adopt');
sandbox.api = async () => { throw new Error('离线'); };
await call('openMainChat');
assert.match(notices.at(-1), /离线.*返回主 Agent/); assert.equal($('return-primary').hidden, false);
assert.equal($('message').disabled, true);
console.log('Primary Agent UI passed: discussion without automatic groups, stored proposal review/confirmation and supersession, duplicate-click guard, approved-options and draft preservation, queued/member isolation, final-answer jump, fixed entry/history, safe text, polling and opening races.');

// Completion metadata never returns technical panels to the visible feed.
const cleanReply={id:'clean',role:'assistant',agent_id:'central',content:'已读资料后的完整回复。',status:'completed',
 wiki_reads:[{path:'/index.md',sha256:'a'.repeat(64)}],template_reads:[{path:'/template.md',sha256:'a'.repeat(64)}],
 skill_reads:[{path:'/skill.md',sha256:'a'.repeat(64)}],context_usage:{enabled:true,total_calls:2},
 wiki_citation_check:{status:'no_citations'},answer_check:{status:'corrected_with_limits'},
 interim_replies:[{id:'audit-before-check',title:'先前回答（校对前）',text:'诊断草稿',status:'completed'}],
 workflow:{gaps:['技术缺口'],receipts:[{call_id:'real-search',tool:'web_search',status:'completed',args:{query:'资料主题'},elapsed_ms:1200}]}};
const storedReply=JSON.stringify(cleanReply);
call('renderMessages',{id:'clean-room',mode:'direct',messages:[cleanReply]},true);
assert.match($('feed').textContent,/完整回复/);
assert.match($('feed').textContent,/已搜索公开资料.*资料主题/);
assert.doesNotMatch($('feed').textContent,/回复详情|资料预读|本轮上下文|引用核对|技术缺口|诊断草稿|template\.md|skill\.md/);
assert.equal(JSON.stringify(cleanReply),storedReply,'Presentation filtering does not mutate stored receipts');
assert.equal(call('replyOperations',cleanReply).length,1,'Only actual actions are visible');
assert.equal(call('validInterimReplies',cleanReply.interim_replies).length,0);
console.log('Clean chat completion preserves actual tool operations and stored metadata, without technical panels.');

// Old task cards stay with their historical messages instead of being appended
// below the latest answer when the server sends only the current window.
const windowed = {id:'windowed', mode:'orchestrated', status:'idle', message_offset:100,
  task_groups:[firstGroup], messages:[{id:'recent',role:'user',content:'当前对话',round_id:'new-round'}]};
call('renderMessages', windowed, true);
assert.doesNotMatch($('feed').textContent, /做一个界面/);
assert.match($('feed').textContent, /查看更早的对话.*100.*当前对话/);
call('renderMessages', {...windowed, message_offset:0}, true);
assert.match($('feed').textContent, /做一个界面/);

// Actual old receipts gain safe, precise reasons without changing stored history.
const failedReads={...cleanReply,id:'reader-failures',operations:[
 {call_id:'search',name:'web_search',status:'completed',target:'公开资料'},
 {call_id:'zhihu',name:'web_read',status:'unavailable',target:'https://zhuanlan.zhihu.com/p/123'},
 {call_id:'baidu',name:'web_read',status:'unavailable',target:'https://ailegal.baidu.com/page'},
 {call_id:'readable',name:'web_read',status:'completed',target:'https://www.36kr.com/page'}],workflow:{
 receipts:[{call_id:'search',tool:'web_search'},{call_id:'zhihu',tool:'web_read'},{call_id:'baidu',tool:'web_read'},{call_id:'readable',tool:'web_read'}],
 observations:[{result:{status:'completed'}},{result:{status:'unavailable',errors:[{error:'该网页的 robots.txt 不允许自动采集 secret=PRIVATE'}]}},
 {result:{status:'unavailable',errors:[{error:'未提取到足够的可读正文；页面可能需要登录或执行脚本'}]}},{result:{status:'completed'}}]}};
const originalFailure=JSON.stringify(failedReads),failureView=call('renderOperations',failedReads,'read-failure',{inline:true});
assert.match(failureView.textContent,/已搜索公开资料.*网站禁止自动读取.*未读到网页正文.*已读取网页/);
assert.doesNotMatch(failureView.textContent,/未取得结果|需要登录|secret|PRIVATE/);
assert.equal(JSON.stringify(failedReads),originalFailure);
const liveFailure=call('renderOperations',{operations:[{call_id:'live-read',name:'web_read',status:'robots_blocked'}]},'live',{inline:true});
assert.match(liveFailure.textContent,/网站禁止自动读取/);
console.log('Public reader UI: historical and live causes, no raw errors or history mutation.');
