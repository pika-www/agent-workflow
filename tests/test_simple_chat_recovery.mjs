import assert from 'node:assert/strict';
import {setTimeout as sleep} from 'node:timers/promises';
import {firstLiveReply} from '../federation/simple-chat-race.mjs';
const candidates=[{model:'primary',protocol:'chat_completions'},{model:'backup',protocol:'responses'}];
const receipt=answer=>({answer,context_usage:{total_calls:1,total_input_tokens:8,total_output_tokens:3},timing:{}});
let seen=[],calls=[];
const fast=await firstLiveReply(candidates,async(c,o)=>{calls.push(c.model);await o.onDelta('实时回答');return receipt('实时回答');},{onDelta:t=>seen.push(t)},{hedgeAfterMs:30,firstTextTimeoutMs:100});
assert.deepEqual(calls,['primary']);assert.deepEqual(seen,['实时回答']);assert.equal(fast.model_transport.winner,0);
seen=[];calls=[];let cancelled=false;const events=[];
const recovered=await firstLiveReply(candidates,async(c,o)=>{
 calls.push(c.model);await o.onAgentEvent({model:c.model});
 if(c.model==='primary'){try{await sleep(1000,null,{signal:o.signal});}catch{cancelled=true;throw new Error('cancelled');}}
 await o.onUpdate({id:'backup',text:'模型正文'});return receipt('模型正文');
},{onAgentEvent:e=>events.push(e),onUpdate:e=>seen.push(e.text)},{hedgeAfterMs:25,firstTextTimeoutMs:150});
await sleep(0);assert.equal(cancelled,true);assert.deepEqual(calls,['primary','backup']);assert.deepEqual(events,[{model:'backup'}]);assert.deepEqual(seen,['模型正文']);
assert.equal(recovered.context_usage.total_calls,2);assert.equal(recovered.context_usage.total_input_tokens,null);assert.equal(recovered.context_usage.usage_complete,false);
assert.ok(recovered.timing.first_text_ms>=20);assert.equal(recovered.model_transport.attempts[0].status,'cancelled');
// Empty results are failures; the second model must generate fresh text.
const empty=await firstLiveReply(candidates,async(c,o)=>{if(c.model==='primary')return receipt('');await o.onDelta('新回答');return receipt('新回答');},{},{hedgeAfterMs:500,firstTextTimeoutMs:100});
assert.equal(empty.answer,'新回答');assert.ok(empty.model_transport.total_ms<100);
// Once visible text is published, a later error cannot splice another model in.
calls=[];seen=[];
await assert.rejects(firstLiveReply(candidates,async(c,o)=>{calls.push(c.model);await o.onDelta('部分正文');throw new Error('broken after text');},{onDelta:t=>seen.push(t)},{hedgeAfterMs:50,firstTextTimeoutMs:100}),/broken after text/);
assert.deepEqual(calls,['primary']);assert.deepEqual(seen,['部分正文']);
// User cancellation aborts both paths and never returns a fabricated response.
const cancel=new AbortController();let aborts=0;
const pending=firstLiveReply(candidates,async(c,o)=>{try{await sleep(500,null,{signal:o.signal});}catch{aborts++;throw new Error('cancelled');}},{signal:cancel.signal},{hedgeAfterMs:5,firstTextTimeoutMs:100});
await sleep(15);cancel.abort(new Error('user cancelled'));await assert.rejects(pending,/user cancelled/);await sleep(0);assert.equal(aborts,2);
aborts=0;const progress=[];
const slow=await firstLiveReply(candidates,async(c,o)=>{
 try{await sleep(c.model==='primary'?65:500,null,{signal:o.signal});}catch{aborts++;throw new Error('cancelled');}
 await o.onDelta('等待后的真实正文');return receipt('等待后的真实正文');
},{onProgress:e=>progress.push(e)},{hedgeAfterMs:5,slowNoticeMs:25});
await sleep(0);assert.equal(aborts,1);assert.equal(slow.answer,'等待后的真实正文');
assert.equal(progress[0].stage,'waiting_model');assert.ok(slow.timing.first_text_ms>=60);
// Long outages must not accumulate stale pre-text events or fake model usage.
const notices=[];
const retries=await firstLiveReply(candidates,async(c,o)=>{
 if(c.model==='backup')throw new Error('permanent failure');
 for(let i=0;i<300;i++){
  o.onModelCall();await o.onAgentEvent({type:'agent.transport.retrying',attempt:i+1});
  await o.onProgress({stage:'reconnecting',detail:'自动重连'});
 }
 await o.onDelta('恢复成功');return receipt('恢复成功');
},{onProgress:e=>notices.push(e)},{hedgeAfterMs:500,slowNoticeMs:1000});
assert.equal(retries.model_transport.attempts[0].calls,300);assert.equal(notices.length,300);
// An early failed backup must not discard a later successful primary.
const late=await firstLiveReply(candidates,async(c,o)=>{if(c.model==='backup')throw new Error('unavailable');await sleep(25);await o.onDelta('主模型回答');return receipt('主模型回答');},{},{hedgeAfterMs:5,firstTextTimeoutMs:100});
assert.equal(late.answer,'主模型回答');assert.equal(late.model_transport.winner,0);assert.equal(late.model_transport.attempts[1].status,'failed');
console.log('Live reply recovery: delayed hedge, slow reply survives notice, cancellation, bounded concurrent paths, retry progress, isolated streaming and honest usage passed.');
