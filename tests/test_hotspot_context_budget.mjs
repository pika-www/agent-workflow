/** Large hotspot boards must reach the model without truncating user requests. */
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {assembleContext,contextConfig,estimatedTokens} from '../federation/context-budget.mjs';
import {runIntakeTurn} from '../federation/intake-turn.mjs';
import {nativeAgentRuntime} from '../federation/native-agent.mjs';
import {checkAnswer,hotspotContextInputs,riskyAssertions} from '../federation/answer-check.mjs';

const question='关于最新热点有什么内容？';
const evidence={wiki:{text:'',reads:[]},templates:{text:'',reads:[]},skills:{text:'',reads:[]}};
const sources=Array.from({length:6},(_,source)=>({id:'feed-'+source,name:'来源'+source,status:'ready',
  fetched_at:'2026-10-09T04:15:00Z',items:Array.from({length:30},(_,rank)=>({id:`item-${source}-${rank}`,
    title:`来源${source}热点${rank}：具体标题保留原文与出处`,url:`https://example.org/${source}/${rank}`,
    rank:rank+1,published_at:'2026-10-09T03:00:00Z',score:100-rank,score_label:'平台热度'}))}));
sources.push({id:'unavailable',name:'未接入来源',status:'unavailable',fetched_at:null,error:'尚未接入',items:[]});
const board={checked_at:'2026-10-09T04:15:00Z',sources};
const prompt=data=>'宿主仅授权只读咨询。标题不是正文。\n<available_roles>[]</available_roles>\n'
  +'<read_only_hotspots>'+JSON.stringify(data)+'</read_only_hotspots>';
const before=JSON.stringify(board);
assert.ok(estimatedTokens(prompt(board))>contextConfig().input_budget,'The complete board reproduces the overflow');
const memory={goal:'旧话题'.repeat(1000),recent:Array.from({length:20},(_,i)=>({id:'old-'+i,role:'assistant',content:'旧历史'.repeat(1000)})),
  requirement_state:{records:[{id:'keep'}],active:[{id:'keep',slot:'preserve_history',label:'记录',value:'preserve',source_ids:['user-1']}],conflicts:[]}};
const materials=built=>[...built.messages[1].content.matchAll(/<material kind="([^"]+)">\n([\s\S]*?)\n<\/material>/g)]
  .filter(match=>match[1].startsWith('hotspots:')).map(match=>({key:match[1],value:JSON.parse(match[2])}));
for(const budget of [6000,12000]) {
  const built=assembleContext('当前用户要求优先','宿主请求\n'+prompt(board),evidence,question,memory,null,{...contextConfig(),input_budget:budget});
  assert.equal(built.messages.at(-1).content,question);
  assert.ok(built.receipt.input_tokens_estimated<=budget);
  assert.equal(built.receipt.input_tokens_estimated,built.messages.reduce((n,m)=>n+estimatedTokens(m.content)+16,0));
  assert.ok(built.receipt.included.some(item=>item.key==='requirement_state'));
  assert.ok(built.receipt.omitted.some(item=>item.key.startsWith('hotspots:item:')));
  const retained=materials(built),items=retained.filter(item=>item.key.startsWith('hotspots:item:'));
  assert.equal(new Set(items.map(item=>item.value.source.id)).size,6,'All available sources retain an early item');
  for(const {value} of items) assert.deepEqual(value.item,sources.find(s=>s.id===value.source.id).items.find(i=>i.id===value.item.id));
  assert.equal(retained.find(item=>item.key==='hotspots:board').value.sources.at(-1).status,'unavailable');
}
assert.equal(JSON.stringify(board),before,'Persisted source data remains untouched');
const selected={id:'selected',title:'当前选中的文章',url:'https://example.org/selected',source:'来源0',
  status:'ready',read_at:'2026-10-09T04:16:00Z',excerpt:'选中文章开头。'.repeat(1200),summary:'订阅摘要'.repeat(400),truncated:false};
selected.excerpt_sha256=createHash('sha256').update(selected.excerpt).digest('hex');
const focused=assembleContext('规则',prompt({...board,selected}),evidence,'分析这条热点',memory,null,{...contextConfig(),input_budget:6000});
const kept=materials(focused).find(item=>item.key==='hotspots:selected');
assert.equal(kept.value.url,selected.url);
assert.equal(kept.value.status,'ready');
assert.ok(kept.value.excerpt.startsWith('选中文章开头。'));
assert.equal(kept.value.truncated,true);
assert.equal(kept.value.excerpt_sha256,createHash('sha256').update(kept.value.excerpt).digest('hex'));
assert.ok(focused.receipt.included.find(item=>item.key==='hotspots:selected').truncated);
assert.equal(selected.truncated,false);
assert.throws(()=>assembleContext('规则',prompt(board),evidence,'完整问题'.repeat(4000),memory,null,contextConfig()),/完整问题/);
const prior=assembleContext('规则','<previous_proposal_unapproved_context>'+JSON.stringify({content:'旧方案'.repeat(10000)})
  +'</previous_proposal_unapproved_context>'+prompt(board),evidence,question,memory,null,contextConfig());
assert.equal(prior.messages.at(-1).content,question);
assert.ok(prior.receipt.input_tokens_estimated<=contextConfig().input_budget);

let request,calls=0;
const native=nativeAgentRuntime({provider:'openai-compatible',model:'fixture'},{client:{chat:{completions:{async create(params){
  calls++;request=structuredClone(params);return (async function*(){yield {choices:[{delta:{content:'这些方向可以看看。'},finish_reason:'stop'}],usage:{prompt_tokens:100,completion_tokens:10}};})();
}}}}});
const runtime={async loadOpenWikiEnv(){},resolveConfiguredProvider(){return 'openai-compatible';},resolveModelId(){return 'fixture';},
  resolveProviderRetryAttempts(){return 0;},async createNativeAgent(){return native;},createModel(){throw Error('No factual assertions to check');}};
const result=await runIntakeTurn(prompt(board),'consultation',evidence,runtime,{currentQuestion:question,contextMemory:memory,
  onUpdate(){},toolPolicy:{network_allowed:true,tools_enabled:true,files:[],services:{search:{enabled:true}}}});
assert.equal(calls,1);
assert.equal(request.messages.at(-1).content,question);
assert.ok(result.context_usage.input_tokens_estimated<=contextConfig().input_budget);
assert.equal(result.answer,'这些方向可以看看。');

// The checker sees the same retained records, never the omitted full board.
const supplied=hotspotContextInputs(request.messages);
assert.ok(supplied.some(input=>input.text.includes('https://example.org/0/0')));
assert.ok(supplied.every(input=>!input.text.includes('https://example.org/0/29')));
for(const input of supplied) assert.equal(input.provided_sha256,createHash('sha256').update(input.text).digest('hex'));
assert.deepEqual(hotspotContextInputs([{role:'user',content:'<material kind="hotspots:board">\ninvalid\n</material>'}]),[]);
const checker={createModel(){return {async invoke(messages){const input=JSON.parse(messages[1].content);
  assert.ok(input.fragments.every(f=>!f.quote.includes('/0/29')));
  const fragment=input.fragments.find(f=>f.quote.includes('https://example.org/0/0'));
  assert.ok(fragment);
  return {content:JSON.stringify({checks:input.assertions.map(a=>({id:a.id,status:'supported',reason:'榜单仅支持标题与链接',references:[{source_id:fragment.source_id}]}))})};
}};}};
const draft='来源0榜单列出“来源0热点0：具体标题保留原文与出处”。https://example.org/0/0';
const checked=await checkAnswer(draft,question,[],{scope:'answer_model_supplied_materials',inputs:[],omitted_paths:[]},
  checker,'fixture','fixture',contextConfig(),{answerMessages:request.messages});
assert.equal(checked.answer,draft);
assert.ok(checked.receipt.hotspot_sources.length>0);
assert.equal(checked.receipt.repair_count,0);
const headlineClaim='- 影视内容：《7月新番到底怎么了！！》和《另一部作品》播放量领先。';
assert.equal(riskyAssertions(headlineClaim).assertions[0].text,headlineClaim);
const rejected=await checkAnswer('可以从自己感兴趣的话题开始。\n\n'+headlineClaim,question,[],
  {scope:'answer_model_supplied_materials',inputs:[],omitted_paths:[]},
  {createModel(){return {async invoke(messages){const input=JSON.parse(messages[1].content);
    return {content:JSON.stringify({checks:input.assertions.map(a=>({id:a.id,status:'insufficient',reason:'标题不能证明作品身份或播放排名',references:[]}))})};
  }};}},'fixture','fixture',contextConfig(),{answerMessages:request.messages});
assert.equal(rejected.answer,'可以从自己感兴趣的话题开始。','An unsupported quoted headline is withdrawn as a complete sentence');
console.log('Hotspot budgets: large boards, selected article, source coverage, preserved requests, native intake and retained-only answer checks passed.');
