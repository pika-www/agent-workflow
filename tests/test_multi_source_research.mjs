import assert from 'node:assert/strict';
import {setTimeout as delay} from 'node:timers/promises';
import {defaultOnlineLookup,publicResearchScope} from '../federation/default-online.mjs';
import {nativeAgentRuntime,runNativeAgent} from '../federation/native-agent.mjs';
import {reviewResearch} from '../federation/research-review.mjs';
const policy={default_online:true,network_allowed:true,services:{browser:{configured:false}}};
for(const question of ['关于今天有什么新闻吗？','今天有哪些新闻？','盘点今天的重要新闻','今天有什么消息','最近发生了什么','给我说说今日要闻','今天有啥新鲜事','今日要闻','看看官方资料，今天有什么新闻','What is in the news today?']){
 const flow=defaultOnlineLookup(question,policy);
 assert.equal(flow?.coverageTarget,3,question);assert.equal(flow.reviewRequired,true,question);
}
for(const q of ['只查一家新闻网站','只用 web_search 查今天新闻','读取 https://example.org/news','查阅 Python 官方文档','Playwright getByRole 用法'])assert.equal(publicResearchScope(q).target,1,q);
assert.equal(publicResearchScope('核实这个传言是否属实').target,2);
assert.equal(publicResearchScope('帮我查查最近的情况').target,2,'Unrecognized research wording must not silently fall back to one source');
assert.equal(defaultOnlineLookup('不要联网，今天有什么新闻',policy),null);
const urls=['https://a.example.org/news','https://b.example.net/news','https://c.example.com/news','https://d.example.edu/news'];
const quote='发布说明指出本次观测结果仍需进一步核对。';
const body=url=>({url,title:'公开报道',excerpt:quote+'独立报道来源 '+url,read_method:'http_text'});
const observations=urls.map(url=>({tool:'web_read',result:{status:'completed',sources:[body(url)]}}));
const assessment=(status='corroborated',evidence=urls.slice(0,2).map(url=>({url,quote})))=>({claims:[{claim:'观测结果仍需核对',status,evidence,note:'两份正文均有上述表述，未把汇总页当成原始测量。'}],gaps:[],follow_up_queries:[]});
assert.equal(reviewResearch({assessment:JSON.stringify(assessment())},observations).claims[0].status,'corroborated');
const sameHost=assessment('corroborated',[{url:urls[0],quote},{url:urls[0],quote}]);
assert.equal(reviewResearch({assessment:JSON.stringify(sameHost)},observations).claims[0].status,'single_source');
assert.equal(reviewResearch({assessment:JSON.stringify(sameHost)},observations,{requireIndependentSupport:true}).coverage_complete,false,'News cannot complete a cross-check merely by quoting one site several times');
assert.equal(reviewResearch({assessment:JSON.stringify(assessment())},observations.map(o=>({...o,result:{...o.result,sources:[{...o.result.sources[0],excerpt:quote}]}}))).claims[0].status,'single_source','Identical syndicated bodies are not independent evidence');
assert.equal(reviewResearch({assessment:JSON.stringify(assessment())},observations.map(o=>({...o,tool:'web_search'}))).status,'failed');
const forged=assessment();forged.claims[0].evidence[0].quote='实际网页里根本没有出现的长段落';
assert.equal(reviewResearch({assessment:JSON.stringify(forged)},observations).status,'failed');

const flow=defaultOnlineLookup('关于今天有什么新闻吗？',policy),events=[],requests=[];
let active=0,peak=0,reviewCount=0,searches=0,saved;
const final={id:'final',type:'message',role:'assistant',phase:'final_answer',content:[{type:'output_text',text:'多来源核对完成；仍保留来源中的不确定性。'}]};
const client={responses:{async create(params){requests.push(structuredClone(params));return (async function*(){
 if(params.tool_choice?.name==='research_review'){
  const value=assessment();
  if(++reviewCount===1){value.gaps=['需要核对原始发布说明'];value.follow_up_queries=['观测结果 原始发布说明'];}
  yield {type:'response.completed',response:{output:[{type:'function_call',call_id:'review-'+reviewCount,name:'research_review',arguments:JSON.stringify({assessment:JSON.stringify(value)})}]}};
 }else{
  yield {type:'response.output_item.added',item:{...final,content:[]}};
  yield {type:'response.output_text.delta',item_id:'final',delta:final.content[0].text};
  yield {type:'response.output_item.done',item:final};yield {type:'response.completed',response:{output:[final]}};
 }
})();}}};
const runtime=nativeAgentRuntime({provider:'openai-compatible',model:'fixture',responses_api:true},{client});
const execute=async(tool,args)=>{
 if(tool==='web_search'){searches++;return {status:'completed',sources:(searches===1?urls:[urls[0]+'/original']).map(url=>({...body(url),read_method:'search_result_snippet'}))};}
 active++;peak=Math.max(peak,active);
 try{await delay(args.url===urls[0]?35:15);if(args.url===urls[2])throw Error('one page timed out');return {status:'completed',sources:[body(args.url)]};}finally{active--;}
};
const options={tools:['web_search','web_read','research_review'],publicReadAhead:true,publicReadConcurrency:3,nextRequiredTool:s=>flow.next(s),nextRequiredBatch:(s,f)=>flow.batch(s,f),maxActions:16,maxTurns:18,maxOutputTokens:2000,onAgentEvent:e=>events.push(e),onCheckpoint:s=>{saved=structuredClone(s);}};
const result=await runNativeAgent(runtime,[{role:'user',content:'今天有什么新闻'}],execute,options);
assert.equal(peak,3,'Reads actually overlap, capped at three');assert.equal(active,0);
assert.equal(searches,2,'A review gap triggers a targeted follow-up query');assert.equal(reviewCount,2);
assert.equal(result.workflow.receipts.filter(r=>r.tool==='web_read').length,5,'One failed read does not cancel successful reads; another domain fills coverage and an original page fills the gap');
assert.equal(result.workflow.receipts.find(r=>r.args.url===urls[2]).status,'failed');
assert.equal(result.workflow.gaps.length,0);
assert.ok(events.filter(e=>e.type==='agent.tool.started'&&e.name==='web_read').slice(0,3).every(e=>events.indexOf(e)<events.findIndex(e=>e.type==='agent.tool.completed'&&e.name==='web_read')));
assert.equal(new Set(result.workflow.receipts.map(r=>r.call_id)).size,result.workflow.receipts.length);
for(let i=0;i<result.workflow.receipts.length;i++)assert.equal(result.workflow.receipts[i].tool,result.workflow.observations[i].tool);
const resumed=await runNativeAgent(runtime,[{role:'user',content:'今天有什么新闻'}],()=>{throw Error('must not repeat');},{...options,resumeCheckpoint:saved});
assert.equal(resumed.native_stream.resumed,true);
assert.equal(requests.length,3,'A completed resume does not repeat provider calls');

// Limited budget may never expand a planned batch past the remaining slots.
let calls=0;
await runNativeAgent(runtime,[{role:'user',content:'今天新闻'}],async(tool,args)=>{calls++;return {status:'completed',sources:(tool==='web_search'?urls:[args.url]).map(body)};},{...options,maxActions:2});
assert.equal(calls,2);
console.log('Multi-source research passed: wording variants, explicit limits, three concurrent reads, failure isolation, two reviews, targeted follow-up, validated quotes, same-site/syndication guard, budget and resume.');

// More tool rounds can produce more than twelve native progress messages.
// Keep the bounded stream and its checkpoint compatible with the server.
const manyClient={responses:{async create(){return (async function*(){
 const messages=[];
 for(let i=0;i<14;i++){
  const item={id:'progress-'+i,type:'message',role:'assistant',phase:i===13?'final_answer':'commentary',content:[{type:'output_text',text:i===13?'已完成本轮核对。':'继续核对来源。'}]};
  messages.push(item);yield {type:'response.output_item.added',item:{...item,content:[]}};
  yield {type:'response.output_text.delta',item_id:item.id,delta:item.content[0].text};yield {type:'response.output_item.done',item};
 }
 yield {type:'response.completed',response:{output:messages}};
})();}}};
const extended=await runNativeAgent(nativeAgentRuntime({provider:'openai-compatible',model:'fixture',responses_api:true},{client:manyClient}),[{role:'user',content:'继续核对'}],null,{tools:[],maxActions:0});
assert.equal(extended.native_stream.message_items.length,14);
assert.match(extended.answer,/已完成/);
