/** Knowledge-health UI contract checks; no network, wiki writes or publication. */
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const source = fs.readFileSync(new URL('../federation/web/federation-controls.js', import.meta.url), 'utf8');
function extractFunction(name) {
  const start = source.search(new RegExp(`  (?:async )?function ${name}\\(`));
  assert.ok(start >= 0, name);
  return source.slice(start, source.indexOf('\n  }', start) + 4);
}
class Element {
  constructor(tag = 'div') {
    this.tagName = tag; this.children = []; this.listeners = {}; this.attributes = {}; this.dataset = {}; this.value = '';
    this.hidden = false; this.disabled = false; this.open = false; this._text = '';
    const classes = new Set();
    this.classList = { add: (key) => classes.add(key), remove: (key) => classes.delete(key), contains: (key) => classes.has(key),
      toggle(key, enabled) { if (enabled) classes.add(key); else classes.delete(key); } };
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map((item) => item.textContent).join(''); }
  set innerHTML(_) { throw new Error('Dynamic HTML is forbidden'); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this._text = ''; this.children = children; }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  get childNodes() { return this.children; }
  get childElementCount() { return this.children.length; }
  querySelectorAll() { return []; }
}
const nodes = new Map(), pending = [], sourceLoads = [], reviewLoads = [];
const $ = (id) => { if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id); };
const make = (tag, className, text) => { const node = new Element(tag); node.className = className || ''; if (text !== undefined) node.textContent = text; return node; };
const walk = (node) => [node, ...node.children.flatMap(walk)];
const definitions = { central: { id: 'central', name: '中央知识库', knowledge_count: 4 }, frontend: { id: 'frontend', name: '前端', parent_id: 'central', source_count: 2, knowledge_count: 4 }, uiux: { id: 'uiux', name: 'UI/UX 设计师', parent_id: 'central', knowledge_count: 1 } };
const state = { selected: 'frontend', tab: 'health', knowledgeRevision: 0, revision: 0, reviewRevision: 0, review: null,
  visited: new Set(), drafts: new Map(), data: { central: definitions.central, branches: [definitions.frontend, definitions.uiux] } };
const sandbox = { state, $, make, URL, Number, String, Object, Array, Set, JSON,
  space: (id = state.selected) => definitions[id], number: (value) => Number(value) || 0,
  knowledge: (item) => item?.knowledge_count || 0, activeJob: () => null, breadcrumb: (item) => item.name,
  manage: new Element('button'), notify() {}, saveDraft() {}, restoreDraft() {}, renderJob() {}, renderAnswers() {},
  loadSources: async () => sourceLoads.push(state.selected), loadReview: async () => reviewLoads.push(state.selected),
  api: (path) => new Promise((resolve, reject) => pending.push({ path, resolve, reject })),
};
vm.createContext(sandbox);
vm.runInContext(['knowledgeSourceURL', 'knowledgeReasonText', 'renderKnowledgeEvidence', 'renderKnowledgeHealth', 'loadKnowledgeHealth',
  'renderTabs', 'renderHeader', 'selectSpace', 'renderReviewKnowledge'].map(extractFunction).join('\n'), sandbox);
const call = (name, ...args) => sandbox[name](...args);

for (const value of ['javascript:alert(1)', 'data:text/html,hello', 'file:///tmp/a', 'https://user:secret@example.org/', 'https://example.org/a b', 'https://example.org/\u0000a']) assert.equal(call('knowledgeSourceURL', value), null, value);
assert.equal(call('knowledgeSourceURL', 'https://www.w3.org/WAI/'), 'https://www.w3.org/WAI/');
assert.equal(call('knowledgeSourceURL', 'http://example.invalid/doc'), 'http://example.invalid/doc');
assert.equal(call('knowledgeReasonText', 'source_version_changed'), '当前来源版本与学习时记录的版本不同');
assert.equal(call('knowledgeReasonText', { code: 'no_learning_record' }), '没有学习追溯记录（历史页面未自动认定为已追溯）');
assert.equal(call('knowledgeReasonText', { message: '<img src=x>', code: 'source_missing' }), '<img src=x>');
assert.equal(call('knowledgeReasonText', 'future_reason'), 'future_reason');

const evidence = { source_id: 'source:stable-001', version: 'a'.repeat(64), name: '<img src=x onerror=bad()>',
  kind: 'web', space_id: 'frontend', status: 'current', freshness: 'current', checked_at: '2026-10-03T10:00:00Z',
  url: 'https://example.invalid/docs', current_version: 'a'.repeat(64), relation: 'run_inputs' };
const pages = [
  { path: 'concepts/current.md', page_id: 'page:stable-001', version: 'b'.repeat(64), title: '已记录示例', status: 'current', reasons: [], evidence: [evidence] },
  { path: 'concepts/stale.md', page_id: 'page:stable-002', version: 'c'.repeat(64), title: '待更新示例', status: 'stale', reasons: ['source_version_changed'],
    evidence: [{ ...evidence, version: 'd'.repeat(64), current_version: 'e'.repeat(64), status: 'changed', reasons: ['source_version_changed'] }] },
  { path: 'concepts/legacy.md', page_id: 'page:stable-003', version: 'f'.repeat(64), title: '历史页面', status: 'untracked', reasons: ['no_learning_record'], evidence: [] },
  { path: 'concepts/review.md', page_id: 'page:stable-004', version: '0'.repeat(64), title: '待复核示例', status: 'review_due', reasons: ['source_check_time_unknown'],
    evidence: [{ ...evidence, checked_at: null, freshness: 'unknown', status: 'available', url: 'javascript:bad()' }] },
];
const data = { schema_version: 1, space_id: 'frontend', summary: { total: 4, current: 1, stale: 1, untracked: 1, review_due: 1 }, pages,
  sources: [evidence], checked_at: '2026-10-03T10:01:00Z' };
call('renderKnowledgeHealth', data);
assert.deepEqual($('health-summary').children.map((item) => item.textContent), ['4全部页面', '1已记录', '1待更新', '1未追溯', '1待复核']);
assert.equal($('health-pages').children.length, 4);
assert.match($('health-pages').textContent, /page:stable-001.*b{64}.*来源 ID：source:stable-001.*a{64}/);
assert.match($('health-pages').textContent, /当前来源版本与学习时记录的版本不同.*来源版本已变化.*来源版本 SHA-256：d{64}.*当前来源版本 SHA-256：e{64}/);
assert.match($('health-pages').textContent, /历史页面未自动认定为已追溯/);
assert.match($('health-pages').textContent, /来源核查日期未记录，需要复核/);
assert.match($('health-status').textContent, /前端.*状态快照.*2026-10-03T10:01:00Z/);
const rendered = walk($('health-pages'));
assert.ok(!rendered.some((item) => ['img', 'script', 'iframe'].includes(item.tagName)));
assert.match($('health-pages').textContent, /<img src=x onerror=bad\(\)>/);
const links = rendered.filter((item) => item.tagName === 'a');
assert.equal(links.length, 2);
assert.ok(links.every((item) => item.href === 'https://example.invalid/docs' && item.rel === 'noopener noreferrer'));
assert.ok(rendered.some((item) => item.tagName === 'span' && item.textContent === 'javascript:bad()'));
assert.match(source, /run_inputs 只代表该次学习的输入资料，不证明页面每条结论/);
assert.match(source, /不代表内容事实正确，也不代表已核实互联网上的最新版本/);

call('renderKnowledgeHealth', { space_id: 'frontend', pages: [{ title: '未知状态页', status: 'future_status' }], sources: [] });
assert.match($('health-pages').textContent, /未知状态页未追溯/);
assert.deepEqual($('health-summary').children.map((item) => item.textContent), ['1全部页面', '0已记录', '0待更新', '1未追溯', '0待复核']);
call('renderKnowledgeHealth', { space_id: 'frontend', pages: [], sources: [] });
assert.match($('health-pages').textContent, /还没有知识页面/);
assert.match($('health-source-list').textContent, /没有已记录的来源/);
call('renderKnowledgeHealth', { ...data, metadata_error: '<script>损坏记录</script>' });
assert.match($('health-status').textContent, /追溯记录异常：<script>损坏记录<\/script>/);
assert.equal($('health-status').classList.contains('error'), true);
call('renderReviewKnowledge', { summary: data.summary, pages });
assert.match($('review-health-summary').textContent, /已记录 1 页 · 待更新 1 页 · 未追溯 1 页 · 待复核 1 页/);
assert.match($('review-health-note').textContent, /请查看知识状态后结合正文审核/);
assert.equal($('publish').disabled, false, 'The provenance summary does not add a publication gate');
call('renderReviewKnowledge', { summary: { current: 4, stale: 0, untracked: 0, review_due: 0 } });
assert.match($('review-health-note').textContent, /事实仍需人工核对/);
call('renderReviewKnowledge', undefined);
assert.match($('review-health-summary').textContent, /没有可展示的知识追溯统计/);
assert.match($('review-health-note').textContent, /缺少追溯不自动认定为版本一致/);

// The tabs preserve source-management/review behavior, and health is available centrally.
$('dialog').open = true; call('renderTabs');
assert.deepEqual($('tabs').children.map((item) => item.textContent), ['资料', '分支提问', '知识状态', '审核发布']);
await $('tabs').children.find((item) => item.textContent === '资料').listeners.click();
assert.deepEqual(sourceLoads, ['frontend']);
await $('tabs').children.find((item) => item.textContent === '审核发布').listeners.click();
assert.deepEqual(reviewLoads, ['frontend']);
state.selected = 'central'; state.tab = 'health'; call('renderHeader');
assert.equal(state.tab, 'health');
assert.deepEqual($('tabs').children.map((item) => item.textContent), ['跨行业提问', '知识状态']);
assert.equal($('health-panel').hidden, false); assert.equal($('review-panel').hidden, true);
assert.equal(pending.length, 0, 'Rendering headers or tabs never reads knowledge-health by itself');

// Switching Agents starts a fresh bounded request; an older response cannot overwrite it.
state.selected = 'frontend'; state.tab = 'health';
const oldRequest = call('loadKnowledgeHealth');
assert.equal(pending[0].path, '/api/spaces/frontend/knowledge-health');
const newRequest = call('selectSpace', 'uiux');
assert.equal(pending[1].path, '/api/spaces/uiux/knowledge-health');
assert.equal(state.tab, 'health'); assert.equal(sourceLoads.length, 1, 'Health selection does not also load sources');
pending[1].resolve({ ...data, space_id: 'uiux', pages: [{ ...pages[0], title: '设计师的页面' }] }); await newRequest;
pending[0].resolve(data); await oldRequest;
assert.match($('health-pages').textContent, /设计师的页面/);
assert.doesNotMatch($('health-pages').textContent, /待更新示例/);
assert.equal($('health-reload').disabled, false);
call('renderHeader'); call('renderHeader');
assert.equal(pending.length, 2, 'Polling-driven header refresh does not refetch knowledge state');
assert.doesNotMatch(extractFunction('poll'), /loadKnowledgeHealth/);

const wrong = call('loadKnowledgeHealth'); pending[2].resolve(data); await wrong;
assert.match($('health-status').textContent, /与当前知识库不一致/);
assert.equal($('health-status').classList.contains('error'), true);
assert.equal($('health-pages').children.length, 0);
const failed = call('loadKnowledgeHealth'); pending[3].reject(new Error('来源读取失败')); await failed;
assert.match($('health-status').textContent, /来源读取失败/); assert.equal($('health-reload').disabled, false);
const closed = call('loadKnowledgeHealth'); $('dialog').open = false;
pending[4].resolve({ ...data, space_id: 'uiux' }); await closed;
assert.equal($('health-pages').children.length, 0, 'Closed panel ignores response');
$('dialog').open = true; state.tab = 'health';
const otherTab = call('loadKnowledgeHealth'); state.tab = 'review';
pending[5].resolve({ ...data, space_id: 'uiux' }); await otherTab;
assert.equal($('health-pages').children.length, 0, 'A response arriving after another tab is selected is ignored');
console.log('Knowledge UI checks passed: four truthful states, full IDs/versions and source changes, safe links/text, legacy/empty/error states, original source/review tabs, central access, on-demand requests and Agent/tab/close races.');

// Chat exposes the same evidence boundary without conflating citations and facts.
const chatSource = fs.readFileSync(new URL('../federation/web/agent-chat.js', import.meta.url), 'utf8');
function extractChat(name) {
  const start = chatSource.search(new RegExp(`  (?:async )?function ${name}\\(`));
  assert.ok(start >= 0, name);
  return chatSource.slice(start, chatSource.indexOf('\n  }', start) + 4);
}
const chatState = { taskExpanded: new Map(), feedSignature: '' };
const chatSandbox = { state: chatState, $, make, URL, Number, String, Object, Array, Set, Map, JSON,
  count: (value) => Number.isFinite(Number(value)) ? Number(value) : 0,
  agentName: (id) => definitions[id]?.name || id || 'Agent', agent: (id) => definitions[id], depth: () => 1,
  persistView() {}, renderContextUsage: () => null, date: String, document: { activeElement: null, createDocumentFragment: () => new Element('fragment') } };
vm.createContext(chatSandbox);
vm.runInContext(chatSource.match(/^  const active = .*$/m)[0], chatSandbox);
vm.runInContext(['markdownBody', 'rememberDetails', 'publicSourceURL', 'renderWikiReads', 'renderTemplateReads', 'renderLearningReceipt', 'taskStatus', 'renderDelegations', 'renderReportArtifacts', 'validInterimReplies', 'renderInterimReplies', 'renderReportCheck', 'mergeReplyMessages', 'questionLanguage','turnLanguage','conversationMessages', 'operationTarget','operationReadFailure','operationFailureDetail','replyOperations','renderOperations','validReplyTimeline','replyTimeline','recordReplyTimeline','renderUnplacedOperations','replyStageLabel', 'processingLabel', 'isNativeReply', 'renderReplyLoading', 'contextAdjustment','renderReplyBody', 'renderMessages'].map(extractChat).join('\n'), chatSandbox);
const chatCall = (name, ...args) => chatSandbox[name](...args);
const wikiRead = { agent_id: 'frontend', path: '/concepts/current.md', sha256: 'a'.repeat(64), hash_scope: 'excerpt',
  page_id: 'page:stable-001', page_version: 'b'.repeat(64), knowledge_status: 'current', reasons: [],
  truncated: true, citation_label: '[Wiki: /concepts/current.md]', sources: [evidence] };
const check = { status: 'valid', citation_count: 1, invalid_count: 0, citations: [{ path: '/concepts/current.md', valid: true }] };
const claimReceipt=chatCall('renderWikiReads',{wiki_reads:[{...wikiRead,claims:[{text:'<script>结论</script>',
  semantic_review:'pending',status:'current',references:[{title:'原文标题',quote:'<img src=x onerror=bad()>',
    url:'javascript:bad()',freshness:'local_only',start_line:7,quote_truncated:true}]}]}]},'claim-proof');
assert.match(claimReceipt.textContent,/含义待核对.*<script>结论<\/script>.*<img src=x onerror=bad\(\)>.*原文第 7 行.*本地归档.*片段已截短/);
assert.ok(!walk(claimReceipt).some(item=>['img','script'].includes(item.tagName)));
assert.ok(!walk(claimReceipt).some(item=>item.tagName==='a'&&item.href==='javascript:bad()'));
const receipt = chatCall('renderWikiReads', { agent_id: 'frontend', wiki_reads: [wikiRead], wiki_citation_check: check }, 'direct');
const assessedReceipt = chatCall('renderWikiReads', {wiki_reads:[wikiRead,{...wikiRead,path:'/omitted.md'}],
  wiki_input:{inputs:[{path:wikiRead.path,excerpt_sha256:'f'.repeat(64),truncated:true}]},
  timing:{request_first_text_ms:1200,request_to_answer_ms:4200},
  answer_check:{status:'corrected_with_limits',checks:[{status:'contradicted',reason:'<script>含义漂移</script>',
    references:[{path:wikiRead.path,quote:'<img src=x onerror=bad()>'}]}]}}
  ,'assessed');
assert.match(assessedReceipt.textContent,/宿主预读 2 页；预算后实际提供 1 页正文.*本轮已补充纠正.*与材料矛盾.*<script>含义漂移<\/script>.*<img src=x onerror=bad\(\)>.*首段回复 1.20 秒.*完成 4.20 秒/);
assert.match(assessedReceipt.textContent,/实际输入摘录 SHA-256：f{64}.*片段已裁剪.*预算后未提供正文/);
assert.ok(!walk(assessedReceipt).some(item=>['img','script'].includes(item.tagName)));
assert.equal(receipt.open, false);
assert.match(receipt.textContent, /前端 · 引用路径匹配.*引用标记 1 个 · 未匹配 0 个.*前端 · \/concepts\/current.md · 已记录/);
assert.match(receipt.textContent, /页面 ID：page:stable-001.*完整页面 SHA-256：b{64}.*读取回执 SHA-256：a{64} · excerpt/);
assert.match(receipt.textContent, /本轮提供的是页面摘录，不能据此声称已读全文/);
assert.match(receipt.textContent, /只检查标记是否匹配本轮已记录的预读路径，不评判事实正确/);
assert.match(receipt.textContent, /run_inputs 只代表学习输入/);
assert.ok(!walk(receipt).some((item) => ['img', 'script'].includes(item.tagName)));
assert.equal(walk(receipt).find((item) => item.tagName === 'a').href, 'https://example.invalid/docs');
receipt.isConnected = true; receipt.open = true; receipt.listeners.toggle();
assert.equal(chatCall('renderWikiReads', { wiki_reads: [wikiRead] }, 'direct').open, true);
assert.equal(chatCall('renderWikiReads', { wiki_reads: [wikiRead] }, 'other').open, false);
assert.equal(chatCall('renderWikiReads', {}, 'legacy'), null);
assert.equal(chatCall('renderWikiReads', { wiki_reads: [null, {}], wiki_citation_check: {} }, 'malformed'), null);
const legacyRead = chatCall('renderWikiReads', { wiki_reads: [{ path: '/legacy.md', sha256: 'c'.repeat(64) }] }, 'legacy-read');
assert.match(legacyRead.textContent, /\/legacy.md · 未追溯.*页面 ID：未记录/);
const aggregated = { agent_id: 'central', wiki_reads: [wikiRead, { ...wikiRead, agent_id: 'uiux', knowledge_status: 'review_due', sources: [] }],
  wiki_citation_checks: [{ ...check, agent_id: 'frontend', phase: 'execute' },
    { agent_id: 'uiux', phase: 'summary', status: 'invalid', citation_count: 1, invalid_count: 1, citations: [{ path: '<script>unknown</script>', valid: false }] },
    { agent_id: 'central', phase: 'summary', status: 'no_citations', citation_count: 0, invalid_count: 0, citations: [] }] };
const aggregatedReceipt = chatCall('renderWikiReads', aggregated, 'summary');
assert.match(aggregatedReceipt.textContent, /前端 · 处理 · 引用路径匹配/);
assert.match(aggregatedReceipt.textContent, /UI\/UX 设计师 · 汇总 · 存在未匹配的引用.*<script>unknown<\/script>/);
assert.match(aggregatedReceipt.textContent, /中央知识库 · 汇总 · 未检测到引用标记/);
assert.match(aggregatedReceipt.textContent, /UI\/UX 设计师 · \/concepts\/current.md · 待复核/);
for (const [status, label] of [['stale', '待更新'], ['untracked', '未追溯']]) assert.ok(chatCall('renderWikiReads', { wiki_reads: [{ ...wikiRead, knowledge_status: status }] }, status).textContent.includes(label));
chatCall('renderMessages', { id: 'room', mode: 'orchestrated', messages: [
  { id: 'user', role: 'user', content: '用户问题', ...aggregated },
  { id: 'summary', role: 'assistant', content: '汇总回答', ...aggregated },
  { id: 'direct', role: 'assistant', agent_id: 'frontend', content: '专业回答', wiki_reads: [wikiRead], wiki_citation_check: check },
] }, true);
const articles = walk($('feed')).filter((item) => /^ag-message(?: |$)/.test(item.className));
assert.doesNotMatch(articles[0].textContent, /本轮读取的知识与引用核对/);
assert.match(articles[1].textContent, /汇总回答/);
assert.doesNotMatch(articles[1].textContent, /本轮读取的知识与引用核对/);
assert.match(articles[2].textContent, /专业回答/);
assert.doesNotMatch(articles[2].textContent, /本轮读取的知识与引用核对/);
const task = chatCall('renderDelegations', { id: 'room', delegations: [{ id: 'task', round_id: 'r', title: '设计知识', agent_id: 'uiux', status: 'completed', phase: 'execute', wiki_reads: [wikiRead], wiki_citation_check: check }] }, 'r');
assert.doesNotMatch(task.textContent, /本轮读取的知识与引用核对|引用路径匹配/);
chatCall('renderMessages',{id:'dedupe-room',mode:'orchestrated',status:'running',active_job_id:'job',messages:[],
  live_reply:{job_id:'job',agent_id:'central',text:'同一段初稿',updates:[{id:'prefix-before-check',title:'先前回答（校对前）',text:'同一段初稿',status:'completed'}]}});
assert.equal(($('feed').textContent.match(/同一段初稿/g)||[]).length,1,'The displayed initial answer is not duplicated while checking');
assert.ok(!extractChat('renderLiveReply').includes('正在输出校对后的回复'),'Unverified streaming text is not labelled as reviewed');
chatSandbox.state.submissions=new Map([['submission-room',{id:'one',content:'<script>问题</script>',created_at:'2026-10-06T10:00:00Z'}]]);
chatCall('renderMessages',{id:'submission-room',mode:'orchestrated',status:'idle',messages:[]},true);
assert.match($('feed').textContent,/<script>问题<\/script>/);
assert.doesNotMatch($('feed').textContent,/本机先回应|消息正在发送|我会先围绕/,'Submission status is not fabricated assistant prose');
assert.doesNotMatch($('feed').textContent,/已收到 · 系统确认/);
assert.ok(!walk($('feed')).some(item=>item.tagName==='script'));
chatCall('renderMessages',{id:'submission-room',mode:'orchestrated',status:'queued',active_job_id:'queued-job',
 messages:[{id:'actual-user',role:'user',content:'<script>问题</script>'}],live_reply:{job_id:'queued-job',text:'',updates:[],
 acknowledgement:{text:'前面还有1个任务，轮到后继续发出依据。'}}},true);
assert.match($('feed').textContent,/正在发送|正在回复/);
assert.doesNotMatch($('feed').textContent,/已收到 · 系统确认|前面还有1个任务/,'Queue acknowledgements remain transport status instead of assistant prose');
assert.doesNotMatch($('feed').textContent,/本机先回应/);
assert.equal(($('feed').textContent.match(/<script>问题<\/script>/g)||[]).length,1);
const fullCoverageReceipt=chatCall('renderWikiReads',{wiki_reads:[wikiRead],answer_check:{status:'corrected_with_limits',assertion_total:25,
 assessed_assertions:24,unassessed_assertions:1,unchecked_assertions_withdrawn:1,
 user_restricted_paths:['/topics/<img src=x onerror=bad()>.md'],user_scope_check:{status:'scope_violation'},
 checks:[{status:'insufficient',assertion_text:'<script>未经核对</script>',reason:'超出核对额度'}]}},'coverage');
assert.match(fullCoverageReceipt.textContent,/检测到 25 条.*辅助判定 24 条.*未完成 1 条.*已从最终模型结论中撤回.*<script>未经核对<\/script>/);
assert.ok(!walk(fullCoverageReceipt).some(item=>item.tagName==='script'));
assert.match(fullCoverageReceipt.textContent,/本轮限定依据.*<img src=x onerror=bad\(\)>.*范围外资料/);
assert.ok(!walk(fullCoverageReceipt).some(item=>item.tagName==='img'));
console.log('Wiki chat receipts passed: direct/aggregate/task integration, four knowledge states, precise citation boundaries, hashes/truncation, safe links/text and legacy records.');
