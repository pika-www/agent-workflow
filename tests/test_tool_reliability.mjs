import assert from 'node:assert/strict';
import {nativeAgentRuntime,runNativeAgent,validateNativeCall} from '../federation/native-agent.mjs';
import {invocationKey} from '../federation/tool-contracts.mjs';
const large={code:'#'+ '中'.repeat(11000),file_ids:''};
validateNativeCall({type:'function_call',name:'code_interpreter',call_id:'large',arguments:JSON.stringify(large)},['code_interpreter']);
assert.equal(invocationKey('server_files',{action:'read',parameters:'{"path":"a","offset":0}'}),invocationKey('server_files',{parameters:'{"offset":0,"path":"a"}',action:'read'}));
async function run(calls,policy,execute){
 let n=0;const requests=[];
 const client={responses:{async create(params){requests.push(params);const value=calls[n++];const output=value?[{id:'fc'+n,type:'function_call',call_id:'call'+n,name:value[0],arguments:JSON.stringify(value[1])}]:[{id:'end',type:'message',role:'assistant',phase:'final_answer',content:[{type:'output_text',text:'已根据实际回执说明结果与缺口。'}]}];return (async function*(){for(const item of output){yield {type:'response.output_item.added',item:{...item,content:[]}};if(item.type==='message')yield {type:'response.output_text.delta',item_id:item.id,delta:item.content[0].text};yield {type:'response.output_item.done',item};}yield {type:'response.completed',response:{id:'r'+n,output,usage:{input_tokens:10,output_tokens:10}}};})();}}};
 const result=await runNativeAgent(nativeAgentRuntime({provider:'openai-compatible',model:'fixture',responses_api:true},{client}),[{role:'user',content:'读取资料'}],execute,{tools:[...new Set(calls.map(c=>c[0]))],maxActions:calls.length,toolPolicy:policy});
 return {result,requests};
}
let executions=0;
const repeated=await run(Array.from({length:3},()=>['wiki_search',{query:'known'}]),{},async()=>{executions++;return {status:'failed',error:'fixture'};});
assert.equal(executions,2);assert.equal(repeated.result.workflow.receipts[2].failure_code,'repeated_failure');
const unknown=await run([['file_read',{file_id:'a'.repeat(32),question:'读取资料',start:'0',limit:'100'}]],{files:[]},()=>{throw Error('must not execute');});
assert.equal(unknown.result.workflow.receipts[0].failure_code,'unknown_object');
const corrected=await run([['wiki_search',{query:4}],['wiki_search',{query:'valid'}]],{},async()=>({status:'completed',text:'fixture'}));
assert.equal(corrected.result.workflow.tool_metrics.correction_successes,1);
const errorOutput=JSON.parse(corrected.requests[1].input.find(x=>x.type==='function_call_output').output);
assert.equal(errorOutput.error_detail.field,'query');assert.equal(errorOutput.executed,false);
console.log('Tool reliability passed: UTF-8 size, canonical arguments, bounded retry, object scope, field feedback, correction metrics.');

let chatTurn=0,largeCalls=0;
const chatClient={chat:{completions:{async create(){const n=++chatTurn;return (async function*(){
 if(n===1){const raw=JSON.stringify(large);for(let i=0;i<raw.length;i+=1000)yield {choices:[{delta:{tool_calls:[{index:0,...(i===0?{id:'large-call',function:{name:'code_interpreter',arguments:raw.slice(i,i+1000)}}:{function:{arguments:raw.slice(i,i+1000)}})}]}}]};yield {choices:[{delta:{},finish_reason:'tool_calls'}]};}
 else yield {choices:[{delta:{content:'完成'},finish_reason:'stop'}]};
})();}}}};
await runNativeAgent(nativeAgentRuntime({provider:'openai-compatible',model:'fixture'},{client:chatClient}),[{role:'user',content:'运行代码'}],async()=>{largeCalls++;return {status:'completed'};},{tools:['code_interpreter'],maxActions:1});
assert.equal(largeCalls,1,'Large UTF-8 arguments also pass streamed Chat Completions');

const {prerequisiteIssue,readCoverage}=await import('../federation/tool-state.mjs');
const page=(start,end,next)=>({tool:'file_read',result:{status:'completed',source:{file_id:'a',sha256:'v1',start,end,next_start:next,total_chars:12000}}});
assert.equal(readCoverage([page(6000,12000,null)])[0].complete,false);
assert.equal(readCoverage([page(0,6000,6000),page(6000,12000,null)])[0].complete,true);
assert.ok(prerequisiteIssue('server_files',{action:'read',parameters:JSON.stringify({path:'/tmp/a',offset:12000})},[]));
