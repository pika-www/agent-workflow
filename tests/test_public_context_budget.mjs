import assert from 'node:assert/strict';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {compactPublicInput,retainedToolObservations} from '../federation/native-agent.mjs';
import {estimatedTokens} from '../federation/context-budget.mjs';
const source={url:'https://example.org/product',title:'产品功能介绍',excerpt:'招聘管理与简历筛选。'.repeat(600),read_method:'http_text'};
const raw={tool:'web_read',result:{status:'completed',sources:[source]}};
const input=[{role:'system',content:'必要规则，不能丢弃。'},{role:'user',content:'请完整回答我对平台功能、区别和适用人群的比较问题。'}];
for(let i=0;i<4;i++)input.push({role:'system',content:'宿主为本轮已授权的只读查询实际执行了 web_read。\n'+JSON.stringify({...raw,result:{...raw.result,sources:[{...source,url:'https://example.org/product/'+i}]}})});
const fixed=JSON.stringify(input.slice(0,2));
assert.ok(estimatedTokens(JSON.stringify(input))>6000);
compactPublicInput(input,6000);
assert.ok(estimatedTokens(JSON.stringify(input))<=6000);
assert.equal(JSON.stringify(input.slice(0,2)),fixed,'Required rules/current question are never cropped');
assert.equal(source.excerpt.length,'招聘管理与简历筛选。'.repeat(600).length,'Original receipts remain complete');
const retained=retainedToolObservations(input,[]);
assert.equal(retained.length,4);assert.ok(retained.some(o=>o.result.context_excerpt_truncated));
assert.ok(retained.every(o=>o.result.sources[0].url.startsWith('https://example.org/product/')));
for(const o of retained.filter(o=>o.result.context_excerpt_truncated))assert.equal(o.result.sources[0].provided_excerpt_sha256.length,64);
const native=[{type:'function_call_output',call_id:'call-a',output:JSON.stringify(raw.result)},{role:'tool',tool_call_id:'call-b',content:JSON.stringify(raw.result)}];
assert.deepEqual(retainedToolObservations(native,[{call_id:'call-a',tool:'web_read'},{call_id:'call-b',tool:'visual_browser'}]).map(o=>o.tool),['web_read','visual_browser']);
// Use one real pipe for stdout and stderr, reproducing the merged worker stream.
const program=`import {writeCheckpoint} from './federation/stream-output.mjs'; await writeCheckpoint({text:'完整中文记录'.repeat(20000)}); process.stderr.write('EXPECTED_ERROR\\n'); process.exitCode=1;`;
// Pass the program as an argument (not shell-interpolated source).
const actual=await promisify(execFile)('/bin/sh',['-c','exec node --input-type=module -e "$1" 2>&1','checkpoint-test',program],{maxBuffer:1000000}).catch(e=>e);
const lines=actual.stdout.trimEnd().split('\n');
assert.equal(JSON.parse(lines[0].slice('OPENWIKI_CHECKPOINT '.length)).text,'完整中文记录'.repeat(20000));
assert.equal(lines[1],'EXPECTED_ERROR');assert.equal(lines.length,2);
console.log('Public context: bounded multi-site excerpts, intact current question/rules/provenance, exact retained checker evidence and complete UTF-8 checkpoint before errors passed.');

const {publicExcerpt}=await import('../federation/public-excerpt.mjs');
const intro='市场变化与行业介绍。'.repeat(100)+'\n\n## A平台\n\n产品介绍：提供简历解析和面试管理。\n\n适用企业：需要集中管理招聘流程的团队。';
const excerpt=publicExcerpt(intro,300,'比较招聘平台的功能、区别和适用人群');
assert.match(excerpt,/简历解析/);assert.match(excerpt,/适用企业/);assert.ok(excerpt.length<=300);
assert.ok(intro.includes('产品介绍：提供简历解析和面试管理。'));
