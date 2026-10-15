/** Exercise the real additive module in a small DOM with controlled HTTP responses. */
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const source = fs.readFileSync(new URL('../federation/web/social-accounts.js', import.meta.url), 'utf8');
const css = fs.readFileSync(new URL('../federation/web/social-accounts.css', import.meta.url), 'utf8');
const walk = (node) => [node, ...node.children.flatMap(walk)];
let document;
class Element {
  constructor(tag) { this.tagName = tag; this.children = []; this.listeners = {}; this.dataset = {}; this.attributes = {}; this._text = ''; this.value = ''; this.checked = false; this.disabled = false; this.hidden = false; this.open = false; this.className = ''; this.classList = { toggle: (cls, value) => { const classes = new Set(this.className.split(' ').filter(Boolean)); if (value) classes.add(cls); else classes.delete(cls); this.className = [...classes].join(' '); } }; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map((child) => child.textContent).join(''); }
  append(...items) { for (const item of items) item.parent = this; this.children.push(...items); }
  prepend(...items) { for (const item of items) item.parent = this; this.children.unshift(...items); }
  replaceChildren(...items) { this._text = ''; this.children = []; this.append(...items); }
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
document = {
  body: new Element('body'), activeElement: null,
  createElement: (tag) => new Element(tag),
  getElementById: (id) => walk(document.body).find((node) => node.id === id) || null,
  querySelector: (selector) => walk(document.body).find((node) => selector.startsWith('.') && node.className.split(' ').includes(selector.slice(1))) || null,
};
const topbar = new Element('div'); topbar.className = 'topbar';
const toolbar = new Element('div'); toolbar.className = 'federation-toolbar'; topbar.append(toolbar);
const chatActions = new Element('div'); chatActions.className = 'ag-header-actions';
const chatDraft = new Element('textarea'); chatDraft.id = 'ag-message'; chatDraft.value = '我的聊天草稿，不应被改写';
document.body.append(topbar, chatActions, chatDraft);
const get = (id) => document.getElementById(`social-${id}`);
const response = (body, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => body });
const providerNames = [['douyin', '抖音'], ['xiaohongshu', '小红书'], ['bilibili', 'B站'], ['weibo', '微博'], ['wechat_official', '微信公众号'], ['wechat_channels', '视频号']];
const providers = providerNames.map(([id, name]) => ({ id, name, description: `${name}官方能力需独立审核`, portal_url: 'https://example.com/portal', docs: [{ label: '官方接入文档', url: 'https://example.com/docs' }, { label: '非法链接', url: 'javascript:alert(1)' }], requirements: ['需要应用申请与用户授权'], capabilities: [{ id: 'read', label: '内容与数据', availability: 'documented_application_required', note: '仅获准数据' }, { id: 'publish', label: '确认后发布', availability: 'limited', note: '以实际权限为准' }, { id: 'comments', label: '评论管理', availability: 'unverified', note: '' }, { id: 'messages', label: '私信管理', availability: 'planned', note: '' }], next_step: '先核对主体资质，再申请应用。', verify_date: '2026-10-04' }));
providers[1].verified_date = '2026-10-03'; delete providers[1].verify_date;
let accounts = [], requests = [], failGet = false, postError = null, holdWrite = null, hangNextRequest = false, observations;
const timers = new Map(); let timerId = 0, lastRequestSignal;
const snapshot = () => ({ providers, accounts, observations, summary: { connected: 0, total: accounts.length }, policy: { mode: 'preparation', note: '本页管理接入准备；平台授权与真实连接尚未完成。' } });
const context = vm.createContext({ document, URL, console, Map, Set, JSON, Object, String, Array, encodeURIComponent, AbortController,
  setTimeout(callback, milliseconds) { const id = ++timerId; timers.set(id, { callback, milliseconds }); return id; },
  clearTimeout(id) { timers.delete(id); },
  async fetch(path, options) {
    const request = { path, method: options.method || 'GET', body: options.body ? JSON.parse(options.body) : null }; requests.push(request);
    lastRequestSignal = options.signal;
    if (hangNextRequest) { hangNextRequest = false; await new Promise((resolve, reject) => { options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true }); }); }
    if (request.method === 'GET') return failGet ? response({ detail: '受控读取失败' }, 503) : response(snapshot());
    if (holdWrite) await holdWrite;
    if (postError) return response({ detail: postError }, 422);
    if (request.method === 'PATCH') { const id = path.split('/').at(-1); accounts = accounts.map((item) => item.id === id ? { ...item, ...request.body } : item); return response({ account: accounts.find((item) => item.id === id) }); }
    const existing = accounts.find((item) => item.provider_id === request.body.provider_id && item.label === request.body.label);
    if (existing) return response({ account: existing, created: false });
    const account = { id: `account-${accounts.length + 1}`, ...request.body, connected: false, status: 'awaiting_application', status_label: '等待应用申请' }; accounts.push(account); return response({ account, created: true });
  },
});
vm.runInContext(source, context);
const form = get('editor').querySelectorAll('form')[0];
const submit = () => form.emit('submit');
const providerCard = (id) => get('providers').children.find((node) => node.dataset.providerId === id);
const add = (id) => providerCard(id).querySelectorAll('button').find((node) => node.dataset.providerId === id);
const edit = (id, index = 0) => providerCard(id).querySelectorAll('button').filter((node) => node.textContent === '编辑')[index];
const click = (node) => node.emit('click');
assert.equal(requests.length, 0, 'Loading the UI alone never touches account state or third parties');
assert.equal(get('launch').parent, toolbar);
assert.equal(get('chat-launch').parent, chatActions);
await click(get('launch'));
assert.equal(get('dialog').open, true);
assert.match(get('summary').textContent, /6 个平台.*0 条准备记录.*0 个 API 已连接/);
assert.equal(get('refresh').textContent, '刷新本地记录');
assert.match(get('policy').textContent, /已保存的只读快照.*不会采集新的平台数据/);
assert.equal(get('providers').children.length, 6);
assert.equal(get('providers').querySelectorAll('a').length, 12, 'Unsafe URL schemes are not linked');
assert.ok(get('providers').querySelectorAll('a').every((node) => node.rel === 'noopener noreferrer'));
assert.match(get('providers').textContent, /需独立审核.*未接通/s);
assert.match(get('providers').textContent, /申请前提与能力范围.*以实际权限为准/s);
assert.doesNotMatch(get('providers').textContent, /立即授权|一键发布|绑定成功/);
for (const label of ['有官方文档，需申请与授权', '受限开放', '尚未核实可用接口', '官方规划中']) assert.ok(providerCard('douyin').textContent.includes(label), `Actual catalog status renders as ${label}`);
assert.match(providerCard('douyin').textContent, /接入资料核对日期：2026-10-04/);
assert.match(providerCard('xiaohongshu').textContent, /接入资料核对日期：2026-10-03/, 'The previous date field remains compatible');
assert.equal(timers.size, 0, 'Completed requests release their deadline timer');

await click(add('douyin'));
assert.equal(get('application-status').value, 'unknown', 'Missing developer application information must stay unknown');
assert.equal(get('capability-read').checked, true, 'Douyin starts with the newly requested read-only scope');
assert.ok(['publish', 'comments', 'messages'].every((id) => !get(`capability-${id}`).checked));
for (const id of ['publish', 'comments', 'messages']) get(`capability-${id}`).checked = true;
assert.equal(document.activeElement, get('account-label'));
assert.equal(get('account-label').maxLength, 60);
assert.match(get('form-note').textContent, /无需填写密码、Cookie、密钥或 Token/);
get('account-label').value = '我的主账号';
get('application-status').value = 'approved';
let release;
holdWrite = new Promise((resolve) => { release = resolve; });
const pending = submit();
assert.equal(form.children[0].disabled, true, 'Submitting locks all editor fields');
assert.equal(get('refresh').disabled, true);
assert.equal(get('save').textContent, '保存中…');
const count = requests.length;
await submit();
assert.equal(requests.length, count, 'Concurrent repeated submit cannot duplicate a write');
await click(add('bilibili'));
assert.equal(get('editor-title').textContent, '添加抖音账号准备记录', 'In-flight writes cannot be redirected to another account');
release(); await pending; holdWrite = null;
assert.equal(accounts.length, 1);
assert.deepEqual(requests.find((item) => item.method === 'POST').body, { provider_id: 'douyin', label: '我的主账号', application_status: 'approved', requested_capabilities: ['read', 'publish', 'comments', 'messages'] });
assert.equal(get('editor').hidden, true);
assert.equal(form.children[0].disabled, false);
assert.match(get('notice').textContent, /已保存.*尚未连接.*均未接通/);
assert.match(providerCard('douyin').textContent, /未连接.*我已获批（尚未核验）/s);
assert.match(get('summary').textContent, /0 个 API 已连接账号/);

await click(edit('douyin'));
get('account-label').value = '<img src=x onerror=alert(1)> 工作室';
get('capability-messages').checked = false;
await submit();
assert.equal(accounts.length, 1);
assert.equal(requests.filter((item) => item.method === 'PATCH').length, 1);
assert.match(providerCard('douyin').textContent, /<img src=x onerror=alert\(1\)> 工作室/);
assert.equal(get('providers').querySelectorAll('img').length, 0, 'Account labels remain literal text');
assert.equal(requests.find((item) => item.method === 'PATCH').body.requested_capabilities.length, 3);

await click(add('douyin'));
get('account-label').value = '同平台第二账号';
postError = '<script>失败</script> 请保留输入';
await submit();
assert.equal(get('editor').hidden, false);
assert.equal(get('account-label').value, '同平台第二账号');
assert.equal(get('application-status').value, 'unknown');
assert.match(get('notice').textContent, /<script>失败<\/script>/);
assert.equal(get('dialog').querySelectorAll('script').length, 0, 'HTTP error details are plain text');
assert.equal(get('save').textContent, '保存准备记录');
postError = null;
await submit();
assert.equal(accounts.length, 2, 'One platform supports multiple named account preparations');

await click(add('weibo'));
assert.ok(['read', 'publish', 'comments', 'messages'].every((id) => get(`capability-${id}`).checked), 'Other platforms retain their previously requested defaults');
get('account-label').value = '未保存的微博记录';
await click(get('refresh'));
assert.equal(get('account-label').value, '未保存的微博记录', 'Refreshing records preserves the editor draft');
let prevented = false;
await get('dialog').emit('cancel', { preventDefault() { prevented = true; } });
assert.equal(prevented, true);
assert.equal(get('dialog').open, false);
assert.equal(document.activeElement, get('launch'), 'Escape restores focus to its exact opener');
await click(get('chat-launch'));
assert.equal(get('account-label').value, '未保存的微博记录', 'Closing and reopening preserves unsaved input');
assert.equal(chatDraft.value, '我的聊天草稿，不应被改写');
await click(get('dialog').querySelectorAll('button').find((node) => node.getAttribute('aria-label') === '关闭社交账号中心'));
assert.equal(document.activeElement, get('chat-launch'));
await click(get('launch'));

// A confirmed successful write followed by failed GET is not offered as another POST.
failGet = true;
await submit();
assert.equal(accounts.length, 3);
assert.equal(get('editor').hidden, true);
assert.match(get('notice').textContent, /准备记录已保存.*列表刷新失败/);
const writes = requests.filter((item) => item.method !== 'GET').length;
await submit();
assert.equal(requests.filter((item) => item.method !== 'GET').length, writes);
failGet = false; await click(get('refresh'));
assert.match(get('summary').textContent, /3 条准备记录.*0 个 API 已连接/);

// Idempotent POST collision is distinguished from updating an existing record.
await click(add('weibo')); get('account-label').value = '未保存的微博记录';
get('application-status').value = 'approved';
await submit();
assert.match(get('notice').textContent, /同平台同别名.*已存在.*编辑/);
assert.equal(accounts.find((item) => item.provider_id === 'weibo').application_status, 'unknown');
assert.equal(accounts.length, 3);
await click(add('bilibili'));
get('account-label').value = '超时后保留的账号';
hangNextRequest = true;
const timeoutSubmit = submit();
assert.equal(form.children[0].disabled, true);
assert.equal(timers.size, 1);
const deadline = [...timers.values()][0];
assert.equal(deadline.milliseconds, 20000, 'All API calls receive a 20-second deadline');
deadline.callback(); await timeoutSubmit;
assert.equal(lastRequestSignal.aborted, true, 'The deadline aborts the actual fetch signal');
assert.equal(timers.size, 0);
assert.equal(get('account-label').value, '超时后保留的账号');
assert.equal(get('editor').hidden, false);
assert.equal(form.children[0].disabled, false, 'An aborted save unlocks the editor');
assert.equal(get('refresh').disabled, false);
assert.match(get('notice').textContent, /请求超时（20 秒）.*输入已保留.*刷新核对/);
assert.equal(accounts.length, 3, 'A request aborted before its response does not invent a saved record');
await click(add('xiaohongshu'));
let beforeInvalid = requests.length;
await submit();
assert.equal(requests.length, beforeInvalid, 'Empty labels never reach the API');
get('account-label').value = '准备号';
for (const id of ['read', 'publish', 'comments', 'messages']) get(`capability-${id}`).checked = false;
await submit();
assert.equal(requests.length, beforeInvalid, 'At least one desired capability is required');
assert.match(get('notice').textContent, /至少选择一个/);
await click(get('refresh'));
await click(get('cancel'));
assert.equal(document.activeElement, get('refresh'), 'After refresh removes an old opener, hiding the editor focuses a visible fallback');

// Persisted browser observations show actual readings, never an API authorization or fresh sync.
observations = { mode: 'local_snapshot', snapshots: [{
  schema_version: 1, provider_id: 'douyin', capture_method: 'creator_center_browser_read', captured_at: '2026-10-04T18:20:00+08:00',
  account: { display_name: '测试创作者 <script>账号</script>', account_identifier: 'test_creator_001' },
  sources: [{ url: 'https://creator.douyin.com/creator-micro/home', title: '创作者中心' }, { url: 'javascript:alert(1)', title: '非法快照来源' }],
  period: { label: '近 7 天', start: '2026-09-27', end: '2026-10-03' },
  metrics: [{ label: '播放量', display_value: '1.2万', scope: '近 7 天作品播放量' }, { label: '粉丝总数', display_value: '128', scope: '读取时的账号累计值' }],
  works: [{ description: '<img src=x onerror=alert(1)> 测试作品', published_at: '2026-10-01 09:30', visibility: '公开', format: '视频', duration: '00:34' }],
  limitations: ['仅记录当前可见页面，未覆盖全部作品。'],
}], errors: [{ provider_id: 'xiaohongshu', message: '<script>错误</script> 快照文件格式无效' }] };
const beforeLocalRefresh = requests.length;
await click(get('refresh'));
assert.equal(requests.length, beforeLocalRefresh + 1);
assert.deepEqual(requests.at(-1), { path: '/api/social/accounts', method: 'GET', body: null }, 'Refreshing observations only reads the local API');
const douyin = providerCard('douyin'), red = providerCard('xiaohongshu');
assert.match(get('summary').textContent, /1 份只读快照.*0 个 API 已连接账号/);
assert.match(douyin.textContent, /已有只读快照.*API 未授权 · 未自动同步/s);
assert.match(douyin.textContent, /测试创作者 <script>账号<\/script>.*test_creator_001/s);
assert.match(douyin.textContent, /读取时间：2026-10-04T18:20:00\+08:00/);
assert.match(douyin.textContent, /统计期：近 7 天 · 2026-09-27 至 2026-10-03/);
assert.match(douyin.textContent, /播放量1.2万口径：近 7 天作品播放量/);
assert.match(douyin.textContent, /粉丝总数128口径：读取时的账号累计值/);
assert.match(douyin.textContent, /<img src=x onerror=alert\(1\)> 测试作品.*发布时间：2026-10-01 09:30.*可见范围：公开.*形式：视频.*时长：00:34/s);
const workDetails = douyin.querySelectorAll('details').find((node) => node.className === 'social-snapshot-works');
assert.equal(workDetails.open, false, 'Detailed work rows stay collapsed by default');
assert.match(workDetails.children[0].textContent, /作品明细（1 项）/);
assert.match(douyin.textContent, /不同口径的指标不直接相加.*仅记录当前可见页面/s);
assert.equal(douyin.querySelectorAll('a').filter((node) => node.href.startsWith('https://creator.douyin.com')).length, 1);
assert.ok(!douyin.querySelectorAll('a').some((node) => node.textContent.includes('非法快照来源')));
assert.equal(douyin.querySelectorAll('script').length, 0);
assert.equal(douyin.querySelectorAll('img').length, 0);
assert.match(red.textContent, /未接通.*本地快照读取失败：<script>错误<\/script> 快照文件格式无效/s);
assert.doesNotMatch(red.textContent, /已有只读快照/);
assert.equal(red.querySelectorAll('script').length, 0, 'Observation failures stay literal text');
observations = { mode: 'local_snapshot', snapshots: [], errors: [] };
await click(get('refresh'));
assert.doesNotMatch(providerCard('douyin').textContent, /已有只读快照|test_creator_001/, 'Removed or unavailable observations are not shown as stale current data');
assert.match(get('summary').textContent, /0 份只读快照.*0 个 API 已连接账号/);
assert.ok(requests.every((item) => item.path.startsWith('/api/social/accounts')));
assert.ok(requests.every((item) => ['GET', 'POST', 'PATCH'].includes(item.method)), 'No delete, login, message or publish actions exist');
assert.equal(chatDraft.value, '我的聊天草稿，不应被改写');
assert.doesNotMatch(source, /innerHTML|localStorage|sessionStorage|ag-message/);
assert.match(css, /var\(--panel/);
assert.match(css, /@media\(max-width:720px\)/);
console.log('Social accounts UI: six platforms, saved read-only observations, unverified API state, safe text, drafts, writes, errors and modal focus passed.');
