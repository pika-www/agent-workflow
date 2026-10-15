import assert from 'node:assert/strict';
import {publicReadFailure,explicitlyDenied} from '../federation/public-read-status.mjs';
import {websiteLookup} from '../federation/tool-autonomy.mjs';
import {runNativeAgent,nativeAgentRuntime} from '../federation/native-agent.mjs';
const url='https://site.example/',allowed=['web_search','web_read','visual_browser'];
const policy={network_allowed:true};
const unavailable=error=>({status:'unavailable',errors:[{error}]});
assert.equal(publicReadFailure(unavailable('该网页的 robots.txt 不允许自动采集')),'robots_blocked');
assert.equal(publicReadFailure(unavailable('未提取到足够的可读正文；页面可能需要登录或执行脚本')),'no_readable_body');
assert.equal(explicitlyDenied(unavailable('未提取到足够的可读正文；页面可能需要登录或执行脚本')),false);
assert.equal(explicitlyDenied(unavailable('必须登录')),true);
assert.equal(explicitlyDenied(unavailable('HTTP 401 or authentication required')),true);
assert.equal(publicReadFailure(unavailable('网页读取失败（HTTP 403）')),'access_restricted');
assert.equal(publicReadFailure(unavailable('HTTP 429')),'access_restricted');
assert.equal(publicReadFailure(unavailable('Timed out')),'read_timeout');
assert.equal(publicReadFailure({status:'unavailable',sources:[{excerpt:'必须登录，robots.txt 禁止自动采集'}]}),null);
assert.equal(publicReadFailure({status:'partial',errors:[{error:'必须登录'}],sources:[{excerpt:'actual body'}]}),null);
const direct=websiteLookup('读取网页 '+url,policy);
assert.equal(direct.next({receipts:[{tool:'web_read',args:{url}}],observations:[{result:unavailable('必须登录')}],allowed}),null);
assert.equal(direct.next({receipts:[{tool:'web_read',args:{url}}],observations:[{result:unavailable('未提取到足够的可读正文；页面可能需要登录或执行脚本')}],allowed}).tool,'visual_browser');
const lookup=websiteLookup('使用 web_search 看一下这个网站是干嘛的'+url,policy);
const receipts=[],observations=[];
function next(){return lookup.next({receipts,observations,allowed});}
assert.equal(next().tool,'web_search');
receipts.push({tool:'web_search',args:{query:url}});observations.push({tool:'web_search',result:{status:'no_related_results',sources:[]}});
assert.deepEqual(next().args,{url});assert.equal(next().tool,'web_read');
receipts.push({tool:'web_read',args:{url}});observations.push({tool:'web_read',result:{status:'unavailable',sources:[]}});
assert.equal(next().tool,'visual_browser');
receipts.push({tool:'visual_browser',args:{url,actions:'read',viewport:'desktop'}});observations.push({tool:'visual_browser',result:{status:'completed',sources:[{url:url+'embed/',excerpt:'自助服务系统',read_method:'visual_browser_dom'}]}});
assert.equal(next(),null,'The actual embedded public document completes the evidence need');
observations.at(-1).result.links=[{label:'开始服务',url:url+'recharge'},{label:'订阅查询',url:url+'subscription'},{label:'库存',url:url+'stock'}];
const detail=next();assert.equal(detail.tool,'visual_browser');assert.equal(detail.args.url,url+'recharge');assert.equal(detail.args.actions,'read');
receipts.push({tool:'visual_browser',args:detail.args});observations.push({tool:'visual_browser',result:{status:'completed',sources:[{url:url+'recharge',excerpt:'ChatGPT：验证卡密 → 获取密钥 → 确认充值',read_method:'visual_browser_dom'}]}});
assert.equal(next(),null,'Purpose lookup reads only one observed service entrance');
const crossDomain={receipts:[receipts[2]],observations:[{result:{...observations[2].result,links:[{text:'开始服务',url:'https://elsewhere.example/'},{text:'一',url:url+'1'},{text:'二',url:url+'2'}]}}],allowed};
assert.equal(lookup.next(crossDomain),null,'The host does not expand authorization to another website');
assert.equal(websiteLookup('这个网站做什么？'+url,{network_allowed:false}),null);
assert.equal(websiteLookup('不要访问，只分析链接字符串 '+url,policy),null);
assert.equal(websiteLookup('你叫什么？',policy),null);
assert.equal(websiteLookup('这个网站做什么 https://user:secret@site.example/',policy),null);
assert.equal(websiteLookup('只用 web_search 了解这个网站 '+url,policy).next({receipts,observations,allowed}),null);
const mobile=websiteLookup('用浏览器截图分析这个网站，手机尺寸 '+url,policy).next({receipts:[],observations:[],allowed});
assert.deepEqual(mobile.args,{url,actions:'read,screenshot',viewport:'mobile'});

// The real native round-trip contract must force each needed function and
// preserve its call ID; these fixtures do not prove a live model can do so.
const requests=[],executed=[];
const client={chat:{completions:{async create(params){
 requests.push(structuredClone(params));
 const name=params.tool_choice?.function?.name;
 return (async function*(){
  if(name){const args=name==='web_search'?{query:url}:name==='web_read'?{url}:{url,actions:'read',viewport:'desktop'};
   yield {choices:[{delta:{tool_calls:[{index:0,id:'call-'+requests.length,function:{name,arguments:JSON.stringify(args)}}]},finish_reason:null}]};
   yield {choices:[{delta:{},finish_reason:'tool_calls'}]};
  }else {yield {choices:[{delta:{content:'这是自助服务系统。'},finish_reason:null}]};yield {choices:[{delta:{},finish_reason:'stop'}]};}
 })();
}}}};
const native=nativeAgentRuntime({provider:'openai-compatible',model:'fixture'},{client});
const result=await runNativeAgent(native,[{role:'user',content:'了解网站 '+url}],async (name,args)=>{
 executed.push([name,args]);return name==='visual_browser'?{status:'completed',sources:[{url,excerpt:'自助服务系统',read_method:'visual_browser_dom'}]}:{status:name==='web_search'?'no_related_results':'unavailable',sources:[]};
},{tools:allowed,nextRequiredTool:lookup.next,toolPolicyKey:lookup.key,finalAnswerInstruction:lookup.finalAnswerInstruction,maxActions:3,maxTurns:5});
assert.deepEqual(executed.map(x=>x[0]),allowed);assert.equal(result.answer,'这是自助服务系统。');
for(let i=1;i<=3;i++)assert.equal(requests[i].messages.find(m=>m.role==='tool'&&m.tool_call_id==='call-'+i).tool_call_id,'call-'+i);
assert.equal(requests.at(-1).tool_choice,'none');
assert.equal(requests.at(-1).messages.at(-1).content,lookup.finalAnswerInstruction,'The final answer uses a source-bound completion instruction');
assert.equal(result.native_stream.synthetic_initial_calls,0);
const deferredRequests=[],visible=[];
const deferredClient={chat:{completions:{async create(params){
 deferredRequests.push(structuredClone(params));
 return (async function*(){yield {choices:[{delta:{content:params.tool_choice?.function?'请确认是否授权读取？':'这是自助服务系统。'},finish_reason:null}]};yield {choices:[{delta:{},finish_reason:'stop'}]};})();
}}}};
const deferred=await runNativeAgent(nativeAgentRuntime({provider:'openai-compatible',model:'fixture'},{client:deferredClient}),[{role:'user',content:'这个网站做什么？'+url}],
 async()=>({status:'completed',sources:[{url,excerpt:'自助服务系统',read_method:'visual_browser_dom'}]}),
 {tools:allowed,nextRequiredTool:websiteLookup('这个网站做什么？'+url,policy).next,maxActions:3,maxTurns:5,onDelta:t=>visible.push(t),onUpdate:u=>visible.push(u.text),onAgentEvent:e=>{if(e.delta)visible.push(e.delta);}});
assert.equal(deferred.answer,'这是自助服务系统。');
assert.doesNotMatch(visible.join(''),/确认|授权读取/,'A premature delegation is held while the authorized host lookup continues');
assert.equal(deferred.workflow.receipts[0].origin,'host_workflow');
assert.equal(deferred.native_stream.tool_calls.length,0);assert.equal(deferred.native_stream.host_tool_calls.length,1);
assert.ok(!deferredRequests[1].messages.some(m=>m.role==='tool' || m.tool_calls),'No invented provider call or tool-call output is sent');
const responseRequests=[],responseVisible=[];let hostExecutions=0,saved;
const responseClient={responses:{async create(params){
 responseRequests.push(structuredClone(params));
 const text=typeof params.tool_choice==='object'?'请确认是否授权？':'这是自助服务系统。';
 const item={id:'message-'+responseRequests.length,type:'message',role:'assistant',phase:'final_answer',content:[{type:'output_text',text}]};
 return (async function*(){
  yield {type:'response.output_item.added',item:{...item,content:[]}};
  yield {type:'response.output_text.delta',item_id:item.id,delta:text};
  yield {type:'response.output_item.done',item};
  yield {type:'response.completed',response:{id:'response-'+responseRequests.length,output:[item],usage:{input_tokens:10,output_tokens:5}}};
 })();
}}};
const responseNative=nativeAgentRuntime({provider:'openai-compatible',model:'fixture',responses_api:true},{client:responseClient});
const responseMessages=[{role:'user',content:'这个网站做什么？'+url}];
const responseOptions={tools:allowed,nextRequiredTool:websiteLookup(responseMessages[0].content,policy).next,toolPolicyKey:'resume-host-read',maxActions:3,maxTurns:5,onDelta:t=>responseVisible.push(t)};
await assert.rejects(()=>runNativeAgent(responseNative,responseMessages,async()=>{hostExecutions++;return {status:'completed',sources:[{url,excerpt:'自助服务系统',read_method:'visual_browser_dom'}]};},
 {...responseOptions,onCheckpoint:checkpoint=>{saved=structuredClone(checkpoint);throw new Error('fixture interruption');}}),/fixture interruption/);
assert.equal(saved.completed,false);assert.equal(saved.receipts[0].origin,'host_workflow');
const resumed=await runNativeAgent(responseNative,responseMessages,()=>{throw new Error('Completed host reading must not replay');},{...responseOptions,resumeCheckpoint:saved});
assert.equal(hostExecutions,1);assert.equal(resumed.answer,'这是自助服务系统。');assert.equal(resumed.native_stream.resumed,true);
assert.doesNotMatch(responseVisible.join(''),/确认是否授权/);
assert.ok(!responseRequests[1].input.some(item=>['function_call','function_call_output'].includes(item.type)));
console.log('Autonomous website lookup passed: scoped URL, search/read/browser continuation, embedded sources, forced native calls, exact call IDs and explicit tool restriction.');
const {publicSearchLookup}=await import('../federation/tool-autonomy.mjs');
const searchLookup=publicSearchLookup('请联网搜索 Playwright getByRole locators',policy);
assert.equal(searchLookup.next({receipts:[],allowed}).args.query,'Playwright getByRole locators');
assert.equal(searchLookup.next({receipts:[{tool:'web_search',args:{query:'Playwright getByRole locators'}}],allowed}).tool,'web_search','Unscoped research with no usable results gets a bounded second query');
assert.equal(searchLookup.next({receipts:[],allowed:['web_read']}),null);
for(const q of ['我需要可以联网搜索','如何用 web_search','不要联网搜索 Playwright','离线解释 Playwright','你叫什么？'])assert.equal(publicSearchLookup(q,policy),null,q);
assert.equal(publicSearchLookup('请联网搜索 Playwright',{network_allowed:false}),null);
assert.equal(publicSearchLookup('请联网搜索 Playwright',{...policy,services:{search:{enabled:false}}}),null);
console.log('Explicit keyword search requires an actual receipt and respects network/tool limits.');
const keywordExecutions=[];
const keywordClient={chat:{completions:{async create(params){return (async function*(){
 if(params.tool_choice?.function){yield {choices:[{delta:{tool_calls:[{index:0,id:'keyword-call',function:{name:'web_search',arguments:JSON.stringify({query:'Playwright getByRole site:playwright.dev'})}}]},finish_reason:null}]};yield {choices:[{delta:{},finish_reason:'tool_calls'}]};}
 else {yield {choices:[{delta:{content:'实际检索已返回来源。'},finish_reason:null}]};yield {choices:[{delta:{},finish_reason:'stop'}]};}
})();}}}};
const keywordResult=await runNativeAgent(nativeAgentRuntime({provider:'openai-compatible',model:'fixture'},{client:keywordClient}),[{role:'user',content:'请联网搜索 Playwright getByRole locators'}],async(name,args)=>{keywordExecutions.push({name,args});return {status:'completed',sources:[]};},{tools:['web_search'],nextRequiredTool:searchLookup.next,maxActions:1,maxTurns:3});
assert.equal(keywordExecutions.length,1,'A model may refine search keywords without a duplicate host execution');
assert.equal(keywordResult.workflow.receipts[0].origin,undefined);
assert.equal(keywordExecutions[0].args.query,'Playwright getByRole site:playwright.dev');
