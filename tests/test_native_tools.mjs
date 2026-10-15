import assert from 'node:assert/strict';
import {nativeTools,consultationTools,validateNativeCall,runNativeAgent,nativeAgentRuntime} from '../federation/native-agent.mjs';
import {artifactLinks} from '../federation/artifact-links.mjs';
const names=['file_search','code_interpreter','image_analyze','image_generate','connector_search','connector_read'];
assert.equal(nativeTools(names).length,6);
assert.ok(consultationTools({executeTool(){},toolPolicy:{tools_enabled:true,network_allowed:false}}).includes('code_interpreter'));
assert.ok(!consultationTools({executeTool(){},toolPolicy:{tools_enabled:true,network_allowed:false}}).includes('image_generate'));
const artifact={id:'a'.repeat(32),room_id:'b'.repeat(32),sha256:'c'.repeat(64),name:'chart.png',url:`/api/chat/rooms/${'b'.repeat(32)}/files/${'a'.repeat(32)}`};
assert.equal(artifactLinks('[图](sandbox:/mnt/data/chart.png)',[artifact]),`[图](${artifact.url})`);
assert.equal(artifactLinks('[虚假下载](sandbox:/mnt/data/missing.png)',[artifact]),'虚假下载');
assert.equal(artifactLinks('[外部资料](https://example.com/chart.png)',[artifact]),'[外部资料](https://example.com/chart.png)');
assert.throws(()=>validateNativeCall({type:'function_call',name:'code_interpreter',call_id:'id',arguments:JSON.stringify({code:'print(38)',file_ids:'not-a-file'})},names),/附件ID无效/);
let turn=0,executions=0;const requests=[];
const call=(id,file_ids)=>({id:'fc-'+id,type:'function_call',call_id:id,name:'code_interpreter',arguments:JSON.stringify({code:'print(38)',file_ids}),status:'completed'});
const final={id:'final',type:'message',role:'assistant',phase:'final_answer',content:[{type:'output_text',text:'平方和38。下载：[chart.png](sandbox:/mnt/data/chart.png)'}]};
const client={responses:{async create(params){requests.push(structuredClone(params));const output=++turn===1?[call('invalid','none')]:turn===2?[call('valid','')]:[final];return (async function*(){
 for(const item of output){yield {type:'response.output_item.added',item:{...item,content:[]}};if(item.type==='message')yield {type:'response.output_text.delta',item_id:item.id,delta:item.content[0].text};yield {type:'response.output_item.done',item};}
 yield {type:'response.completed',response:{id:'r'+turn,output,usage:{input_tokens:100,output_tokens:30}}};
})();}}};
const r=await runNativeAgent(nativeAgentRuntime({provider:'openai-compatible',model:'fixture',responses_api:true},{client}),[{role:'user',content:'算平方和'}],async()=>{executions++;return {status:'completed',stdout:'38',artifacts:[artifact]};},{tools:['code_interpreter'],maxActions:2});
assert.equal(executions,1,'Invalid parameters never reach execution');
assert.equal(r.workflow.receipts.length,2);assert.equal(r.workflow.receipts[0].status,'failed');assert.equal(r.workflow.receipts[1].status,'completed');
assert.equal(requests[1].input.find(i=>i.type==='function_call_output').call_id,'invalid');
assert.equal(JSON.parse(requests[1].input.find(i=>i.type==='function_call_output').output).executed,false);
assert.equal(requests[2].input.findLast(i=>i.type==='function_call_output').call_id,'valid');
assert.equal(r.workflow.scope,'chat-scoped-tools');assert.equal(r.native_stream.artifact_links_normalized,true);assert.match(r.answer,/\/api\/chat\/rooms\//);
console.log('Native tools passed: schemas, offline boundary, argument correction without execution, original call IDs, real attachment link resolution.');
