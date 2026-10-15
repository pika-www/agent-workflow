import assert from 'node:assert/strict';
import { runSocialReplyTurn, assertLocalReplyProvider } from '../federation/social-reply-turn.mjs';
let invoked = 0, output = { type:'ai', content:'{"reply":"你好呀！","needs_human":false,"reason":""}' };
const runtime = {
  env:{OPENAI_COMPATIBLE_BASE_URL:'http://127.0.0.1:18733/v1'},
  async loadOpenWikiEnv(){}, resolveConfiguredProvider:()=> 'openai-compatible',
  resolveModelId:()=> 'local-test-model', resolveProviderRetryAttempts:()=>1,
  createModel(){ return { get bindTools(){throw new Error('no tools');}, async invoke(messages, options){
    invoked++; assert.equal(messages.length,2); assert.match(messages[0].content,/没有工具/);
    assert.equal(options.response_format.type,'json_object'); return output;
  }}; },
};
const evidence={text:'仅使用专门公开资料',reads:[]};
const result=await runSocialReplyTurn('你好',evidence,runtime);
assert.equal(result.model,'local-test-model'); assert.deepEqual(result.wiki_reads,[]);
for(const env of [{}, {OPENAI_COMPATIBLE_BASE_URL:'https://example.com/v1'}, {OPENAI_COMPATIBLE_BASE_URL:'http://localhost.evil.test/v1'}, {OPENAI_COMPATIBLE_BASE_URL:'http://secret@localhost/v1'}]) {
  assert.throws(()=>assertLocalReplyProvider('openai-compatible',env));
}
for(const bad of [
 {type:'ai', content:'ok',tool_calls:[{name:'send'}]},
 {type:'ai', content:'partial',response_metadata:{finish_reason:'length'}},
 {type:'ai',content:'x'.repeat(8001)},
]) { output=bad; await assert.rejects(runSocialReplyTurn('hello',evidence,runtime)); }
const before=invoked;
await assert.rejects(runSocialReplyTurn('hello',evidence,{...runtime,env:{OPENAI_COMPATIBLE_BASE_URL:'https://example.com'}}));
assert.equal(invoked,before);
console.log('Social reply model: local endpoint boundary, no tools, strict visible output and truncation rejection passed.');
