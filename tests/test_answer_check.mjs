import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {assembleContext, contextConfig} from '../federation/context-budget.mjs';
import {suppliedWikiInputs, checkWikiCitations} from '../federation/wiki-evidence.mjs';
import {riskyAssertions, validateAssessment, checkAnswer, assessmentFragments, resolveAssessmentReferences, enforceQuoteBoundaries, restrictedEvidencePaths,userContextInputs} from '../federation/answer-check.mjs';
import {runIntakeTurn, firstEvidenceReply} from '../federation/intake-turn.mjs';
import {repairLanguagePolicy} from '../federation/reply-language.mjs';
import {nativeAgentRuntime} from '../federation/native-agent.mjs';

const sha = s => createHash('sha256').update(s).digest('hex');
const paths = ['/index.md','/topics/metr.md','/topics/omitted.md'];
const reads = paths.map(path=>({path,page_version:'a'.repeat(64),knowledge_status:'untracked',truncated:false,citation_label:`[Wiki: ${path}]`}));
const text = 'METR 测量的是开发任务完成时间，不是学习掌握速度。';
const envelope = items => '<verified_wiki_reads>'+JSON.stringify({evidence:items})+'</verified_wiki_reads>';
const evidence = {wiki:{reads,text:envelope([{path:paths[0],text:'目录列出 /topics/omitted.md。'},
  {path:paths[1],text,claims:[{id:'claim',text,kind:'fact',semantic_review:'pending',status:'current',references:[{quote:'Time to complete development tasks.',freshness:'local_only'}]}]},
  {path:paths[2],text:'不可用于已被预算省略的页面。'.repeat(5000),claims:Array.from({length:40},()=>({references:[{quote:'very long metadata '.repeat(1000)}]}))}])},templates:{text:'',reads:[]},skills:{text:'',reads:[]}};
const built = assembleContext('安全规则','宿主要求',evidence,'这项研究说明什么？',null,null,{...contextConfig(),input_budget:3000});
const supplied = suppliedWikiInputs(built.suppliedMaterials,reads);
assert.ok(supplied.inputs.some(i=>i.path===paths[1]));
assert.ok(supplied.omitted_paths.includes(paths[2]));
assert.equal(checkWikiCitations('[Wiki: /topics/omitted.md]',reads,supplied).citations[0].reason,'not_supplied_to_answer_model');
assert.equal(checkWikiCitations('根据我读过的 /topics/omitted.md 得出结论。',reads,supplied).status,'invalid');
assert.equal(checkWikiCitations('可以去阅读 /topics/omitted.md。',reads,supplied).status,'no_citations');
assert.equal(checkWikiCitations('[Wiki: /topics/metr.md]',reads,supplied).status,'valid');
for(const material of built.suppliedMaterials.filter(m=>m.key.startsWith('wiki:'))) {
 const input = supplied.inputs.find(i=>i.origin===material.key);
 if(input) {assert.equal(input.provided_sha256,sha(material.text));assert.ok(built.messages[1].content.includes(JSON.parse(material.text).text));}
}
const clipped = assembleContext('规则','宿主要求',{...evidence,wiki:{reads:[reads[1]],text:envelope([{path:paths[1],text:'abcdef '.repeat(6000)}])}},'问题',null,null,{...contextConfig(),input_budget:1600});
const clippedInput = suppliedWikiInputs(clipped.suppliedMaterials,[reads[1]]).inputs[0];
assert.ok(clippedInput.truncated);
assert.ok(clippedInput.excerpt_chars < 42000);
assert.equal(clippedInput.excerpt_sha256,sha(clippedInput.text));
assert.deepEqual(suppliedWikiInputs([{key:'wiki',text:'非结构化资料'}],reads).inputs,[],'Fail closed without a reliable page/body mapping');
const tool = {tool:'wiki_search',result:{status:'completed',text:envelope([{path:paths[1],text}])}};
assert.equal(suppliedWikiInputs([{key:'tools:0',text:JSON.stringify(tool)}],reads).inputs[0].path,paths[1]);
assert.equal(suppliedWikiInputs([{key:'tools:0',text:JSON.stringify({...tool,result:{...tool.result,text:tool.result.text.slice(0,70)}})}],reads).inputs.length,0);

const draft = 'METR 研究发现开发者更快掌握 AI 工具。[Wiki: /topics/metr.md]';
const assertions = riskyAssertions(draft).assertions;
assert.equal(assertions.length,1);
assert.equal(riskyAssertions('假设耗时降低20%，可以试试。没有数据证明现在更快。你好！').assertions.length,0);
assert.equal(riskyAssertions('METR 在2026年2月表示，无法可靠估计生产力效果。').assertions.length,1,'An uncertain result does not exempt the study/date claim from verification');
const assessment = {checks:[{id:assertions[0].id,status:'contradicted',reason:'衡量开发耗时，不衡量学习掌握速度。',references:[{path:paths[1],quote:'测量的是开发任务完成时间'}]}]};
const fragments = assessmentFragments(supplied);
const fragment = fragments.find(f=>f.path===paths[1] && f.quote.includes('开发任务完成时间'));
const typedAssessment = {checks:[{...assessment.checks[0],references:[{source_id:fragment.source_id}]}]};
// Compatible Responses gateways may prepend an empty unphased message. The
// private verifier must retain its checked JSON rather than withdraw real facts.
const supportedDraft=text+'[Wiki: /topics/metr.md]';
const supportedAssessment={checks:riskyAssertions(supportedDraft).assertions.map(a=>({id:a.id,status:'supported',reason:'原文明确说明',references:[{source_id:fragment.source_id}]}))};
const assessmentItems=[{id:'prelude',type:'message',role:'assistant',status:'completed',content:[]},
  {id:'verified',type:'message',role:'assistant',phase:'final_answer',status:'completed',content:[{type:'output_text',text:JSON.stringify(supportedAssessment),annotations:[]}]}];
const compatibleVerifier={async createNativeAgent(){return nativeAgentRuntime({provider:'openai-compatible',model:'fixture',responses_api:true,api_key:'fixture'},
  {client:{responses:{async create(){return (async function*(){
    yield {type:'response.created',response:{id:'assessment-fixture'}};
    for(const item of assessmentItems){yield {type:'response.output_item.added',item:{...item,content:[]}};if(item.content.length)yield {type:'response.output_text.delta',item_id:item.id,delta:item.content[0].text};yield {type:'response.output_item.done',item};}
    yield {type:'response.completed',response:{id:'assessment-fixture',output:assessmentItems,usage:{input_tokens:100,output_tokens:20}}};
  })();}}}});},createModel(){throw new Error('Valid exact evidence needs no rewrite');}};
const nativeChecked=await checkAnswer(supportedDraft,'METR说明什么',reads,supplied,compatibleVerifier,'openai-compatible','fixture',contextConfig());
assert.ok(nativeChecked.answer.includes(text));
assert.equal(nativeChecked.receipt.failure,undefined,JSON.stringify(nativeChecked.receipt));
assert.equal(nativeChecked.receipt.checks[0].status,'supported');
assert.equal(JSON.parse(resolveAssessmentReferences(JSON.stringify(typedAssessment),fragments)).checks[0].references[0].quote,fragment.quote);
assert.throws(()=>resolveAssessmentReferences(JSON.stringify({checks:[{references:[{source_id:'invented'}]}]}),fragments),/实际输入/);
assert.equal(validateAssessment(JSON.stringify(assessment),assertions,supplied)[0].basis,'model_assessment_with_exact_input_quotes');
assert.throws(()=>validateAssessment(JSON.stringify({checks:[{...assessment.checks[0],references:[{path:paths[2],quote:'我伪造了实际输入没有的句子'}]}]}),assertions,supplied),/实际输入/);
assert.throws(()=>validateAssessment(JSON.stringify({checks:[{...assessment.checks[0],status:'supported',references:[]}]}),assertions,supplied),/逐字依据/);
assert.throws(()=>validateAssessment(JSON.stringify({checks:[assessment.checks[0],assessment.checks[0]]}),assertions,supplied));

let calls = [], interim = [], progress = [];
const runtime = {async loadOpenWikiEnv(){},resolveConfiguredProvider(){return 'fixture';},resolveModelId(){return 'fixture';},resolveProviderRetryAttempts(){return 0;},
 createModel(provider,id,retries,max){calls.push(max);return {async invoke(messages){if(max===1500)assert.ok(messages[0].content.includes(repairLanguagePolicy));return {content:max===1600?JSON.stringify(typedAssessment):'目前无法确认掌握速度。'};}};}};
const checked = await checkAnswer(draft,'METR说明什么',reads,supplied,runtime,'fixture','fixture',contextConfig(),{onUpdate:e=>interim.push(e),onProgress:e=>progress.push(e)});
assert.deepEqual(calls,[1600,1500]);
assert.equal(checked.receipt.repair_count,1);
assert.equal(checked.receipt.human_review,'unchanged');
assert.equal(checked.receipt.status,'corrected_with_limits');
assert.equal(checked.receipt.repair_status,'bounded_rewrite');
assert.equal(interim[0].text,draft);
assert.equal(progress[0].stage,'checking_evidence');
assert.ok(!checked.answer.includes('开发者更快掌握'));
const failed = await checkAnswer(draft,'问题',reads,supplied,{createModel(){return {async invoke(){throw new Error('模型断连');}}}},'fixture','fixture',contextConfig());
assert.equal(failed.receipt.calls,1);
assert.equal(failed.receipt.repair_count,0);
assert.equal(failed.receipt.failure,'invalid_or_failed_assessment');
assert.doesNotMatch(failed.answer,/校对补充|语义核对未完成|对应原文/);
assert.match(failed.receipt.internal_notice,/核对未完成/);
assert.ok(!failed.answer.includes('开发者更快掌握'));
const inventedRewrite = await checkAnswer(draft,'问题',reads,supplied,{createModel(p,i,r,max){return {async invoke(){return {content:max===1600?JSON.stringify(typedAssessment):'METR发现效率提高900%。[Wiki: /topics/metr.md]'};}}}},'fixture','fixture',contextConfig());
assert.equal(inventedRewrite.receipt.repair_status,'withdrawal_fallback');
assert.ok(!inventedRewrite.answer.includes('900%'));
const narratedRewrite = await checkAnswer(draft,'问题',reads,supplied,{createModel(p,i,r,max){return {async invoke(){return {content:max===1600?JSON.stringify(typedAssessment):'校对补充：现有资料不足以确定这个问题，需要补充对应原文。'};}}}},'fixture','fixture',contextConfig());
assert.equal(narratedRewrite.receipt.repair_status,'withdrawal_fallback');
assert.doesNotMatch(narratedRewrite.answer,/校对补充|对应原文/);
const freshnessDraft = '这项研究是今天的最新网页结果。[Wiki: /topics/metr.md]';
const freshnessAssertion = riskyAssertions(freshnessDraft).assertions;
const noFreshness = {checks:freshnessAssertion.map(a=>({id:a.id,status:'insufficient',reason:'只有本地归档，无法确认今天。',references:[]}))};
const freshness = await checkAnswer(freshnessDraft,'问题',reads,supplied,{createModel(p,i,r,max){return {async invoke(){return {content:max===1600?JSON.stringify(noFreshness):'无法确认当前网页状态，只有归档资料。'};}}}},'fixture','fixture',contextConfig());
assert.ok(!freshness.answer.includes('最新网页结果'));
const simple = await checkAnswer('你好！','你好',reads,supplied,{createModel(){throw new Error('不应增加模型调用');}},'fixture','fixture',contextConfig());
assert.equal(simple.receipt.calls,0);
assert.equal(simple.answer,'你好！');
assert.match(firstEvidenceReply(supplied,{}).text,/含义尚待人工核对/);
const hax={...supplied.inputs[1],path:'/topics/hax.md',claims:[{kind:'fact',text:'允许用户编辑纠正 AI 输出。',status:'current',semantic_review:'pending'}]};
assert.equal(firstEvidenceReply({...supplied,inputs:[hax,...supplied.inputs]}, {},'METR 这项研究说明什么？').path,'/topics/metr.md');
assert.equal(firstEvidenceReply(supplied,{},'完全无关的物种名称'),null,'No canned reply replaces loading when there is no relevant source');
const rawPage={...supplied.inputs[1],claims:[],text:'# METR\n\nMETR 的归档正文介绍开发者参与研究的条件。'};
assert.equal(firstEvidenceReply({...supplied,inputs:[rawPage]}, {},'METR 说明什么').origin,'host_prefetched_excerpt');
const alphabetical={...evidence,wiki:{reads,text:envelope([{path:'/index.md',text:'目录列出 /topics/metr.md。'},
 {path:'/topics/hax.md',text:'无关交互资料。'.repeat(4000)},
 {path:'/topics/metr.md',text,claims:[{kind:'fact',text,semantic_review:'pending',status:'current'}]}])}};
const rankedBudget=assembleContext('安全规则','问题',alphabetical,'METR 的实验结论是什么？',null,null,{...contextConfig(),input_budget:1800});
assert.equal(rankedBudget.suppliedMaterials[0].key,'wiki:/topics/metr.md');
assert.ok(suppliedWikiInputs(rankedBudget.suppliedMaterials,reads).inputs.some(i=>i.path==='/topics/metr.md'));
assert.equal(firstEvidenceReply({inputs:[]},{missing_evidence:true}),null);
const longDraft = Array.from({length:8},(_,i)=>`研究发现效率提升${i+10}%。`).join('');
const longFailure = await checkAnswer(longDraft,'问题',reads,supplied,{createModel(){return {async invoke(){throw new Error('核对不可用');}}}},'fixture','fixture',contextConfig());
assert.ok(!longFailure.answer.includes('效率提升'));
assert.equal(longFailure.receipt.unchecked_assertions_withdrawn,8);
const noInputs = await checkAnswer('研究发现效率提升90%。','问题',[],{scope:'answer_model_supplied_materials',inputs:[],omitted_paths:[]},
 {createModel(){throw new Error('No evidence must not cause an extra model call');}},'fixture','fixture',contextConfig());
assert.ok(['no_actual_evidence_inputs','no_usable_evidence_fragments'].includes(noInputs.receipt.failure));
assert.equal(noInputs.receipt.calls,0);
assert.ok(!noInputs.answer.includes('效率提升90%'));
const overreachDraft = 'METR研究测量开发任务时间，因此证明开发者学习更快。\n这项研究是今天的最新网页结果。';
const overreachAssertions = riskyAssertions(overreachDraft).assertions;
const overreachAssessment = {checks:overreachAssertions.map((a,i)=>({id:a.id,status:i===0?'supported':'insufficient',reason:'模拟核对模型遗漏了额外推测',
 references:i===0?[{source_id:fragment.source_id}]:[]}))};
const conservative = await checkAnswer(overreachDraft,'METR说明什么',reads,supplied,{createModel(p,i,r,max){return {async invoke(){return {content:max===1600?JSON.stringify(overreachAssessment):'研究发现效率提高900%。'};}}}},'fixture','fixture',contextConfig());
assert.equal(conservative.receipt.fallback_basis,'exact_input_quotes_and_archive_annotation');
assert.ok(conservative.answer.includes(fragment.quote));
assert.ok(!conservative.answer.includes('因此证明开发者学习更快'));
assert.equal(enforceQuoteBoundaries({status:'supported',references:[{quote:'AI may reduce time by 20%.'}]},
 {text:'实验导致耗时降低20%。'}).basis,'host_quote_boundary');
assert.equal(enforceQuoteBoundaries({status:'supported',references:[{quote:'Time to complete development tasks.'}]},
 {text:'实验效率提高900%。'}).status,'insufficient');
assert.equal(riskyAssertions('这个系统采用 Redis 保存订单。').assertions.length,1);
assert.equal(riskyAssertions('当前要求是使用 Angular。').assertions[0].risks.includes('causal_or_result'),false,'使用 must not be parsed as a causal 使 claim');
assert.equal(riskyAssertions('建议采用 Redis 保存订单。').assertions.length,0);
const conceptQuestion='只做本轮文字推演，不联网、不使用工具。请以30个汉字说明排空时为何不能强制停止已受理任务；只解释概念，不执行任何操作。';
const conceptAnswer='排空是缓冲机制，强制停止会破坏状态一致性，导致数据丢失或逻辑错误。';
assert.equal(riskyAssertions(conceptAnswer,{question:conceptQuestion}).assertions.length,0);
assert(riskyAssertions(conceptAnswer,{question:'当前项目的实际执行结果是什么？'}).assertions.length>0);
for(const claim of ['当前系统已经部署完成。','这个系统采用新算法，导致错误减少。','研究证明该流程提高90%的效率。','该方案会降低20%的成本。','保证排空不会导致数据丢失。'])
  assert(riskyAssertions(claim,{question:conceptQuestion}).assertions.length>0,claim);
assert(riskyAssertions(conceptAnswer,{question:conceptQuestion,sourceOnly:true}).assertions.length>0);
assert.equal(riskyAssertions('建议先记录数据清洗任务的输入和产出。每步包含通过标准，再按标准检查产出。').assertions.length,0);
assert.equal(riskyAssertions('建议在流程末端保留回溯机制，允许修改上游定义（例如：发现后端接口文档与实际服务不一致时）。').assertions.length,0,'A conditional discovery example is advice, not a completed research finding');
assert.ok(riskyAssertions('建议修改步骤。例如，研究发现该流程提高90%的效率。').assertions.length>0,'Examples must not exempt factual research claims');
assert.ok(riskyAssertions('建议先记录任务。研究证明效率提升90%。').assertions.length>0);
assert.ok(riskyAssertions('建议先记录任务。页面提供免费服务。').assertions.length>0);
assert.ok(riskyAssertions('建议先记录任务。该方法已部署生产。').assertions.length>0);
assert.ok(riskyAssertions('建议先记录任务。该方法提高90%的效率。').assertions.length>0);
assert.ok(riskyAssertions('建议先记录任务。利用构建错误拦截流程能显著降低后期合并冲突的概率，这是一种经过行业验证的通用做法。').assertions.length>0);
assert.ok(riskyAssertions('建议采用自动检查。虽然工具效果尚不能确认，但该流程能显著降低合并冲突，这是一种经过行业验证的做法。').assertions.some(a=>a.text.includes('显著降低')),'A caveat before but must not exempt the positive effect claim');
assert.equal(riskyAssertions('建议在关键路径设置人工评审点，以此作为阶段性的“已验证”标记。若需求变更，则需重新校准这些标准。').assertions.length,0,'A suggested workflow status label is not an execution receipt');
let adviceRepairCalls=0;
const adviceRetained=await checkAnswer('建议先定义输入、输出和验收标准。每个步骤只处理一个目标。\n\n建议采用构建检查。该流程能显著降低合并冲突，这是一种经过行业验证的通用做法。',
 '如何把复杂任务拆解成可验证的步骤？',[],{scope:'answer_model_supplied_materials',inputs:[],omitted_paths:[]},
 {createModel(p,i,r,max){return {async invoke(messages){adviceRepairCalls++;assert.equal(max,1600,'No all-answer rewrite should erase advice with no external source');const input=JSON.parse(messages[1].content);return {content:JSON.stringify({checks:input.assertions.map(a=>({id:a.id,status:'insufficient',reason:'没有外部效果证据',references:[]}))})};}};}},
 'fixture','fixture',contextConfig(),{answerMessages:[{role:'user',content:'如何把复杂任务拆解成可验证的步骤？'}]});
assert.equal(adviceRepairCalls,1);assert.match(adviceRetained.answer,/建议先定义输入、输出和验收标准/);assert.ok(!adviceRetained.answer.includes('显著降低合并冲突'));
assert.equal(riskyAssertions('请补充您当前项目使用的框架名称，以便我提供后续支持。').assertions.length,0,'A request for missing context is not a factual capability claim');
assert.equal(riskyAssertions('你好，我是你的主 Agent。').assertions.length,0);
assert.equal(enforceQuoteBoundaries({status:'supported',references:[{quote:'检索后把资料提供给模型。'}]},
 {text:'这样能够减少模型幻觉。'}).status,'insufficient');
assert.deepEqual(restrictedEvidencePaths('只根据METR的归档正文回答',supplied),['/topics/metr.md']);
assert.equal(restrictedEvidencePaths('只依据归档资料回答',supplied),null);
assert.equal(riskyAssertions('```js\nconst text = "研究效率提高900%";\n```').assertions.length,0);
const batchedRuntime={createModel(p,i,r,max){return {async invoke(messages){
 if(max===1500)return {content:'METR研究发现效率提高900%。'};
 const input=JSON.parse(messages[1].content);return {content:JSON.stringify({checks:input.assertions.map(a=>({id:a.id,
  status:'supported',reason:'模拟辅助判断',references:[{source_id:fragment.source_id}]}))})};
}};}};
const lateUnsupported=Array.from({length:7},()=>text).join('\n')+'\nMETR研究证明效率提高900%。';
const late=await checkAnswer(lateUnsupported,'METR说明什么',reads,supplied,batchedRuntime,'fixture','fixture',contextConfig());
assert.equal(late.receipt.assertion_total,8);
assert.equal(late.receipt.assessed_assertions,8);
assert.equal(late.receipt.model_usage.filter(m=>m.stage==='answer_check').length,2);
assert.equal(late.receipt.checks.find(c=>c.id==='assertion-8').basis,'host_quote_boundary');
assert.ok(!late.answer.includes('提高900%'));
const overLimit=await checkAnswer(Array.from({length:25},()=>text).join('\n'),'METR说明什么',reads,supplied,batchedRuntime,'fixture','fixture',contextConfig());
assert.equal(overLimit.receipt.assertion_total,25);
assert.equal(overLimit.receipt.assessed_assertions,24);
assert.equal(overLimit.receipt.unassessed_assertions,1);
assert.equal(overLimit.receipt.coverage_status,'partial');
assert.equal(overLimit.receipt.checks.find(c=>c.id==='assertion-25').basis,'host_unassessed_assertion');
assert.equal(overLimit.receipt.unchecked_assertions_withdrawn,1);
const onlyMetr=await checkAnswer('这个定义是检索后交给模型。[Wiki: /index.md]','只根据METR的归档正文回答',reads,supplied,batchedRuntime,'fixture','fixture',contextConfig());
assert.equal(onlyMetr.receipt.user_scope_check.status,'scope_violation');
assert.ok(!onlyMetr.answer.includes('[Wiki: /index.md]'));
const missingScope=await checkAnswer('METR研究证明效率提高900%。','只根据不存在主题的归档正文回答，METR供比对',reads,supplied,
 {createModel(){return {async invoke(){throw new Error('模拟核对失败');}}}},'fixture','fixture',contextConfig());
assert.deepEqual(missingScope.receipt.user_restricted_paths,[]);
assert.ok(!missingScope.answer.includes('[Wiki: /topics/metr.md]'),'Fallback archive annotation must preserve explicit evidence scope');
const userOnly=await checkAnswer('你这次确认采用 React。','我确认这次采用 React。',[],{scope:'answer_model_supplied_materials',inputs:[],omitted_paths:[]},
 {createModel(){return {async invoke(messages){const item=JSON.parse(messages[1].content);return {content:JSON.stringify({checks:item.assertions.map(a=>({id:a.id,status:'supported',reason:'复述用户要求',references:[{source_id:item.fragments.find(f=>f.source_basis==='user_record').source_id}]}))})};}};}},'fixture','fixture',contextConfig(),{answerMessages:[{role:'user',content:'我确认这次采用 React。'}]});
assert.ok(!userOnly.answer.includes('[Wiki:'),'A user record is not a Wiki citation');
assert.equal(userOnly.receipt.status,'assessed_with_limits');

// Draft generation stays private through verification, with one original
// generation, one check and at most one repair; no separate preliminary call.
const {AIMessageChunk} = await import('../openwiki-upstream/node_modules/@langchain/core/dist/messages/ai.js');
let events=[];
const streaming = {...runtime,createModel(p,i,r,max){return {async *stream(){events.push('initial');yield new AIMessageChunk({content:draft});},
 async invoke(){events.push(max===1600?'check':'repair');return {content:max===1600?JSON.stringify(typedAssessment):'不能确定学习掌握速度，先前说法没有依据，已撤回。'};}};}};
const liveShape = {...evidence,wiki:{...evidence.wiki,text:envelope(JSON.parse(evidence.wiki.text.match(/<verified_wiki_reads>(.*)<\/verified_wiki_reads>/)[1]).evidence.slice(0,2))}};
const turn = await runIntakeTurn('请按资料回答','consultation',liveShape,streaming,{currentQuestion:'METR说明什么？',onDelta:t=>events.push('visible'),onUpdate:e=>events.push('interim')});
assert.ok(events.indexOf('visible')>events.indexOf('check'));
assert.ok(events.indexOf('visible')>events.indexOf('repair'));
assert.equal(events.filter(e=>e==='visible').length,1);
assert.equal(events.includes('interim'),false,'Unchecked draft updates stay private');
assert.equal(turn.initial_reply,null);
assert.equal(turn.preliminary_reply,null);
assert.equal(turn.reply_delivery.mode,'after_checks');
assert.equal(turn.context_usage.total_calls,3);
assert.equal(turn.wiki_input.scope,'answer_model_supplied_materials');
assert.equal(turn.answer_check.repair_count,1);
assert.ok(turn.timing.intake_first_text_ms <= turn.timing.intake_total_ms);
assert.ok(turn.timing.answer_check_ms >= 0);
console.log('Answer checks passed: actual-input budgets, omitted/directory/bare-path citations, retained hashes, supplemental reads, semantic drift, fabricated quotes, stale-currentness, one repair, failure withdrawal and check-before-display accounting.');
const userMemory={task_id:'task',goal:'页面使用 Vue。',requirement_state:{records:[{slot:'framework',value:'angular'}],active:[{slot:'framework',label:'前端框架',value:'angular',text:'改用 Angular。'},{slot:'network',label:'资料范围',value:'local_only',text:'页面使用 Vue，不联网。'}],conflicts:[]},project_memory:{source_status:'current',requirements:[{text:'页面使用 Vue，不联网。'}],progress:'当前只有方案，尚未部署。',next_steps:'检查曲线'}};
const userBuilt=assembleContext('规则','宿主',{wiki:{text:'',reads:[]},templates:{text:'',reads:[]},skills:{text:'',reads:[]}},'复述当前框架和资料范围。',userMemory,null,contextConfig());
const userSources=userContextInputs('复述当前框架和资料范围。',userBuilt.messages);
assert.ok(userSources.some(i=>i.text.includes('Angular')));assert.ok(!userSources.some(i=>i.text.includes('Vue')),'An unrelated slot source sentence must not revive the old framework');
const fakeSecret='sk_test_only_12345678901234567890';assert.ok(!JSON.stringify(userContextInputs('密钥：'+fakeSecret,userBuilt.messages)).includes(fakeSecret));
assert.deepEqual(userContextInputs('旧项目框架？',[{role:'user',content:'<material kind="project_memory">\n'+JSON.stringify({source_status:'forgotten',requirements:[{text:'使用 Vue。'}]})+'\n</material>'}]).map(i=>i.text).filter(t=>t.includes('Vue')),[]);
const userRuntime={createModel(p,i,r,max){return {async invoke(messages){const input=JSON.parse(messages[1].content);return {content:max===1600?JSON.stringify({checks:input.assertions.map(a=>({id:a.id,status:'supported',reason:'符合当前用户要求',references:[{source_id:input.fragments.find(f=>f.quote.includes('Angular')).source_id}]}))}):'研究证明效率提高90%。'};}};}};
const userChecked=await checkAnswer('当前框架是 Angular。','复述当前框架和资料范围。',[],{scope:'answer_model_supplied_materials',inputs:[],omitted_paths:[]},userRuntime,'fixture','fixture',contextConfig(),{answerMessages:userBuilt.messages});
assert.equal(userChecked.answer,'当前框架是 Angular。');assert.equal(userChecked.receipt.calls,1);assert.equal(userChecked.receipt.checks[0].references[0].source_basis,'user_record');
const overRecord=await checkAnswer('Angular 已部署生产，研究证明效率提高90%。','复述当前框架和资料范围。',[],{scope:'answer_model_supplied_materials',inputs:[],omitted_paths:[]},userRuntime,'fixture','fixture',contextConfig(),{answerMessages:userBuilt.messages});
assert.ok(overRecord.receipt.checks.every(c=>c.status==='insufficient'));assert.ok(!overRecord.answer.includes('提高90%'));assert.match(overRecord.answer,/你当前确认的要求/);
console.log('User context assessment: retained current requirements, omitted/forgotten boundaries, known-slot normalization, user-record-only evidence and execution/research rejection passed.');

const audioDraft='转写已完成。\n\n产品价格是288元。\n该信息出现在语音的0-11.00秒。';
const audioTool={tool:'audio_transcribe',result:{status:'completed',text:'[0.00-11.00s] 今天讨论产品，产品价格是288元。',source:{name:'voice.wav',start:0,end:11.16}}};
const audioChecked=await checkAnswer(audioDraft,'转写语音并告诉我价格',[],{scope:'answer_model_supplied_materials',inputs:[],omitted_paths:[]},{createModel(){return {async invoke(messages){const input=JSON.parse(messages[1].content);const fragment=input.fragments.find(f=>f.quote.includes('288'));return {content:JSON.stringify({checks:input.assertions.map(a=>({id:a.id,status:'supported',reason:'实际转写与时间范围',references:[{source_id:fragment.source_id}]}))})};}};}},'fixture','fixture',contextConfig(),{toolEvidence:[audioTool]});
assert.equal(audioChecked.answer,audioDraft,'Decimal timestamps and a hyphenated range must not erase a supported audio answer');
assert.equal(audioChecked.receipt.repair_count,0);
const badAudio=await checkAnswer('已转写。\n\n产品价格是288元。\n实际价格是999元。','语音的价格是多少',[],{scope:'answer_model_supplied_materials',inputs:[],omitted_paths:[]},{createModel(){return {async invoke(messages){const input=JSON.parse(messages[1].content);const fragment=input.fragments.find(f=>f.quote.includes('288'));return {content:JSON.stringify({checks:input.assertions.map(a=>({id:a.id,status:'supported',reason:'模拟遗漏错误数字',references:[{source_id:fragment.source_id}]}))})};}};}},'fixture','fixture',contextConfig(),{toolEvidence:[audioTool]});
assert.match(badAudio.answer,/288/);assert.doesNotMatch(badAudio.answer,/undefined|\{"tool"|999/);
console.log('Media answer checking passed: signed numbers, decimal timestamp ranges and plain-text tool evidence without receipt leakage.');
const adjacentDraft='校验码是 TAIL-9281，金额是 288 元。';
const adjacent=await checkAnswer(adjacentDraft,'告诉我末尾的校验码和金额',[],{scope:'answer_model_supplied_materials',inputs:[],omitted_paths:[]},{createModel(){return {async invoke(messages){const input=JSON.parse(messages[1].content);const fragment=input.fragments.find(f=>f.quote.includes('TAIL-9281'));return {content:JSON.stringify({checks:input.assertions.map(a=>({id:a.id,status:'supported',reason:'同一段落中的编号和金额',references:[{source_id:fragment.source_id}]}))})};}};}},'fixture','fixture',contextConfig(),{toolEvidence:[{tool:'file_read',result:{status:'completed',text:'校验码：TAIL-9281。金额288元。',source:{name:'medium.txt',start:12000,end:12025}}}]});
assert.equal(adjacent.answer,adjacentDraft,'Adjacent facts from one actual paragraph must survive a narrow single-fragment reference');
assert.equal(adjacent.receipt.repair_count,0);

// Browser regression: 32 long user records, with a correction behind filler.
// The reply model had answered correctly; the checker previously lost the
// correction under its 40-fragment cap and replaced the reply with stale data.
const correctedText='预算上限改为17200元，交付日改为2026年11月9日；禁止上传到云端仍然有效，验收口令竹影-47不变。';
const longRecords=Array.from({length:32},(_,i)=>({role:'user',content:`<material kind="conversation:fixture-${i}">\n${JSON.stringify({role:'user',content:'合成会议只讨论书架整理和纸张颜色。\n编号习惯不构成项目要求。\n'+(i===22?correctedText:'继续讨论书架编号与整理方式。')})}\n</material>`}));
longRecords.push({role:'user',content:'<material kind="requirement_state">\n'+JSON.stringify({active:[{slot:'budget',label:'项目预算',value:'17200元'},{slot:'network',label:'资料范围',value:'online_available',origin:'host_policy'}],conflicts:[]})+'\n</material>'});
const longQuestion='最终预算上限、交付日期、云端上传限制和验收口令分别是什么？';
const memoryCorrectionDraft='预算上限17200元，交付日期2026年11月9日，禁止上传到云端，验收口令为竹影-47。';
const longSources=userContextInputs(longQuestion,longRecords);
assert.ok(!longSources.some(i=>i.text.includes('online_available')));
const selectedLong=assessmentFragments({inputs:longSources},longQuestion+'\n'+memoryCorrectionDraft);
assert.ok(selectedLong.some(f=>f.quote.includes('17200元')&&f.quote.includes('竹影-47')));
assert.equal(selectedLong.find(f=>f.quote.includes('竹影-47')).user_record_order,23);
const longChecked=await checkAnswer(memoryCorrectionDraft,longQuestion,[],{scope:'answer_model_supplied_materials',inputs:[],omitted_paths:[]},{createModel(){return {async invoke(messages){const input=JSON.parse(messages[1].content);const source=input.fragments.find(f=>f.quote.includes('17200元')&&f.quote.includes('竹影-47'));assert.ok(source,'All constraints must reach the actual checker input');assert.match(source.source_id,/^u\d+$/);assert.equal(source.provided_sha256,undefined);assert.equal(source.path,undefined);assert.equal(typeof source.user_record_order,'number');assert(input.fragments.some(f=>f.quote.includes('书架')),'Compaction must not silently discard supplied records');return {content:JSON.stringify({checks:input.assertions.map(a=>({id:a.id,status:'supported',reason:'后续用户原文明确纠正',references:[{source_id:source.source_id}]}))})};}};}},'fixture','fixture',contextConfig(),{answerMessages:longRecords});
assert.equal(longChecked.answer,memoryCorrectionDraft);
assert.equal(longChecked.receipt.repair_count,0);
console.log('Long conversation checking preserves decisive correction fragments and excludes host policy from user requirements.');

assert.equal(longChecked.receipt.user_record_check.mode,'compact_exact_sources');
assert.equal(longChecked.receipt.user_record_check.deadline_ms,90000);
assert(longChecked.receipt.checks.every(c=>c.references.every(r=>r.path.startsWith('user-context:'))));
