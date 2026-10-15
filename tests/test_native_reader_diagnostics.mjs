import assert from 'node:assert/strict';
import {nativeAgentRuntime,runNativeAgent} from '../federation/native-agent.mjs';
const final={id:'final',type:'message',role:'assistant',phase:'final_answer',content:[{type:'output_text',text:'规则检查暂时失败，正文尚未读取。'}]};
const client={responses:{async create(){return (async function*(){yield {type:'response.output_item.added',item:{...final,content:[]}};yield {type:'response.output_text.delta',item_id:'final',delta:final.content[0].text};yield {type:'response.output_item.done',item:final};yield {type:'response.completed',response:{output:[final]}};})();}}};
const runtime=nativeAgentRuntime({provider:'openai-compatible',model:'fixture',responses_api:true},{client});
for(const supported of [false,true]){
 const events=[];
 const result=await runNativeAgent(runtime,[{role:'user',content:'读取这个网页'}],async()=>({status:'unavailable',errors:[{code:'robots_check_failed',stage:'robots',http_status:500,attempts:3,error:'规则检查失败'}]}),{
  tools:['web_read'],publicReadAhead:true,maxActions:1,maxTurns:3,toolPolicy:{public_read_diagnostics:supported},
  nextRequiredTool:s=>s.receipts.length?null:{tool:'web_read',args:{url:'https://reader.example/article'},instruction:'读取公开文章'},
  onAgentEvent:e=>events.push(e)
 });
 assert.equal(result.workflow.receipts[0].failure_code,'robots_check_failed');
 assert.match(result.workflow.receipts[0].failure_detail,/HTTP 500，已尝试 3 次/);
 const finished=events.find(e=>e.type==='agent.tool.completed');assert.equal(finished.status,'robots_check_failed');
 assert.equal('failure_detail' in finished,supported,'An older running server must not receive unknown event fields');
 if(supported)assert.match(finished.failure_detail,/尚未请求文章正文/);
}
console.log('Native reader diagnostics passed: actual host receipt, live error detail and old-server event compatibility.');
