import assert from 'node:assert/strict';
import {evidenceLoop,toolDecision,decisionOptions,createDecisionModel,modelObservation} from '../federation/tool-loop.mjs';
import {runIntakeTurn} from '../federation/intake-turn.mjs';
import {queryTerms} from '../federation/retrieval.mjs';
import {runProductAnalysis} from '../federation/product-analysis-turn.mjs';
assert(queryTerms('怎么赚钱').some(t=>t.term==='商业模式'));
const named=queryTerms('@AI 产品思维 Agent 先用知识库补查 Intercom 的按结果收费');
assert(named.some(t=>t.term==='Intercom'));assert(!named.some(t=>t.term==='Agent'||t.term==='思维'));
const fullObservation={tool:'wiki_search',result:{status:'completed',text:'实际正文',reads:[{path:'/cost.md',sources:[{private_audit_marker:'AUDIT_ONLY'}]}]}};
assert(!JSON.stringify(modelObservation(fullObservation)).includes('AUDIT_ONLY'));assert(JSON.stringify(fullObservation).includes('AUDIT_ONLY'),'Audit evidence must remain complete outside the model prompt');
assert.throws(()=>toolDecision('{"action":"tool","tool":"shell","args":{}}',['wiki_search']));
assert.equal(decisionOptions('openai-compatible','qwen3.5:9b',{OPENAI_COMPATIBLE_BASE_URL:'http://127.0.0.1:11436/v1'}).reasoning.effort,'none');
assert.equal(decisionOptions('openai-compatible','cloud-model',{OPENAI_COMPATIBLE_BASE_URL:'https://example.org/v1'}).reasoning,undefined);
const localBefore=process.env.OPENAI_COMPATIBLE_BASE_URL,effortBefore=process.env.OPENWIKI_REASONING_EFFORT;
process.env.OPENAI_COMPATIBLE_BASE_URL='http://127.0.0.1:11436/v1';
try {
 const m=createDecisionModel({createModel:()=>({effort:process.env.OPENWIKI_REASONING_EFFORT,supported:process.env.OPENWIKI_OPENAI_COMPATIBLE_REASONING_EFFORT_SUPPORTED})},'openai-compatible','qwen3.5:9b',0,1100);
 assert.equal(m.effort,'none');assert.equal(m.supported,'true');assert.equal(process.env.OPENWIKI_REASONING_EFFORT,effortBefore);
}finally{if(localBefore===undefined)delete process.env.OPENAI_COMPATIBLE_BASE_URL;else process.env.OPENAI_COMPATIBLE_BASE_URL=localBefore;}
let decisions=0;const finalInputs=[];
const intakeRuntime={loadOpenWikiEnv:async()=>{},resolveConfiguredProvider:()=> 'openai-compatible',resolveModelId:()=> 'test-model',resolveProviderRetryAttempts:()=>0,
 createModel:(_p,_m,_r,budget)=>({invoke:async(messages,opts)=>{
   if(budget===1100){assert.equal(opts.response_format.type,'json_object');return {content:JSON.stringify(decisions++===0?{action:'tool',tool:'wiki_search',args:{query:'单位贡献与成本'}}:{action:'finish',gaps:[]})};}
   finalInputs.push(messages);return {content:'根据实际补查结果解释单位贡献。'};
 }})};
const intake=await runIntakeTurn('请先用知识库补查单位贡献','consultation',{wiki:{text:'预读内容只有通用介绍',reads:[],retrieval:{missing_evidence:false}},templates:{text:'',reads:[]},skills:{text:'',reads:[]}},intakeRuntime,
 {currentQuestion:'请先用知识库补查单位贡献',executeTool:async()=>({status:'completed',text:'工具实际返回的单位成本资料'})});
assert.equal(intake.workflow.receipts.length,1);assert(finalInputs[0].some(m=>m.content.includes('工具实际返回的单位成本资料')));
let calls=0;const observed=[];
const model={invoke:async messages=>{observed.push(messages);return {content:JSON.stringify(calls++===0?{action:'tool',tool:'wiki_search',args:{query:'定价与成本'},reason:'缺成本'}:{action:'finish',gaps:[]})};}};
const loop=await evidenceLoop(model,'如何收费',{},async(t,a)=>({status:'completed',text:'真实读取片段',reads:[{path:'/cost.md'}]}));
assert.equal(loop.receipts.length,1);assert(observed[1][1].content.includes('真实读取片段'));assert.equal(loop.scope,'read-only');
const repeated=await evidenceLoop({invoke:async()=>({content:'{"action":"tool","tool":"wiki_search","args":{"query":"同一查询"}}'})},'测试',{},async()=>({status:'failed',error:'来源不可用'}));
assert.equal(repeated.receipts.length,1);assert(repeated.gaps.includes('补查重复，已停止'));
const malformed=await evidenceLoop({invoke:async()=>({content:'不是JSON'})},'测试',{},async()=>{throw Error('不应该执行');});assert.equal(malformed.receipts.length,0);assert(malformed.gaps.length);
let n=0;const source={url:'https://example.org/product',title:'Fixture',excerpt:'产品公开页展示用户可以阅读研究报告。',sha256:'test'};
const fake={createModel:()=>({invoke:async()=>({content:++n===1?'{"action":"finish","gaps":["没有市场规模证据"]}':n===2?'{"price":"10","unit_cost":"3","fixed_cost":"100","units":"20","discount":"1"}':n===3?'[{"url":"https://example.org/product","quote":"用户可以阅读研究报告","fact":"用户可以阅读研究报告"}]':'# 测试产品分析\n\n这是受控模型草稿，公开来源有限。'} )})};
const result=await runProductAnalysis(fake,'fixture','controlled-model',0,'分析产品',{sources:[source],status:'completed'}, {executeTool:async()=>({status:'completed',inputs:{price:'10',unit_cost:'3',fixed_cost:'100',units:'20',discount:'1'},revenue:'200',total_cost:'160',profit:'40',unit_margin:'7',break_even_units:'15',formula:'fixture'})});
assert(result.analysis_run.quality.calculation_checked);assert(result.answer.includes('利润 40'));assert(result.analysis_run.quality.unresolved_gaps.includes('没有市场规模证据'));assert.equal(result.analysis_run.quality.independently_verified,false);
console.log('Bounded observe-and-replan tools, alias retrieval, invalid decisions, repeated queries, calculation receipt and report gaps passed.');
