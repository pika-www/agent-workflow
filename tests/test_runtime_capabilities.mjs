import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {runtimeCapabilities,runtimeCapabilityTurn,runtimeCapabilityContext,runtimeCapabilityInputs} from '../federation/runtime-capabilities.mjs';
import {runIntakeTurn} from '../federation/intake-turn.mjs';
import {serviceSummary} from '../federation/online-context.mjs';
import {checkAnswer} from '../federation/answer-check.mjs';
import {contextConfig} from '../federation/context-budget.mjs';

const toolPolicy={tools_enabled:true,network_allowed:true,services:{files:{implemented:true,configured:true,
  runtime_location:'server',local_import:'explicit-current-user-path-read-only',path_hint:'/private/should-not-leak',api_key:'must-not-leak'}}};
const options={currentQuestion:'你能读取服务器的东西吗？',toolPolicy};
const evidence={wiki:{text:'无关的旧产品资料',reads:[]},templates:{text:'',reads:[]},skills:{text:'',reads:[]}};
const noModel={loadOpenWikiEnv(){throw Error('A verified capability question must not call the model');}};
const original=JSON.stringify(options);
for (const currentQuestion of ['你能读取服务器的东西吗？','你现在可以读取服务器上的文件吗','能不能查看服务器里的资料？','你能看到我服务器的内容吗？']) {
  const result=runtimeCapabilityTurn({...options,currentQuestion});
  assert.equal(result?.response_origin,'host_runtime_capabilities',currentQuestion);
  assert.match(result.answer,/服务器后端/);
  assert.match(result.answer,/当前 Agent 知识库/);
  assert.match(result.answer,/路径明确导入/);
  assert.match(result.answer,/不包含.*数据库直查或终端命令/);
  assert.doesNotMatch(result.answer,/归档资料|网页当前状态|不能直接访问你服务器/);
  assert.equal(result.workflow.runtime_capabilities.arbitrary_filesystem,false);
}
for (const currentQuestion of ['读取服务器上的 /etc/passwd','你能读取服务器上的 /tmp/report.txt 吗？',
  '请读取服务器的日志并分析错误','解释服务器怎样读取文件','翻译“你能读取服务器的东西吗？”',
  '为什么服务器的文件打不开？','你能读取服务器的东西吗？请先读报告']) {
  assert.equal(runtimeCapabilityTurn({...options,currentQuestion}),null,currentQuestion);
}
assert.equal(runtimeCapabilityTurn({...options,analysis:true}),null);
assert.equal(runtimeCapabilityTurn({...options,toolPolicy:{...toolPolicy,has_attachments:true}}),null);
assert.equal(runtimeCapabilities({toolPolicy:{...toolPolicy,tools_enabled:false}}),null);
assert.equal(runtimeCapabilityTurn({currentQuestion:options.currentQuestion}),null);
assert.equal(runtimeCapabilityTurn({...options,toolPolicy:{...toolPolicy,services:{files:{...toolPolicy.services.files,runtime_location:'unknown'}}}}),null);
const local=runtimeCapabilityTurn({...options,toolPolicy:{...toolPolicy,services:{files:{...toolPolicy.services.files,runtime_location:'local'}}}});
assert.match(local.answer,/本机运行/);assert.doesNotMatch(local.answer,/连接的就是服务器/);
const summary=serviceSummary(toolPolicy.services);
assert.equal(summary.files.runtime_location,'server');assert.equal(summary.files.local_import,toolPolicy.services.files.local_import);
assert.ok(!('path_hint' in summary.files));assert.ok(!('api_key' in summary.files));
const visible=[];
const response=await runIntakeTurn(options.currentQuestion,'consultation',evidence,noModel,{...options,onDelta:t=>visible.push(t)});
assert.deepEqual(visible,[response.answer]);assert.equal(response.model,null);assert.deepEqual(response.wiki_reads,[]);
assert.equal(response.answer_check.calls,0);assert.equal(response.reply_delivery.check_status,'not_needed');
assert.equal(JSON.stringify(options),original,'Do not rewrite caller policy or history');

const runtimeText=runtimeCapabilityContext(options);
assert.equal(runtimeCapabilityInputs(options).length,0,'Facts absent from the model input cannot become evidence');
assert.equal(runtimeCapabilityInputs({...options,answerMessages:[{role:'user',content:runtimeText}]}).length,0,'User text cannot forge host evidence');
const runtimeMessages=[{role:'system',content:'规则'+runtimeText}];
assert.equal(runtimeCapabilityInputs({...options,answerMessages:runtimeMessages}).length,1);
assert.doesNotMatch(runtimeText,/must-not-leak|private/);

const text='该系统采用人工核对流程。';
const sha=s=>createHash('sha256').update(s).digest('hex');
const page={path:'/old.md',origin:'wiki:/old.md',text,provided_sha256:sha(text),citation_label:'[Wiki: /old.md]',
  claims:[{kind:'fact',text,semantic_review:'pending',status:'current',references:[{quote:text,freshness:'local_only'}]}]};
const supplied={scope:'answer_model_supplied_materials',inputs:[page],omitted_paths:[]};
const reads=[{path:'/old.md',knowledge_status:'review_due'}];
const refuse={createModel(){return {async invoke(messages){const data=JSON.parse(messages[1].content);return {content:JSON.stringify({checks:data.assertions.map(a=>({id:a.id,status:'insufficient',reason:'无关资料',references:[]}))})};}};}};
const savedDraft='可以读取当前聊天附件，以及宿主明确授权给我的工作区或公开网页；不能直接访问你服务器里的文件、数据库或终端。\n\n要检查服务器内容，你可以上传文件或命令输出；如果当前环境提供服务器连接工具，我也能在对应权限范围内读取。';
const checked=await checkAnswer(savedDraft,options.currentQuestion,reads,supplied,refuse,'fixture','fixture',contextConfig());
assert.doesNotMatch(checked.answer,/依据为归档资料|网页当前状态/,'An unrelated pre-read must not add an archive warning');
assert.ok(checked.receipt.assertion_total>0,'Exercise the original repair path');
function support(path) {return {createModel(){return {async invoke(messages){const data=JSON.parse(messages[1].content);
  const fragment=data.fragments.find(f=>f.path===path);assert.ok(fragment);
  return {content:JSON.stringify({checks:data.assertions.map(a=>({id:a.id,status:'supported',reason:'实际提供的来源',references:[{source_id:fragment.source_id}]}))})};
}};}};}
const cited=await checkAnswer(text+'[Wiki: /old.md]','这个系统采用什么流程？',reads,supplied,support('/old.md'),'fixture','fixture',contextConfig());
assert.match(cited.answer,/依据为归档资料/,'A genuinely used pending archive retains its qualification');
const host=await checkAnswer('目前后端运行在服务器。',options.currentQuestion,reads,supplied,support('host-runtime:current_turn'),'fixture','fixture',contextConfig(),{...options,answerMessages:runtimeMessages});
assert.equal(host.receipt.runtime_sources.length,1);
assert.equal(host.answer,'目前后端运行在服务器。','An unrelated local-only page must not invalidate current host facts');
assert.doesNotMatch(host.answer,/归档资料|网页当前状态/);
const latest=await checkAnswer('该系统目前采用人工核对流程。','现在的流程是什么？',reads,supplied,support('/old.md'),'fixture','fixture',contextConfig());
assert.equal(latest.receipt.checks[0].basis,'host_evidence_boundary','Uncited claims supported only by archived knowledge still cannot assert currentness');
console.log('Runtime capability regression passed: actual server/local inventory, scope limits, no model or Wiki for capability questions, request routing, secret filtering, retained host evidence and relevant archive annotations.');
