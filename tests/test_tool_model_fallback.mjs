/** A non-native tool service may fall back only before any reply or action. */
import assert from 'node:assert/strict';
import {mkdtemp,writeFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {runIntakeTurn} from '../federation/intake-turn.mjs';
import {nativeAgentRuntime} from '../federation/native-agent.mjs';
const root=await mkdtemp(path.join(tmpdir(),'openwiki-tool-fallback-'));
const old=process.env.FEDERATION_TOOL_AGENT_MODEL_CONFIG;
try{
 const file=path.join(root,'model.json');
 await writeFile(file,JSON.stringify({provider:'openai-compatible',model:'not-native',base_url:'https://example.com/v1',api_key:'test-only',responses_api:false}),{mode:0o600});
 process.env.FEDERATION_TOOL_AGENT_MODEL_CONFIG=file;
 const final={id:'final',type:'message',role:'assistant',phase:'final_answer',content:[{type:'output_text',text:'网站提供产品文档。'}]};
 const client={responses:{async create(){return (async function*(){yield {type:'response.output_item.added',item:{...final,content:[]}};yield {type:'response.output_text.delta',item_id:final.id,delta:final.content[0].text};yield {type:'response.output_item.done',item:final};yield {type:'response.completed',response:{output:[final]}};})();}}};
 const native=nativeAgentRuntime({provider:'openai-compatible',model:'local-fixture',responses_api:true},{client});
 let executions=0,models=0;
 const runtime={async loadOpenWikiEnv(){},resolveConfiguredProvider(){return 'openai-compatible'},resolveModelId(){return 'local-fixture'},resolveProviderRetryAttempts(){return 1},createNativeAgent(){models++;return native},createModel(){throw new Error('No second model needed')}};
 const evidence={wiki:{text:'',reads:[]},templates:{text:'',reads:[]},skills:{text:'',reads:[]}};
 const result=await runIntakeTurn('读取 https://example.com/ 的用途','consultation',evidence,runtime,{currentQuestion:'读取 https://example.com/ 的用途',onUpdate(){},toolPolicy:{tools_enabled:true,network_allowed:true,use_tool_model:true},executeTool:async name=>{executions++;assert.equal(name,'web_read');return {status:'completed',sources:[{excerpt:'网站提供产品文档。',url:'https://example.com/',read_method:'http_body'}]}}});
 assert.equal(models,1);assert.equal(executions,1);assert.equal(result.tool_model_route.status,'fallback_before_execution');
 assert.equal(result.tool_model_route.fallback_model,'local-fixture');assert.equal(result.answer,'网站提供产品文档。');
 console.log('Tool-model fallback passed: unavailable native protocol, one main model, one real host read, no replay.');
}finally{
 if(old===undefined)delete process.env.FEDERATION_TOOL_AGENT_MODEL_CONFIG;else process.env.FEDERATION_TOOL_AGENT_MODEL_CONFIG=old;
 await rm(root,{recursive:true,force:true});
}
