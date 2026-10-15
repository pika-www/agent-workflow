/** Invocation prerequisites and read coverage derive only from actual receipts. */
export function prerequisiteIssue(name,args,observations){
 const issue=(field,expected)=>({code:'missing_prerequisite',field,expected,retryable:true});
 if(name==='platform_read'){
  const entries=observations.filter(o=>o.tool==='platform_tools'&&o.result.status==='completed').flatMap(o=>o.result.platforms||[]);
  const catalog=entries.findLast(p=>p.id===args.platform);
  if(!catalog)return issue('platform','先调用 platform_tools 获取当前平台真实工具及参数');
  if(!catalog.tools.includes(args.tool))return issue('tool','只使用平台目录实际返回的工具名');
 }
 if(name==='server_files'&&['read','list'].includes(args.action)){
  const p=JSON.parse(args.parameters);
  if(p.offset>0&&!observations.some(o=>o.tool===name&&o.result.status==='completed'&&o.result.action===args.action&&o.result.path===p.path&&o.result.next_offset===p.offset))
   return issue('parameters.offset','先读取该路径第一页，再使用实际回执中的 next_offset 继续');
 }
 return null;
}
export function readCoverage(observations){
 const byObject=new Map();
 for(const {tool,result:r} of observations){
  if(r.status!=='completed'||!['file_read','server_files'].includes(tool))continue;
  const source=r.source||r;
  const object=source.file_id||(['read','list'].includes(r.action)?r.path:null);
  const key=object?JSON.stringify([tool,r.action,object,source.sha256||r.version]):null;
  if(!key)continue;
  const row=byObject.get(key)||{object,tool,unit:tool==='file_read'?'characters':r.action==='list'?'entries':'bytes',version:source.sha256||r.version,ranges:[],next:null,complete:false};
  const start=source.start??r.offset??0,end=source.end??r.next_offset??r.total_bytes;
  if(Number.isFinite(end))row.ranges.push([start,end]);
  row.next=source.next_start??r.next_offset??null;
  // Directory enumeration has no numeric total; its first-page origin matters.
  if(r.action==='list'){row.started_at_zero ||= start===0;row.complete=row.started_at_zero&&row.next===null;}
  else {
   const ranges=row.ranges.sort((a,b)=>a[0]-b[0]);let covered=0;
   for(const [a,b] of ranges){if(a>covered)break;covered=Math.max(covered,b);}
   row.covered_until=covered;
   const total=source.total_chars??r.total_bytes;
   row.complete=Number.isFinite(total)&&covered>=total&&row.next===null&&!source.extraction_truncated;
  }
  byObject.set(key,row);
 }
 return [...byObject.values()];
}
