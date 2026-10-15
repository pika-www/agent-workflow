/** Separate employee mention and Skill slash pickers, using the actual DOM handlers and mention insertion. */
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import vm from 'node:vm';
const require=createRequire(new URL('../openwiki-upstream/package.json',import.meta.url));
const {JSDOM}=require('jsdom');
const source=readFileSync(new URL('../federation/web/agent-chat.js',import.meta.url),'utf8');
function extract(name){const start=source.indexOf('  function '+name+'(');assert.ok(start>=0);return source.slice(start,source.indexOf('\n  }',start)+4);}
const dom=new JSDOM('<!doctype html><body><section id="ag-dialog"><header class="ag-dialog-header"></header><form id="ag-message-form"><textarea id="ag-message"></textarea><footer class="ag-compose-footer"><span class="ag-compose-hint"></span><button type="submit">发送</button></footer></form></section></body>',{runScripts:'outside-only',url:'http://127.0.0.1/'});
const {window}=dom;window.HTMLElement.prototype.scrollIntoView=function(){};
vm.runInContext(`
 const state={roomId:'room',loaded:true,agents:[
  {id:'central',name:'主 Agent',description:'日常问答与协作',depth:0},
  {id:'software',name:'互联网与软件 Agent',description:'软件领域',depth:1,parent_id:'central'},
  {id:'frontend',name:'前端 Agent',description:'Web 前端、浏览器性能与交互',depth:2,parent_id:'software',ancestor_ids:['central','software']},
  {id:'design',name:'设计 Agent',description:'交互、用户研究、体验、前端交接',depth:2,parent_id:'software',ancestor_ids:['central','software']},
  {id:'xss',name:'<img src=x onerror=alert(1)> Agent',description:'<script>attack()</script>',depth:2,parent_id:'software',ancestor_ids:['central','software']}]};
 const $=id=>document.getElementById('ag-'+id);
 const make=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};
 const agent=id=>state.agents.find(a=>a.id===id), depth=a=>a?.depth || 0;
 const industryId=a=>(a.ancestor_ids || []).find(id=>depth(agent(id))===1) || a.id;
 ${extract('orderedAgents')}
 ${extract('mentionAgent')}
 ${extract('setupAgentPicker')}
 const catalogs={central:[
  {id:'pdf',display_name:'PDF 创建与处理',description:'阅读 PDF 文件并检查排版',status:'ready'},
  {id:'documents',display_name:'文档创建与编辑',description:'Word 文档处理',status:'ready'},
  {id:'broken',display_name:'损坏技能',description:'不可选择',status:'conflict'}],
  frontend:[{id:'client-test',display_name:'客户端测试',description:'浏览器交互测试',status:'ready'},
  {id:'documents',display_name:'文档创建与编辑',description:'Word 文档处理',status:'ready'}],
  design:[{id:'documents',display_name:'文档创建与编辑',description:'Word 文档处理',status:'ready'}]};
 window.requests=[];window.catalogs=catalogs;window.delayed=new Map();
 const api=async path=>{window.requests.push(path);if(window.delayed.has(path))return window.delayed.get(path);const id=path.split('/')[3];if(!catalogs[id])throw new Error('offline');return {skills:catalogs[id]};};
 window.state=state;setupAgentPicker();
`,dom.getInternalVMContext());
const input=window.document.getElementById('ag-message'),menu=window.document.getElementById('ag-agent-picker'),button=window.document.getElementById('ag-agent-picker-open'),search=window.document.querySelector('.ag-agent-picker-search');
let submits=0;window.document.querySelector('form').addEventListener('submit',e=>{e.preventDefault();submits++;});
const type=value=>{input.value=value;input.setSelectionRange(value.length,value.length);input.dispatchEvent(new window.Event('input',{bubbles:true}));};
const key=(name,options={})=>input.dispatchEvent(new window.KeyboardEvent('keydown',{key:name,bubbles:true,cancelable:true,...options}));
const options=()=>[...menu.querySelectorAll('[role=option]')];
type('@');assert.equal(menu.hidden,false);assert.equal(options().length,5);assert.equal(input.getAttribute('aria-controls'),'ag-agent-picker-list');
assert.equal(menu.querySelector('img'),null);assert.equal(menu.querySelector('script'),null,'Names/descriptions stay text');
key('ArrowUp');assert.equal(options().at(-1).getAttribute('aria-selected'),'true');key('ArrowDown');assert.equal(options()[0].getAttribute('aria-selected'),'true');
type('@浏览器');assert.equal(options().length,1,'Find by actual purpose as well as name');key('Enter');assert.equal(input.value,'@前端 Agent ');assert.equal(menu.hidden,true);assert.equal(submits,0);
type('解释这个问题 @设计 后续内容');const caret=input.value.indexOf(' 后续内容');input.setSelectionRange(caret,caret);input.dispatchEvent(new window.Event('input',{bubbles:true}));
key('Tab');assert.equal(input.value,'解释这个问题 @设计 Agent  后续内容','Replace only the slash token, preserving prefix and suffix');
type('@没有这种智能体');assert.equal(options().length,0);assert.match(menu.textContent,/没有匹配/);key('Enter');assert.equal(input.value,'@没有这种智能体');key('Escape');assert.equal(menu.hidden,true);
for(const value of ['/学习 研究产品','/记住 我喜欢简短回复','/忘记 偏好','https://example.com/path','/Users/me/file.txt','1 / 2','`@前端','person@example.com']){type(value);assert.equal(menu.hidden,true,value);}
type('@前端');assert.match(options()[0].textContent,/^前端/,'Exact name precedes matches in descriptions');key('Enter',{isComposing:true});assert.equal(input.value,'@前端');assert.equal(menu.hidden,false);key('Escape');
type('@前端');key('Enter',{shiftKey:true});assert.equal(input.value,'@前端','Shift+Enter remains a newline shortcut, not selection');
window.document.querySelector('button[type=submit]').click();assert.equal(input.value,'@前端 Agent ');assert.equal(submits,0,'Send while selecting must not submit a slash query');
input.value='保留全部草稿';input.setSelectionRange(0,input.value.length);button.click();assert.equal(menu.hidden,false);search.value='用户研究';search.dispatchEvent(new window.Event('input',{bubbles:true}));assert.equal(options().length,1);options()[0].click();assert.equal(input.value,'@设计 Agent 保留全部草稿','Button selection never replaces highlighted draft text');
button.click();search.value='前端';search.dispatchEvent(new window.Event('input',{bubbles:true}));search.dispatchEvent(new window.KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));assert.equal(menu.hidden,true);assert.equal(input.value,'@设计 Agent 保留全部草稿');
type('@前端 Agent 解释一下 @前端');key('Enter');assert.equal((input.value.match(/@前端 Agent/g)||[]).length,1,'Do not insert duplicate recipients');
type('@');window.dispatchEvent(new window.CustomEvent('openwiki:chat-state',{detail:{id:'room-two'}}));assert.equal(menu.hidden,true);
assert.equal(submits,0,'Choosing an employee is never sending a message');

const settle=()=>new Promise(resolve=>setImmediate(resolve));
const skillButton=window.document.getElementById('ag-skill-picker-open');
type('/');assert.equal(menu.getAttribute('aria-label'),'技能目录');assert.match(menu.textContent,/正在读取技能目录/);await settle();
assert.equal(options().length,3);assert.match(options()[0].textContent,/PDF/);assert.equal(options().at(-1).getAttribute('aria-disabled'),'true');
assert.equal(window.requests.length,1,'Opening Skill menu reads the local catalog once');
type('/PDF');await settle();assert.equal(options().length,1);key('Enter');assert.equal(input.value,'$pdf ');assert.equal(menu.hidden,true);assert.equal(submits,0);
type('保留原话 /文档 后续内容');input.setSelectionRange(input.value.indexOf(' 后续内容'),input.value.indexOf(' 后续内容'));input.dispatchEvent(new window.Event('input',{bubbles:true}));key('Enter');assert.equal(input.value,'保留原话 $documents  后续内容');
type('$pdf 核对文档 /PDF');key('Enter');assert.equal(input.value,'$pdf 核对文档 ','No duplicate Skill tokens');
type('@前端');skillButton.click();await settle();search.value='PDF';search.dispatchEvent(new window.Event('input',{bubbles:true}));options()[0].click();assert.equal(input.value,'$pdf ','Switching menu types replaces the unfinished trigger');
type('@前端 Agent /');await settle();assert.match(menu.textContent,/客户端测试/);assert.ok(!options().some(o=>/^PDF/.test(o.textContent)),'Only the selected employee skills appear');
type('@前端 Agent /客户端');key('Enter');assert.equal(input.value,'@前端 Agent $client-test ');
type('@前端 Agent @设计 Agent /');await settle();assert.equal(options().length,1);assert.match(options()[0].textContent,/文档/);assert.match(menu.textContent,/共同技能/);
window.state.room={mode:'direct',participants:['frontend']};type('/');await settle();assert.match(menu.textContent,/客户端测试/);window.state.room=null;
type('保留草稿');input.setSelectionRange(0,input.value.length);skillButton.click();await settle();search.value='PDF';search.dispatchEvent(new window.Event('input',{bubbles:true}));options()[0].click();assert.equal(input.value,'$pdf 保留草稿');
type('/');await settle();const broken=options().find(o=>o.getAttribute('aria-disabled')==='true');broken.click();assert.equal(menu.hidden,false);assert.equal(input.value,'/');key('ArrowUp');assert.notEqual(input.getAttribute('aria-activedescendant'),broken.id,'Keyboard skips unavailable skills');key('Escape');
const keyPath='/api/spaces/central/skills';let release;window.delayed.set(keyPath,new Promise(resolve=>release=resolve));window.dispatchEvent(new window.Event('federation:changed'));type('/');type('@');release({skills:window.catalogs.central});await settle();assert.equal(menu.getAttribute('aria-label'),'员工目录');assert.equal(options().length,5,'Late Skill catalog must not replace employee menu');
window.delayed.delete(keyPath);window.catalogs.central=null;window.dispatchEvent(new window.Event('federation:changed'));type('/');await settle();assert.match(menu.textContent,/暂时未能读取/);assert.equal(options().length,0);
window.catalogs.central=[];menu.querySelector('.ag-text-button').click();await settle();assert.match(menu.textContent,/还没有已导入/);assert.equal(options().length,0);
key('Escape');assert.equal(submits,0);
console.log('Employee/Skill picker passed: @ versus /, real catalog scoping and caching, keyboard/IME, safe metadata, commands/URLs/email, exact insertion, no auto-send, skill tokens, conflicts, multi-employee intersection, failures/retry and stale response guards.');
