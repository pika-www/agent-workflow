/** Select literal, task-related passages; never synthesize page facts. */
export function publicExcerpt(text,limit,question='') {
 if(typeof text!=='string'||text.length<=limit)return text;
 if(!/平台|软件|产品/u.test(question)||!/功能|比较|对比|区别|适用人群/u.test(question))return text.slice(0,limit);
 const blocks=text.split(/\n\s*\n/u),ranked=[];
 for(let i=0;i<blocks.length;i++){
  const block=blocks[i].trim();
  if(!block||/^\|[\s:|-]+$/.test(block))continue;
  const score=(/(?:产品介绍|功能特点|核心功能|适用企业|适用人群|平台优势|主要功能)[：:]/u.test(block)?12:0)
   +( /直接沟通|实时在线|简历解析|人才库|面试管理|岗位匹配|智能推荐|招聘管理系统|招聘流程/u.test(block)?6:0)
   +( /功能|适用|产品|支持|提供/u.test(block)?1:0)
   -( /本节甄选|本篇|本文将|在这份|市场.*(?:浪潮|难题)|以下是/u.test(block)?4:0);
  const heading=blocks[i-1]?.trim();
  ranked.push({i,text:(heading&&/^#{1,6}\s|^\d+[.、]\s*/u.test(heading)&&heading.length<100?heading+'\n\n':'')+block,score});
 }
 if(!ranked.some(r=>r.score>=6))return text.slice(0,limit);
 const selected=[];let remaining=limit;
 for(const item of ranked.sort((a,b)=>b.score-a.score||a.i-b.i)){
  if(remaining<60||selected.length===3)break;
  const take=Math.min(remaining,Math.max(240,Math.floor(limit/2)));
  const excerpt=item.text.slice(0,take);
  selected.push({...item,text:excerpt});remaining-=excerpt.length+2;
 }
 return selected.sort((a,b)=>a.i-b.i).map(i=>i.text).join('\n\n').slice(0,limit);
}
