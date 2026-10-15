/** Actual topic retrieval through the same native prefetch used by consultation. */
import fs from 'node:fs/promises';
import path from 'node:path';
import { prefetchWiki } from '../federation/agent-turn.mjs';
import { parseKnowledgeEvidence } from '../federation/wiki-evidence.mjs';
const [wiki,metadata,fixture,output]=process.argv.slice(2);
if(!output)throw new Error('需要 Wiki、追溯快照、题集和输出文件四个路径');
const bank=JSON.parse(await fs.readFile(fixture,'utf8'));
const provenance=parseKnowledgeEvidence(JSON.parse(await fs.readFile(metadata,'utf8')),bank.space);
const cases=[];
for(const item of bank.cases){
  const evidence=await prefetchWiki(wiki,item.question,provenance,{compact:true});
  const paths=evidence.reads.map(read=>read.path);
  cases.push({id:item.id,question:item.question,expected_page:item.page||null,paths,
    retrieval:evidence.retrieval,claims:evidence.reads.flatMap(read=>read.claims||[]),
    passed:item.expect_missing?evidence.retrieval.missing_evidence:paths.includes(item.page)});
}
const report={evidence_class:'actual_topic_native_retrieval_no_model',space:bank.space,
  total:cases.length,passed:cases.filter(c=>c.passed).length,cases,
  semantic_correctness:'not_evaluated',notes:'命中页面和缺证据判断，不代表回答内容正确。'};
await fs.writeFile(output,JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify({total:report.total,passed:report.passed,failed:cases.filter(c=>!c.passed).map(c=>c.id)}));
