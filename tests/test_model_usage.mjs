import assert from 'node:assert/strict';
import {mkdtempSync,readFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {trackModel,startModelUsage} from '../federation/model-usage.mjs';
const root=mkdtempSync(join(tmpdir(),'model-usage-test-')),file=join(root,'receipts.jsonl');
try {
 const secret='sk_fake_test_1234567890123456789';
 const model={async invoke(){return {content:secret,usage_metadata:{input_tokens:10,output_tokens:5}};},async stream(){return (async function*(){yield {content:secret,usage_metadata:{input_tokens:10,output_tokens:0}};yield {content:'ok',usage_metadata:{input_tokens:0,output_tokens:5}};})();}};
 const tracked=trackModel(model,'test','test-model',file);await tracked.invoke(secret);for await(const chunk of await tracked.stream(secret)){}
 await assert.rejects(trackModel({async invoke(){throw Error(secret);}},'test','test-model',file).invoke(secret));
 const broken=trackModel({async stream(){return (async function*(){yield {content:'ok',usage_metadata:{input_tokens:20,output_tokens:1}};throw Error(secret);})();}},'test','test-model',file);
 await assert.rejects(async()=>{for await(const chunk of await broken.stream(secret)){};});
 const raw=readFileSync(file,'utf8');assert.ok(!raw.includes(secret));const unique=[...new Map(raw.trim().split('\n').map(line=>JSON.parse(line)).map(row=>[row.id,row])).values()];
 assert.equal(unique.length,4);assert.deepEqual(unique.map(r=>r.status),['completed','completed','failed','interrupted']);assert.equal(unique[1].input_tokens,10);assert.equal(unique[1].output_tokens,5);assert.equal(unique[2].input_tokens,null);assert.equal(unique[3].input_tokens,20);
 assert.equal(trackModel(tracked,'test','test-model',file),tracked);
 const native=startModelUsage('openai-compatible','native-test',file);
 native.finish('completed',{input_tokens:42,output_tokens:7,cached_tokens:10,secret});
 const receipts=[...new Map(readFileSync(file,'utf8').trim().split('\n').map(line=>JSON.parse(line)).map(row=>[row.id,row])).values()];
 assert.equal(receipts.length,5);assert.equal(receipts.at(-1).input_tokens,42);assert.equal(receipts.at(-1).output_tokens,7);
 assert.equal(receipts.at(-1).calls,1);assert.ok(!readFileSync(file,'utf8').includes(secret));
 console.log('Model receipts: invocation, chunk aggregation, failure, interruption, dedup and no prompt/output persistence passed.');
}finally{rmSync(root,{recursive:true,force:true});}
