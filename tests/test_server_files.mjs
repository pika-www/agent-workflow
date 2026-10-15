import assert from 'node:assert/strict';
import {consultationTools,nativeTools,validateNativeCall} from '../federation/native-agent.mjs';
import {runtimeCapabilities,runtimeCapabilityTurn,runtimeCapabilityContext} from '../federation/runtime-capabilities.mjs';
import {serviceSummary} from '../federation/online-context.mjs';
const policy={tools_enabled:true,network_allowed:false,services:{
 files:{implemented:true,configured:true,runtime_location:'server'},
 server_files:{implemented:true,configured:true,runtime_location:'server',account:'winfield',confirmation:'every-mutation-and-command',administrator:false}}};
const options={toolPolicy:policy,executeTool:()=>{},currentQuestion:'你能读取服务器的东西吗？'};
assert(consultationTools(options).includes('server_files'));
assert(!consultationTools({...options,toolPolicy:{...policy,tools_enabled:false}}).includes('server_files'));
assert(!consultationTools({...options,toolPolicy:{...policy,services:{}}}).includes('server_files'));
assert.equal(nativeTools(['server_files'])[0].parameters.additionalProperties,false);
assert.equal(validateNativeCall({type:'function_call',call_id:'one',name:'server_files',arguments:JSON.stringify({action:'write',parameters:JSON.stringify({path:'/tmp/test',content:'x'.repeat(12000)})})},['server_files']).action,'write');
assert.throws(()=>validateNativeCall({type:'function_call',call_id:'one',name:'server_files',arguments:JSON.stringify({action:'delete',parameters:'{}',approved:true})},['server_files']));
assert.equal(runtimeCapabilities(options).arbitrary_filesystem,true);
assert.match(runtimeCapabilityTurn(options).answer,/winfield/);
assert.match(runtimeCapabilityTurn(options).answer,/确认后执行/);
assert.match(runtimeCapabilityContext(options),/pending_confirmation 不代表已执行/);
assert.equal(runtimeCapabilityTurn({...options,currentQuestion:'读取服务器 /home/winfield/test.txt'}),null);
assert.equal(serviceSummary(policy.services).server_files.account,'winfield');
console.log('Server tool schemas, grants, runtime capability and confirmation guidance passed.');
