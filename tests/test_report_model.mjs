/** Controlled generation validates routing, secret isolation and no fallback. */
import assert from 'node:assert/strict';
import {mkdtemp,writeFile,chmod,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {runIntakeTurn} from '../federation/intake-turn.mjs';
import {reportRuntime} from '../federation/report-model.mjs';

const root=await mkdtemp(path.join(tmpdir(),'report-route-'));
const file=path.join(root,'report-model.json');
const key='REPORT_SECRET_FIXTURE';
const config={provider:'openai-compatible',model:'fixture-strong-model',base_url:'http://127.0.0.1:9901/v1',api_key:key,responses_api:false};
const evidence={wiki:{text:'local methods',reads:[]},templates:{text:'',reads:[]},skills:{text:'',reads:[]}};
const research={sources:[{url:'https://product.example.test',excerpt:'Product catalog shows downloadable applications.',title:'Catalog',sha256:'a'.repeat(64)}]};
const originals={};
for(const name of ['FEDERATION_REPORT_MODEL_CONFIG','OPENAI_COMPATIBLE_API_KEY','OPENAI_COMPATIBLE_BASE_URL','OPENWIKI_REASONING_EFFORT'])originals[name]=process.env[name];
const calls=[];
let promptText='', fail=false;
const runtime={
  async loadOpenWikiEnv(){},resolveConfiguredProvider(){return 'openai-compatible';},
  resolveModelId(){return 'fixture-local-model';},resolveProviderRetryAttempts(){return 0;},
  createModel(provider,model,retries,maxTokens){
    const report=model==='fixture-strong-model';
    calls.push({provider,model,key:process.env.OPENAI_COMPATIBLE_API_KEY,url:process.env.OPENAI_COMPATIBLE_BASE_URL,effort:process.env.OPENWIKI_REASONING_EFFORT});
    if(report) {assert.equal(process.env.OPENAI_COMPATIBLE_API_KEY,key);assert.equal(process.env.OPENAI_COMPATIBLE_BASE_URL,config.base_url);assert.equal(process.env.OPENWIKI_REASONING_EFFORT,undefined);}
    return {async invoke(messages){
      promptText+=JSON.stringify(messages);
      if(fail)throw new Error('provider failed with '+key);
      if(report && maxTokens===1800){const input=JSON.parse(messages[1].content);return {content:JSON.stringify({checks:input.assertions.map(a=>({id:a.id,status:'insufficient',reason:'测试材料不支持这条报告表述',references:[]}))})};}
      if(report && maxTokens===2400)return {content:JSON.stringify([{url:research.sources[0].url,quote:'downloadable applications',fact:'downloadable applications'}])};
      return {content:report?'This is a controlled fixture report. Source: https://product.example.test':'Local chat fixture answer.'};
    }};
  }
};
try {
  await writeFile(file,JSON.stringify(config),{mode:0o600});
  process.env.FEDERATION_REPORT_MODEL_CONFIG=file;
  process.env.OPENAI_COMPATIBLE_API_KEY='LOCAL_KEY_FIXTURE';
  process.env.OPENAI_COMPATIBLE_BASE_URL='http://127.0.0.1:11436/v1';
  process.env.OPENWIKI_REASONING_EFFORT='none';
  const result=await runIntakeTurn('analyze product','consultation',evidence,runtime,{analysis:true,researchContext:research,currentQuestion:'analyze product'});
  assert.equal(result.model,config.model);
  assert.equal(calls.length,6);
  assert.ok(calls.every(call=>call.model===config.model));
  assert.equal(result.analysis_run.model_route.fallback,'disabled');
  assert.ok(!JSON.stringify(result).includes(key));
  assert.ok(!promptText.includes(key));
  assert.equal(process.env.OPENAI_COMPATIBLE_API_KEY,'LOCAL_KEY_FIXTURE');
  assert.equal(process.env.OPENWIKI_REASONING_EFFORT,'none');
  // Ordinary conversation ignores even a broken report file and retains Qwen route.
  process.env.FEDERATION_REPORT_MODEL_CONFIG=path.join(root,'nonexistent.json');
  const local=await runIntakeTurn('hello','consultation',evidence,runtime);
  assert.equal(local.model,'fixture-local-model');
  assert.equal(calls.at(-1).key,'LOCAL_KEY_FIXTURE');
  const previous=calls.length;
  await assert.rejects(runIntakeTurn('analyze','consultation',evidence,runtime,{analysis:true,researchContext:research}));
  assert.equal(calls.length,previous,'Invalid report credentials must not fall back to local generation');
  process.env.FEDERATION_REPORT_MODEL_CONFIG=file;
  fail=true;
  await assert.rejects(runIntakeTurn('analyze','consultation',evidence,runtime,{analysis:true,researchContext:research}),error=>!error.message.includes(key)&&error.message.includes('[REDACTED]'));
  fail=false;
  await chmod(file,0o644);
  await assert.rejects(reportRuntime(runtime,file),/600/);
  await chmod(file,0o600);
  await writeFile(file,'{"api_key":"'+key+'", broken');
  await assert.rejects(reportRuntime(runtime,file),error=>!error.message.includes(key));
  console.log('Report model routing: independent report model, ordinary chat unchanged, invalid config fails closed, secrets redacted.');
} finally {
  for(const [name,value] of Object.entries(originals)){if(value===undefined)delete process.env[name];else process.env[name]=value;}
  await rm(root,{recursive:true,force:true});
}
