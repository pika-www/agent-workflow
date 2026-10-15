/** Human decisions stay outside the model tool protocol. Never render tool text as HTML. */
export function initializeServerOperations({getRoom, api, notice}) {
  const form=document.getElementById('ag-message-form');
  if(!form)return;
  const host=document.createElement('section');host.className='ag-server-operations';host.hidden=true;
  host.setAttribute('aria-label','服务器操作确认');form.before(host);
  const statuses={pending_confirmation:'等待你确认',running:'正在执行，请勿重复操作',completed:'已完成',
    failed:'执行失败，请核对是否产生部分更改',interrupted:'执行中断，结果待核对，不会自动重试',rejected:'已拒绝',expired:'确认已过期',stale:'文件已变化，未执行'};
  let previous='',busy=false;
  const make=(tag,text)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e;};
  async function refresh(){
    const rid=getRoom()?.id;if(!rid){host.hidden=true;previous='';return;}
    try{
      const data=await api(`/api/chat/rooms/${rid}/server-operations`);
      if(getRoom()?.id!==rid)return;
      const items=data.operations || [],signature=rid+JSON.stringify(items);
      if(signature===previous)return;previous=signature;host.replaceChildren();host.hidden=!items.length;
      const pending=items.filter(x=>x.status==='pending_confirmation'||x.status==='running');
      const container=make('details');container.open=!!pending.length;
      container.append(make('summary',pending.length?`服务器操作 · ${pending.length} 项待处理`:'服务器操作记录'));
      container.append(make('p','以服务器账号运行。文件更改和命令须逐项确认；拒绝后不会执行。'));
      for(const item of [...pending,...items.filter(x=>!pending.includes(x)).slice(-3).reverse()]){
        const row=make('article');row.dataset.operationId=item.id;
        row.append(make('strong',`${item.label} · ${statuses[item.status] || item.status}`));
        const args=item.arguments;
        row.append(make('p',item.action==='exec'?`账号：${item.account} · 目录：${args.cwd} · 最长 ${args.timeout} 秒`:`路径：${args.path}`));
        if(args.destination)row.append(make('p','目标：'+args.destination));
        if(item.action==='delete' && item.status==='pending_confirmation')row.append(make('p','确认后永久删除此路径，无法在界面撤销；目录操作包含目录内的全部内容。'));
        if(args.command!==undefined||args.content!==undefined)row.append(make('pre',args.command ?? args.content));
        if(item.result)row.append(item.result.output!==undefined?make('pre',item.result.output):make('p',item.result.error || '服务器已完成该操作。'));
        if(item.status==='pending_confirmation'){
          row.append(make('p','有效期至 '+new Date(item.expires_at*1000).toLocaleTimeString()));
          for(const [decision,label] of [['approve','确认执行'],['reject','拒绝']]){
            const button=make('button',label);button.type='button';button.className='ag-text-button';
            button.addEventListener('click',async()=>{
              if(busy)return;busy=true;row.querySelectorAll('button').forEach(b=>b.disabled=true);
              try{
                const response=await fetch(`/api/chat/rooms/${rid}/server-operations/${item.id}/decision`,{
                  method:'POST',headers:{'Content-Type':'application/json','X-Weiming-Confirm':'server-operation'},
                  body:JSON.stringify({decision}),signal:AbortSignal.timeout(75000)});
                const result=await response.json();if(!response.ok)throw new Error(result.detail || '操作未完成');
                notice(statuses[result.status] || result.status);
              }catch(error){notice('确认结果暂未取得，请查看操作记录后再继续：'+error.message,true);}
              finally{busy=false;row.querySelectorAll('button').forEach(b=>b.disabled=false);previous='';await refresh();}
            });row.append(button);
          }
        }
        container.append(row);
      }
      host.append(container);
    }catch(error){if(getRoom()?.id===rid){host.hidden=false;host.textContent='服务器操作记录读取失败：'+error.message;previous='';}}
  }
  void refresh();setInterval(()=>{if(document.visibilityState==='visible')void refresh();},2500);
}
