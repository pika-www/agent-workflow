/** Project the current host work mode without rewriting stored conversations. */
export function onlineContext(memory, policy={}) {
 if(!memory || !policy.default_online || !policy.network_allowed)return memory;
 const state=memory.requirement_state;
 if(!state)return memory;
 const keep=items=>(items || []).filter(item=>item.slot!=='network');
 const current={id:'current-online-policy',slot:'network',label:'本轮资料范围',value:'online_available',
  origin:'host_policy',resolution_origin:'current_work_mode',source_ids:[],status:'active'};
 const requirements=(memory.requirements || []).flatMap(item=>{
  const changes=item.requirement_changes || [];
  if(!changes.some(r=>r.slot==='network'))return [item];
  if(changes.every(r=>r.slot==='network'))return [];
  return [{...item,requirement_changes:keep(changes),network_requirement_status:'superseded_by_current_work_mode'}];
 });
 return {...memory,requirements,requirement_state:{...state,records:[...keep(state.records),current],
  active:[...keep(state.active),current],conflicts:keep(state.conflicts),
  notice:'本轮允许按需联网，不代表每条消息都要求搜索；普通聊天直接回应。旧会话的网络限制仅是历史，当前用户明确的离线要求及其他已确认要求保留。'}};
}

export function serviceSummary(services={}) {
 return Object.fromEntries(Object.entries(services).map(([key,value])=>[key,key==='platform_mcp'?value:key==='connectors'?serviceSummary(value):
  value && typeof value==='object'?Object.fromEntries(['implemented','configured','enabled','scope','network',...(key==='files'?['runtime_location','local_import']:[]),...(key==='server_files'?['runtime_location','account','confirmation','administrator']:[])]
   .filter(k=>value[k]!==undefined).map(k=>[k,value[k]])):value]));
}
