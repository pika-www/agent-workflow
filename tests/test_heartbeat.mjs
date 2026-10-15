/** The heart traces received activity, never a timer presented as model output. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { createRequire } from 'node:module';

const require = createRequire(new URL('../openwiki-upstream/package.json', import.meta.url));
const { JSDOM } = require('jsdom');
const source = fs.readFileSync(new URL('../federation/web/workspace.js', import.meta.url), 'utf8');
const html = fs.readFileSync(new URL('../federation/web/workspace.html', import.meta.url), 'utf8');
const controller = source.slice(source.indexOf('  function createHeartbeat()'), source.indexOf('  const stageName ='));
const stageLabel = vm.runInNewContext(source.split('\n').find(line => line.startsWith('  const stageName =')) + '\nstageName',
  {active:status=>['queued','running'].includes(status)});
assert.equal(stageLabel({action:'ask',status:'completed',intake_stage:'reading_memory'}),'读取已确认要求');
assert.equal(stageLabel({action:'ask',status:'completed',intake_stage:'answered'}),'已回复');

function fixture(reduced = false) {
  const dom = new JSDOM(html, { url: 'http://127.0.0.1:18732/', pretendToBeVisual: true });
  const document = dom.window.document, frames = new Map(), motionListeners = new Set();
  let time = 100, next = 0;
  const motion = { matches: reduced,
    addEventListener: (_, callback) => motionListeners.add(callback),
    removeEventListener: (_, callback) => motionListeners.delete(callback) };
  dom.window.matchMedia = () => motion;
  const context = vm.createContext({ window: dom.window, document, performance: { now: () => time },
    $: id => document.getElementById(id), state: { stopped: false },
    active: status => ['queued', 'running'].includes(status),
    clock: value => new Date(value).toISOString().slice(11, 19),
    agentName: id => id === 'central' ? '主 Agent' : '前端 Agent',
    requestAnimationFrame: callback => { frames.set(++next, callback); return next; },
    cancelAnimationFrame: id => frames.delete(id) });
  const heart = vm.runInContext(controller + '\ncreateHeartbeat()', context);
  const get = id => document.getElementById(id);
  return { heart, frames, context, dom, motionListeners,
    mode: () => get('ws-pulse').dataset.mode,
    path: () => get('ws-pulse').querySelector('path').getAttribute('d'),
    label: () => get('ws-heart-signal').textContent,
    title: () => get('ws-heart-state').textContent,
    advance(ms) { time += ms; const callbacks = [...frames.values()]; frames.clear(); callbacks.forEach(cb => cb(time)); },
    reduce(value) { motion.matches = value; motionListeners.forEach(callback => callback()); },
    close() { heart.destroy(); dom.window.close(); } };
}
const room = { id: 'room-a', status: 'running', active_job_id: 'job-a' };
const reply = (revision, text, extra = {}) => ({ job_id: 'job-a', turn_id: 'turn-a', agent_id: 'central', revision, text, ...extra });
const receipt = (observed_at, running = 1) => ({ observed_at: '2026-10-06T12:00:' + observed_at + '+00:00', running, queued: 0 });
const curveYs = trace => [...trace.matchAll(/C([^CHM]+)/g)].flatMap(match =>
  match[1].trim().split(/\s+/).map(Number).filter((_, index) => index % 2 === 1));

// Service arrival produces a small trace; the trace moves with elapsed time.
const f = fixture();
f.heart.room(room);
f.heart.receipt(receipt('01'));
assert.equal(f.mode(), 'waiting');
assert.match(f.label(), /服务回执/);
const servicePath = f.path();
assert.notEqual(servicePath, 'M0 40 H260');
f.advance(400);
assert.notEqual(f.path(), servicePath);
const serviceBeforeDuplicate = f.path();
f.heart.receipt(receipt('01'));
assert.equal(f.path(), serviceBeforeDuplicate, 'same receipt must not invent another peak');

// Incremental Unicode characters set the two-second receive rate and a larger peak.
f.heart.reply(reply(1, '你好🙂啊'));
assert.equal(f.mode(), 'reply');
assert.equal(f.label(), '接收 2 字/秒 · 文本回执');
assert.equal(f.title(), '主 Agent 正在回复');
const textPath = f.path();
assert.ok(Math.min(...curveYs(textPath)) < Math.min(...curveYs(servicePath)), 'text pulse is stronger than a service receipt');
f.heart.reply(reply(1, '重复的包不应算作新增文本'));
f.heart.reply(reply(0, '旧版本'));
f.heart.reply(reply(2, '别的任务', { job_id: 'job-old' }));
assert.equal(f.label(), '接收 2 字/秒 · 文本回执');
assert.equal(f.path(), textPath);
f.advance(450);
assert.notEqual(f.path(), textPath, 'text pulse moves, rather than a fixed ECG with dash animation');
f.heart.reply(reply(2, '你好🙂啊' + '字'.repeat(40)));
assert.equal(f.label(), '接收 22 字/秒 · 文本回执');
assert.ok(Math.min(...curveYs(f.path())) < Math.min(...curveYs(textPath)), 'larger text batches produce a stronger pulse');

// A poll duplicating an SSE snapshot is counted once. Silence goes back to waiting.
f.heart.room({ ...room, live_reply: reply(2, '你好🙂啊' + '字'.repeat(40)) });
assert.equal(f.label(), '接收 22 字/秒 · 文本回执');
f.advance(2600);
assert.equal(f.mode(), 'waiting');
assert.match(f.label(), /慢脉冲/);
const silentPath = f.path();
f.heart.receipt(receipt('05'));
assert.notEqual(f.path(), silentPath, 'fresh service receipt, not silence, triggers a small peak');

// Task completion clears the graph. Old jobs cannot revive a completed room.
f.heart.room({ ...room, active_job_id: null, status: 'idle' });
f.heart.receipt(receipt('06', 0));
assert.equal(f.mode(), 'idle');
assert.equal(f.path(), 'M0 40 H260');
f.heart.reply(reply(3, '旧任务姗姗来迟'));
assert.equal(f.mode(), 'idle');
assert.equal(f.frames.size, 0);

// Reloading/opening a live conversation seeds historical text without a fake burst.
f.heart.room({ ...room, live_reply: reply(5, '已经收到的历史文字') });
f.heart.receipt(receipt('07'));
assert.equal(f.mode(), 'waiting');
f.advance(400);
f.heart.reply(reply(6, '已经收到的历史文字新增'));
assert.equal(f.label(), '接收 1 字/秒 · 文本回执');
f.heart.offline();
assert.equal(f.mode(), 'offline');
assert.equal(f.path(), 'M0 40 H260');
assert.match(f.title(), /未连接/);
f.heart.setVisible(false);
assert.equal(f.frames.size, 0);
f.heart.receipt(receipt('08'));
assert.equal(f.frames.size, 0, 'hidden panel must not animate');
f.heart.setVisible(true);
assert.ok(f.frames.size > 0);
f.reduce(true);
assert.equal(f.frames.size, 0);
assert.equal(f.path(), 'M0 40 H260');
f.heart.reply(reply(7, '已经收到的历史文字新增文字'));
assert.equal(f.label(), '接收 2 字/秒 · 文本回执');
f.reduce(false);
assert.ok(f.frames.size > 0);
f.heart.destroy();
assert.equal(f.frames.size, 0);
assert.equal(f.motionListeners.size, 0);
f.dom.window.close();

const reduced = fixture(true);
reduced.heart.receipt(receipt('01'));
reduced.heart.room(room);
reduced.heart.reply(reply(1, '文本仍然更新'));
assert.equal(reduced.mode(), 'reply');
assert.equal(reduced.label(), '接收 3 字/秒 · 文本回执');
assert.equal(reduced.path(), 'M0 40 H260');
assert.equal(reduced.frames.size, 0);
reduced.heart.room({ ...room, status: 'failed', active_job_id: null });
reduced.heart.receipt(receipt('02', 0));
assert.equal(reduced.mode(), 'failed');
assert.match(reduced.label(), /失败信息/);
reduced.close();
console.log('Heartbeat: real text/receipt pulses, scrolling, Unicode receive rate, deduplication, stale jobs, silence, completion, reload, offline, hidden view and reduced motion passed.');
