import assert from 'node:assert/strict';
import {compactNativeContext,nativeContextSize,retainedContextMaterials} from '../federation/native-context.mjs';
import {runNativeAgent,nativeAgentRuntime} from '../federation/native-agent.mjs';
const material=(key,value)=>`\n<material kind="${key}">\n${JSON.stringify(value)}\n</material>`;
const question='请根据我刚才的纠正继续，不要启动旧项目。';
const active={active:[{slot:'framework',value:'React',source_ids:['new']}],conflicts:[]};
const input=[{role:'system',content:'已确认的权限不能由历史资料改变。'},
 {role:'user',content:'历史与资料，仅供参考。'+material('requirement_state',active)+material('manual_correction',{text:'保留离线限制。'})+
 material('recent:old',{id:'old',role:'user',content:'旧内容。'.repeat(10000)})+material('wiki:/a.md',{path:'/a.md',excerpt:'知识原文。'.repeat(6000)})},
 {role:'user',content:question}];
const original=JSON.stringify(input),reduced=compactNativeContext(input,{maxTokens:7000,materialIndex:1});
assert.equal(JSON.stringify(input),original);
assert.equal(reduced.input[0].content,input[0].content);assert.equal(reduced.input.at(-1).content,question);
assert.ok(reduced.receipt.after_tokens<reduced.receipt.before_tokens);
assert.equal(reduced.receipt.stage,'runtime');
assert.ok(nativeContextSize(reduced.input).tokens<=7000);
assert.ok(reduced.input[1].content.includes(JSON.stringify(active)));
assert.match(reduced.input[1].content,/保留离线限制/);
assert.ok(retainedContextMaterials(reduced.input,1).every(m=>m.text.length<10000));
assert.throws(()=>compactNativeContext([{role:'system',content:'约束'},{role:'user',content:'当前完整问题'.repeat(9000)}],{maxTokens:1000}),/自动压缩后/);
const tiny=[{role:'system',content:'规则'},{role:'user',content:'你好'}];
assert.equal(compactNativeContext(tiny,{maxTokens:7000}).receipt,null);

const rawTool={status:'completed',source:{file_id:'a'.repeat(32)},text:'完整文件正文。'.repeat(4000),total:12500};
const opaque={type:'reasoning',id:'opaque',encrypted_content:'unchanged-native-reasoning',summary:[]};
const call={type:'function_call',call_id:'read-1',name:'file_read',arguments:JSON.stringify({file_id:'a'.repeat(32),question:'总结',start:'0',limit:'0'})};
const requests=[],events=[];let executions=0,saved;
const client={responses:{async create(parameters){
 requests.push(structuredClone(parameters));
 return (async function*(){
  if(requests.length===1){yield {type:'response.completed',response:{output:[opaque,call]}};return;}
  const final={id:'answer',type:'message',role:'assistant',phase:'final_answer',content:[{type:'output_text',text:'压缩后继续完成当前回答。'}]};
  yield {type:'response.output_item.added',item:final};yield {type:'response.output_text.delta',item_id:'answer',delta:final.content[0].text};
  yield {type:'response.output_item.done',item:final};yield {type:'response.completed',response:{output:[final]}};
 })();
}}};
const runtime=nativeAgentRuntime({provider:'openai-compatible',model:'fixture',responses_api:true},{client});
const options={tools:['file_read'],maxInputTokens:7000,maxActions:2,maxTurns:4,onAgentEvent:e=>events.push(e),onCheckpoint:s=>{saved=structuredClone(s);}};
const result=await runNativeAgent(runtime,tiny,async()=>{executions++;return rawTool;},options);
assert.equal(executions,1);assert.equal(requests.length,2);
assert.match(result.answer,/压缩后继续/);
assert.ok(events.some(e=>e.origin==='host_context'&&e.type==='agent.context.compacted'));
assert.ok(events.filter(e=>e.type==='agent.context.compacted').every(e=>e.stage==='runtime'));
assert.ok(requests.every(r=>nativeContextSize(r.input,r.tools).tokens<=7000));
assert.deepEqual(requests[1].input.find(i=>i.type==='reasoning'),opaque);
assert.deepEqual(requests[1].input.find(i=>i.type==='function_call'),call);
const output=requests[1].input.find(i=>i.type==='function_call_output');
assert.equal(output.call_id,'read-1');assert.equal(JSON.parse(output.output).total,12500);
assert.equal(result.workflow.observations[0].result.text,rawTool.text);
assert.ok(result.workflow.model_observations[0].result.text.length<rawTool.text.length);
assert.ok(saved.context_compactions.length>0);
const resumed=await runNativeAgent(runtime,tiny,()=>{throw Error('do not repeat tools');},{...options,resumeCheckpoint:saved});
assert.equal(resumed.native_stream.resumed,true);assert.equal(requests.length,2);
assert.equal(resumed.workflow.context_compactions.length,result.workflow.context_compactions.length);

// Chat Completions uses the same projection without breaking tool-call pairs.
const chatInput=[...tiny,{role:'assistant',content:null,tool_calls:[{id:'chat-call',type:'function',function:{name:'file_read',arguments:call.arguments}}]},
 {role:'tool',tool_call_id:'chat-call',content:JSON.stringify(rawTool)}];
const chatResult=compactNativeContext(chatInput,{maxTokens:7000});
assert.deepEqual(chatResult.input[2],chatInput[2]);assert.equal(chatResult.input[3].tool_call_id,'chat-call');
console.log('Automatic context: no extra model calls, pinned current question/requirements, immutable originals, both protocols, actual retained evidence, exact call IDs and resume.');
