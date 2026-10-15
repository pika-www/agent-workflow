import assert from 'node:assert/strict';
import {localModelOptions,localStructuredInit} from '../federation/local-model-transport.mjs';

const endpoint=new URL('http://127.0.0.1:11436/v1/chat/completions');
const request={body:JSON.stringify({model:'qwen3.5:9b',response_format:{type:'json_object'}})};
assert.equal(JSON.parse(localStructuredInit(endpoint,request).body).reasoning_effort,'none');
for (const payload of [{model:'qwen3.5:9b'}, {model:'other',response_format:{}},
  {model:'qwen3.5:9b',response_format:{},reasoning_effort:'high'}]) {
  const init={body:JSON.stringify(payload)};
  assert.equal(localStructuredInit(endpoint,init),init);
}
assert.equal(localStructuredInit(new URL('https://cloud.example/v1/chat/completions'),request),request);

const env={WEIMING_LOCAL_MODEL_TIMEOUT_SECONDS:'1800'};
assert.deepEqual(localModelOptions('https://cloud.example/v1',{},env),{});
assert.deepEqual(localModelOptions('http://127.0.0.1:11436/v1',{},{}),{});
assert.deepEqual(localModelOptions('http://127.0.0.1:11437/v1',{},env),{});
assert.throws(()=>localModelOptions('http://127.0.0.1:11436/v1',{}, {...env,WEIMING_LOCAL_MODEL_TIMEOUT_SECONDS:'0'}));
const options=localModelOptions('http://127.0.0.1:11436/v1',{apiKey:'local-only'},env);
assert.equal(options.timeout,1800000);
assert.equal(options.configuration.apiKey,'local-only');
assert.throws(()=>options.configuration.fetch('http://remote.example/v1/chat/completions',{}),/mismatch/);
await assert.rejects(options.configuration.fetch('http://127.0.0.1:11436/v1/chat/completions',{signal:AbortSignal.abort()}),{name:'AbortError'});
console.log('local model transport scope, bounded timeout and caller cancellation passed');
