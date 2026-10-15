/** Real observatory DOM interactions; all graph, browser storage and reader data are isolated fixtures. */
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const upstreamRequire = createRequire(new URL('../openwiki-upstream/package.json', import.meta.url));
const toolsRequire = createRequire(new URL('../openwiki-tools/package.json', import.meta.url));
const { JSDOM, requestInterceptor } = upstreamRequire('jsdom');
const { build } = toolsRequire('esbuild');
const compiled = await build({
  entryPoints: [fileURLToPath(new URL('../federation/web/observatory.js', import.meta.url))],
  bundle: true, write: false, format: 'iife', platform: 'browser', target: 'es2022', logLevel: 'silent',
});
const source = compiled.outputFiles[0].text;
const JOURNAL_KEY = 'openwiki.observatory.journal.v1';
const attack = '<img src="https://tracker.example.test/pixel" onerror="window.__attack++">';

function hub(id, title, parent = 'central') {
  return { id: `${id}/index`, title, spaceId: id, isFederationHub: true,
    spaceDepth: id === 'central' ? 0 : parent === 'central' ? 1 : 2,
    ancestorSpaceIds: id === 'central' ? [] : parent === 'central' ? ['central'] : ['central', parent],
    parentSpaceId: id === 'central' ? null : parent,
    breadcrumb: ['中央', parent === 'central' ? title : '软件', ...(parent === 'central' ? [] : [title])],
    description: '知识库结构入口；尚未积累正式知识。', body: '# 结构导航', tags: [], links: [], backlinks: [] };
}
function page(slug, title, body = '本地测试正文与来源线索。') {
  return { id: `software-frontend/${slug}`, title, spaceId: 'software-frontend', isFederationHub: false,
    spaceDepth: 2, parentSpaceId: 'software', ancestorSpaceIds: ['central', 'software'],
    breadcrumb: ['中央', '软件', '前端'], description: '', body, tags: ['Web'], links: [], backlinks: [] };
}
const fixture = { root: '受控测试知识库', types: [], edges: [], nodes: [
  hub('central', '中央'), hub('software', '软件'), hub('content', '影视'),
  hub('commerce', '电商'), hub('business', '经营'),
  hub('software-uiux', '交互设计', 'software'), hub('software-frontend', '前端', 'software'),
  hub('software-testing', '测试', 'software'),
  page('constraint-validation', '约束验证', '特殊检索词 NebulaToken 与表单约束。'),
  page('constraint-violations', '违反状态类型'),
  page('css-validity-pseudo-classes', 'CSS 验证伪类'),
  page('cva-api-methods', `API 方法 ${attack}`),
  page('sources/mdn', 'MDN 来源档案', '原始资料入口。'),
] };

const openDOMs = new Set();
const totals = { scenarios: 0, graphRequests: 0, unexpectedRequests: 0, uncaughtErrors: 0 };
async function settle(predicate, message) {
  for (let i = 0; i < 100; i++) {
    if (predicate()) return;
    await new Promise(resolve => setImmediate(resolve));
  }
  assert.ok(predicate(), message);
}
async function mount({ stored = null, serverStored = null, storage = 'normal', response = { ok: true, status: 200, data: fixture }, sidebarReady = true } = {}) {
  const requests = [], resources = [], errors = [], nativeClicks = [];
  const dom = new JSDOM('<!doctype html><html><head></head><body><div class="topbar"><button id="ag-launch">主 Agent</button></div><main id="main"><nav id="sidebar"></nav><section id="detail"></section></main></body></html>', {
    url: 'https://openwiki.example.test/', runScripts: 'dangerously', pretendToBeVisual: true,
    resources: { interceptors: [requestInterceptor(request => {
      resources.push(request.url);
      return new Response('', { status: 200, headers: { 'content-type': 'text/plain' } });
    })] },
  });
  openDOMs.add(dom);
  const { window } = dom, document = window.document;
  window.__attack = 0;
  window.Math.random = () => 0;
  window.addEventListener('error', event => { errors.push(event.error || event.message); event.preventDefault(); });
  // jsdom has no top-layer layout; keep actual dialog elements and their open state.
  window.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  window.HTMLDialogElement.prototype.close = function () {
    if (this.open) { this.open = false; this.dispatchEvent(new window.Event('close')); }
  };
  if (stored !== null) window.localStorage.setItem(JOURNAL_KEY, typeof stored === 'string' ? stored : JSON.stringify(stored));
  if (storage === 'denied') Object.defineProperty(window, 'localStorage', {
    get() { throw new window.DOMException('Storage blocked by browser settings', 'SecurityError'); },
  });
  if (storage === 'quota') window.Storage.prototype.setItem = function () {
    throw new window.DOMException('Storage quota exceeded', 'QuotaExceededError');
  };
  let serverJournal = serverStored ? structuredClone(serverStored) : {};
  let currentResponse = response;
  window.fetch = async (url, options = {}) => {
    requests.push({ url, method: options.method || 'GET' });
    if (url === '/api/browser-state/journal') {
      if (options.method === 'POST') serverJournal = JSON.parse(options.body).value;
      return { ok: true, status: 200, json: async () => ({ value: structuredClone(serverJournal), saved: true }) };
    }
    assert.equal(url, '/api/graph', 'Exploration only reads the graph and saves server-side notes');
    assert.equal(options.method || 'GET', 'GET', 'No model or permanent knowledge mutation is allowed');
    if (currentResponse instanceof Error) throw currentResponse;
    return { ok: currentResponse.ok, status: currentResponse.status, json: async () => structuredClone(currentResponse.data) };
  };
  function addSidebar() {
    for (const node of fixture.nodes) {
      const item = document.createElement('button');
      item.className = 'nav-item'; item.dataset.id = node.id; item.textContent = node.title;
      item.addEventListener('click', () => {
        nativeClicks.push(node.id);
        document.getElementById('detail').textContent = node.title;
        document.dispatchEvent(new window.CustomEvent('openwiki:select', { detail: { nodeId: node.id, spaceId: node.spaceId } }));
      });
      document.getElementById('sidebar').append(item);
    }
  }
  if (sidebarReady) addSidebar();
  vm.runInContext(source, dom.getInternalVMContext());
  await settle(() => document.getElementById('ob-hero-note') && document.getElementById('ob-hero-note').textContent !== '正在接收知识库的微光…', 'Graph loading should finish');
  const api = {
    dom, window, document, requests, resources, errors, nativeClicks,
    $(id) { return document.getElementById(`ob-${id}`); },
    nav(view) { document.querySelector(`.ob-nav [data-view="${view}"]`).click(); },
    search(query) { this.$('search').value = query; this.$('search').dispatchEvent(new window.Event('input', { bubbles: true })); },
    button(text, within = document) {
      const button = [...within.querySelectorAll('button')].find(item => item.textContent.includes(text));
      assert.ok(button, `Button exists: ${text}`); return button;
    },
    journal() { return structuredClone(serverJournal); },
    addSidebar,
    setResponse(next) { currentResponse = next; },
    close() {
      assert.equal(window.__attack, 0, 'API metadata and notes must not execute scripts');
      assert.deepEqual(resources, [], 'Exploration must not load external resources');
      assert.deepEqual(errors, [], 'DOM interaction must not throw uncaught exceptions');
      assert.ok(requests.every(request => request.url === '/api/browser-state/journal' || (request.url === '/api/graph' && request.method === 'GET')));
      totals.scenarios++; totals.graphRequests += requests.filter(r => r.url === '/api/graph').length;
      totals.unexpectedRequests += resources.length; totals.uncaughtErrors += errors.length;
      dom.window.close(); openDOMs.delete(dom);
    },
  };
  return api;
}

try {
  // Data counts must distinguish actual pages, navigation hubs and source files.
  const app = await mount();
  assert.equal(app.document.title, '未明 · 知识观测站');
  assert.equal(app.document.querySelectorAll('#ob-shell').length, 1);
  assert.equal(app.$('home').hidden, false);
  assert.equal(app.$('hero-note').textContent, '8 个知识库入口 · 4 篇知识 · 1 份来源');
  assert.equal(app.document.querySelectorAll('.ob-territory').length, 4);
  assert.equal(app.$('territory-count').textContent, '00 / 04 星域已抵达');
  assert.equal([...app.document.querySelectorAll('.ob-territory-foot')].filter(item => item.textContent.includes('待充实')).length, 3);
  assert.equal(app.$('secret').hidden, true);
  // Native bootstrap broadcasts must not leave home or create fake visit records.
  app.document.dispatchEvent(new app.window.CustomEvent('openwiki:select', { detail: { nodeId: 'central/index', spaceId: 'central' } }));
  assert.equal(app.$('home').hidden, false);
  assert.equal(app.journal().visits, undefined);
  app.nav('archive');
  assert.equal(app.document.querySelectorAll('#ob-results .ob-node-card').length, fixture.nodes.length);
  app.search('NebulaToken');
  assert.equal(app.document.querySelectorAll('#ob-results .ob-node-card').length, 1);
  assert.equal(app.document.querySelector('#ob-results .ob-node-title').textContent, '约束验证');
  app.document.querySelector('#ob-results .ob-node-title').click();
  assert.equal(app.nativeClicks.at(-1), 'software-frontend/constraint-validation');
  assert.equal(app.document.body.classList.contains('ob-native'), true);
  assert.equal(app.$('content').hidden, true);
  assert.equal(app.$('reader-bar').hidden, false);
  await settle(() => app.journal().visits?.length === 1, 'Visit saved on server');
  assert.deepEqual(app.journal().visits, ['software-frontend/constraint-validation']);
  app.$('read-save').click();
  await settle(() => app.$('read-save').getAttribute('aria-pressed') === 'true', 'Bookmark confirmed by server');
  assert.equal(app.$('read-save').getAttribute('aria-pressed'), 'true');
  app.$('note').click();
  assert.equal(app.$('dialog').open, true);
  const note = `想到一个问题：${attack}<script>window.__attack++</script>`;
  app.document.querySelector('.ob-note-input').value = note;
  app.button('保存短笺与星标', app.$('dialog')).click();
  await settle(() => !app.$('dialog').open, 'Note closes after server acknowledgment');
  assert.equal(app.$('dialog').open, false);
  assert.equal(app.journal().notes['software-frontend/constraint-validation'], note);
  assert.deepEqual(app.journal().bookmarks, ['software-frontend/constraint-validation']);
  app.nav('journal');
  assert.equal(app.document.querySelector('.ob-card-note').textContent, note);
  assert.equal(app.$('bookmarks').querySelectorAll('img,script,iframe').length, 0);
  const persisted = JSON.stringify(app.journal());
  assert.equal(app.window.localStorage.getItem(JOURNAL_KEY), null, 'No browser notebook is written');
  app.close();

  // A new browser document uses saved note text and deduplicated footprints.
  const restored = await mount({ serverStored: JSON.parse(persisted) });
  restored.nav('journal');
  assert.equal(restored.$('bookmark-count').textContent, '1');
  assert.equal(restored.document.querySelector('.ob-card-note').textContent, note);
  assert.equal(restored.document.querySelectorAll('#ob-history .ob-history-row').length, 1);
  restored.document.querySelector('#ob-bookmarks .ob-save-icon').click();
  await settle(() => restored.journal().bookmarks.length === 0, 'Removal saved on server');
  assert.deepEqual(restored.journal().bookmarks, []);
  assert.equal(restored.journal().notes['software-frontend/constraint-validation'], note, 'Removing a bookmark must not delete the note');
  restored.nav('archive'); restored.search('API 方法');
  assert.equal(restored.document.querySelector('#ob-results .ob-node-title').textContent, `API 方法 ${attack}`);
  assert.equal(restored.$('results').querySelectorAll('img,script,iframe').length, 0);
  restored.search('这个词不会出现');
  assert.equal(restored.document.querySelectorAll('#ob-results .ob-node-card').length, 0);
  restored.button('查看全部档案', restored.$('results')).click();
  assert.equal(restored.$('search').value, '');
  restored.$('kind').value = 'source'; restored.$('kind').dispatchEvent(new restored.window.Event('change'));
  assert.equal(restored.document.querySelectorAll('#ob-results .ob-node-card').length, 1);
  assert.match(restored.$('results').textContent, /MDN 来源档案/);
  restored.window.dispatchEvent(new restored.window.StorageEvent('storage', { key: JOURNAL_KEY, newValue: '{invalid' }));
  restored.nav('journal');
  assert.equal(restored.document.querySelectorAll('#ob-history .ob-history-row').length, 1, 'Malformed storage from another tab must preserve current state');
  restored.close();

  // Wander offers real unseen pages without visiting until the user departs.
  const journey = await mount();
  journey.$('wander').click();
  assert.equal(journey.$('dialog').open, true);
  assert.equal(journey.nativeClicks.length, 0);
  const firstReveal = journey.document.querySelector('.ob-reveal h3').textContent;
  assert.equal(firstReveal, '约束验证');
  journey.button('再接收一束信号', journey.$('dialog')).click();
  assert.notEqual(journey.document.querySelector('.ob-reveal h3').textContent, firstReveal);
  journey.button('就从这里出发', journey.$('dialog')).click();
  assert.equal(journey.nativeClicks.at(-1), 'software-frontend/constraint-violations');
  assert.equal(journey.$('dialog').open, false);
  journey.$('back-home').click();
  const route = [...journey.document.querySelectorAll('.ob-route-row')].find(row => row.textContent.includes('HTML 表单验证'));
  assert.ok(route); route.click();
  assert.equal(journey.document.querySelectorAll('.ob-route-step').length, 4);
  assert.match(journey.$('dialog-body').textContent, /1 \/ 4 个坐标已抵达/);
  journey.button('继续这条路线', journey.$('dialog')).click();
  assert.equal(journey.nativeClicks.at(-1), 'software-frontend/constraint-validation');
  assert.match(journey.$('next').textContent, /沿线前行 2\/4/);
  journey.$('next').click();
  assert.equal(journey.nativeClicks.at(-1), 'software-frontend/constraint-violations');
  journey.$('next').click(); journey.$('next').click(); journey.$('next').click();
  assert.equal(journey.$('dialog').open, true);
  assert.match(journey.$('dialog-body').textContent, /4 \/ 4 个坐标已抵达/);
  await settle(() => journey.journal().visits?.length >= 4, 'All route visits saved');
  assert.equal(new Set(journey.journal().visits).size, journey.journal().visits.length);
  journey.$('dialog-close').click();
  journey.document.querySelector('#sidebar [data-id="content/index"]').click();
  assert.equal(journey.$('next').textContent, '随机下一站 ↗', 'Native navigation outside the route must clear stale route progression');
  journey.$('next').click();
  assert.match(journey.$('dialog-label').textContent, /偶然相遇/, 'Next after unrelated navigation should offer a fresh wander');
  journey.close();

  // Opening before upstream sidebar hydration must wait and then use its click.
  const delayed = await mount({ sidebarReady: false });
  delayed.nav('archive'); delayed.search('NebulaToken'); delayed.document.querySelector('.ob-node-title').click();
  assert.equal(delayed.nativeClicks.length, 0);
  assert.match(delayed.$('notice').textContent, /阅读器正在连接/);
  delayed.addSidebar();
  await settle(() => delayed.nativeClicks.length === 1, 'Pending selection opens after sidebar hydration');
  assert.equal(delayed.nativeClicks[0], 'software-frontend/constraint-validation');
  await settle(() => delayed.journal().visits?.length === 1, 'Delayed visit saved');
  assert.deepEqual(delayed.journal().visits, ['software-frontend/constraint-validation']);
  delayed.close();

  const canceled = await mount({ sidebarReady: false });
  canceled.nav('archive'); canceled.search('NebulaToken'); canceled.document.querySelector('.ob-node-title').click();
  canceled.$('back-home').click(); canceled.addSidebar();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(canceled.nativeClicks.length, 0, 'Leaving the reader must cancel a pending selection');
  assert.equal(canceled.$('home').hidden, false);
  canceled.document.dispatchEvent(new canceled.window.KeyboardEvent('keydown', { key: 'k', metaKey: true, bubbles: true }));
  assert.equal(canceled.document.activeElement.id, 'ob-search');
  canceled.search('NebulaToken');
  canceled.document.dispatchEvent(new canceled.window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  assert.equal(canceled.$('search').value, '');
  canceled.document.dispatchEvent(new canceled.window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  assert.equal(canceled.$('home').hidden, false);
  canceled.close();

  // A central hub or repeated visits within one territory must not unlock the room.
  const secret = await mount();
  secret.nav('atlas'); secret.document.querySelector('#sidebar [data-id="central/index"]').click(); secret.$('back-home').click();
  assert.equal(secret.$('territory-count').textContent, '00 / 04 星域已抵达');
  assert.equal(secret.$('secret').hidden, true);
  const territoryVisits = ['software-frontend/constraint-validation', 'content/index', 'commerce/index', 'business/index'];
  for (const [index, id] of territoryVisits.entries()) {
    secret.nav('atlas'); secret.document.querySelector(`#sidebar [data-id="${id}"]`).click(); secret.$('back-home').click();
    assert.equal(secret.$('territory-count').textContent, `0${index + 1} / 04 星域已抵达`);
    assert.equal(secret.$('secret').hidden, index < 3, 'Only all four actual territories unlock the room');
    if (index === 0) {
      secret.nav('atlas'); secret.document.querySelector('#sidebar [data-id="software-frontend/constraint-violations"]').click(); secret.$('back-home').click();
      assert.equal(secret.$('territory-count').textContent, '01 / 04 星域已抵达');
      assert.equal(secret.$('secret').hidden, true);
    }
  }
  secret.$('secret').click();
  assert.equal(secret.$('dialog').open, true);
  assert.equal(secret.$('dialog-label').textContent, 'ROOM ZERO / 第零号观测室');
  assert.equal(secret.$('dialog-title').textContent, '答案之外，还有连接。');
  assert.match(secret.$('dialog-body').textContent, /思考邀请卡，不是知识库中的事实结论/);
  secret.button('带着这个问题，再出发', secret.$('dialog')).click();
  assert.equal(secret.nativeClicks.at(-1), 'software-uiux/index');
  assert.equal(secret.$('dialog').open, false);
  secret.close();

  // Replacing a filter/card after an action must keep keyboard focus on that action.
  const focus = await mount();
  focus.nav('archive');
  const oldFilter = focus.document.querySelector('#ob-territory-filters [data-territory="software"]');
  oldFilter.focus(); oldFilter.click();
  const newFilter = focus.document.querySelector('#ob-territory-filters [data-territory="software"]');
  assert.notEqual(newFilter, oldFilter, 'Exercise a rebuilt filter instead of an unchanged DOM node');
  assert.equal(focus.document.activeElement, newFilter);
  assert.equal(newFilter.getAttribute('aria-pressed'), 'true');
  focus.search('NebulaToken');
  const oldSave = focus.document.querySelector('#ob-results [data-bookmark="software-frontend/constraint-validation"]');
  oldSave.focus(); oldSave.click();
  const newSave = focus.document.querySelector('#ob-results [data-bookmark="software-frontend/constraint-validation"]');
  assert.notEqual(newSave, oldSave, 'Exercise a rebuilt result card');
  assert.equal(focus.document.activeElement, newSave);
  assert.equal(newSave.getAttribute('aria-pressed'), 'true');
  newSave.click();
  assert.equal(focus.document.activeElement.dataset.bookmark, 'software-frontend/constraint-validation');
  assert.equal(focus.document.activeElement.getAttribute('aria-pressed'), 'false');
  focus.close();

  // Capture the actual Markdown Blob and download anchor without browser navigation.
  const exportData = JSON.parse(persisted);
  exportData.notes['software-frontend/css-validity-pseudo-classes'] = '没有收藏也应该导出的另一则短笺。';
  const exported = await mount({ stored: exportData });
  const blobs = [], downloads = [], revoked = [], releaseCallbacks = [];
  exported.window.URL.createObjectURL = blob => { blobs.push(blob); return 'blob:https://openwiki.example.test/isolated-export'; };
  exported.window.URL.revokeObjectURL = url => { revoked.push(url); };
  exported.window.HTMLAnchorElement.prototype.click = function () {
    downloads.push({ href: this.href, name: this.download, attached: this.isConnected });
  };
  const schedule = exported.window.setTimeout.bind(exported.window);
  exported.window.setTimeout = (callback, delay, ...args) => {
    if (delay === 1000) { releaseCallbacks.push(callback); return 999999; }
    return schedule(callback, delay, ...args);
  };
  exported.nav('journal'); exported.button('导出探索手记', exported.$('journal-storage')).click();
  assert.equal(blobs.length, 1);
  assert.ok(blobs[0] instanceof exported.window.Blob);
  assert.equal(blobs[0].type, 'text/markdown;charset=utf-8');
  assert.deepEqual(downloads, [{ href: 'blob:https://openwiki.example.test/isolated-export', name: '未明-探索手记.md', attached: true }]);
  assert.equal(exported.document.querySelectorAll('a[download]').length, 0, 'The temporary download anchor should be removed');
  const markdown = await new Promise((resolve, reject) => {
    const reader = new exported.window.FileReader();
    reader.onload = () => resolve(reader.result); reader.onerror = () => reject(reader.error); reader.readAsText(blobs[0]);
  });
  assert.ok(markdown.startsWith('# 未明 · 探索手记\n'));
  assert.match(markdown, /## 收藏的星光\n\n### 约束验证\n\n坐标：software-frontend\/constraint-validation/);
  assert.ok(markdown.includes(note), 'Export must retain the user note verbatim as text');
  assert.match(markdown, /## 最近经过\n\n- 约束验证 · software-frontend\/constraint-validation/);
  assert.match(markdown, /## 其他短笺\n\n### CSS 验证伪类\n\n没有收藏也应该导出的另一则短笺。/);
  assert.equal(releaseCallbacks.length, 1);
  releaseCallbacks[0]();
  assert.deepEqual(revoked, ['blob:https://openwiki.example.test/isolated-export']);
  assert.deepEqual(exported.journal(), exportData, 'Export must not alter the saved exploration journal');
  exported.close();

  // Browser storage restrictions do not prevent server-side note persistence.
  for (const storage of ['denied', 'quota']) {
    const blocked = await mount({ storage });
    blocked.nav('archive'); blocked.search('NebulaToken'); blocked.document.querySelector('.ob-node-title').click();
    blocked.$('read-save').click();
    await settle(() => blocked.journal().bookmarks?.length === 1, 'Browser storage is not required to save on the server');
    blocked.$('note').click();
    blocked.document.querySelector('.ob-note-input').value = '本次浏览器会话的念头';
    blocked.button('保存短笺与星标', blocked.$('dialog')).click();
    await settle(() => !blocked.$('dialog').open, 'Note saved without browser persistence');
    blocked.nav('journal');
    assert.equal(blocked.$('bookmark-count').textContent, '1');
    assert.equal(blocked.document.querySelector('.ob-card-note').textContent, '本次浏览器会话的念头');
    assert.match(blocked.$('journal-storage').textContent, /由服务器保存/);
    blocked.close();
  }

  // Errors remain visible and retry uses the same read-only endpoint.
  for (const response of [{ ok: false, status: 503 }, { ok: true, status: 200, data: { nodes: null } }, new Error('测试网络中断')]) {
    const failed = await mount({ response });
    assert.equal(failed.$('error').hidden, false);
    assert.match(failed.$('hero-note').textContent, /信号暂时中断/);
    assert.ok(failed.$('error-message').textContent.length > 0);
    failed.setResponse({ ok: true, status: 200, data: fixture }); failed.$('retry').click();
    await settle(() => failed.$('error').hidden, 'Retry should recover after a successful graph response');
    assert.equal(failed.$('hero-note').textContent, '8 个知识库入口 · 4 篇知识 · 1 份来源');
    assert.equal(failed.requests.filter(r => r.url === '/api/graph').length, 2);
    failed.close();
  }
  process.stdout.write(JSON.stringify({ ok: true, ...totals, realObservatoryBundle: true, nativeSidebarNavigation: true, safePersistence: true, noModelCalls: true }) + '\n');
} finally {
  for (const dom of openDOMs) dom.window.close();
}
