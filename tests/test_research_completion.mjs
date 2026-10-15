import assert from 'node:assert/strict';
import {defaultOnlineLookup,publicResearchScope,publicSearchQuery,hasProductBody} from '../federation/default-online.mjs';
import {publicSearchLookup} from '../federation/tool-autonomy.mjs';
import {checkAnswer,assessmentFragments,riskyAssertions} from '../federation/answer-check.mjs';
import {publicToolInputs,hasAnswerBody} from '../federation/public-evidence.mjs';
import {contextConfig} from '../federation/context-budget.mjs';
const policy={default_online:true,network_allowed:true,services:{search:{enabled:true},browser:{configured:true}}};
const question='帮我找招聘平台／软件的信息，比较功能、区别和适用人群。';
const lookup=defaultOnlineLookup(question,policy),allowed=['web_search','web_read','visual_browser'];
assert.equal(lookup.coverageTarget,3);
assert.equal(publicSearchLookup('请联网搜索招聘平台的功能、区别和适用人群',{network_allowed:true}).coverageTarget,3);
assert.equal(publicResearchScope('只查一家招聘平台').target,1);
assert.equal(publicResearchScope('只用 web_search 比较招聘平台').onlyTool,'web_search');
assert.equal(publicResearchScope('Playwright getByRole 用法').target,1);
assert.match(publicSearchQuery('关于今天行业招聘有没有什么信息？',new Date('2026-10-08T18:00:00Z')),/2026-10-09/);
const state={receipts:[],observations:[],allowed};
const add=(tool,args,result)=>{state.receipts.push({tool,args});state.observations.push({tool,result});};
const sources=['https://jobs.example.com/','https://jobs.example.com/jobs','https://b.example.org/','https://c.example.net/'];
add('web_search',{query:'招聘平台'},{status:'completed',sources:sources.map(url=>({url,title:'招聘资料',excerpt:'搜索摘要',read_method:'search_result_snippet'}))});
for(const url of [sources[0],sources[2],sources[3]]){
 assert.equal(lookup.next(state).args.url,url);
 add('web_read',{url},{status:'completed',sources:[{url,title:'招聘平台',excerpt:'平台提供职位搜索和简历投递功能。',read_method:'http_text'}]});
}
assert.equal(lookup.next(state),null,'Three independent domains complete minimum coverage; same-site pages do not count twice');
const blocked={receipts:state.receipts.slice(0,1),observations:state.observations.slice(0,1),allowed};
blocked.receipts.push({tool:'web_read',args:{url:sources[0]}});
blocked.observations.push({tool:'web_read',result:{status:'unavailable',errors:[{error:'robots.txt 不允许自动采集'}]}});
assert.notEqual(lookup.next(blocked).tool,'visual_browser','Explicit denial cannot be bypassed');
const exhausted={receipts:[{tool:'web_search',args:{query:'q'}}],observations:[{tool:'web_search',result:{sources:[]}}],allowed};
assert.equal(lookup.next(exhausted).tool,'web_search');
exhausted.receipts.push({tool:'web_search',args:{query:'q 官方 功能 介绍'}});exhausted.observations.push({tool:'web_search',result:{sources:[]}});
assert.equal(lookup.next(exhausted),null,'Do not loop searches indefinitely');
const empty={scope:'answer_model_supplied_materials',inputs:[],omitted_paths:[]};
const draft='目前资料里能确认的招聘方向，主要集中在 AI/算法：图像算法、自然语言处理、大模型算法、机器学习、深度学习、AIGC 应用工程师、AI 训练师，以及推荐、搜索、风控、SLAM 等岗位。\n\n但页面没有提供“今日新增数量”、具体企业、薪资或发布时间，因此不能据此判断今天哪些岗位最热门。\n\n来源：https://www.jrzp.com/';
const actual=[{tool:'web_read',result:{status:'completed',sources:[{url:'https://www.jrzp.com/',title:'招聘求职找工作',read_method:'http_text',excerpt:'图像算法、自然语言处理、大模型算法、AIGC 应用工程师、AI 训练师。'}]}}];
const incomplete={createModel(){return {async invoke(){return {content:'{"checks":[{"id":"assertion-1","'};}};}};
const failed=await checkAnswer(draft,'那关于今天行业招聘有没有什么信息？',[],empty,incomplete,'fixture','fixture',contextConfig(),{toolEvidence:actual});
assert.equal(failed.receipt.failure,'invalid_or_failed_assessment');
assert.ok(failed.receipt.content_fallback==='actual_public_source_excerpts'||failed.receipt.repair_status==='preserved_with_uncertainty');
assert.equal(failed.receipt.semantic_correctness,'not_evaluated');
assert.ok(hasAnswerBody(failed.answer));assert.match(failed.answer,/自动核对没有完成|尚待核实/);assert.match(failed.answer,/图像算法/);
assert.doesNotMatch(failed.answer,/已核实|已验证/,'Do not present an incomplete check as verified');
const noModel={createModel(){throw new Error('A bare link has no factual assertion to assess');}};
const bare=await checkAnswer('来源：https://www.jrzp.com/','介绍招聘平台',[],empty,noModel,'fixture','fixture',contextConfig(),{toolEvidence:actual});
assert.match(bare.answer,/图像算法/);assert.ok(hasAnswerBody(bare.answer));
const links=await checkAnswer('来源：https://www.jrzp.com/','只要网址',[],empty,noModel,'fixture','fixture',contextConfig(),{toolEvidence:actual});
assert.equal(links.answer,'来源：https://www.jrzp.com/');
const snippets=publicToolInputs([state.observations[0]]);
assert.ok(snippets.every(s=>s.search_snippet));
assert.match(snippets[0].text,/未读取网页正文/);
const inputs=publicToolInputs(state.observations);
assert.equal(inputs[0].search_snippet,false);
assert.ok(inputs.every(i=>!i.text.includes('"sources":')));
const fragments=assessmentFragments({inputs:[{...inputs[0],text:'很长的一页内容。\n'.repeat(100)},...inputs.slice(1)]});
assert.ok(fragments.some(f=>f.path===inputs[2].path),'Long first page must not starve later source evidence');
console.log('Research completion: archived link-only failure, partial assessment, honest source fallback, user link-only preference, multi-domain reads, explicit search, timezone and bounded exhaustion passed.');

const comparison='| 平台/软件 | 主要功能与区别 | 更适合谁 |\n|---|---|---|\n| BOSS直聘 | 直接沟通，反馈通常更即时 | 中小企业 |';
assert.equal(riskyAssertions(comparison,{question}).assertions.length,1,'Concrete product claims in comparison tables need evidence; headings and separators do not');

assert.match(publicSearchQuery('今日招聘这个平台有什么功能？'),/今日招聘/,'Preserve an explicitly named platform instead of rewriting its brand as a date');

assert.equal(publicSearchQuery(question+'请简要整理，不超过400字。'),publicSearchQuery(question),'Answer-format constraints must not distort the public search topic');

const precise=await checkAnswer('研究证明招聘效率提高900%。\n\n来源：https://www.jrzp.com/','比较招聘平台',[],empty,incomplete,'fixture','fixture',contextConfig(),{toolEvidence:actual});
assert.doesNotMatch(precise.answer,/提高900%/,'A real source URL cannot protect unassessed numeric/research claims from withdrawal');
assert.ok(hasAnswerBody(precise.answer));

const lost=await checkAnswer(comparison+'\n\n建议先试用再选择。\n\n来源：https://www.jrzp.com/',question,[],empty,incomplete,'fixture','fixture',contextConfig(),{toolEvidence:actual});
assert.equal(lost.receipt.content_fallback,'actual_public_source_excerpts','A comparison stripped to general advice still needs its actual evidence');
assert.doesNotMatch(lost.answer,/反馈通常更即时/);

assert.equal(hasProductBody({read_method:'http_text',excerpt:'[招聘岗位](https://site.example/jobs)'.repeat(20)}),false);
assert.equal(hasProductBody({read_method:'http_text',excerpt:'平台提供简历解析与面试管理功能。'}),true);
const mixedRows='| 平台 | 功能 | 人群 |\n|---|---|---|\n| A平台 | 提供职位搜索和简历投递功能 | 求职者 |\n| B平台 | 保证马上入职 | 所有人 |';
const confirmed=[{tool:'web_read',result:{status:'completed',sources:[{url:'https://example.org/a',title:'A平台',read_method:'http_text',excerpt:'A平台提供职位搜索和简历投递功能，面向求职者。'}]}}];
const partial=await checkAnswer(mixedRows,question,[],empty,{createModel(){return {async invoke(messages){const data=JSON.parse(messages[1].content);return {content:JSON.stringify({checks:data.assertions.map((a,i)=>({id:a.id,status:i===0?'supported':'insufficient',reason:'逐项依据',references:i===0?[{source_id:data.fragments.find(f=>f.quote.includes('A平台提供')).source_id}]:[]}))})};}};}},'fixture','fixture',contextConfig(),{toolEvidence:confirmed});
assert.match(partial.answer,/A平台[\s|]*提供职位搜索/,'Supported product information survives as bounded prose or an actual source excerpt');
assert.doesNotMatch(partial.answer,/保证马上入职/);
assert.match(partial.answer,/https:\/\/example.org\/a/,'Retained supported rows receive their actual source citation');
const qualifiedTable='| 平台/软件 | 功能 | 适用人群建议 |\n|---|---|---|\n| A平台 | 第三方资料称有职位检索，官网未核实 | 建议求职者关注 |\n| B平台 | 会员专属预约通道 | 所有人 |\n| C平台 | 第三方资料称有职位分类，官网未核实 | 建议求职者关注 |';
const keptTable=await checkAnswer(qualifiedTable,question,[],empty,incomplete,'fixture','fixture',contextConfig(),{toolEvidence:actual});
assert.match(keptTable.answer,/\| 平台\/软件[^\n]+\n\|---\|---\|---\|\n\| A平台/,'Withdrawing one row must retain the table header and separator');
assert.match(keptTable.answer,/\| A平台[^\n]+\n\| C平台/,'Surviving qualified rows stay in one table');
assert.doesNotMatch(keptTable.answer,/会员专属预约通道/);
