(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const make = (tag, text, cls) => {const el=document.createElement(tag);el.textContent=text;if(cls)el.className=cls;return el;};
  const labels={queued:'等待知识复查',planning:'选择学习问题',collecting:'读取行业原文',drafting:'整理知识',reviewing:'核对依据和冲突',recovering:'正在补查与修复',publishing:'更新知识',upgrading:'检查代码改进',completed:'已完成',unchanged:'已检查，无新增',failed:'待自动续学',needs_attention:'待自动修复',retry_pending:'已排队自动续学',budget_wait:'等待次日预算续学',paused:'已暂停，进度保留',interrupted:'中断，等待自动续跑'};
  labels.foreground_wait='前台任务优先，等待空闲续学';
  const time = v => v ? new Date(v).toLocaleString('zh-CN',{hour12:false}) : '尚未运行';
  let state=null,locked=false;
  async function api(url,method='GET',body){const r=await fetch(url,{method,headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(15000)});const d=await r.json();if(!r.ok)throw Error(d.detail||'读取失败');return d;}
  async function action(fn){if(locked)return;locked=true;try{await fn();await refresh();}catch(e){$('summary').textContent=e.message;}finally{locked=false;}}
  async function detail(id){
    const data=await api('/api/autonomy/runs/'+id),body=$('detail-body'),r=data.run;
    $('detail').hidden=false;body.replaceChildren(make('p',r.title||r.reason||r.plan?.goal||r.agent_name));
    body.append(make('p',(labels[r.status]||r.status)+' · '+time(r.started_at)));
    if(r.kind==='knowledge_refresh')body.append(make('p','对话知识复查 · '+r.path),make('p',r.reason||'正在核对本地知识与实际联网原文。'));
    if(r.error)body.append(make('p',(state?.active_run===r.id?'上次尝试：':'')+r.error,'error'));
    if(r.resumed_from)body.append(make('p','本轮接着上次的原目标继续，已恢复保存的原文、草稿和核对反馈。'));
    if(r.repairs?.length)body.append(make('p','本轮已记录 '+r.repairs.length+' 次补查或修订反馈；完成前仍需通过独立核对和入库回读。'));
    if(r.publication?.conflict_resolution?.strategy==='preserve_and_version')body.append(make('p','发现已有页面存在独立修改，已保留原页，并将本次核对通过的内容保存为新版本。'));
    if(r.kind==='knowledge_refresh'&&data.proposal?.old_quote){body.append(make('h3','核对到的差异'),make('p','原结论：'+data.proposal.old_quote),make('p','核对后：'+data.proposal.replacement),make('p',data.proposal.version_basis||''));}
    if(data.draft){
      for(const claim of data.draft.claims||[])body.append(make('p',claim.text));
      body.append(make('h3','应用与适用范围'),make('p',data.draft.application),make('p',data.draft.limitations));
    }
    if(r.sources?.length){body.append(make('h3','本轮实际阅读的来源'));for(const s of r.sources){const p=make('p',''),link=make('a',s.title||s.url);if(/^https?:\/\//.test(s.url))link.href=s.url;link.target='_blank';link.rel='noopener noreferrer';p.append(link);body.append(p);}}
    if(r.verification?.questions){body.append(make('h3','学到之后能回答什么'));r.verification.questions.forEach((q,i)=>body.append(make('p',q),make('p',r.verification.answers?.[i]||'')));}
    const raw=make('details','');raw.append(make('summary','查看完整运行回执'),make('pre',JSON.stringify(data,null,2),'receipt'));body.append(raw);
    $('detail').scrollIntoView({behavior:'instant',block:'start'});
  }
  async function refresh(){
    const d=await api('/api/autonomy');state=d;
    $('online').disabled=false;$('online').checked=d.settings.conversation_online;$('refresh-knowledge').disabled=false;$('refresh-knowledge').checked=d.settings.conversation_refresh;const checks=d.runs.filter(r=>r.kind==='knowledge_refresh');$('refresh-status').textContent='最近对话复查 '+checks.length+' 条 · 已纠正 '+checks.filter(r=>r.status==='completed').length+' 条。'+(!d.settings.enabled?'自主运行已暂停，已排队复查会保留。':'');
    $('toggle').disabled=false;$('toggle').textContent=d.settings.enabled?'暂停自主学习':'开启自主学习';
    $('code').disabled=false;$('code').checked=d.settings.code_enabled;$('run').disabled=!d.settings.enabled;
    $('continuous').disabled=false;$('continuous').checked=d.settings.continuous_learning;
    const current=d.runs.find(r=>r.id===d.active_run);
    const local=d.settings.model_policy==='local', exhausted=!local&&d.budget.calls>=d.settings.daily_model_calls;
    const budgetResume=d.settings.enabled&&exhausted?new Date(new Date(d.budget.date+'T00:00:01+08:00').getTime()+86400000):null;
    $('summary').textContent=!d.settings.enabled?'自主运行已暂停。':!d.worker_running?'自主运行已设置，后台工作进程尚未运行。':current?current.agent_name+' · '+(labels[current.status]||current.status):exhausted?'今日调用预算已用完；未完成目标和进度已保留，次日自动继续。':'自主运行中，等待下一个成员或前台任务结束。';
    $('budget').textContent=d.agents.filter(a=>a.enabled).length+' 位启用成员 · '+(local?'服务器本地模型 · 今日已调用 '+d.budget.calls+' 次 · 不调用云模型':'今日模型调用 '+d.budget.calls+'/'+d.settings.daily_model_calls)+' · '+d.agents.filter(a=>a.last_success).length+' 位已完成知识入库';
    $('runtime-policy').textContent=(d.settings.continuous_learning?'各成员持续轮转，完成一轮后继续寻找知识缺口。':'各成员每 '+d.settings.interval_hours+' 小时学习一轮。')+'每轮最多使用 '+d.settings.pages_per_run+' 份原文。'+(local?'使用服务器本地模型，不受云模型每日额度限制；前台任务到来时中断后台推理并保存步骤，空闲后续学。':'每日最多 '+d.settings.daily_model_calls+' 次模型调用，达到预算后次日从原步骤继续。')+'来源不足或核对失败会保存进度并延后重试，避免反复空转。服务重启后恢复进度。';
    const list=document.createDocumentFragment();
    for(const a of d.agents){const active=current?.kind==='learning'&&current.agent_id===a.id?current:null;const budgetWait=budgetResume&&a.enabled&&!active&&!['completed','unchanged'].includes(a.status);const nextAt=budgetWait?new Date(Math.max(budgetResume.getTime(),a.next_at?new Date(a.next_at).getTime():0)):a.next_at;const row=make('article','','agent'),name=make('div',''),content=make('div',''),status=make('div','','status');name.append(make('div',a.name,'agent-name'),make('div',a.scope,'scope'));content.append(make('p',active?.plan?.goal||a.last_goal||'将从本行业的基础实务与知识缺口开始。','goal'));if(a.error&&!active)content.append(make('p',(local&&a.status==='budget_wait'?'上次尝试：':'')+a.error,'error'));status.append(make('div',a.enabled?(local&&a.status==='budget_wait'&&!active?'等待本地模型续学':labels[budgetWait?'budget_wait':active?.status||a.status]||'等待首轮学习'):'该成员已暂停'),make('div','上次成功：'+time(a.last_success)));if(a.enabled&&d.settings.continuous_learning&&['completed','unchanged'].includes(a.status)&&!active)status.append(make('div','下次：持续轮转中'));else if(local&&a.status==='budget_wait'&&!active)status.append(make('div','下次空闲时继续'));else if(nextAt)status.append(make('div','下次：'+time(nextAt)));const b=make('button','安排学习');b.type='button';b.disabled=!d.settings.enabled;b.onclick=()=>action(()=>api('/api/autonomy/run','POST',{agent_id:a.id}));status.append(b);row.append(name,content,status);list.append(row);}
    $('agents').replaceChildren(list);
    const runs=document.createDocumentFragment();
    for(const r of d.runs){const li=make('li',''),b=make('button',r.agent_name+' · '+(r.kind==='code_upgrade'?(labels[r.status]||r.status)+(r.changed_files?.length?'，更新 '+r.changed_files.length+' 项策略':''):(r.kind==='knowledge_refresh'?'知识复查 · '+r.path:(r.title||r.plan?.goal||labels[r.status]||r.status))));b.type='button';b.onclick=()=>action(()=>detail(r.id));li.append(b,make('span',time(r.started_at),'time'),make('p',(labels[r.status]||r.status)+(r.kind==='learning'?' · 原文 '+(r.source_count||0)+' 份 · 更新 '+(r.changed_pages?.length||0)+' 页':'')));if(r.error)li.append(make('p',(d.active_run===r.id?'上次尝试：':'')+r.error,'error'));runs.append(li);}
    if(!d.runs.length)runs.append(make('li','尚无自主运行记录。'));
    $('runs').replaceChildren(runs);
  }
  function settings(changes){return api('/api/autonomy/settings','PUT',{enabled:state.settings.enabled,code_enabled:state.settings.code_enabled,interval_hours:state.settings.interval_hours,daily_model_calls:state.settings.daily_model_calls,pages_per_run:state.settings.pages_per_run,conversation_online:state.settings.conversation_online,conversation_refresh:state.settings.conversation_refresh,...changes});}
  $('online').onchange=()=>action(()=>settings({conversation_online:$('online').checked}));
  $('refresh-knowledge').onchange=()=>action(()=>settings({conversation_refresh:$('refresh-knowledge').checked}));
  $('toggle').onclick=()=>action(()=>settings({enabled:!state.settings.enabled}));
  $('code').onchange=()=>action(()=>settings({code_enabled:$('code').checked}));
  $('run').onclick=()=>action(()=>api('/api/autonomy/run','POST',{}));
  $('continuous').onchange=()=>action(()=>settings({continuous_learning:$('continuous').checked}));
  refresh().catch(e=>{$('summary').textContent=e.message;});
  setInterval(()=>{if(!locked&&!document.hidden)refresh().catch(e=>{$('summary').textContent='状态读取失败：'+e.message;});},7000);
})();
