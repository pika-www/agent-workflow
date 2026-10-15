/** Deterministic task requirement reads; never asserts execution or permission. */
import {readFileSync} from 'node:fs';
const spec=JSON.parse(readFileSync(new URL('./memory-read-queries.json',import.meta.url),'utf8'));
export function memoryReadSlots(question) {
  if(typeof question!=='string'||question.length>500)return null;
  let text=question.trim().replace(/^@[^\s]+\s+/u,'').replace(/\s/gu,'').replace(/^[，,。！？?!]+|[，,。！？?!]+$/gu,'').replace(/^继续[，,]/u,'').replace(/[，,](?:不推测执行状态|只复述已确认要求|不要推测执行状态)$/u,'');
  if(new RegExp(spec.all,'u').test(text))return Object.keys(spec.slots);
  if(!new RegExp(spec.specific,'u').test(text))return null;
  const tokens=new Map(Object.entries(spec.slots).flatMap(([slot,pattern])=>pattern.split('|').map(token=>[token,slot])));
  const found=[...text.matchAll(new RegExp([...tokens.keys()].sort((a,b)=>b.length-a.length).join('|'),'gu'))].map(m=>tokens.get(m[0]));
  return Object.keys(spec.slots).filter(slot=>found.includes(slot));
}
const clean=text=>text.replace(/(?:sk[-_][A-Za-z0-9_-]{12,}|Bearer\s+\S+|(?:api[_ -]?key|密钥|密码)\s*[:：=]\s*\S+)/gi,'[已隐藏私密配置]');
export function memoryReadAnswer(question,memory) {
  const slots=memoryReadSlots(question);if(!slots||!memory)return null;
  const state=memory.requirement_state || {},groups=Object.fromEntries(slots.map(slot=>[slot,[]]));
  const subjects=new Set([...(state.active || []),...(state.conflicts || [])].filter(r=>slots.includes(r.slot)).map(r=>r.subject ?? null));
  if(subjects.size>1)return null; // Normal contextual route must select the project.
  for(const record of [...(state.active || []),...(state.conflicts || [])])if(record.origin!=='host_policy' && Object.hasOwn(groups,record.slot) && typeof record.value==='string'&&record.value.length<=200&&!groups[record.slot].some(r=>r.value===record.value))groups[record.slot].push(record);
  const display=r=>clean(spec.display[r.value] || r.value);
  const conflicts=slots.filter(slot=>groups[slot].length>1 || groups[slot].some(r=>r.status==='conflict'));
  let answer;
  if(conflicts.length)answer=conflicts.map(slot=>spec.labels[slot]+'有“'+groups[slot].map(display).join('”与“')+'”的未解决冲突').join('；')+'。请先确认采用哪条要求，可以在“记忆”中选择。';
  else {
    const confirmed=slots.filter(slot=>groups[slot].length).map(slot=>spec.labels[slot]+'为 '+display(groups[slot][0]));
    const missing=slots.filter(slot=>!groups[slot].length);
    answer=confirmed.length?'你当前确认的要求是：'+confirmed.join('；')+'。':slots.length===Object.keys(spec.slots).length?'当前任务还没有可用的已确认要求。':'';
    if(missing.length&&slots.length!==Object.keys(spec.slots).length)answer+='当前没有已确认的'+missing.map(slot=>spec.labels[slot]).join('、')+'要求。';
  }
  return {answer,provider:'host',model:null,engine:'宿主任务记忆',response_origin:'host_memory_read',
    memory_read:{slots,source_ids:[...new Set(Object.values(groups).flat().flatMap(r=>r.source_ids || []))],basis:'confirmed_user_requirements',conflicts:Boolean(conflicts.length)},
    context_usage:{enabled:true,task_id:memory.task_id,project_id:memory.project_memory?.id || null,input_tokens_estimated:0,total_input_tokens_estimated:0,total_calls:0,total_input_tokens:0,total_output_tokens:0,
      reply:{input_tokens:0,output_tokens:0,cached_tokens:0},summary:{status:'not_needed',calls:0,input_tokens:0,output_tokens:0},included:[{key:'requirement_state',tokens:0,reason:'host_memory_read_no_model'}],omitted:[],personal_omitted:[]},
    timing:{model_ms:0,first_text_ms:0,chunks:0,input_chars:0}};
}
