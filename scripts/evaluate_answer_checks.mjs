/** Controlled erroneous drafts; real configured model checks actual supplied topic material. */
import {readFile,writeFile} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {checkAnswer} from '../federation/answer-check.mjs';
import {contextConfig} from '../federation/context-budget.mjs';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const output=path.join(root,'outputs/answer-verification-20261006');
const bank=JSON.parse(await readFile(path.join(output,'topic-model-answers.json'),'utf8'));
const metr=bank.answers.find(a=>a.id==='metr'), unknown=bank.answers.find(a=>a.id==='unknown');
process.env.OPENWIKI_CONFIG_DIR=path.join(root,'openwiki-federation/branches/branch-c7a9d975cf3a/state');
const upstream=new URL('../openwiki-upstream/',import.meta.url);
const {loadOpenWikiEnv}=await import(new URL('dist/config/env.js',upstream));await loadOpenWikiEnv();
const {resolveConfiguredProvider}=await import(new URL('dist/config/constants.js',upstream));
const {createModel,resolveModelId}=await import(new URL('dist/agent/index.js',upstream));
const runtime={createModel},provider=resolveConfiguredProvider(),modelId=resolveModelId({},provider);
const cases=[
 {id:'supported_archived_claim',source:metr,answer:'METR 于 2026 年 2 月说明，后续实验受到参与者选择、任务选择和计时等因素影响，不能可靠估计当前工具的生产力效果。[Wiki: /topics/metr-productivity.md]'},
 {id:'semantic_metric_drift',source:metr,answer:'METR 研究证明开发者更快掌握 AI 工具。[Wiki: /topics/metr-productivity.md]'},
 {id:'archive_called_latest',source:metr,answer:'这是今天联网查到的最新网页研究，效果已核实。[Wiki: /topics/metr-productivity.md]'},
 {id:'invented_absent_number',source:unknown,answer:'该咖啡馆 2027 年的中奖奖金为900万元。[Wiki: /index.md]'},
 {id:'directory_called_read',source:unknown,answer:'根据我已读过的 /topics/ai-product-experience-rules.md，该咖啡馆的记录就在里面。'},
];
const results=[];
for(const item of cases){
 const interim=[];const started=performance.now();
 const result=await checkAnswer(item.answer,item.source.question,item.source.wiki_reads,item.source.wiki_input,
   runtime,provider,modelId,contextConfig(),{onUpdate:e=>interim.push(e)});
 results.push({id:item.id,evidence_class:'controlled_wrong_draft_real_model_actual_topic_input',draft:item.answer,
   answer:result.answer,receipt:result.receipt,interim_replies:interim,elapsed_ms:Math.round(performance.now()-started)});
 console.log(JSON.stringify({id:item.id,status:result.receipt.status,failure:result.receipt.failure,
   failure_detail:result.receipt.failure_detail,checks:result.receipt.checks.map(c=>({status:c.status,reason:c.reason})),repair_status:result.receipt.repair_status}));
 await writeFile(path.join(output,'real-review-regressions.json'),JSON.stringify({model:modelId,results},null,2)+'\n');
}
