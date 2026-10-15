import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {mkdtemp,writeFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {runIntakeTurn} from '../federation/intake-turn.mjs';
const root=await mkdtemp(path.join(tmpdir(),'weiming-recovery-'));
let requests=[],localCalls=0,failAll=false;
const server=createServer(async(req,res)=>{
 let raw='';for await(const chunk of req)raw+=chunk;const body=JSON.parse(raw);requests.push({url:req.url,body});
 if(failAll){res.writeHead(401,{'Content-Type':'application/json'});res.end(JSON.stringify({error:{message:'test-only upstream failure'}}));return;}
 if(body.model==='slow-primary')return;
 res.writeHead(200,{'Content-Type':'text/event-stream'});
 const item={id:'answer',type:'message',role:'assistant',phase:'final_answer',content:[{type:'output_text',text:'你好，老王。我叫未明。'}]};
 for(const event of [{type:'response.output_item.added',item:{...item,content:[]}},{type:'response.output_text.delta',item_id:'answer',delta:item.content[0].text},{type:'response.output_item.done',item},{type:'response.completed',response:{output:[item],usage:{input_tokens:50,output_tokens:8}}}])res.write('data: '+JSON.stringify(event)+'\n\n');
 res.end();
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const previous=process.env.FEDERATION_TOOL_AGENT_MODEL_CONFIG;
try {
 const file=path.join(root,'model.json');
 await writeFile(file,JSON.stringify({provider:'openai-compatible',model:'slow-primary',simple_chat_fallback_model:'backup',base_url:'http://127.0.0.1:'+server.address().port+'/v1',api_key:'test-only',responses_api:false,reasoning_effort:'none'}),{mode:0o600});
 process.env.FEDERATION_TOOL_AGENT_MODEL_CONFIG=file;
 const workspace={name:'未明',identity:'名称：未明',soul:'温和直接',rules:'保护任务',user:'中文',profile:{},nicknames:{user_address:'老王'},memory:['长期约定'],excerpts:[],reads:[]};
 for(let round=0;round<2;round++) {
  const text=[],started=performance.now();
  const result=await runIntakeTurn('hello','consultation',{}, {loadOpenWikiEnv(){localCalls++;throw new Error('No local fallback');}},
   {currentQuestion:'hello',toolPolicy:{use_tool_model:true},workspaceContext:workspace,onDelta:t=>text.push(t),onUpdate(){}});
  assert.equal(result.answer,'你好，老王。我叫未明。');assert.equal(text.join(''),result.answer);
  assert.equal(result.model,'backup');assert.equal(result.tool_model_route.model,'backup');assert.equal(result.model_transport.attempts.length,2);
  assert.equal(result.context_usage.total_calls,2);assert.equal(result.context_usage.total_input_tokens,null);
  assert.ok(performance.now()-started<4000);assert.equal(localCalls,0);
  const pair=requests.slice(round*2,round*2+2);assert.equal(pair[0].url,'/v1/chat/completions');assert.equal(pair[1].url,'/v1/responses');
  assert.deepEqual(pair[0].body.messages,pair[1].body.input);
  assert.match(JSON.stringify(pair[0].body.messages),/未明.*温和直接.*保护任务.*老王.*长期约定/s);
 }
 assert.equal(requests.length,4,'Repeated questions use new live requests');
 failAll=true;
 await assert.rejects(runIntakeTurn('hello','consultation',{}, {loadOpenWikiEnv(){localCalls++;}},
  {currentQuestion:'hello',toolPolicy:{use_tool_model:true}}),e=>!e.message.includes('test-only')&&e.message.includes('[REDACTED]'));
 assert.equal(localCalls,0);assert.equal(requests.length,6,'Permanent authentication errors do not keep retrying or use CPU fallback');
 console.log('Actual HTTP recovery: stalled primary replaced by live alternate, identical identity/memory, fresh repeated calls, two-request bound and secret sanitization passed.');
} finally {
 if(previous===undefined)delete process.env.FEDERATION_TOOL_AGENT_MODEL_CONFIG;else process.env.FEDERATION_TOOL_AGENT_MODEL_CONFIG=previous;
 server.closeAllConnections();await new Promise(resolve=>server.close(resolve));await rm(root,{recursive:true,force:true});
}
