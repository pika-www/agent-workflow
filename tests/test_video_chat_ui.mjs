/** Real-DOM composer submission; no model, provider, or formal-data calls. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {createRequire} from 'node:module';
const require=createRequire(new URL('../openwiki-upstream/package.json',import.meta.url));
const {JSDOM}=require('jsdom');
const source=fs.readFileSync(new URL('../federation/web/agent-chat.js',import.meta.url),'utf8');
const markup=source.match(/template.innerHTML = `([\s\S]+?)`;/)[1];
const dom=new JSDOM('<body>'+markup+'</body>',{url:'http://127.0.0.1/',runScripts:'outside-only'});
const {window}=dom,context=dom.getInternalVMContext();
const room={id:'a'.repeat(32),purpose:'primary',mode:'orchestrated',status:'idle',messages:[]};
window.fixtureRoom=room;
function extract(name){const a=source.indexOf('  function '+name+'(');assert.ok(a>=0);return source.slice(a,source.indexOf('\n  }',a)+4);}
const start=source.indexOf('  $("message-form").addEventListener("submit",');
const end=source.indexOf('\n  $("dialog").addEventListener("close", () => { stopRoomStream();',start);
vm.runInContext(`
const $=id=>document.getElementById('ag-'+id);
const state={room:fixtureRoom,roomId:fixtureRoom.id,view:'room',sending:new Set(),sendModes:new Map(),videoRequests:new Map(),submissions:new Map(),drafts:new Map(),unconfirmed:new Map(),epoch:0,listRevision:0};
window.requests=[];window.notices=[];window.fileIds=[];window.fail=false;window.cleared=0;
window.openWikiHotspots={context:()=>{window.hotspotReads=(window.hotspotReads||0)+1;return {hotspot_view:true};}};
window.openWikiTools={attachments:()=>window.fileIds,sent:()=>window.cleared++,renderDraft:()=>{}};
const active=status=>['running','queued'].includes(status);
const notice=(text)=>window.notices.push(text),persistView=()=>{},saveDraft=()=>{},renderMessages=()=>{},renderComposerContext=()=>{},renderLearningControls=()=>{},schedulePoll=()=>{};
const hasLearningPrefix=text=>text.trim().startsWith('/学习');
const learningRequested=()=>$('learning').checked||hasLearningPrefix($('message').value),researchRequested=()=>$('research').checked;
const upsertRoom=()=>{},renderRoom=()=>{},selectRoom=async()=>{};
async function api(path,options){window.requests.push({path,body:JSON.parse(options.body)});if(window.fail)throw Error('connection lost');return {room:fixtureRoom};}
${extract('resetLearningControls')}
${extract('videoMessageIntent')}
${extract('composerIntent')}
${extract('renderComposer')}
${source.slice(start,end)}
window.ui={state,renderComposer,videoMessageIntent};
`,context);
const input=window.document.getElementById('ag-message'),form=window.document.getElementById('ag-message-form');
const settle=()=>new Promise(resolve=>setImmediate(resolve));
async function submit(text){input.value=text;form.dispatchEvent(new window.Event('submit',{bubbles:true,cancelable:true}));await settle();}
window.ui.state.sendModes.set(room.id,'video');window.document.getElementById('ag-learning').checked=true;window.document.getElementById('ag-research').checked=true;
input.value='清晨海边一只奔跑的猫';window.ui.renderComposer();
assert.equal(window.document.getElementById('ag-send').textContent,'发送提示词');
assert.equal(window.document.getElementById('ag-send').disabled,false);
const prompt='  /学习 海面上的白色帆船\n缓慢推进  ';
window.fail=true;await submit(prompt);
const first=window.requests.at(-1).body;
assert.deepEqual(Object.keys(first).sort(),['content','request_id','video_generation']);
assert.equal(first.content,prompt);assert.equal(first.video_generation,true);assert.match(first.request_id,/^[a-f0-9]{32}$/);
assert.equal(input.value,prompt,'Uncertain submissions keep the exact draft');
assert.equal(window.hotspotReads,undefined,'Video mode never reads hotspot context');
window.fail=false;await submit(prompt);
assert.equal(window.requests.at(-1).body.request_id,first.request_id,'Retry retains idempotency key');
assert.equal(window.ui.state.videoRequests.size,0);assert.equal(window.cleared,0);
assert.equal(window.ui.state.sendModes.get(room.id),'chat','Successful generation returns to normal chat');
window.ui.state.sendModes.set(room.id,'video');window.fileIds=['b'.repeat(32)];const count=window.requests.length;await submit('another');
assert.equal(window.requests.length,count,'Attachments block prompt-only mode');assert.equal(input.value,'another');
window.fileIds=[];window.ui.state.sendModes.set(room.id,'chat');window.document.getElementById('ag-learning').checked=false;window.document.getElementById('ag-research').checked=false;
await submit('normal message');
assert.equal(window.requests.at(-1).body.video_generation,undefined);assert.equal(window.requests.at(-1).body.hotspot_view,true);assert.equal(window.cleared,1);
for (const [text,selected,recent,expected] of JSON.parse(fs.readFileSync(new URL('fixtures/video-intent-cases.json',import.meta.url),'utf8'))) {
  assert.equal(window.ui.videoMessageIntent(text,selected,recent),expected,text);
}
window.ui.state.sendModes.set(room.id,'video');
input.value='检查一下视频生成好了吗？';window.ui.renderComposer();
assert.equal(window.document.getElementById('ag-send').textContent,'查询视频进度');
const beforeHotspots=window.hotspotReads;await submit(input.value);
assert.equal(window.requests.at(-1).body.video_generation,undefined);
assert.equal(window.hotspotReads,beforeHotspots,'Status queries skip unrelated hotspot context');
assert.equal(window.ui.state.sendModes.get(room.id),'chat');
window.ui.state.sendModes.set(room.id,'video');
await submit('今天的天气怎么样？');
assert.equal(window.requests.at(-1).body.video_generation,undefined,'Normal questions cannot generate');
console.log('Video chat composer passed: raw prompt, exclusive route, no context/attachments, retained retry key/draft, normal chat unchanged.');
dom.window.close();
