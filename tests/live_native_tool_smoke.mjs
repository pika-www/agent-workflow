/** Opt-in real local provider check. Uses only synthetic arithmetic and temp data. */
import {writeFileSync} from 'node:fs';
import assert from 'node:assert/strict';
import {nativeAgentRuntime,runNativeAgent} from '../federation/native-agent.mjs';
import {hostTool} from '../federation/tool-loop.mjs';
if(process.env.WEIMING_LIVE_SMOKE!=='1')throw Error('Explicit live smoke environment required');
const started=performance.now();
const result=await runNativeAgent(nativeAgentRuntime({provider:'openai-compatible',model:'qwen3.5:9b',base_url:'http://127.0.0.1:11436/v1'}),
 [{role:'system',content:'这是合成算术测试。必须调用 profit_calculate 后，根据实际回执简短回答利润，不执行其他操作。'},
  {role:'user',content:'单价25元、单位成本10元、固定成本500元、销量100件、折扣1，请调用工具核算利润。'}],hostTool,
 {tools:['profit_calculate'],maxActions:2,maxOutputTokens:384,maxReconnects:0,signal:AbortSignal.timeout(180000)});
assert.ok(result.workflow.receipts.some(r=>r.tool==='profit_calculate'&&r.status==='completed'));
assert.equal(result.workflow.observations.find(o=>o.tool==='profit_calculate'&&o.result.status==='completed').result.profit,'1000');
const receipt={evidence_class:'real-local-model-and-real-host-tool-isolated-input',model:'qwen3.5:9b',seconds:(performance.now()-started)/1000,
 answer:result.answer,metrics:result.workflow.tool_metrics,receipts:result.workflow.receipts};
writeFileSync(process.env.WEIMING_SMOKE_OUTPUT,JSON.stringify(receipt,null,2));
console.log(JSON.stringify({status:'passed',seconds:receipt.seconds,metrics:receipt.metrics}));
