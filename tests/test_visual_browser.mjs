import assert from 'node:assert/strict';
import {nativeTools,validateNativeCall,consultationTools,nativeToolTarget} from '../federation/native-agent.mjs';
import {modelObservation} from '../federation/tool-loop.mjs';
const call={type:'function_call',call_id:'visual-1',name:'visual_browser',arguments:JSON.stringify({url:'https://example.com/',actions:'read,screenshot,next_page,read',viewport:'desktop'})};
assert.equal(nativeTools(['visual_browser'])[0].name,'visual_browser');
assert.equal(validateNativeCall(call,['visual_browser']).viewport,'desktop');
assert.ok(consultationTools({executeTool(){},toolPolicy:{network_allowed:true}}).includes('visual_browser'));
assert.ok(!consultationTools({executeTool(){},toolPolicy:{network_allowed:false}}).includes('visual_browser'));
for(const actions of ['eval','click,read','read,submit','screenshot,screenshot,screenshot,screenshot','read,read,read,read,read,read,read'])
 assert.throws(()=>validateNativeCall({...call,arguments:JSON.stringify({url:'https://example.com/',actions,viewport:'desktop'})},['visual_browser']));
assert.throws(()=>validateNativeCall(call,[]));
assert.equal(nativeToolTarget('visual_browser',{url:'https://example.com/page?secret=hidden#part'}),'https://example.com/page');
const result=modelObservation({tool:'visual_browser',result:{status:'completed',sources:[{url:'https://example.com/',excerpt:'actual DOM',sha256:'a'.repeat(64),read_method:'visual_browser_dom'}],operations:[{action:'scroll_down',status:'completed'}],artifacts:[{id:'b'.repeat(32)}],links:[{url:'https://example.com/next'}]}}).result;
assert.equal(result.sources[0].excerpt,'actual DOM');assert.equal(result.operations[0].action,'scroll_down');assert.equal(result.artifacts[0].id,'b'.repeat(32));
console.log('Visual browser tool policy, argument bounds, source observations and target redaction passed.');
