import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {checkedFacts,runProductAnalysis} from '../federation/product-analysis-turn.mjs';
import {replyLanguagePolicy} from '../federation/reply-language.mjs';
const source={url:'https://example.com/app',title:'产品公开页',sha256:'a'.repeat(64),excerpt:'应用目录有节点编辑器。GPU 资源可按时使用。'};
const ledger=JSON.stringify([
  {url:source.url,quote:'应用目录有节点编辑器',fact:'目录描述节点编辑器'},
  {url:source.url,quote:'虚构引文',fact:'不应接受'},
  {url:'https://unread.example/',quote:'GPU 资源可按时使用',fact:'未读取页面不应接受'}
]);
assert.equal(checkedFacts(ledger,[source]).facts.length,1);
assert.equal(checkedFacts(ledger,[source]).rejected,2);
assert.equal(checkedFacts(JSON.stringify([{url:source.url,quote:'应用目录有节点编辑器',fact:'已经证明用户可免费运行全部模型'}]),[source]).facts[0].fact,'应用目录有节点编辑器','A quote match must not certify an unrelated model interpretation');
assert.equal(checkedFacts('bad json',[source]).facts.length,0);
let invocation=0,events=[],streamed='',requests=[];
const outputs=[ledger,'# 示例产品分析报告\n\n## 用户与交互\n页面提供节点编辑器。[来源](https://example.com/app)',
 '## 技术实现\n这里是参考实现，页面不足以确认内部框架。',
 '## 市场与盈利\n成本示例是计算假设。当前知识库优先服务聊天学习。',
 '# 示例产品分析报告\n\n## 用户与交互\n页面提供节点编辑器。[来源](https://example.com/app)\n\n## 技术实现\n这里是参考实现，页面不足以确认内部框架。\n\n## 市场与盈利\n成本示例是计算假设。当前知识库优先服务聊天学习。'];
const runtime={createModel(p,id,retries,max){return {async invoke(messages){requests.push(messages);invocation++;
 if(max===1800){const input=JSON.parse(messages[1].content);return {content:JSON.stringify({checks:input.assertions.map(a=>({id:a.id,status:'supported',reason:'原文提及节点编辑器',references:[{source_id:input.fragments[0].source_id}]}))})};}
 return {content:outputs[invocation-1]};}};}};
const result=await runProductAnalysis(runtime,'local','fixture-model',0,'只分析并生成文档',{sources:[source],status:'completed',note:'只读公开页',errors:[]},
 {referenceContext:{wiki:'本地经验：先确认用户任务再讨论技术。',templates:'方案模板',skills:'参考规范'},onProgress:event=>events.push(event),onDelta:text=>{streamed+=text;}});
assert.equal(invocation,6,'Source ledger, three drafts, self-review and auxiliary check are separate calls');
assert.equal(streamed,result.answer,'Final answer must match actual model stream without a host-authored replacement');
assert.equal(result.response_origin,'local_product_analysis_model');
assert.equal(result.analysis_run.stages.length,6);
assert.equal(result.analysis_run.source_facts.length,1);
assert.equal(result.analysis_run.quality.unsupported_urls.length,0);
assert.equal(result.analysis_run.quality.status,'draft');
assert.equal(result.analysis_run.quality.program_checks,'passed');
assert.equal(result.analysis_run.quality.independently_verified,false);
assert.equal(result.analysis_run.answer_sha256,createHash('sha256').update(result.answer).digest('hex'));
assert.equal(events.at(-1).stage,'exporting_report');
for(const request of requests){assert.ok(request[1].content.includes(source.url));assert.ok(!request[1].content.includes('host_product_analysis_supplement'));}
assert.ok(requests[3][0].content.includes('聊天学习'));
for(const request of requests.slice(1,5))assert.ok(request[0].content.includes(replyLanguagePolicy),'Drafts and report review retain the same reply language policy');
assert.ok(requests[3][1].content.includes('先确认用户任务再讨论技术'));
assert.equal(requests[3].at(-1).role,'user');
assert.ok(requests[3].at(-1).content.includes('只分析并生成文档'));
assert.equal(result.analysis_run.stages.at(-1).stage,'report_assertion_check');
await assert.rejects(runProductAnalysis(runtime,'local','fixture-model',0,'分析',{sources:[]}),/未取得产品网页正文/);
console.log('Product analysis model provenance and source-quote checks passed');

// The user-facing delivery gate suppresses section drafts and skips the extra
// initial-answer model call, while retaining report review and assertion checks.
const {checkedReply}=await import('../federation/checked-reply.mjs');
invocation=0;requests=[];
const published=[];
const delivery=checkedReply({analysis:true,onUpdate(){throw new Error('Report draft exposed');},onDelta:text=>published.push(text)});
const deferred=await runProductAnalysis(runtime,'local','fixture-model',0,'只分析并生成文档',{sources:[source],status:'completed',errors:[]},delivery.options);
assert.equal(invocation,6,'No seventh call for an initial answer that is not displayed');
assert.deepEqual(published,[],'All sections and self-review stay private until assertion checking finishes');
await delivery.publish(deferred);
assert.deepEqual(published,[deferred.answer]);
