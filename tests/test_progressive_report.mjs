import assert from 'node:assert/strict';
import {runProductAnalysis} from '../federation/product-analysis-turn.mjs';
const source={url:'https://example.com/app',title:'公开产品页',sha256:'a'.repeat(64),excerpt:'应用目录有节点编辑器。'};
const ledger=JSON.stringify([{url:source.url,quote:'应用目录有节点编辑器',fact:'应用目录有节点编辑器'}]);
const outputs=['先从网页能看到的应用目录说起。内部实现还需查证。',ledger,
  '# 示例分析\n\n## 用户任务\n目录提供节点编辑器。',
  '## 实现参考\n公开页面不能确认内部框架。',
  '## 运营假设\n成本数据尚待核实。',
  '# 示例完整报告\n\n内部实现和成本数据尚待核实。[来源](https://example.com/app)'];
let calls=0,finalText='',updates=[],progress=[];
class Chunk { constructor(content){this.content=content;} concat(other){return new Chunk(this.content+other.content);} }
const runtime={createModel(){return {
  async invoke(){return new Chunk(outputs[calls++]);},
  async *stream(){const text=outputs[calls++];yield new Chunk(text.slice(0,8));yield new Chunk(text.slice(8));}
};}};
const result=await runProductAnalysis(runtime,'fixture','fixture-model',0,'分析公开产品页，生成下载报告',
  {sources:[source],status:'completed',errors:[]},{
    onUpdate(event){
      if(!updates.length){assert.equal(calls,0,'Actual source excerpt precedes every model call');assert.equal(event.id,'first-source');assert.ok(event.text.includes(source.excerpt));assert.equal(finalText,'');}
      if(event.id==='first-answer')assert.equal(calls,1,'Initial model answer precedes the ledger and all report passes');
      updates.push(event);
    },onDelta(text){finalText+=text;},onProgress(event){progress.push(event);}
  });
assert.equal(calls,6);
assert.deepEqual([...new Set(updates.map(item=>item.id))],['first-source','first-answer','section-1','section-2','section-3']);
for(const id of ['first-answer','section-1','section-2','section-3']){
  const parts=updates.filter(item=>item.id===id);
  assert.equal(parts.at(-1).status,'completed');
  assert.equal(parts.slice(0,-1).every(item=>item.status==='streaming'),true);
  assert.ok(parts.map(item=>item.text).join('').length>10);
}
assert.equal(finalText,result.answer,'Final text is the separate reviewed model response');
assert.equal(result.analysis_run.stages[0].stage,'initial_reply');
assert.equal(result.analysis_run.quality.independently_verified,false);
assert.ok(result.timing.first_text_ms<=result.timing.model_ms);
assert.ok(result.timing.intake_first_reply_ms<=result.timing.first_text_ms);
assert.equal(progress.at(-1).stage,'exporting_report');
console.log('Progressive reports: actual initial model reply before expensive passes, three streaming drafts, distinct final review and model provenance passed.');
