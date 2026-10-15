import assert from 'node:assert/strict';
import {runProductAnalysis} from '../federation/product-analysis-turn.mjs';
const source={url:'https://example.com/app',title:'公开页',sha256:'a'.repeat(64),excerpt:'公开应用目录提供节点编辑器。'};
let saved,calls=[],fail=true;
const runtime={createModel(p,id,retries,max){return {async invoke(messages){const system=messages[0].content;
 if(max===1800){calls.push('check');const data=JSON.parse(messages[1].content);return {content:JSON.stringify({checks:data.assertions.map(a=>({id:a.id,status:'supported',reason:'逐字原文',references:[{source_id:data.fragments[0].source_id}]}))})};}
 if(max===2400){calls.push('ledger');return {content:JSON.stringify([{url:source.url,quote:source.excerpt,fact:source.excerpt}])};}
 if(max===11000){calls.push('review');return {content:'# 示例报告\n\n页面提供节点编辑器。\n\n建议测试一段用户任务。'};}
 if(max===600){calls.push('initial');return {content:'根据已读页面，先看节点编辑器对应的用户任务。'};}
 const part=system.includes('只写参考实现')?'part2':system.includes('写约1500')?'part3':'part1';calls.push(part);
 if(part==='part2' && fail)throw new Error('临时断线');return {content:part==='part1'?'# 示例报告\n\n页面提供节点编辑器。':'## 设计建议\n\n建议测试一段用户任务。'};
}};}};
const options={onUpdate(){},onCheckpoint(value){saved=structuredClone(value);}};
await assert.rejects(runProductAnalysis(runtime,'fixture','fixture',0,'分析产品',{sources:[source]},options),/临时断线/);
assert.equal(saved.sections.length,1);fail=false;calls=[];
const resumed=await runProductAnalysis(runtime,'fixture','fixture',0,'分析产品',{sources:[source]},{...options,resumeCheckpoint:saved});
assert.equal(resumed.analysis_run.resumed,true);assert.deepEqual(calls,['part2','part3','review','check']);assert.ok(resumed.answer.includes('上次保存的原文'));assert.equal(resumed.analysis_run.coverage[0].reused,true);
const complete=saved;calls=[];await runProductAnalysis(runtime,'fixture','fixture',0,'分析产品',{sources:[source]},{...options,resumeCheckpoint:complete});assert.deepEqual(calls,['check'],'Completed prose is reused but final evidence is checked again');
calls=[];const changed=await runProductAnalysis(runtime,'fixture','fixture',0,'分析产品',{sources:[{...source,sha256:'b'.repeat(64)}]},{...options,resumeCheckpoint:complete});assert.equal(changed.analysis_run.resumed,false);assert.ok(calls.includes('ledger'));assert.ok(calls.includes('part1'));
console.log('Report continuation: completed sections and self-review survive interruption, recheck always runs, source change invalidates reuse.');
