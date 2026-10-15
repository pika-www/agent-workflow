/** Reader fallback, external-origin isolation and asynchronous view choices. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { createRequire } from 'node:module';

const require = createRequire(new URL('../openwiki-upstream/package.json', import.meta.url));
const { JSDOM } = require('jsdom');
const dom = new JSDOM(fs.readFileSync(new URL('../federation/web/workspace.html', import.meta.url), 'utf8'),
  { url: 'http://127.0.0.1:18732/' });
const { document } = dom.window;
const source = fs.readFileSync(new URL('../federation/web/workspace.js', import.meta.url), 'utf8');
const helpers = source.slice(source.indexOf('  const $ ='), source.indexOf('  const state ='));
const publicUrl = source.slice(source.indexOf('  function publicUrl('), source.indexOf('  function renderHotspots('));
const readers = source.slice(source.indexOf('  function updateHotspotChatContext('), source.indexOf("  $('ws-reader-back').addEventListener"));
const state = { readerEpoch: 0, selectedHotspot: null, hotOpen: true };
let nextResponse;
dom.window.openWikiChat = { renderBody(text) { const body = document.createElement('div'); body.textContent = text; return body; } };
const context = vm.createContext({ document, window: dom.window, URL, AbortSignal, state, globe: null,
  fetch: () => nextResponse });
vm.runInContext(helpers + publicUrl + readers, context);
const item = { id: 'douyin-item', source_id: 'douyin', source: '抖音热榜', title: '动态热点',
  rank: 1, url: 'https://www.douyin.com/hot/2682883' };
const reply = article => ({ ok: true, json: async () => article });
const byId = id => document.getElementById(id);

// Only a known platform origin can be embedded; public links do not grant iframe access.
for (const url of ['http://www.douyin.com/hot/1', 'https://127.0.0.1/', 'https://www.douyin.com.evil.test/',
  'https://user:secret@www.douyin.com/', 'https://www.douyin.com:8080/', 'javascript:alert(1)']) {
  assert.equal(context.readerFrameUrl({ ...item, url }), null);
}
assert.equal(context.readerFrameUrl({ ...item, source_id: 'unknown' }), null);

// A failed body exposes a real viewing route; embedding is an explicit choice, not a success claim.
nextResponse = Promise.resolve(reply({ status: 'unavailable', error: '动态页面', text: '' }));
await context.openHotspot(item);
assert.equal(byId('ws-reader-fallback').hidden, false);
assert.equal(byId('ws-reader-web').hidden, true);
assert.equal(byId('ws-reader-fallback-open').href, item.url);
byId('ws-reader-fallback-frame').click();
let frame = byId('ws-reader-frame-host').querySelector('iframe');
assert.equal(frame.src, item.url);
assert.equal(frame.referrerPolicy, 'no-referrer');
assert.equal(frame.getAttribute('sandbox'), 'allow-scripts allow-same-origin allow-forms');
assert.equal(frame.getAttribute('allow'), 'fullscreen; picture-in-picture');
assert.equal(byId('ws-reader-text-view').hidden, true);
assert.equal(byId('ws-reader-web').hidden, false);
assert.match(byId('ws-reader-web-note').textContent, /只有榜单标题.*不会自动提供给 Agent/);
assert.equal(byId('ws-reader-open').href, item.url);
assert.equal(byId('ws-reader-open').target, '_blank');
assert.match(byId('ws-reader-open').rel, /noopener/);
byId('ws-reader-text').click();
assert.equal(byId('ws-reader-frame-host').childElementCount, 0, 'Switching views stops the external page');
assert.equal(byId('ws-reader-text-view').hidden, false);

// An explicit text choice while reading is in flight must survive a failed response.
let complete;
nextResponse = new Promise(resolve => { complete = resolve; });
const pending = context.openHotspot(item);
byId('ws-reader-text').click();
complete(reply({ status: 'unavailable', error: '动态页面', summary: '真实摘要' }));
await pending;
assert.equal(byId('ws-reader-web').hidden, true);
assert.equal(byId('ws-reader-body').textContent, '真实摘要');

// Opening the original before extraction finishes keeps the chosen view and updates evidence status.
nextResponse = new Promise(resolve => { complete = resolve; });
const ready = context.openHotspot(item);
byId('ws-reader-original').click();
complete(reply({ status: 'ready', text: '已验证正文' }));
await ready;
assert.equal(byId('ws-reader-web').hidden, false);
assert.match(byId('ws-reader-web-note').textContent, /Agent 已读取正文/);
context.closeReader();
assert.equal(byId('ws-reader-frame-host').childElementCount, 0);

// A late old-item response must not overwrite the next item's links, content or view.
nextResponse = new Promise(resolve => { complete = resolve; });
const old = context.openHotspot(item);
const github = { ...item, id: 'github-item', source_id: 'github', source: 'GitHub',
  title: 'tester-army/e2e', url: 'https://github.com/tester-army/e2e' };
nextResponse = Promise.resolve(reply({ status: 'ready', text: 'GitHub 正文' }));
await context.openHotspot(github);
complete(reply({ status: 'unavailable', error: '旧请求' }));
await old;
assert.equal(byId('ws-reader-original').disabled, true);
assert.match(byId('ws-reader-original').title, /禁止跨站嵌入/);
assert.equal(byId('ws-reader-open').href, github.url);
assert.equal(byId('ws-reader-body').textContent, 'GitHub 正文');
assert.equal(byId('ws-reader-frame-host').childElementCount, 0);

// A network failure exposes the link and an optional iframe attempt, without a fabricated body.
nextResponse = Promise.reject(new Error('读取超时'));
await context.openHotspot(item);
assert.equal(byId('ws-reader-fallback').hidden, false);
assert.equal(byId('ws-reader-web').hidden, true);
byId('ws-reader-original').click();
assert.equal(byId('ws-reader-web').hidden, false);
assert.match(byId('ws-reader-status').textContent, /读取超时/);
assert.equal(byId('ws-reader-body').textContent, '');
context.closeReader();
dom.window.close();
console.log('Hotspot iframe: trusted origins, real failure fallback, isolated frame, explicit choices, late responses and cleanup passed.');
