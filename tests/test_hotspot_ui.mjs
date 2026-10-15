/** Real DOM: added platforms, safe text, score labels and reconnect recovery. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { createRequire } from 'node:module';

const require = createRequire(new URL('../openwiki-upstream/package.json', import.meta.url));
const { JSDOM } = require('jsdom');
const html = fs.readFileSync(new URL('../federation/web/workspace.html', import.meta.url), 'utf8');
const source = fs.readFileSync(new URL('../federation/web/workspace.js', import.meta.url), 'utf8');
const dom = new JSDOM(html, { url: 'http://127.0.0.1:18732/' });
const { document } = dom.window;
const common = source.slice(source.indexOf('  const $ ='), source.indexOf('  const state ='));
const clock = source.split('\n').find(line => line.startsWith('  const clock ='));
const functions = source.slice(source.indexOf('  function compact('), source.indexOf('  function updateHotspotChatContext('));
const opened = [];
const context = vm.createContext({ document, window: dom.window, URL, state: { hotKey: '' },
  openHotspot: item => opened.push(item.id) });
vm.runInContext(common + clock + '\n' + functions, context);

const data = { checked_at: '2026-10-06T11:34:00Z', sources: [
  ['openai', 'OpenAI', 'ai'], ['google-ai', 'Google AI', 'ai'], ['baidu', '百度热搜', 'general'],
  ['bilibili', '哔哩哔哩', 'general'], ['douyin', '抖音热榜', 'general'], ['github', 'GitHub', 'tech'],
].map(([id,name,group]) => ({ id, name, group, status: 'ready', fetched_at: '2026-10-06T11:34:00Z',
  items: [{ id: id+'-item', title: id+' headline', url: 'https://example.com/'+id,
    rank: 1, score: 1720, score_label: id === 'github' ? '今日新增 Star' : '平台热度' }] })) };
data.sources.push({ id: 'xiaohongshu', name: '小红书', kind: 'pending', group: 'general',
  status: 'unavailable', description: '小红书热点 · 待接入', error: 'HTTP 406，尚未接入', items: [] });
data.items = data.sources.flatMap(source => source.items);
data.sources.find(source => source.id === 'baidu').data_route = {method:'mcp', label:'开源 MCP · 本机', board:'热搜榜'};
data.sources.find(source => source.id === 'douyin').data_route = {method:'direct', label:'平台公开来源 · MCP 暂不可用，已回退'};
context.renderHotspots(data);
assert.match(document.querySelector('[data-source-id="baidu"]').textContent, /开源 MCP · 本机 · 热搜榜/);
assert.match(document.querySelector('[data-source-id="douyin"]').textContent, /MCP 暂不可用，已回退/);
assert.equal(document.querySelector('#ws-hot-available').textContent, '6/7');
assert.equal(document.querySelector('#ws-hot-ai-count').textContent, '3');
assert.equal(document.querySelector('#ws-hot-general-count').textContent, '3');
assert.equal(document.querySelector('#ws-hot-source').options.length, 8);
assert.equal(document.querySelector('option[value="xiaohongshu"]').textContent, '小红书（待接入）');
const github = document.querySelector('[data-source-id="github"]');
assert.equal(github.parentElement.id, 'ws-hot-ai');
assert.equal(github.querySelector('.ws-score').title, '今日新增 Star');
assert.equal(github.querySelector('.ws-score').textContent, '1,720 ★');
github.querySelector('button').click();
assert.deepEqual(opened, ['github-item']);
const xhs = document.querySelector('[data-source-id="xiaohongshu"]');
assert.equal(xhs.querySelectorAll('.ws-hot-item').length, 0);
assert.match(xhs.textContent, /HTTP 406，尚未接入/);

// A transient service error must clear even if the recovered feed is identical.
document.querySelector('#ws-hot-time').textContent = '本地服务未连接';
context.renderHotspots(data);
assert.match(document.querySelector('#ws-hot-time').textContent, /采集.*每 5 分钟更新/);
assert.equal(document.querySelector('[data-source-id="github"]'), github, 'Unchanged feeds need no rebuild');

document.querySelector('#ws-hot-source').value = 'github';
document.querySelector('#ws-hot-ai').scrollTop = 360;
document.querySelector('#ws-hot-general').scrollTop = 720;
const attack = '<img src="https://tracker.example/pixel" onerror="alert(1)">';
data.sources[0].name = attack;
data.sources[0].description = attack;
data.sources[0].items[0].title = attack;
data.sources[0].items.push({ title: 'bad link', url: 'javascript:alert(1)' });
context.renderHotspots(data);
assert.equal(document.querySelector('#ws-hot-source').value, 'github');
assert.equal(document.querySelector('#ws-hot-ai').scrollTop, 360, 'Updated feeds preserve the reading position');
assert.equal(document.querySelector('#ws-hot-general').scrollTop, 720);
assert.equal(document.querySelectorAll('.ws-feed img, .ws-feed script').length, 0);
assert.equal(document.querySelectorAll('.ws-feed a[href^="javascript:"]').length, 0);
assert.match(document.querySelector('[data-source-id="openai"]').textContent, /<img src=/);
dom.window.close();
console.log('Hotspot DOM: seven platform states, tech grouping, daily Star label, safe text/links, item reader and unchanged-feed reconnect recovery passed.');
