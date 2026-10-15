import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {createRequire} from 'node:module';
const require=createRequire(new URL('../openwiki-upstream/package.json',import.meta.url));
const {JSDOM}=require('jsdom');
const source=fs.readFileSync(new URL('../federation/web/agent-chat.js',import.meta.url),'utf8');
function extract(name){const start=source.search(new RegExp(`  function ${name}\\(`));assert.ok(start>=0,name);return source.slice(start,source.indexOf('\n  }',start)+4);}
const dom=new JSDOM('<dialog id="ag-dialog" open><p id="ag-stream-notice" hidden></p></dialog>',{runScripts:'outside-only'});
const {window}=dom,timers=new Map(),connections=[];let timerId=0,polls=0;
class Source {
  constructor(url){this.url=url;this.listeners={};this.closed=false;connections.push(this);}
  addEventListener(type,fn){this.listeners[type]=fn;}
  close(){this.closed=true;}
  emit(type,data){this.listeners[type]?.({data:JSON.stringify(data)});}
}
const ctx=dom.getInternalVMContext();
Object.assign(ctx,{EventSource:Source,setTimeout:(fn,ms)=>{timers.set(++timerId,{fn,ms});return timerId;},clearTimeout:id=>timers.delete(id),schedulePoll:()=>polls++});
vm.runInContext(`
  const state={roomId:'room',room:{id:'room',status:'running',active_job_id:'job',live_reply:{native_seq:7}}};
  const $=id=>document.getElementById('ag-'+id), active=status=>['queued','running'].includes(status);
  const renderRoom=value=>{state.room=value;watchRoomStream(value);renderStreamNotice(value);};
  const renderLiveReply=value=>{state.room.live_reply=value;renderStreamNotice(state.room);}, renderNativeAgentEvent=()=>{};
  ${['stopRoomStream','watchRoomStream','questionLanguage','turnLanguage','renderStreamNotice'].map(extract).join('\n')}
  window.test={state,watchRoomStream,stopRoomStream,renderStreamNotice};
`,ctx);
const {state,watchRoomStream:watch,stopRoomStream:stop}=window.test;
const note=window.document.getElementById('ag-stream-notice');
watch(state.room);assert.equal(new URL(connections[0].url,'http://localhost').searchParams.get('after'),'7');connections[0].emit('open');
for(let index=0;index<6;index++){
  const current=connections[index];current.emit('error');current.emit('error');assert.equal(current.closed,true);
  watch(state.room);assert.equal(connections.length,index+1,'Polling does not bypass the reconnect limit');
  if(index<5){assert.match(note.textContent,new RegExp(`第 ${index+1}/5 次`));assert.equal(timers.size,1);
    const [id,timer]=[...timers][0];timers.delete(id);timer.fn();assert.equal(connections.length,index+2);}
}
assert.equal(connections.length,6);assert.equal(timers.size,0);assert.equal(state.streamReconnect.exhausted,true);
assert.match(note.textContent,/自动重连 5 次仍失败/);assert.equal(note.getAttribute('role'),'alert');
assert.equal(note.classList.contains('ag-connection-error'),true);assert.equal(note.querySelector('button'),null);
connections[0].emit('open');assert.equal(state.streamConnected,false,'Late events from a closed connection are ignored');
stop();state.room={id:'room',status:'running',active_job_id:'next',live_reply:{native_seq:12}};watch(state.room);
const next=connections.at(-1);next.emit('error');assert.equal(timers.size,1);stop();assert.equal(timers.size,0);
assert.equal(note.hidden,true);assert.equal(state.replyStreamKey,null);
watch(state.room);connections.at(-1).emit('open');assert.equal(note.hidden,true);
state.room.live_reply.transport_retry={attempt:4,max_attempts:5,status:'retrying'};window.test.renderStreamNotice(state.room);
assert.match(note.textContent,/模型连接.*第 4\/5 次/);
state.room.live_reply.transport_retry={attempt:42,max_attempts:null,retry_policy:'until_cancelled',status:'retrying'};
window.test.renderStreamNotice(state.room);assert.match(note.textContent,/第 42 次.*可随时停止等待/);
assert.doesNotMatch(note.textContent,/42\/5|失败/);
state.room.live_reply.transport_retry.status='restored';window.test.renderStreamNotice(state.room);assert.equal(note.hidden,true);
stop();state.room.status='completed';watch(state.room);assert.equal(timers.size,0);
assert.ok(polls>=6);console.log('Reconnect UI passed: initial + five only, cursor continuity, duplicate/stale-event guard, room/close timer cleanup, red text without buttons, provider retry notices.');
