/* Connection settings and receipts; prompts are submitted from chat. */
const $=id=>document.getElementById(id);
const make=(tag,text)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;return node;};
let config=null,timer=null;
async function api(path,options={}){
  const response=await fetch('/api/video-generation/'+path,{...options,headers:{'Content-Type':'application/json'}});
  const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'请求未完成');return data;
}
function showConfig(current){
  config=current;$('enabled').checked=current.enabled;$('base-url').value=current.base_url;
  $('key-state').textContent=current.has_api_key?'服务器已保存 API Key；留空保留原值。':'未配置 API Key；接口无需鉴权时可留空。';
  $('default-workflow').replaceChildren();
  for(const item of current.workflows.filter(item=>!item.image_required && item.name.endsWith('_server_upload'))){
    const option=make('option',item.label);option.value=item.name;$('default-workflow').append(option);
  }
  $('default-workflow').value=current.default_workflow;
  if(!$('default-workflow').value)$('default-workflow').value='reference_4step_sla_server_upload';
  $('page-status').textContent=current.enabled?'已启用。在对话中选择“生成视频”后发送描述即可。':current.configured?'视频接口已关闭。启用并保存后，可从对话发送提示词。':'尚未配置生成服务地址。保存连接配置后，可从对话发送提示词。';
  if(!current.configured)$('connection').open=true;
}
$('connection-form').addEventListener('submit',async event=>{
  event.preventDefault();$('save-config').disabled=true;
  try{
    showConfig(await api('config',{method:'PUT',body:JSON.stringify({enabled:$('enabled').checked,base_url:$('base-url').value.trim(),api_key:$('api-key').value.trim(),clear_api_key:$('clear-key').checked,default_workflow:$('default-workflow').value})}));
    $('api-key').value='';$('clear-key').checked=false;$('config-status').textContent='配置已保存。返回对话后选择“生成视频”即可使用。';
  }catch(error){$('config-status').textContent=error.message;}finally{$('save-config').disabled=false;}
});
const states={submitting:'提交中',submitted:'已提交',rejected:'提交被拒绝',submission_unknown:'提交结果待核对'};
async function refresh(){
  clearTimeout(timer);
  try{
    const data=await api('jobs');$('job-list').replaceChildren();
    if(!data.jobs.length)$('job-list').append(make('p','还没有提交记录。'));
    for(const job of data.jobs){
      const article=make('article');article.className='job';
      article.append(make('h3',(states[job.status]||'待核对')+' · '+(config?.workflows.find(item=>item.name===job.workflow)?.label||job.workflow)));
      const meta=make('p',new Date(job.created_at).toLocaleString('zh-CN')+' · 请求 '+job.id);meta.className='meta';article.append(meta,make('p',job.parameters.prompt),make('p',job.message));
      if(job.receipt?.promptId)article.append(make('p','外部任务 ID：'+job.receipt.promptId));
      const details=make('details');details.append(make('summary','查看实际请求与回执'),make('pre',JSON.stringify({parameters:job.parameters,images:job.images,receipt:job.receipt},null,2)));article.append(details);$('job-list').append(article);
    }
    if(data.jobs.some(job=>job.status==='submitting'))timer=setTimeout(refresh,2000);
  }catch(error){$('job-list').replaceChildren(make('p','记录读取失败：'+error.message));}
}
$('refresh-jobs').addEventListener('click',refresh);
window.addEventListener('pagehide',()=>clearTimeout(timer));
(async()=>{try{showConfig(await api('config'));await refresh();}catch(error){$('page-status').textContent='配置读取失败：'+error.message;}})();
