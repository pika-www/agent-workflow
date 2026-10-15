/** One-request context accounting, accessible composer disclosure, no provider calls. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {createRequire} from 'node:module';
const require = createRequire(new URL('../openwiki-upstream/package.json', import.meta.url));
const {JSDOM} = require('jsdom');
const source = fs.readFileSync(new URL('../federation/web/agent-chat.js', import.meta.url), 'utf8');
function extract(name) {
  const start = source.search(new RegExp(`  function ${name}\\(`));
  assert.ok(start >= 0, name);
  return source.slice(start, source.indexOf('\n  }', start) + 4);
}
const meterMarkup = source.match(/<details class="ag-context-meter"[\s\S]*?<\/details>/)[0];
const dom = new JSDOM(`<body><div id="ag-dialog"><form>${meterMarkup}<textarea id="ag-message"></textarea></form></div>`, {runScripts:'outside-only'});
const {window} = dom, document = window.document;
vm.runInContext(`
  const state={sending:new Set(),memoryView:'tasks'};
  const $=id=>document.getElementById('ag-'+id);
  const make=(tag,cls,text)=>{const node=document.createElement(tag);if(cls)node.className=cls;if(text!==undefined)node.textContent=String(text);return node;};
  const active=status=>['running','queued'].includes(status);
  const agentName=id=>id || 'Agent', date=value=>value;
  let openedMemory=0; const openMemory=()=>openedMemory++;
  ${['contextAdjustment','composerContext','contextSummaryText','renderComposerContext','bindComposerContext'].map(extract).join('\n')}
  window.testContext={state,composerContext,renderComposerContext,bindComposerContext,openedMemory:()=>openedMemory};
`,dom.getInternalVMContext());
const {state,composerContext,renderComposerContext:render,bindComposerContext:bind} = window.testContext;
const meter = document.getElementById('ag-context-meter'), toggle = document.getElementById('ag-context-toggle');
const body = document.getElementById('ag-context-body'), ring = document.getElementById('ag-context-fill');
const reply = {id:'reply',role:'assistant',agent_id:'central',model:'qwen',context_usage:{enabled:true,context_window:32768,budget:12000,output_reserve:4096,
  input_tokens_estimated:11755,reply:{input_tokens:5512,output_tokens:191,cached_tokens:5000},total_input_tokens:8877,total_calls:4,
  summary:{status:'generated',input_tokens:1863},summary_persistence:{status:'saved'}}};
const room = {id:'room',status:'idle',messages:[reply]};
render(room);
assert.equal(composerContext(room).input,5512,'Use the last reply call, never the multi-call total, estimate or cache-subtracted count');
assert.match(body.textContent,/5,512 \/ 32,768 Token/);
assert.match(body.textContent,/17% 输入占用/);
assert.doesNotMatch(body.textContent,/8,877|11,755/);
assert.match(body.textContent,/本地配置.*尚未.*校验/);
assert.match(body.textContent,/任务摘要 · 已保存/);
meter.open=true;
const originalLink=body.querySelector('button'); originalLink.focus(); render(room);
assert.equal(document.activeElement,originalLink,'An unchanged poll keeps disclosure focus and DOM');
assert.equal(meter.open,true);
render({...room,status:'running'});
assert.match(body.textContent,/本轮处理中.*发送消息不会清空/);
assert.equal(composerContext({...room,status:'running'}).input,5512);
assert.match(toggle.getAttribute('aria-label'),/更新中，保留已有用量/);
assert.equal(ring.style.strokeDasharray,'17 100','Sending must retain the known usage instead of resetting the ring');
assert.equal(meter.dataset.level,'normal');
assert.match(toggle.title,/17%.*更新中/);
render({...room,status:'running',active_job_id:'current',live_reply:{job_id:'current',context_compaction:{stage:'runtime',before_tokens:26000,after_tokens:20000,budget_tokens:28160}}});
assert.match(body.textContent,/本轮压缩回执：处理前约 26,000 → 处理后约 20,000/);
render({...room,status:'running',active_job_id:'current',live_reply:{job_id:'stale',context_compaction:{stage:'runtime',before_tokens:26000,after_tokens:20000,budget_tokens:28160}}});
assert.doesNotMatch(body.textContent,/本轮压缩回执/,'Do not borrow a previous job compaction');
render({...room,messages:[{...reply,context_usage:{...reply.context_usage,selection:{before_tokens:20000,after_tokens:11000,budget_tokens:12000}}}]});
assert.match(body.textContent,/按预算节选资料/);assert.doesNotMatch(body.textContent,/自动压缩/);

const estimate = {...room,messages:[{...reply,context_usage:{...reply.context_usage,reply:{input_tokens:null},summary:{status:'failed_using_previous_and_originals'}}}]};
render(estimate);
assert.equal(composerContext(estimate).estimated,true);
assert.match(body.textContent,/约 11,755/);
assert.match(body.textContent,/初始选材估算/);
assert.match(body.textContent,/工具续接后的输入量/);
assert.match(body.textContent,/摘要未成功/);
const unknown = {...room,messages:[{id:'unknown',role:'assistant',native_stream:{usage:[{input_tokens:700},{input_tokens:9000,output_tokens:30}]}}]};
render(unknown);
assert.equal(composerContext(unknown).input,9000,'Native rounds use the final call, not the sum');
assert.equal(composerContext(unknown).percent,null,'No guessed window for a different model or report route');
assert.match(body.textContent,/9,000 Token/);
assert.doesNotMatch(body.textContent,/%/);
assert.equal(meter.dataset.level,'unknown');

const missing = {...room,messages:[reply,{id:'new',role:'assistant',content:'host answer without usage'}]};
render(missing);
assert.equal(composerContext(missing).input,null,'A newer answer without usage does not silently borrow the previous receipt');
assert.match(body.textContent,/输入用量尚未提供/);
assert.doesNotMatch(toggle.title,/0%/);
render({...room,messages:[{...reply,context_usage:{...reply.context_usage,total_calls:0,reply:{input_tokens:0,output_tokens:0}}}]});
assert.match(body.textContent,/未调用回复模型/);
assert.doesNotMatch(body.textContent,/%/);
assert.equal(meter.dataset.level,'unknown');
assert.equal(ring.style.strokeDasharray,'0 100');
render({...room,messages:[{...reply,context_usage:{context_window:100,reply:{input_tokens:150},total_input_tokens:99999}}]});
assert.match(body.textContent,/150%/,'An over-budget receipt stays visible instead of hiding the overrun');
assert.equal(ring.style.strokeDasharray,'100 100','SVG arc stays bounded');
assert.equal(meter.dataset.level,'high');
render({...room,messages:[{...reply,context_usage:{context_window:100,reply:{input_tokens:'10'},input_tokens_estimated:-1}}]});
assert.equal(composerContext({...room,messages:[]}).input,null);
assert.match(body.textContent,/输入用量尚未提供/,'Invalid numeric values cannot create a percentage');

bind(); render(room); meter.open=true;
const escape=new window.KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true});
toggle.dispatchEvent(escape);
assert.equal(meter.open,false);assert.equal(escape.defaultPrevented,true);assert.equal(document.activeElement,toggle);
meter.open=true;
document.getElementById('ag-message').dispatchEvent(new window.Event('pointerdown',{bubbles:true}));
assert.equal(meter.open,false,'Outside click closes only the disclosure');
meter.open=true;render({...room,id:'other-room'});assert.equal(meter.open,false,'Switching rooms resets the disclosure');
meter.open=true;body.querySelector('button').click();assert.equal(meter.open,false);
assert.equal(state.memoryView,'usage');assert.equal(window.testContext.openedMemory(),1);
const literal = {...room,messages:[{...reply,model:'<img src=x onerror=alert(1)>'}]};
render(literal);assert.equal(body.querySelector('img'),null,'Metadata always uses literal text');
console.log('Context indicator: per-call receipts, estimates, missing windows, pending turns, disclosure keyboard and room isolation passed.');
