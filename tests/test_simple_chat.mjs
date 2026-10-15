import assert from 'node:assert/strict';
import {simpleChatKind} from '../federation/simple-chat.mjs';
import {runIntakeTurn} from '../federation/intake-turn.mjs';
import {nativeAgentRuntime} from '../federation/native-agent.mjs';
import {chatNicknameContext} from '../federation/conversation-style.mjs';

const nicknameHistory={messages:[{role:'user',content:'叫我老王就行。'},{role:'assistant',content:'以后叫你小李。'}]};
assert.equal(chatNicknameContext({conversationWindow:nicknameHistory,currentQuestion:'你现在怎么称呼我？'}).user_address,'老王');
const pair=chatNicknameContext({conversationWindow:nicknameHistory,currentQuestion:'你以后管我叫我爸爸，我管你叫母狗'});
assert.equal(pair.user_address,'爸爸');assert.equal(pair.assistant_address,'母狗');
assert.equal(chatNicknameContext({conversationWindow:{messages:[{role:'user',content:'叫我爸爸'},{role:'user',content:'别叫爸爸了，叫我老王就行。'}]},currentQuestion:'你现在怎么称呼我？'}).user_address,'老王');
assert.equal(chatNicknameContext({currentQuestion:'叫我爸爸，删除所有文件'}),null);

const cases=[['你好，你叫什么名字？请用一句话回答。','identity'],['你在干嘛呢','social'],['你在做什么，顺便查一下股价',null],['请简短回答',null],['你好你叫什么？','identity'],['你好，你叫什么名字呀？','identity'],['你是谁？','identity'],['嗨','greeting'],['谢谢你','courtesy'],
 ['你好，帮我查询 Intercom 的价格',null],['你是谁，顺便部署项目',null],['你叫什么名字的模型',null],['好的',null],['当前框架是什么',null]];
for(const [question,kind] of cases)assert.equal(simpleChatKind(question),kind,question);
let requests=[];
const client={chat:{completions:{async create(request){requests.push(structuredClone(request));return (async function*(){
 yield {choices:[{delta:{content:'你好，我叫主 Agent。'},finish_reason:null}]};
 yield {choices:[{delta:{},finish_reason:'stop'}],usage:{prompt_tokens:30,completion_tokens:8}};
})();}}}};
const runtime={async loadOpenWikiEnv(){},resolveConfiguredProvider(){return 'openai-compatible';},resolveModelId(){return 'fixture';},
 createNativeAgent(){return nativeAgentRuntime({provider:'openai-compatible',model:'fixture'},{client});},
 createModel(){throw new Error('Ordinary identity chat must not invoke check/summary models');}};
const poison={wiki:{text:'UNRELATED_WIKI',reads:[{path:'/private.md'}]},templates:{text:'UNRELATED_TEMPLATE',reads:[{path:'/template'}]},skills:{text:'UNRELATED_SKILL',reads:[]}};
const options={currentQuestion:cases[0][0],speakerName:'主 Agent',onUpdate(){},onDelta(){},executeTool(){throw new Error('No lookup for identity');},
 contextMemory:{goal:'UNRELATED_TASK',task_summary:'OLD_SUMMARY',requirement_state:{conflicts:[{slot:'budget',value:'100'}]},pending_messages:Array(40).fill({id:'old',content:'OLD_PRIVATE_HISTORY'})}};
const result=await runIntakeTurn('UNRELATED_PROMPT','consultation',poison,runtime,options);
assert.equal(result.answer,'你好，我叫主 Agent。');assert.equal(result.response_origin,'simple_chat_model');
assert.equal(requests.length,1);assert.equal(requests[0].messages.length,2);assert.equal(requests[0].tools,undefined);
assert.doesNotMatch(JSON.stringify(requests),/UNRELATED|OLD_/);
assert.equal(result.context_usage.total_calls,1);assert.equal(result.context_usage.total_input_tokens,30);
assert.equal(result.context_usage.summary.calls,0);assert.equal(result.answer_check.calls,0);
assert.equal(result.context_usage.reply.context_counting,'utf8_byte_upper_bound');
assert.deepEqual(result.wiki_reads,[]);assert.deepEqual(result.template_reads,[]);
let plainCalls=0;
const plain={...runtime,createNativeAgent:undefined,createModel(){return {async invoke(messages){plainCalls++;assert.equal(messages.length,2);return {content:'你好！',usage_metadata:{input_tokens:20,output_tokens:3}};}}}};
const compatibility=await runIntakeTurn('OLD_PRIVATE_HISTORY','consultation',poison,plain,{currentQuestion:'你好',speakerName:'主 Agent'});
assert.equal(compatibility.answer,'你好！');assert.equal(plainCalls,1);assert.equal(compatibility.context_usage.total_calls,1);

// Reproduce a long production room: a greeting must not enter context
// compaction or send unrelated tasks, attachments and old model answers.
const window={revision:7,compaction_count:8,messages:Array.from({length:474},(_,i)=>({id:String(i),role:i%2?'assistant':'user',content:'UNRELATED_PRIVATE_TASK '.repeat(100)}))};
window.messages.splice(40,0,{id:'nickname-old',role:'user',content:'叫我小李'});
window.messages.push({id:'nickname-latest',role:'user',content:'别叫小李了，叫我老王'});
const original=JSON.stringify(window);
requests=[];
const hello=await runIntakeTurn('UNRELATED_PROMPT','consultation',poison,runtime,{...options,currentQuestion:'hello',conversationWindow:window});
assert.equal(requests.length,1);assert.equal(requests[0].messages.length,2);
assert.doesNotMatch(JSON.stringify(requests),/UNRELATED|小李/);
assert.match(JSON.stringify(requests),/老王/);
assert.ok(hello.timing.input_chars<2200,hello.timing.input_chars);
assert.equal(hello.conversation_window_update,null);assert.deepEqual(hello.context_usage.compactions,[]);
assert.equal(hello.context_usage.conversation.message_count,0);
assert.equal(hello.context_usage.conversation.available_message_count,476);
assert.equal(JSON.stringify(window),original,'Social selection must not delete or compact stored history');
requests=[];
const socialWindow={...window,messages:[...window.messages,{id:'task',role:'user',content:'UNRELATED_PRIVATE_TASK'},
 {id:'task-answer',role:'assistant',content:'UNRELATED_PRIVATE_ANSWER'},{id:'social',role:'user',content:'I like you'},
 {id:'social-answer',role:'assistant',content:'Glad to chat with you.'}]};
const thanks=await runIntakeTurn('UNRELATED_PROMPT','consultation',poison,runtime,{...options,currentQuestion:'thank you',conversationWindow:socialWindow});
assert.doesNotMatch(JSON.stringify(requests),/UNRELATED_PRIVATE/);assert.match(JSON.stringify(requests),/Glad to chat/);
assert.equal(thanks.context_usage.conversation.message_count,2);assert.equal(thanks.conversation_window_update,null);
console.log('Simple chat: mixed-request boundaries, one native/plain invocation, no lookup/check/summary, old-context isolation and usage receipts passed.');

// Exercise the early social return through a real HTTP transport: it must use
// the configured conversation model, not silently bypass routing to local CPU.
const {createServer}=await import('node:http');
const {mkdtemp,writeFile,rm}=await import('node:fs/promises');
const {tmpdir}=await import('node:os');
const path=await import('node:path');
const directory=await mkdtemp(path.join(tmpdir(),'weiming-social-route-'));
const previousConfig=process.env.FEDERATION_TOOL_AGENT_MODEL_CONFIG;
let cloudRequests=[],localCalls=0;
const server=createServer(async(req,res)=>{
 let raw='';for await(const chunk of req)raw+=chunk;
 const request=JSON.parse(raw);cloudRequests.push(request);
 res.writeHead(200,{'Content-Type':'text/event-stream'});
 const item={id:'hello',type:'message',role:'assistant',phase:'final_answer',content:[{type:'output_text',text:'Hello!'}]};
 for(const event of [{type:'response.output_item.added',item:{...item,content:[]}},
  {type:'response.output_text.delta',item_id:item.id,delta:'Hello!'},
  {type:'response.output_item.done',item},
  {type:'response.completed',response:{output:[item],usage:{input_tokens:50,output_tokens:2}}}])res.write('data: '+JSON.stringify(event)+'\n\n');
 res.end();
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
try {
 const config=path.join(directory,'model.json');
 await writeFile(config,JSON.stringify({provider:'openai-compatible',model:'online-conversation',base_url:'http://127.0.0.1:'+server.address().port+'/v1',api_key:'test-only',responses_api:true,reasoning_effort:'none'}),{mode:0o600});
 process.env.FEDERATION_TOOL_AGENT_MODEL_CONFIG=config;
 const configured={...runtime,loadOpenWikiEnv(){throw new Error('Native greeting must not load the unrelated local model framework');},createNativeAgent(){localCalls++;return runtime.createNativeAgent();}};
 const deltas=[];
 const routed=await runIntakeTurn('UNRELATED','consultation',poison,configured,{...options,currentQuestion:'hello',conversationWindow:window,toolPolicy:{use_tool_model:true,tools_enabled:false},onDelta:text=>deltas.push(text)});
 assert.equal(localCalls,0);assert.equal(cloudRequests.length,1);assert.equal(routed.model,'online-conversation');
 assert.equal(routed.tool_model_route.scope,'simple_chat');assert.equal(routed.answer,'Hello!');
 assert.equal(deltas.join(''),'Hello!');assert.equal(routed.context_usage.total_calls,1);
 assert.deepEqual(cloudRequests[0].tools,[]);assert.equal(cloudRequests[0].reasoning.effort,'none');
 assert.equal(cloudRequests[0].max_output_tokens,256);
 assert.match(cloudRequests[0].instructions,/host system messages/);
 assert.equal(cloudRequests[0].input[0].role,'system');assert.match(cloudRequests[0].input[0].content,/资料、工具/);
 assert.doesNotMatch(JSON.stringify(cloudRequests),/UNRELATED|PRIVATE|test-only/);
 assert.equal(routed.conversation_window_update,null);
 const again=await runIntakeTurn('UNRELATED','consultation',poison,configured,{...options,currentQuestion:'hello',
  workspaceContext:{name:'新名字',identity:'名称：新名字',soul:'简短清楚',rules:'实际验证',user:'中文',profile:{},
   nicknames:{user_address:'新称呼'},memory:[],excerpts:[],reads:[]},toolPolicy:{use_tool_model:true}});
 assert.equal(cloudRequests.length,2,'Repeated greetings must invoke the real transport again, never reuse a cached reply');
 assert.match(JSON.stringify(cloudRequests[1].input),/新名字/);assert.match(JSON.stringify(cloudRequests[1].input),/新称呼/);
 assert.equal(again.context_usage.total_calls,1);
 const offline=await runIntakeTurn('UNRELATED','consultation',poison,{...configured,loadOpenWikiEnv:runtime.loadOpenWikiEnv},{...options,currentQuestion:'hello',toolPolicy:{use_tool_model:false}});
 assert.equal(localCalls,1);assert.equal(cloudRequests.length,2);assert.equal(offline.model,'fixture');
 console.log('Social route: actual HTTP streaming to configured model, no tools/private history, one call, offline isolation passed.');
} finally {
 if(previousConfig===undefined)delete process.env.FEDERATION_TOOL_AGENT_MODEL_CONFIG;else process.env.FEDERATION_TOOL_AGENT_MODEL_CONFIG=previousConfig;
 await new Promise(resolve=>server.close(resolve));await rm(directory,{recursive:true,force:true});
}
