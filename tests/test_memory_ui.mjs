/** Real DOM management actions, stale writes, scope and literal source rendering. */
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
const require = createRequire(new URL('../openwiki-upstream/package.json',import.meta.url));
const {JSDOM}=require('jsdom');
const source=fs.readFileSync(new URL('../federation/web/agent-chat.js',import.meta.url),'utf8');
const functionNames=[...source.matchAll(/^  (?:async )?function (\w+)\(/gm)].map(m=>m[1]);assert.equal(new Set(functionNames).size,functionNames.length,'Top-level UI handlers must not shadow an existing renderer');
function extract(name){const start=source.search(new RegExp(`  (?:async )?function ${name}\\(`));assert.ok(start>=0,name);return source.slice(start,source.indexOf('\n  }',start)+4);}
const dom=new JSDOM('<!doctype html><body><dialog id="ag-memory-dialog" open></dialog><p id="ag-memory-status"></p><button id="ag-memory-refresh"></button><button id="ag-memory-tasks"></button><button id="ag-memory-personal"></button><label id="ag-memory-agent-label"></label><select id="ag-memory-agent"><option value="central">主 Agent</option></select><div id="ag-memory-list"></div>',{url:'http://127.0.0.1/',runScripts:'outside-only'});
const context=dom.getInternalVMContext(), document=dom.window.document;
const requests=[];
const task={id:'task-1',goal:'使用 Vue 的页面 <img src=x onerror=alert(1)>',status:'active',message_ids:['original'],versions:[],summary:null,
requirement_state:{records:[{id:'rule-1',slot:'framework',label:'前端框架',value:'vue',text:'使用 Vue。',status:'conflict',source_ids:['original']},{id:'rule-2',slot:'framework',label:'前端框架',value:'react',text:'使用 React。',status:'conflict',source_ids:['changed']} ]}};
const data={roomId:'room-1',agentId:'central',tasks:{revision:7,enabled:true,tasks:[task]},personal:{preferences:{pref:{text:'回复用中文',scope:'project',revision:2,versions:[]}},learning:{}}};
Object.assign(context,{state:{memoryEpoch:1,memoryBusy:false,memoryView:'tasks',memoryData:data,roomId:'room-1',room:{title:'隔离测试'},agents:[{id:'central',name:'主 Agent'}]},
agentName:id=>id==='central'?'主 Agent':id,date:String,
api:async(path,options)=>{requests.push({path,options});if(options?.method==='POST')return {status:'saved'};if(path.includes('/sources/'))return {role:'user',created_at:'2026-10-06',content:'原文 <script>window.attack=1</script> 不联网。'};return path==='/api/user-memory'?data.personal:data.tasks;}});
vm.runInContext(`const $=id=>document.getElementById('ag-'+id);const make=(tag,cls,text)=>{const node=document.createElement(tag);if(cls)node.className=cls;if(text!==undefined)node.textContent=String(text);return node;};`+['memoryScopePath','memoryAction','changeMemory','memoryEditor','memoryConfirm','memorySources','renderMemory','loadMemory','projectEditor','renderProjects','renderMemoryUsage','renderContextUsage'].map(extract).join('\n'),context);
const call=(name,...args)=>context[name](...args);
call('renderMemory',data);
assert.equal(document.querySelectorAll('img,script').length,0);
const find=text=>[...document.querySelectorAll('button')].find(button=>button.textContent===text);
find('采用这条要求').click();await new Promise(resolve=>setImmediate(resolve));
assert.deepEqual(JSON.parse(requests.find(r=>r.options?.method==='POST').options.body),{agent_id:'central',task_id:'task-1',expected_revision:7,action:'resolve',requirement_id:'rule-1'});
assert.equal(context.state.memoryBusy,false);assert.equal(find('修正目标').disabled,false);
find('修正目标').click();const input=document.querySelector('textarea');input.value='新的目标';document.querySelector('form').dispatchEvent(new dom.window.Event('submit',{cancelable:true}));await new Promise(resolve=>setImmediate(resolve));
assert.equal(JSON.parse(requests.filter(r=>r.options?.method==='POST').at(-1).options.body).text,'新的目标');
const read=[...document.querySelectorAll('button')].find(button=>button.textContent.startsWith('读取原消息'));read.click();await new Promise(resolve=>setImmediate(resolve));
assert.ok(document.querySelector('pre').textContent.includes('<script>'));assert.equal(document.querySelectorAll('script').length,0);
context.state.memoryView='personal';call('renderMemory',data);find('修正').click();document.querySelector('textarea').value='回复用中文，语气温和';document.querySelector('form').dispatchEvent(new dom.window.Event('submit',{cancelable:true}));await new Promise(resolve=>setImmediate(resolve));
assert.equal(JSON.parse(requests.filter(r=>r.options?.method==='POST').at(-1).options.body).expected_revision,2);
find('忘记').click();assert.equal(requests.filter(r=>r.options?.method==='POST').length,3);find('确认忘记').click();await new Promise(resolve=>setImmediate(resolve));
assert.equal(JSON.parse(requests.filter(r=>r.options?.method==='POST').at(-1).options.body).forget,true);
context.api=async()=>{throw new Error('记忆版本已变化');};find('修正').click();document.querySelector('textarea').value='保留这段未保存修正';document.querySelector('form').dispatchEvent(new dom.window.Event('submit',{cancelable:true}));await new Promise(resolve=>setImmediate(resolve));
assert.equal(document.querySelector('textarea').value,'保留这段未保存修正');assert.ok(document.getElementById('ag-memory-status').textContent.includes('未自动重试'));assert.equal(context.state.memoryBusy,false);
const project={id:'project-1',revision:3,title:'心跳项目 <script>bad</script>',source_status:'current',original_goal:'使用 React。',requirements:[{text:'不联网。'}],progress:'尚未部署',next_steps:'先做曲线',allowed_agents:['central']};
data.tasks.active_task=task.id;data.projects={revision:8,binding:{project_id:null,task_id:null,revision:2},projects:[project]};data.usage={room:{rounds:2,calls:1,input:null,output:null,input_unknown_rounds:2,output_unknown_rounds:2,calls_unknown_rounds:1,first_text_ms:{samples:0},notice:'计数缺失不视为零。'},project:null};
context.api=async(path,options)=>{requests.push({path,options});if(options?.method==='POST')return {};if(path.includes('memory-projects'))return data.projects;if(path.includes('context-usage'))return data.usage;return path==='/api/user-memory'?data.personal:data.tasks;};
context.state.memoryView='projects';call('renderMemory',data);assert.equal(document.querySelectorAll('script').length,0);
find('关联此项目').click();await new Promise(resolve=>setImmediate(resolve));assert.equal(JSON.parse(requests.filter(r=>r.options?.method==='POST').at(-1).options.body).binding_revision,2);
find('保存当前任务为项目').click();document.querySelector('[aria-label="项目名称"]').value='项目新名称';document.querySelector('[aria-label="下一步"]').value='检查移动布局';document.querySelector('form').dispatchEvent(new dom.window.Event('submit',{cancelable:true}));await new Promise(resolve=>setImmediate(resolve));
const saved=JSON.parse(requests.filter(r=>r.options?.method==='POST').at(-1).options.body);assert.equal(saved.action,'create');assert.equal(saved.expected_task_revision,7);assert.equal(saved.next_steps,'检查移动布局');assert.deepEqual(saved.allowed_agents,['central']);
const emptyLinked={...data,tasks:{revision:0,active_task:null,tasks:[]},projects:{...data.projects,binding:{project_id:project.id,task_id:null,revision:3}}};call('renderMemory',emptyLinked);assert.equal(find('关联此项目'),undefined,'An already-linked empty room should wait for its first task rather than offer duplicate attachment');
context.state.memoryView='usage';call('renderMemory',data);assert.match(document.getElementById('ag-memory-list').textContent,/输入计数缺失 2 次/);assert.match(document.querySelector('td').textContent,/未返回/);assert.match(document.getElementById('ag-memory-list').textContent,/0 条完整计时/);

data.usage.admission={settings:{revision:3,calls:0,input:0},limits:{calls:0,input:0},near:[],allowed:true,notice:'当前一轮可能超出剩余额度。'};
call('renderMemory',data);
context.api=async(path,options)=>{requests.push({path,options});return {...data.usage.admission,settings:{revision:4,calls:20,input:5000},limits:{calls:20,input:5000}};};
document.querySelector('[aria-label="累计调用次数"]').value='20';document.querySelector('[aria-label="累计输入 token"]').value='5000';
find('保存门槛').click();find('保存门槛').click();await new Promise(resolve=>setImmediate(resolve));
const limitRequest=requests.filter(r=>r.path.endsWith('/context-limits')).at(-1);
assert.deepEqual(JSON.parse(limitRequest.options.body),{expected_revision:3,calls:20,input:5000});assert.equal(context.state.memoryBusy,false);
context.api=async()=>{throw new Error('用量设置已更新');};document.querySelector('[aria-label="累计调用次数"]').value='31';find('保存门槛').click();await new Promise(resolve=>setImmediate(resolve));
assert.equal(document.querySelector('[aria-label="累计调用次数"]').value,'31');assert.match(document.getElementById('ag-memory-status').textContent,/填写内容保留/);
assert.equal(context.state.memoryBusy,false);assert.equal(document.querySelector('[aria-label="累计调用次数"]').disabled,false);

context.rememberDetails=()=>{};
const zeroReceipt=call('renderContextUsage',{response_origin:'host_memory_read',context_usage:{enabled:true,total_calls:0,total_input_tokens:0,reply:{input_tokens:0,output_tokens:0},summary:{status:'not_needed'},included:[]}},'fixture');
assert.match(zeroReceipt.textContent,/回复链未调用模型/);assert.ok(!zeroReceipt.textContent.includes('undefined'));

dom.window.close();console.log('Memory UI: literal rendering, source reads, versioned edits, reviewed conflict/forget, stale-edit preservation, scoped project association/create and missing usage passed.');
