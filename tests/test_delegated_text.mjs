import assert from 'node:assert/strict';
import os from 'node:os';
import path from 'node:path';
import {mkdtemp,mkdir,writeFile,rm,symlink} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {isTextOnlyDelegation,prepareDelegatedText,assertDelegatedIdentifiers} from '../federation/delegated-text.mjs';

const original='仅输出聊天方案，不联网、不运行命令、不修改文件、不部署。每名成员最多80字。';
assert.equal(isTextOnlyDelegation(original,'execute','完整回执'),true);
const paraphrase='本轮仅做文字方案，不联网、不调用外部工具、不写文件、不执行部署。前端必须等后端完成后读取并引用实际 acceptance_code。'.replace('实际 acceptance','实际acceptance');
assert.equal(isTextOnlyDelegation(paraphrase,'execute','完整回执'),true);
for(const extra of ['读取原始文档','查看附件','根据长期记忆'])assert.equal(isTextOnlyDelegation(paraphrase+extra,'summary','完整回执'),false);
for(const phase of ['plan','review','consultation','research'])assert.equal(isTextOnlyDelegation(original,phase,''),false);
for(const extra of ['读取原始文档','检索知识库','查看附件','需要来源链接','沿用上次决定','参考我的偏好','根据长期记忆'])
  assert.equal(isTextOnlyDelegation(original+extra,'summary',''),false);
assert.equal(isTextOnlyDelegation('请完成研究任务','execute',''),false);
assert.equal(isTextOnlyDelegation(original,'summary','下级结果已截短'),false);
const identifierTask='后端自行选一个 WM- 加四位数字的标识。前端原样引用标识。';
assert.throws(()=>assertDelegatedIdentifiers('委派失败，后端(WM-0001)。','summary',identifierTask,'汇总',[]),/未提供的标识/);
assert.throws(()=>assertDelegatedIdentifiers('WM-0524-frontend','execute',identifierTask,'原样引用实际标识',['WM-0524']),/未提供的标识/);
assertDelegatedIdentifiers('后端 WM-0524，前端依赖后端。','summary',identifierTask,'汇总',['WM-0524']);
assertDelegatedIdentifiers('WM-0524','execute',identifierTask,'生成一个标识',[]);
assert.throws(()=>assertDelegatedIdentifiers('前端已收到。','execute',identifierTask,'原样引用实际标识',['WM-0524']),/遗漏/);
const temp=await mkdtemp(path.join(os.tmpdir(),'delegated-text-'));
try {
  await mkdir(path.join(temp,'_delegation_results'));
  const body='后端原件 WM-0524；前端需要等待后端完成。';
  const sha=createHash('sha256').update(body).digest('hex');
  const ref='/_delegation_results/'+'1'.repeat(32)+'-'+sha+'.md';
  const file=path.join(temp,ref.slice(1));
  await writeFile(file,body);
  const result=await prepareDelegatedText('任务证据 '+ref+' '+ref,'引用标识',original,'execute',temp,12000);
  assert.equal(result.receipt.original_artifacts.length,1);
  assert.equal(result.receipt.original_artifacts[0].sha256,sha);
  assert.equal(result.receipt.tools_enabled,false);
  assert(result.text.includes(body));
  const host={agent_id:'software',phase:'summary',original,task:'汇总',depends_on:[],
    records:[{id:'1'.repeat(32),status:'failed',error:'缺少核对材料',depends_on:[]}]};
  const concise=await prepareDelegatedText(('重复模板 '.repeat(400))+ref,'汇总',original,'summary',temp,12000,host);
  assert.equal(concise.receipt.host_context_compacted,true);
  assert(concise.text.includes(original) && concise.text.includes('缺少核对材料'));
  assert.equal(concise.text.split(body).length,2);
  assert(!concise.text.includes('重复模板'));
  const mismatch=await prepareDelegatedText('完整提示 '+ref,'汇总',original,'summary',temp,12000,{...host,original:'其他任务'});
  assert.equal(mismatch.receipt.host_context_compacted,false);
  assert.equal(await prepareDelegatedText(ref,'引用标识',original,'execute',temp,2),null);
  await writeFile(file,'被替换的版本');
  await assert.rejects(()=>prepareDelegatedText(ref,'引用标识',original,'execute',temp),/版本不一致/);
  await rm(file);await writeFile(path.join(temp,'other'),body);await symlink(path.join(temp,'other'),file);
  await assert.rejects(()=>prepareDelegatedText(ref,'引用标识',original,'execute',temp),/有效文件/);
}finally{await rm(temp,{recursive:true,force:true});}
process.stdout.write('Text-only delegation: explicit scope, native fallback, complete evidence, hash and symlink boundaries passed.\n');
