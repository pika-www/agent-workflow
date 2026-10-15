import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {createRequire} from 'node:module';
const require=createRequire(new URL('../openwiki-upstream/package.json',import.meta.url));
const {JSDOM}=require('jsdom');
const source=fs.readFileSync(new URL('../federation/web/agent-chat.js',import.meta.url),'utf8');
const extract=name=>{const start=source.indexOf('  function '+name+'(');assert.ok(start>=0,name);return source.slice(start,source.indexOf('\n  }',start)+4);};
const dom=new JSDOM('<div id="ag-turn-label"></div><div id="result"></div>',{runScripts:'outside-only'});
const context=dom.getInternalVMContext();
vm.runInContext(`
 const state={room:{status:'running',active_job_id:'job'}};
 const active=status=>status==='running';const $=id=>document.getElementById('ag-'+id);
 const renderLiveReply=value=>{state.room.live_reply=value;};
 const make=(tag,cls,text)=>{const n=document.createElement(tag);n.className=cls||'';if(text!==undefined)n.textContent=String(text);return n;};
 const rememberDetails=()=>{};
 ${['publicSourceURL','operationTarget','operationReadFailure','operationFailureDetail','replyOperations','validReplyTimeline','recordReplyTimeline','renderOperations','renderNativeAgentEvent'].map(extract).join('\n')}
 window.test={state,renderNativeAgentEvent,renderOperations,replyOperations};
`,context);
const {state,renderNativeAgentEvent:emit,renderOperations,replyOperations}=dom.window.test;
let seq=0;
const event=(type,id,name,status)=>emit({origin:'host_tool',protocol:'responses',type,call_id:id,name,status,target:name==='web_read'?'https://example.org/'+id:'',job_id:'job',seq:++seq,revision:seq});
for(let i=0;i<3;i++)event('agent.tool.started','read-'+i,'web_read');
assert.equal(state.room.live_reply.operations.filter(o=>o.status==='running').length,3);
for(const i of [2,0,1])event('agent.tool.completed','read-'+i,'web_read','completed');
for(let i=3;i<12;i++){const name=i===11?'research_review':'web_read';event('agent.tool.started','step-'+i,name);event('agent.tool.completed','step-'+i,name,'completed');}
const reply=state.room.live_reply;
assert.equal(reply.operations.length,12,'Live progress after the eighth tool must not disappear');
assert.equal(reply.timeline[0].call_ids.length,12);
assert.equal(replyOperations(reply).length,12);
const rendered=renderOperations(reply,'research',{inline:true});dom.window.document.querySelector('#result').append(rendered);
assert.equal(rendered.querySelectorAll('.ag-operation-row').length,12);
assert.match(rendered.textContent,/已核对多来源证据/);
assert.equal(rendered.querySelectorAll('[data-status="running"]').length,0);
assert.match(dom.window.document.querySelector('#ag-turn-label').textContent,/多来源证据核对/);
console.log('Research UI passed: three concurrent rows, out-of-order completion, twelve streamed operations, crosscheck label and complete timeline.');

// Historical robots 403 must override the old, misleading access_restricted label.
const historical={workflow:{receipts:[{call_id:'old',tool:'web_read',args:{url:'https://public.example/page'},status:'unavailable',failure_code:'access_restricted'}],observations:[{result:{status:'unavailable',errors:[{error:'无法确认 robots.txt 访问许可（HTTP 403）'}]}}]}};
const oldRows=replyOperations(historical);assert.equal(oldRows[0].status,'robots_check_failed');assert.match(oldRows[0].failure_detail,/HTTP 403.*尚未请求文章正文/);
const oldDOM=renderOperations(historical,'old');assert.match(oldDOM.textContent,/robots.txt 检查异常/);assert.doesNotMatch(oldDOM.textContent,/文章访问受限/);
const current={workflow:{receipts:[{call_id:'new',tool:'web_read',args:{url:'https://public.example/page'},status:'unavailable'}],observations:[{result:{status:'unavailable',errors:[{code:'article_http_error',stage:'article',http_status:503,attempts:3,error:'文章请求失败'}]}}]}};
const newDOM=renderOperations(current,'new');assert.match(newDOM.textContent,/文章请求失败/);assert.match(newDOM.querySelector('.ag-operation-detail').textContent,/HTTP 503.*3 次/);
emit({origin:'host_tool',protocol:'responses',type:'agent.tool.completed',call_id:'robots-failure',name:'web_read',status:'robots_check_failed',failure_detail:'HTTP 500 · 已尝试 3 次 · 尚未请求文章正文',job_id:'job',seq:++seq,revision:seq});
assert.match(replyOperations(state.room.live_reply).at(-1).failure_detail,/HTTP 500/);
const escaped=renderOperations({operations:[{call_id:'safe',name:'web_read',status:'robots_check_failed',failure_detail:'<img src=x onerror=alert(1)>'}]},'safe');assert.equal(escaped.querySelectorAll('img').length,0);
console.log('Reader UI passed: historical robots errors, structured HTTP/attempt details, live SSE and escaped diagnostics.');
const rejected=renderOperations({operations:[{call_id:'invalid',name:'profit_calculate',status:'invalid_arguments'},{call_id:'absent',name:'file_read',status:'unknown_object'}]},'guards');
assert.match(rejected.textContent,/参数校验未通过，未执行/);assert.match(rejected.textContent,/对象无效，未执行/);assert.doesNotMatch(rejected.textContent,/结果待核对/);
