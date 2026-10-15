/** Model cross-check with host-validated provenance. This is not a truth oracle. */
import {createHash} from 'node:crypto';
export const researchReviewDescription='核对本轮公开资料是否覆盖用户问题。assessment 是 JSON 字符串：{claims:[{claim,status,evidence:[{url,quote}],note}],gaps:[字符串],follow_up_queries:[公开查询词]}。status 为 corroborated、single_source、conflicting 或 unverified。quote 必须逐字摘自本轮已读取的正文，不能引用搜索摘要；corroborated 要有至少两个独立网站对同一事实的支持，转载同一稿件不算独立印证。最多 12 项结论、8 个缺口和 3 个补查查询词，按优先级排列。逐项核对发布日期、统计口径、原始出处及冲突。未核实的关键事实写入 gaps，并给出能补足它的查询词。不同产品各自的官方功能可以是 single_source，不强求两个网站重复说明。资料不完整时如实记录，不为结束任务而宣称一致。';
const canonical=value=>{try{const u=new URL(value);u.hash='';return /^https?:$/.test(u.protocol)&&!u.username&&!u.password?u.href:null;}catch{return null;}};
export const researchHost=value=>{
 const url=canonical(value);if(!url)return '';
 const parts=new URL(url).hostname.toLowerCase().split('.');
 return parts.slice(-(/^(?:com|org|net|co|ac|gov)\.[a-z]{2}$/.test(parts.slice(-2).join('.'))?3:2)).join('.');
};
export function reviewResearch(args,observations,{requireIndependentSupport=false}={}) {
 let assessment;try{assessment=JSON.parse(args.assessment);}catch{return {status:'failed',error:'assessment 必须是完整 JSON。'};}
 if(!Array.isArray(assessment?.claims)||!assessment.claims.length||assessment.claims.length>12
  ||!Array.isArray(assessment.gaps)||assessment.gaps.length>8||!assessment.gaps.every(s=>typeof s==='string'&&s.length<=500)
  ||!Array.isArray(assessment.follow_up_queries)||assessment.follow_up_queries.length>12
  ||!assessment.follow_up_queries.every(s=>typeof s==='string'&&s.trim().length>=3&&s.length<=180))
  return {status:'failed',error:'请提供 1–12 项结论、gaps 和最多 3 个补查查询词。'};
 const sources=new Map(observations.filter(o=>['web_read','visual_browser'].includes(o.tool))
  .flatMap(o=>o.result?.sources||[]).filter(s=>canonical(s.url)&&s.excerpt&&s.read_method!=='search_result_snippet')
  .map(s=>[canonical(s.url),s]));
 const claims=[];
 for(const row of assessment.claims){
  if(typeof row.claim!=='string'||!row.claim.trim()||row.claim.length>600||!['corroborated','single_source','conflicting','unverified'].includes(row.status)
   ||!Array.isArray(row.evidence)||row.evidence.length>6||typeof row.note!=='string'||row.note.length>800)
   return {status:'failed',error:'每项需要 claim、status、evidence 和 note，结论及备注须简短。'};
  const evidence=[],hosts=new Set(),bodies=new Set();
  for(const ref of row.evidence){
   const url=canonical(ref.url),source=sources.get(url);
   if(!source||typeof ref.quote!=='string'||ref.quote.trim().length<12||ref.quote.length>1200||!source.excerpt.includes(ref.quote))
    return {status:'failed',error:'核对引用必须指向本轮实际读取的网页，并提供正文中至少 12 字的逐字摘录。搜索摘要和未读链接不能作为交叉核实依据。'};
   hosts.add(researchHost(url));bodies.add(createHash('sha256').update(source.excerpt.replace(/\s/g,'')).digest('hex'));
   evidence.push({url,quote:ref.quote});
  }
  let status=row.status;
  if(!evidence.length)status='unverified';
  else if(['corroborated','conflicting'].includes(status)&&(hosts.size<2||bodies.size<2))status='single_source';
  claims.push({...row,status,evidence});
 }
 const gaps=[...assessment.gaps];
 for(const row of claims)if(['conflicting','unverified'].includes(row.status)&&!gaps.includes(row.claim))gaps.push(row.claim);
 if(requireIndependentSupport)for(const row of claims)if(row.status==='single_source')gaps.push('仍为单一来源，未交叉印证：'+row.claim);
 return {status:'completed',basis:'model_crosscheck_with_validated_quotes',claims,gaps:gaps.slice(0,12),
  follow_up_queries:assessment.follow_up_queries.slice(0,3),coverage_complete:!gaps.length,
  note:'引用网址与摘录已校验；事实支持关系由模型判断。单一来源不等于多方核实，重复转载不等于独立证据。'};
}
