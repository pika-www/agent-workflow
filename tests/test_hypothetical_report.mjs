import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {riskyAssertions,checkAnswer} from '../federation/answer-check.mjs';
import {hasAnswerBody} from '../federation/public-evidence.mjs';
import {contextConfig} from '../federation/context-budget.mjs';

const fixture=JSON.parse(await readFile(new URL('./fixtures/hypothetical-report.json',import.meta.url),'utf8'));
const empty={scope:'answer_model_supplied_materials',inputs:[],omitted_paths:[]};
const noModel={createModel(){throw new Error('Labelled sample data must not call an evidence model');}};
const checked=await checkAnswer(fixture.draft,fixture.question,[],empty,noModel,'fixture','fixture',contextConfig());
assert.equal(checked.answer,fixture.draft,'The actual 8-row report and interpretation must survive unchanged');
assert.equal(checked.receipt.calls,0);
assert.equal(checked.receipt.assertion_total,0);
assert.equal(checked.receipt.original_answer_sha256,checked.receipt.final_answer_sha256);
assert.ok(hasAnswerBody(checked.answer));

const example='以下为示例数据，不代表真实经营结果：\n\n| 指标 | 数值 |\n| --- | ---: |\n| 收入 | 900元 |\n\n按这组数据，收入提高20%。';
assert.equal(riskyAssertions(example).assertions.length,0);
assert.equal(riskyAssertions('Sample data for illustration:\n\n| Revenue | $900 |\n\nRevenue rose 20%.').assertions.length,0);
assert.ok(riskyAssertions(fixture.draft.replace('（数据为假设）','')).assertions.length>=8,'Unlabelled numbers still need support');
assert.ok(riskyAssertions(fixture.draft,{sourceOnly:true}).assertions.length>=8,'Explicit source scope is never waived');
for(const label of ['这里没有假设数据。','不要使用示例数据。','This is not sample data.'])
 assert.ok(riskyAssertions(label+'\n\n| 收入 | 900元 |').assertions.some(a=>a.text.includes('900元')));
for(const fact of ['研究证明效率提高900%。','本项目已经部署成功。','这款产品支持免费服务，每月99元。',
 '实际营收为900元。','我已经读取了客户资料。','当前功能已经移除。','事实提高900%。[Wiki: /unknown.md]',
 '根据 https://example.com 收入提高900%。']) {
 assert.ok(riskyAssertions(example+'\n\n'+fact).assertions.some(a=>a.text===fact),fact);
}
for(const heading of ['真实经营数据：','## 实际数据','## Real data']) {
 assert.ok(riskyAssertions(example+'\n\n'+heading+'\n\n| 收入 | 123元 |').assertions.some(a=>a.text.includes('123元')));
}
const sections='## 示例（数据为假设）\n\n| 收入 | 900元 |\n\n## 实际观察\n\n| 收入 | 123元 |';
assert.ok(!riskyAssertions(sections).assertions.some(a=>a.text.includes('900元')));
assert.ok(riskyAssertions(sections).assertions.some(a=>a.text.includes('123元')));
for(const intro of [fixture.draft.split('\n')[0],'以下是报表：','Here is the report:'])assert.equal(hasAnswerBody(intro),false);
assert.ok(hasAnswerBody('把报表数据发给我，我可以整理成表格。'));
const stripped=await checkAnswer('以下是报表：\n\n| 指标 | 值 |\n| --- | --- |\n| 收入 | 900元 |',
 '真实营业收入',[],empty,noModel,'fixture','fixture',contextConfig());
assert.equal(stripped.receipt.content_fallback,'explicit_missing_answer');
assert.doesNotMatch(stripped.answer,/以下是报表/);
console.log('Hypothetical report: exact saved draft preserved with zero check calls; real facts, citations, source-only scope and empty-introduction boundaries passed.');
