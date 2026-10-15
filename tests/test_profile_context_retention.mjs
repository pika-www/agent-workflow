import assert from 'node:assert/strict';
import {assembleContext,contextConfig} from '../federation/context-budget.mjs';
import {compactNativeContext, nativeContextSize} from '../federation/native-context.mjs';
import {userContextInputs} from '../federation/answer-check.mjs';

const profile={revision:3,required_for_question:true,origin:'explicit_user_profile',source_status:'user_provided',
 sections:[{label:'简历片段 1',text:'林澄\n前端与 AI 应用开发。\n'+'React、TypeScript、Python 项目经验。'.repeat(35)}]};
const original=structuredClone(profile);
const evidence={wiki:{text:'旧网页正文。'.repeat(2000),reads:[]},templates:{text:'',reads:[]},skills:{text:'',reads:[]}};
const config={...contextConfig(),input_budget:2400};
const memory={goal:'一个较早的产品分析任务',recent:[{id:'old',role:'assistant',content:'旧产品介绍。'.repeat(2000)}]};
const built=assembleContext('当前只读，不能执行写入。'.repeat(65),'',evidence,'结合我的简历，给我求职建议',memory,{profile},config);
const retained=JSON.parse(built.messages[1].content.match(/<material kind="user_profile">\n([\s\S]*?)\n<\/material>/)[1]);
assert.deepEqual(retained,profile);
assert.ok(built.receipt.budget>config.input_budget && built.receipt.budget<=config.hard_input);
assert.ok(!built.receipt.omitted.some(item=>item.key==='user_profile'));
assert.ok(userContextInputs('结合我的简历，给我求职建议',built.messages).some(s=>s.path==='user-context:user_profile'&&s.text.includes('林澄')));
assert.deepEqual(profile,original);
assert.throws(()=>assembleContext('当前只读。','',evidence,'我叫什么',null,{profile},
 {...config,hard_input:1000}),/相关个人资料超过模型输入上限/);

// Actual runtime compression must retain the same bounded profile even when
// old retrieved history is much larger than the model's available input.
const input=[{role:'system',content:'只读问答。'},
 {role:'user',content:'\n<material kind="user_profile">\n'+JSON.stringify(profile)+'\n</material>\n<material kind="recent:old">\n'+JSON.stringify({content:'旧话题。'.repeat(5000)})+'\n</material>'},
 {role:'user',content:'我是谁？我叫什么？'}];
const before=structuredClone(input);
const projected=compactNativeContext(input,{maxTokens:4000,materialIndex:1});
assert.ok(projected.receipt);
assert.deepEqual(JSON.parse(projected.input[1].content.match(/<material kind="user_profile">\n([\s\S]*?)\n<\/material>/)[1]),profile);
assert.equal(projected.input.at(-1).content,input.at(-1).content);
assert.ok(nativeContextSize(projected.input).tokens<=4000);
assert.deepEqual(input,before);
console.log('Profile retention: relevant resume stays complete under selection and runtime pressure, reaches answer checking, and respects the hard input limit.');
