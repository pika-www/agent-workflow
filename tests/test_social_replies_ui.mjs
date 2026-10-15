/** Runs the actual workbench against a controlled DOM and local API contract. */
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const source = fs.readFileSync(new URL('../federation/web/social-replies.js', import.meta.url), 'utf8');
const css = fs.readFileSync(new URL('../federation/web/social-replies.css', import.meta.url), 'utf8');
const walk = (node) => [node, ...node.children.flatMap(walk)];
let document;
class Element {
  constructor(tag) { this.tagName = tag; this.children = []; this.listeners = {}; this.dataset = {}; this.attributes = {}; this._text = ''; this.value = ''; this.checked = false; this.disabled = false; this.hidden = false; this.open = false; this.className = ''; this.classList = { toggle: (cls, enabled) => { const values = new Set(this.className.split(' ').filter(Boolean)); if (enabled) values.add(cls); else values.delete(cls); this.className = [...values].join(' '); } }; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map((child) => child.textContent).join(''); }
  append(...nodes) { for (const node of nodes) node.parent = this; this.children.push(...nodes); }
  replaceChildren(...nodes) { this._text = ''; this.children = []; this.append(...nodes); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name]; }
  addEventListener(name, callback) { (this.listeners[name] ||= []).push(callback); }
  async emit(name, event = {}) { for (const callback of this.listeners[name] || []) await callback({ preventDefault() {}, ...event }); }
  focus() { document.activeElement = this; }
  showModal() { this.open = true; }
  close() { this.open = false; void this.emit('close'); }
  get isConnected() { return walk(document.body).includes(this); }
  querySelectorAll(selector) { return walk(this).slice(1).filter((node) => selector.startsWith('.') ? node.className.split(' ').includes(selector.slice(1)) : node.tagName === selector); }
}
document = { body: new Element('body'), activeElement: null, createElement: (tag) => new Element(tag), getElementById: (id) => walk(document.body).find((node) => node.id === id) || null, querySelector: (selector) => walk(document.body).find((node) => selector.startsWith('.') && node.className.split(' ').includes(selector.slice(1))) || null };
const topbar = new Element('div'); topbar.className = 'topbar';
const toolbar = new Element('div'); toolbar.className = 'federation-toolbar'; topbar.append(toolbar);
const chatDraft = new Element('textarea'); chatDraft.value = '原有聊天草稿'; document.body.append(topbar, chatDraft);
const get = (id) => document.getElementById(`replies-${id}`), click = (node) => node.emit('click');
const response = (value, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => value });
const settings = { enabled: true, tone: '简短自然', knowledge: '' }, transport = { ready: false, reason: '尚未接通评论与私信发送通道' };
let messages = [], requests = [], holdRequest = null, failGet = false, writeError = '', hanging = false, requestSignal, copied = '', jobs = {}, completeJob = false;
const timers = new Map(); let timerId = 0;
const snapshot = () => ({ settings: { ...settings }, messages: messages.map((item) => ({ ...item })), transport: { ...transport }, summary: {} });
const context = vm.createContext({ document, URL, console, Map, Set, String, Object, Array, JSON, encodeURIComponent, AbortController,
  navigator: { clipboard: { async writeText(value) { copied = value; } } },
  setTimeout(callback, milliseconds) { const id = ++timerId; timers.set(id, { callback, milliseconds }); return id; }, clearTimeout(id) { timers.delete(id); },
  async fetch(path, options) {
    const request = { path, method: options.method || 'GET', body: options.body ? JSON.parse(options.body) : null }; requests.push(request); requestSignal = options.signal;
    if (hanging) { hanging = false; await new Promise((resolve, reject) => options.signal.addEventListener('abort', () => reject(new Error('Aborted')), { once: true })); }
    if (holdRequest) await holdRequest;
    if (path.startsWith('/api/jobs/')) {
      const id = path.split('/').at(-1);
      if (completeJob) { const message = messages.find((item) => item.generation_job_id === id); if (message) Object.assign(message, { status: message.is_test ? 'test_completed' : 'blocked', reply: '<script>你好</script>，谢谢关注。', reason: message.is_test ? '本地测试，不外发' : '抖音收发通道未接通', generation_metadata: { model: '实际测试模型', engine: 'local_model' } }); return response({ id, status: 'completed' }); }
      return response(jobs[id] || { id, status: 'running' });
    }
    if (request.method === 'GET') return failGet ? response({ detail: '读取失败' }, 503) : response(snapshot());
    if (writeError) return response({ detail: writeError }, 422);
    if (request.method === 'PATCH') { Object.assign(settings, request.body); return response(snapshot()); }
    if (path.endsWith('/generate')) {
      const message = messages.find((item) => item.id === path.split('/').at(-2)); message.generation_job_id = `job-${message.id}-retry`; message.status = 'generating'; jobs[message.generation_job_id] = { id: message.generation_job_id, status: 'running' }; return response({ job: jobs[message.generation_job_id] });
    }
    const existing = request.body.external_id && messages.find((item) => item.external_id === request.body.external_id);
    if (existing) return response({ message: existing, created: false });
    const message = { id: `m${messages.length + 1}`, ...request.body, status: settings.enabled ? 'generating' : 'pending', received_at: '2026-10-05T00:30:00+08:00', generation_metadata: {} };
    let job;
    if (settings.enabled) { message.generation_job_id = `job-${message.id}`; job = { id: message.generation_job_id, status: 'running' }; jobs[job.id] = job; }
    messages.unshift(message); return response({ message, created: true, job });
  },
});
vm.runInContext(source, context);
const submit = () => get('import-form').emit('submit');
const save = () => get('settings-form').emit('submit');
const card = (id) => get('inbox').children.find((node) => node.dataset.messageId === id);
const cardButton = (id, text) => card(id).querySelectorAll('button').find((node) => node.textContent === text);
const flush = async () => { for (let i = 0; i < 15; i++) await Promise.resolve(); };
const runTimer = async (milliseconds) => { const [id, entry] = [...timers].find(([, item]) => item.milliseconds === milliseconds) || []; assert.ok(entry, `Expected a ${milliseconds}ms timer`); timers.delete(id); await entry.callback(); await flush(); };

assert.equal(requests.length, 0, 'Script initialization never fetches messages or changes settings');
assert.equal(get('launch').parent, toolbar);
assert.equal(get('is-test').checked, true, 'Imports begin as explicit local tests');
await click(get('launch'));
assert.equal(get('dialog').open, true);
assert.equal(get('dialog').getAttribute('aria-labelledby'), 'replies-title');
assert.match(get('transport-title').textContent, /自动回复规则已启用；抖音消息收发未接通/);
assert.match(get('transport-reason').textContent, /尚未接通/);
assert.match(get('dialog').textContent, /当前账号官方入口要求内测邀请码；本地工作台不代替开通/);
assert.ok(get('dialog').querySelectorAll('a').some((node) => node.href === 'https://creator.douyin.com/creator-micro/ai-application/ai-avatar' && node.rel === 'noopener noreferrer'));
assert.equal(get('toggle').textContent, '暂停处理');
assert.match(get('inbox').textContent, /还没有导入消息/);
assert.equal(get('tone').value, '简短自然');
assert.equal(timers.size, 0);
assert.equal(chatDraft.value, '原有聊天草稿');
assert.ok(!get('dialog').querySelectorAll('button').some((node) => /批准|审核|确认发送|自动发送/.test(node.textContent)), 'No per-message approval or nonexistent send actions');

get('tone').value = '友好自然'; await get('tone').emit('input'); get('knowledge').value = '<img src=x onerror=alert(1)> 已确认的业务资料'; await get('knowledge').emit('input');
await click(get('refresh'));
assert.equal(get('knowledge').value, '<img src=x onerror=alert(1)> 已确认的业务资料', 'Readbacks preserve unsaved settings drafts');
await save();
assert.equal(settings.tone, '友好自然');
assert.equal(settings.knowledge, '<img src=x onerror=alert(1)> 已确认的业务资料');
assert.match(get('notice').textContent, /规则已保存/);
assert.equal(requests.find((item) => item.method === 'PATCH').body.enabled, undefined, 'Editing knowledge does not implicitly change enabled state');
await click(get('toggle'));
assert.equal(settings.enabled, false); assert.match(get('transport-title').textContent, /已暂停.*未接通/);
await click(get('toggle')); assert.equal(settings.enabled, true);

get('account').value = 'ROS'; get('sender').value = '粉丝'; get('content').value = '<img src=x onerror=alert(1)> 你好'; get('context').value = '<script>上下文</script>'; get('source').value = 'javascript:alert(1)';
const beforeInvalid = requests.length; await submit(); assert.equal(requests.length, beforeInvalid); assert.match(get('notice').textContent, /抖音 HTTPS/);
get('source').value = 'https://creator.douyin.com/creator-micro/interaction/comment'; get('external-id').value = 'comment-one';
let release; holdRequest = new Promise((resolve) => { release = resolve; });
const pending = submit(); assert.equal(get('import-form').children[0].disabled, true); assert.equal(get('refresh').disabled, true);
const writeCount = requests.length; await submit(); assert.equal(requests.length, writeCount, 'Double submit cannot queue duplicates');
release(); holdRequest = null; await pending;
assert.equal(messages.length, 1); assert.equal(get('content').value, '', 'Confirmed persisted import clears only the accepted message draft');
assert.equal(get('account').value, 'ROS'); assert.equal(get('is-test').checked, true);
assert.match(get('notice').textContent, /AI 正在自动处理.*测试消息，不会外发/);
assert.equal(get('inbox').querySelectorAll('img').length, 0); assert.equal(get('inbox').querySelectorAll('script').length, 0);
assert.match(card('m1').textContent, /<img src=x onerror=alert\(1\)> 你好/);
assert.match(card('m1').textContent, /<script>上下文<\/script>/);
assert.equal(card('m1').querySelectorAll('a')[0].rel, 'noopener noreferrer');
assert.equal(card('m1').querySelectorAll('button').length, 0, 'No extra generation can be started during generation');
await runTimer(500); assert.ok([...timers.values()].some((item) => item.milliseconds === 1500));
completeJob = true; await runTimer(1500);
assert.match(card('m1').textContent, /测试生成完成.*<script>你好<\/script>/s);
assert.match(card('m1').textContent, /生成模型：实际测试模型.*local_model/);
assert.equal(card('m1').querySelectorAll('script').length, 0);
assert.equal(timers.size, 0, 'Completed jobs stop polling and release deadlines');
await click(cardButton('m1', '复制回复')); assert.equal(copied, '<script>你好</script>，谢谢关注。');
assert.match(get('notice').textContent, /不会向抖音发送/);
assert.ok(requests.every((item) => item.path.startsWith('/api/')), 'UI never sends third-party platform requests');

get('channel').value = 'private'; get('sender').value = '私信来访者'; get('content').value = '这条私信来自真实页面'; get('is-test').checked = false; get('external-id').value = 'private-one';
completeJob = false; await submit(); assert.equal(messages.length, 2); assert.equal(messages[0].channel, 'private');
const privateFilter = get('dialog').querySelectorAll('button').find((node) => node.dataset.channel === 'private'); await click(privateFilter);
assert.equal(get('inbox').children.length, 1); assert.equal(get('inbox').children[0].dataset.messageId, 'm2');
assert.equal(privateFilter.getAttribute('aria-pressed'), 'true');
completeJob = true; await runTimer(500);
assert.match(card('m2').textContent, /待接通发送通道.*抖音收发通道未接通/s);
assert.doesNotMatch(card('m2').textContent, /已发送/);
await click(get('dialog').querySelectorAll('button').find((node) => node.dataset.channel === 'all'));
assert.equal(get('inbox').children.length, 2);

// Errors preserve message input; transport flags never become true because of a local generation.
writeError = '<script>受控拒绝</script>'; get('sender').value = '测试来访者'; get('content').value = '失败时保留'; await submit();
assert.equal(get('content').value, '失败时保留'); assert.match(get('notice').textContent, /<script>受控拒绝<\/script>/);
assert.equal(get('dialog').querySelectorAll('script').length, 0); assert.equal(get('import-form').children[0].disabled, false); writeError = '';
hanging = true; const timeoutImport = submit(); assert.ok([...timers.values()].some((item) => item.milliseconds === 20000)); await runTimer(20000); await timeoutImport;
assert.equal(requestSignal.aborted, true); assert.match(get('notice').textContent, /超时（20 秒）.*输入已保留/); assert.equal(get('content').value, '失败时保留'); assert.equal(timers.size, 0);

// Persisted import followed by failed refresh is acknowledged once, not re-offered as another POST.
failGet = true; await submit(); assert.equal(messages.length, 3); assert.equal(get('content').value, ''); assert.match(get('notice').textContent, /已导入.*列表刷新失败/);
failGet = false; await click(get('refresh')); completeJob = true; await runTimer(500);
get('sender').value = '粉丝'; get('content').value = '重复记录'; get('external-id').value = 'comment-one'; await submit(); assert.equal(messages.length, 3); assert.match(get('notice').textContent, /已有记录，未重复导入/);

// Closing stops polling and returning to the dialog resumes known in-flight jobs.
completeJob = false; await click(cardButton('m1', '重新生成')); assert.ok([...timers.values()].some((item) => item.milliseconds === 500));
get('knowledge').value = '未保存资料'; await get('knowledge').emit('input');
await get('dialog').emit('cancel'); assert.equal(get('dialog').open, false); assert.equal(document.activeElement, get('launch')); assert.equal(timers.size, 0);
const requestsBeforeClosed = requests.length; await flush(); assert.equal(requests.length, requestsBeforeClosed);
await click(get('launch')); assert.equal(get('knowledge').value, '未保存资料'); assert.ok([...timers.values()].some((item) => item.milliseconds === 500));
completeJob = true; await runTimer(500); assert.equal(timers.size, 0);

// An in-flight polling response may arrive after close; it cannot reopen or paint a stale session.
completeJob = false; await click(cardButton('m2', '重新生成')); holdRequest = new Promise((resolve) => { release = resolve; });
const [pollTimerId, pollEntry] = [...timers].find(([, item]) => item.milliseconds === 500); timers.delete(pollTimerId); const stalePoll = pollEntry.callback(); await flush();
await get('dialog').emit('cancel'); const closedNotice = get('notice').textContent; completeJob = true; release(); holdRequest = null; await stalePoll; await flush();
assert.equal(get('dialog').open, false); assert.equal(get('notice').textContent, closedNotice); assert.equal(timers.size, 0);
await click(get('launch'));

// Mixed untrusted message metadata is rendered as text, with no arbitrary links or status spoofing.
messages.push({ id: 'unsafe', channel: 'comment', account_label: '<svg onload=alert(1)>', sender: '<iframe>', content: '<script>raw</script>', reply: '<img>', context: 'plain', status: 'sent', source_url: 'https://douyin.com.attacker.test/', metadata: { model: '<img onerror=1>' } });
await click(get('refresh')); assert.match(card('unsafe').textContent, /发送状态待核对/); assert.equal(card('unsafe').querySelectorAll('a').length, 0); assert.equal(card('unsafe').querySelectorAll('img').length, 0);
messages.push({ id: 'handoff', channel: 'private', content: '报价多少', status: 'handoff', needs_human: true, reason: '没有已确认报价', source_url: 'https://user:secret@creator.douyin.com/' });
await click(get('refresh')); assert.match(card('handoff').textContent, /需要人工处理：没有已确认报价/); assert.equal(card('handoff').querySelectorAll('a').length, 0);
await click(get('toggle')); assert.equal(cardButton('m1', '重新生成').disabled, true);
assert.equal(chatDraft.value, '原有聊天草稿');
assert.match(css, /@media\(max-width:620px\)/); assert.match(css, /:focus-visible/); assert.match(css, /minmax\(0,1fr\)/);
assert.doesNotMatch(source, /\.innerHTML\s*=|insertAdjacentHTML|localStorage|document\.cookie/);
assert.ok(requests.every((item) => !/send|approve|publish/.test(item.path)), 'No fabricated sending or approval routes');
assert.ok(requests.filter((item) => item.method === 'POST').every((item) => item.path === '/api/social/replies/messages' || item.path.endsWith('/generate')));
vm.runInContext(source, context); assert.equal(document.body.querySelectorAll('dialog').length, 1, 'Loading the module twice does not duplicate the dialog');
console.log('Social AI reply UI: render, automatic queue, paused rules, filters, copying, local-only transport, job polling, timeout, duplicate handling, draft preservation, XSS, and focus checks passed.');
