import assert from 'node:assert/strict';
import { openServerState } from '../federation/web/browser-state.js';
const wallTimeout=globalThis.setTimeout;
globalThis.setTimeout=callback=>wallTimeout(callback,0);

class Storage {
  values = new Map(); writes = [];
  getItem(key) { return this.values.get(key) ?? null; }
  setItem(key, value) { this.writes.push(key); this.values.set(key, value); }
  removeItem(key) { this.values.delete(key); }
}
function environment() {
  const local = new Storage(), session = new Storage(), requests = [];
  globalThis.localStorage = local;
  globalThis.window = { localStorage: local, sessionStorage: session };
  let value = {}, fail = false;
  globalThis.fetch = async (url, options = {}) => {
    const body = options.body && JSON.parse(options.body);
    requests.push({ url, options, body });
    if (fail) return { ok: false, status: 503 };
    if (body) value = body.value;
    return { ok: true, json: async () => ({ saved: true, value: structuredClone(value) }) };
  };
  return { local, session, requests, fail(v) { fail = v; } };
}

{
  const e = environment(), legacy = { notes: { one: '已有短笺' } };
  e.local.setItem('legacy', JSON.stringify(legacy)); e.local.writes = [];
  e.fail(true);
  await assert.rejects(openServerState('journal', 'localStorage', 'legacy'));
  assert.equal(e.local.getItem('legacy'), JSON.stringify(legacy), 'Network failures preserve the original browser copy');
  e.fail(false);
  const state = await openServerState('journal', 'localStorage', 'legacy');
  assert.deepEqual(state.value, legacy);
  assert.equal(e.local.getItem('legacy'), null, 'Only a confirmed import removes the browser copy');
  assert.deepEqual(e.local.writes, [], 'No notebook content is written back to browser storage');
  const first = state.save({ notes: { one: '新稿' } });
  const second = state.save({ notes: { one: '后续修改' } });
  await Promise.all([first, second]);
  assert.deepEqual(e.requests.at(-1).body.before, { notes: { one: '新稿' } }, 'Writes preserve their order');
  e.fail(true); await assert.rejects(state.save({ notes: { one: '失败后保留' } }));
  e.fail(false); await state.save({ notes: { one: '重试' } });
  assert.deepEqual(e.requests.at(-1).body.before, { notes: { one: '后续修改' } }, 'Failed saves do not advance the confirmed base');
}
{
  const e = environment();
  e.session.setItem('legacy-chat', JSON.stringify({ drafts: [['room', '待发送草稿']] })); e.session.writes = [];
  const state = await openServerState('chat', 'sessionStorage', 'legacy-chat');
  await state.save({ drafts: [['room', '新的草稿']] });
  assert.equal(e.session.getItem('legacy-chat'), null);
  assert.deepEqual(e.session.writes, []);
  assert.deepEqual(e.local.writes, ['weiming.browser-client.v1']);
  assert.match(e.local.getItem('weiming.browser-client.v1'), /^[a-f0-9]{32}$/);
  assert.ok(e.requests.every(r => /^\/api\/browser-state\/chat-[a-f0-9]{32}$/.test(r.url)));
}
{
  const e=environment(), state=await openServerState('chat','sessionStorage','legacy-chat');
  const realFetch=globalThis.fetch, realTimeout=globalThis.setTimeout;
  let attempts=0;
  globalThis.setTimeout=callback=>realTimeout(callback,0);
  globalThis.fetch=async (...args)=>{
    attempts++;
    if(attempts===1)return {ok:false,json:async()=>({code:'release_draining',accepted:false})};
    if(attempts===2)throw new TypeError('API is restarting');
    return realFetch(...args);
  };
  try {
    const first=state.save({drafts:[['room','被拒绝的未发送消息']]});
    const second=state.save({drafts:[['room','用户继续编辑']]});
    await Promise.all([first,second]);
    assert.equal(attempts,4);
    assert.deepEqual(e.requests.at(-1).body.before,{drafts:[['room','被拒绝的未发送消息']]});
    assert.deepEqual(e.requests.at(-1).body.value,{drafts:[['room','用户继续编辑']]});
    assert.deepEqual(e.local.writes,['weiming.browser-client.v1']);
    let disconnected=0;
    globalThis.fetch=async(...args)=>{if(++disconnected===1)throw new TypeError('API restart before 503');return realFetch(...args);};
    await state.save({drafts:[['room','重启窗口中的新草稿']]});
    assert.equal(disconnected,2);
    let refused=0;
    globalThis.fetch=async()=>{refused++;return {ok:false,json:async()=>({code:'release_draining',accepted:false})};};
    await assert.rejects(state.save({drafts:[['room','尚未保存']]}),/安全发布/);
    assert.equal(refused,30);
  } finally {globalThis.fetch=realFetch;globalThis.setTimeout=realTimeout;}
}
globalThis.setTimeout=wallTimeout;
process.stdout.write('Server browser-state migration, save ordering, bounded release retry, failure retention and content-free browser storage passed.\n');
