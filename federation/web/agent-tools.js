/** Attachment and service controls. Model text never creates these controls. */
export function initializeTools({getRoom,api,notice}) {
  const drafts=new Map(),form=document.getElementById('ag-message-form'),actions=form?.querySelector('.ag-compose-actions');
  if(!form || !actions)return;
  const make=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
  const button=make('button','＋');button.type='button';button.className='ag-text-button ag-attach-button';button.title='添加文档、图片、音频或视频';button.setAttribute('aria-label','添加文件或图片');
  const input=make('input');input.type='file';input.multiple=true;input.hidden=true;input.accept='.pdf,.doc,.docx,.rtf,.ppt,.pptx,.txt,.md,.json,.csv,.xlsx,.png,.jpg,.jpeg,.webp,.mp3,.wav,.m4a,.aac,.flac,.ogg,.aiff,.aif,.mp4,.mov,.webm,.mkv,.m4v';
  const selected=make('div');selected.className='ag-attachments';selected.setAttribute('aria-label','待发送附件');
  form.prepend(selected);actions.prepend(button,input);
  const settings=make('button','工具与连接');settings.type='button';settings.className='ag-text-button ag-tool-settings';
  document.querySelector('#ag-dialog .ag-header-actions')?.prepend(settings);
  const video=make('a','视频接口');video.href='/video-generation';video.target='_blank';video.rel='noopener';video.className='ag-text-button';
  document.querySelector('#ag-dialog .ag-header-actions')?.prepend(video);
  const dialog=make('dialog');dialog.className='ag-tools-dialog';dialog.setAttribute('aria-label','工具与连接');
  const title=make('h2','工具与连接'),close=make('button','关闭');close.type='button';close.className='ag-text-button';
  close.addEventListener('click',()=>dialog.close());dialog.append(title,close);document.body.append(dialog);
  function renderDraft(){selected.replaceChildren();for(const f of drafts.get(getRoom()?.id) || []){const row=make('span');row.append(make('span',f.name));const remove=make('button','移除');remove.type='button';remove.setAttribute('aria-label','移除附件 '+f.name);remove.addEventListener('click',()=>{drafts.set(f.room_id,(drafts.get(f.room_id)||[]).filter(i=>i.id!==f.id));renderDraft();});row.append(remove);selected.append(row);}}
  async function upload(files){
    const room=getRoom();if(!room?.id || ['running','queued'].includes(room.status)){notice('请等本轮结束后添加附件。',true);return;}
    const rid=room.id;
    if((drafts.get(rid)||[]).length+files.length>8){notice('每轮最多8个附件。',true);return;}
    button.disabled=true;
    try {for(const file of files){
      const media=/\.(mp3|wav|m4a|aac|flac|ogg|aiff|aif|mp4|mov|webm|mkv|m4v)$/i.test(file.name);
      if(file.size>(media?50000000:10000000))throw new Error('文档和图片最多10MB，音视频最多50MB');
      const data=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(String(r.result).split(',')[1]);r.onerror=()=>reject(new Error('文件读取失败'));r.readAsDataURL(file);});
      const result=await api(`/api/chat/rooms/${rid}/files`,{method:'POST',body:JSON.stringify({filename:file.name,data_base64:data})});
      drafts.set(rid,[...(drafts.get(rid)||[]),result]);
    }if(getRoom()?.id===rid)renderDraft();notice('附件已添加，发送问题后由 Agent 读取。');}
    catch(e){notice('附件未添加：'+e.message,true);}finally{button.disabled=false;input.value='';}
  }
  button.addEventListener('click',()=>input.click());input.addEventListener('change',()=>upload([...input.files]));
  form.addEventListener('dragover',e=>{if(e.dataTransfer?.types?.includes('Files')){e.preventDefault();e.dataTransfer.dropEffect='copy';}});
  form.addEventListener('drop',e=>{if(e.dataTransfer?.files?.length){e.preventDefault();void upload([...e.dataTransfer.files]);}});
  const labels={search:'联网搜索',browser:'浏览器可视化浏览',code:'Python 与图表',files:'文档与本地文件',tool_agent:'工具任务模型',vision:'看图',audio:'音频转写',video:'视频分析',image:'生成图片',github:'GitHub',notion:'Notion',gmail:'Gmail'};
  const fields={search:[['provider','搜索服务','select']],vision:[['provider','看图方式','select'],['model','云端模型名称','text'],['base_url','云端接口地址','url'],['api_key','云端 API 密钥','password']],image:[['image_api','图片接口','select'],['model','图片模型','text'],['response_model','Responses 主模型（沿用报告服务时可留空）','text'],['base_url','接口地址','url'],['api_key','API 密钥','password']],github:[['api_key','已授权的 GitHub Token','password']],notion:[['api_key','已授权的 Notion Integration Token','password']],gmail:[['access_token','已授权的只读 Access Token','password'],['client_id','OAuth Client ID','text'],['client_secret','OAuth Client Secret','password'],['refresh_token','已授权的 Refresh Token','password']]};
  function statusText(id,current){
    if(current?.verified)return '已通过实际调用验证';
    if(current?.identity_check?.status==='failed')return '账号验证失败，请检查授权';
    if(current?.last_execution?.status==='failed')return '上次调用失败，请检查服务配置';
    if(current?.identity_verified)return '账号已连接；资料读取尚未验证';
    if(id==='github' && !current?.configured)return '公共仓库可读取；私有仓库需要授权';
    return current?.configured?'已配置，尚未完成实际调用验证':'等待配置或账号授权';
  }
  function validArtifact(artifact,rid){
    return artifact && artifact.room_id===rid && /^[a-f0-9]{32}$/.test(artifact.id) && artifact.url===`/api/chat/rooms/${rid}/files/${artifact.id}`;
  }
  function appendArtifact(block,artifact,rid,preload='metadata'){
    if(!validArtifact(artifact,rid))return;
    const link=make('a',artifact.name);link.href=artifact.url;link.target='_blank';link.rel='noopener noreferrer';link.setAttribute('download',artifact.name);
    if(artifact.kind==='image'){const image=make('img');image.src=artifact.url;image.alt=artifact.name;image.loading='lazy';block.append(image);}
    if(['audio','video'].includes(artifact.kind)){const media=make(artifact.kind);media.src=artifact.url;media.controls=true;media.preload=preload;media.style.maxWidth='100%';media.setAttribute('aria-label',artifact.name);block.append(media);}
    block.append(link);
  }
  const expandedMedia=new Set();
  function mediaName(name){
    return String(name || '未命名文件').replace(/^[a-f0-9]{64}[_-]/i,'').replace(/\.[^.]+$/,'').replace(/_upload_/g,' · ').replace(/_/g,' ');
  }
  function mediaSize(bytes){
    if(!Number.isFinite(bytes) || bytes<0)return '';
    return bytes>=1048576?`${(bytes/1048576).toFixed(1)} MB`:`${Math.max(1,Math.round(bytes/1024))} KB`;
  }
  function appendMedia(block,artifact){
    const row=make('div');row.className='ag-media-row';
    const details=make('details'),summary=make('summary'),label=mediaName(artifact.name),key=`${artifact.room_id}:${artifact.id}`;
    details.className='ag-media-preview';summary.title=artifact.name;
    const heading=make('span',label);heading.className='ag-media-name';
    const metadata=make('span',[artifact.kind==='video'?'视频':'音频',String(artifact.name || '').match(/\.([a-z0-9]+)$/i)?.[1]?.toUpperCase(),mediaSize(artifact.size ?? artifact.bytes)].filter(Boolean).join(' · '));
    metadata.className='ag-media-meta';summary.append(heading,metadata);details.append(summary);
    let player;
    const preview=()=>{
      if(!details.open){expandedMedia.delete(key);player?.pause();return;}
      expandedMedia.add(key);if(player)return;
      player=make(artifact.kind);player.controls=true;player.preload='metadata';player.src=artifact.url;
      player.setAttribute('aria-label',label);if(artifact.kind==='video')player.setAttribute('playsinline','');
      const original=make('p',artifact.name);original.className='ag-media-original';
      details.append(player,original);
    };
    details.addEventListener('toggle',preview);
    if(expandedMedia.has(key)){details.open=true;preview();}
    const download=make('a','下载');download.className='ag-media-download';download.href=artifact.url;
    download.setAttribute('download',artifact.name);download.setAttribute('aria-label',`下载 ${label}`);
    row.append(details,download);block.append(row);
  }
  function removeRepeatedMediaLinks(article,artifacts){
    const urls=new Set(artifacts.filter(a=>['audio','video'].includes(a.kind)).map(a=>a.url));
    const onlyAttachment=node=>{
      const links=[...node.querySelectorAll('a')];
      return links.length===1 && urls.has(links[0].getAttribute('href')) && node.textContent.trim()===links[0].textContent.trim()
        && [...node.querySelectorAll('*')].every(child=>['A','P','BR'].includes(child.tagName));
    };
    // Only replace standalone attachment lists/paragraphs. Prose, citations,
    // source previews and the saved message are left intact.
    for(const list of article.querySelectorAll('.ag-reply-body .ag-message-text ul,.ag-reply-body .ag-message-text ol')){
      if(list.children.length && [...list.children].every(item=>item.tagName==='LI' && onlyAttachment(item)))list.remove();
    }
    for(const p of article.querySelectorAll('.ag-reply-body .ag-message-text > p'))if(onlyAttachment(p))p.remove();
  }
  let version=0;
  let platformTimer=null;
  async function renderPlatforms(container,epoch){
    try{
      const data=await api('/api/platform-mcp/status');if(epoch!==version||!dialog.open)return;
      container.replaceChildren(make('h3','平台 MCP'),make('p','搜索平台内容、读取详情和评论。需要账号时在这里登录；连接状态与实际读取结果分别显示。'));
      let waiting=false;
      for(const platform of data.platforms||[]){
        const row=make('section');row.className='ag-platform-row';row.append(make('h4',platform.name));
        const label=!platform.installed?'尚未安装':!platform.handshake_verified?'已安装，连接尚未验证':platform.credentials_saved?'MCP 已连接；登录信息已保存':platform.id==='bilibili'?'MCP 已连接；部分公开信息可读，受限内容需要登录':platform.id==='douyin-openapi'?'MCP 已连接；等待应用授权':'MCP 已连接；等待登录';
        row.append(make('p',label));
        if(platform.last_read?.status)row.append(make('p',platform.last_read.status==='completed'?'最近一次资料读取成功':'最近一次资料读取未完成，请检查登录或网络。'));
        const login=platform.login||{};
        if(login.message){const message=make('p',login.message);message.setAttribute('role','status');row.append(message);}
        if(platform.id==='douyin-openapi'){row.append(make('p',platform.login_hint));}
        else if(platform.installed){
          const pending=['starting','waiting'].includes(login.state);waiting ||= pending;
          const start=make('button',pending?'等待登录…':platform.credentials_saved?'重新登录':'登录 '+platform.name);start.type='button';start.className='ag-text-button';start.disabled=pending;
          start.addEventListener('click',async()=>{start.disabled=true;try{await api(`/api/platform-mcp/${platform.id}/login`,{method:'POST',body:'{}'});await renderPlatforms(container,epoch);}catch(e){notice(e.message,true);start.disabled=false;}});row.append(start);
          if(platform.id==='bilibili'&&login.state==='waiting'){
            const qr=make('img');qr.src='/api/platform-mcp/bilibili/login-qr';qr.alt='哔哩哔哩登录二维码';qr.style.width='180px';qr.style.maxWidth='100%';qr.style.display='block';row.append(qr);
          }
        }
        if(platform.note)row.append(make('p',platform.note));
        container.append(row);
      }
      clearTimeout(platformTimer);if(waiting)platformTimer=setTimeout(()=>renderPlatforms(container,epoch),2500);
    }catch(e){container.replaceChildren(make('p','平台状态读取失败：'+e.message));}
  }
  async function show(){
    const epoch=++version;dialog.replaceChildren(title,close,make('p','正在读取工具状态…'));if(!dialog.open)dialog.showModal();
    try {
      const status=await api('/api/tool-services/status');if(epoch!==version || !dialog.open)return;
      const onServer=status.files?.runtime_location==='server';
      dialog.replaceChildren(title,close,make('p',onServer?'文件、代码和凭据由服务器保存和处理。第三方连接仅搜索与读取；凭据不进入模型上下文。':'文件和代码在本聊天的隔离目录中处理。第三方连接仅搜索与读取；凭据只保存到本机私有配置，不进入模型上下文。'));
      if(status.server_files?.configured){const scope=make('section');scope.append(make('h3','服务器文件与终端'),make('p',`账号：${status.server_files.account}。可列目录、读取和查找该账号能访问的文件。文件更改与命令先在聊天中展示，确认后执行；不自动提权。`));dialog.append(scope);}
      const platforms=make('section');platforms.setAttribute('aria-label','平台 MCP');platforms.append(make('h3','平台 MCP'),make('p','正在读取平台状态…'));dialog.append(platforms);void renderPlatforms(platforms,epoch);
      for(const id of Object.keys(labels)){
        const current=status[id] || status.connectors?.[id],section=make('section'),heading=make('h3',labels[id]);
        const state=make('p',statusText(id,current));section.append(heading,state);
        if(id==='code'){section.append(make('p','支持 pandas、numpy、matplotlib、openpyxl；禁止网络和宿主文件读写，超时会终止执行。'));dialog.append(section);continue;}
        if(id==='files'){
          section.append(make('p','上传 PDF、Word（含旧版 DOC）、PPT/PPTX、Excel、文本与图片；每份10MB以内。音视频每份50MB以内。长文会分段读取并显示实际范围。'));
          const f=make('form'),label=make('label',onServer?'导入服务器上的文件或目录':'导入指定本地文件或目录'),path=make('input');path.type='text';path.name='local_path';path.placeholder=current?.path_hint||'/Users/…/资料';path.autocomplete='off';label.append(path);f.append(label);
          if(onServer)f.append(make('p','这台电脑上的文件，请用聊天输入框的附件按钮上传。这里填写服务器路径。'));
          const submit=make('button','只读导入'),feedback=make('p');submit.type='submit';feedback.setAttribute('role','status');f.append(submit,feedback,make('p','只复制你指定的资料到当前聊天；目录读取当前层，最多8份。导入后发送问题。'));
          f.addEventListener('submit',async e=>{e.preventDefault();const rid=getRoom()?.id;if(!rid)return;submit.disabled=true;
            try{const r=await api(`/api/chat/rooms/${rid}/local-files`,{method:'POST',body:JSON.stringify({path:path.value.trim()})});const existing=drafts.get(rid)||[];if(existing.length+r.files.length>8)throw new Error('本轮最多8个附件；请先移除部分待发送附件。');drafts.set(rid,[...existing,...r.files]);renderDraft();feedback.textContent=`已添加 ${r.files.length} 份资料。`+(r.skipped_count?`另有 ${r.skipped_count} 项未导入。`:'');}catch(e){feedback.textContent=e.message;}finally{submit.disabled=false;}});
          section.append(f);dialog.append(section);continue;
        }
        if(id==='browser'){section.append(make('p','在独立浏览器中打开公开页面、滚动、翻页、读取正文和截图；支持桌面与手机尺寸。截图保存在当前聊天中，不使用个人登录状态。'));dialog.append(section);continue;}
        if(id==='tool_agent')section.append(make('p','明确要求执行联网工具的任务使用这里的模型。附件任务使用主对话模型及本地读取工具，避免依赖云端工具模型。关闭后联网工具任务也使用原有模型。'));
        if(id==='audio')section.append(make('p','本地 Whisper small 转写，带原文件时间戳与可下载文字。每次最多5分钟，可继续读取；媒体最多2小时。语音识别可能有错字。'));
        if(id==='video')section.append(make('p','本地识别抽样画面，结合音轨转写。每5分钟最多6张画面，按时间线返回；没有逐帧观看，短暂变化可能遗漏。'));
        if(id==='vision')section.append(make('p','本地 Qwen 读取图片及扫描 PDF，离线可用；也可选择已配置的云端服务。PDF按页继续读取，未读页会保留在回执中。'));
        const f=make('form');f.className='ag-service-form';
        const enabled=make('input');enabled.type='checkbox';enabled.name='enabled';enabled.checked=!!current?.enabled;
        const enableLabel=make('label',['github','notion','gmail'].includes(id)?'启用账号授权':'启用此工具');enableLabel.prepend(enabled);f.append(enableLabel);
        if(['vision','image','tool_agent'].includes(id)){
          const reuse=make('input');reuse.type='checkbox';reuse.name='reuse_report';reuse.checked=current?.reuse_report!==false;const label=make('label','沿用已配置的报告模型服务');label.prepend(reuse);f.append(label);
          const responses=make('input');responses.type='checkbox';responses.name='responses_api';responses.checked=!!current?.responses_api;const format=make('label','独立服务使用 Responses 接口');format.prepend(responses);if(id!=='image')f.append(format);
          f.append(make('p','独立服务需要取消勾选后填写接口地址、模型和密钥。看图或画图是否支持以实际调用回执为准。'));
        }
        for(const [name,label,type] of fields[id] || (id==='tool_agent'?fields.vision.filter(f=>f[0]!=='provider'):[])){
          const l=make('label',label),i=make(type==='select'?'select':'input');i.name=name;
          if(type==='select'){const choices=id==='vision'?[['local-ollama','本地 Qwen'],['remote','云端服务']]:name==='image_api'?[['images','Images API'],['responses','Responses 图片工具']]:[['auto','自动选择，失败时切换'],['duckduckgo','DuckDuckGo'],['bing-rss','Bing RSS'],['tavily','Tavily']];for(const [v,t] of choices){const o=make('option',t);o.value=v;i.append(o);}i.value=id==='vision'?(current?.provider==='local-ollama'?'local-ollama':'remote'):current?.[name] || choices[0][0];}
          else {i.type=type;i.autocomplete='off';if(['model','base_url','response_model'].includes(name))i.value=id==='vision' && current?.provider==='local-ollama'?'':current?.[name] || '';}
          l.append(i);f.append(l);
        }
        if(id==='vision'){
          const mode=f.querySelector('[name=provider]');
          const renderMode=()=>{const local=mode.value==='local-ollama';for(const control of f.querySelectorAll('[name=reuse_report],[name=responses_api],[name=model],[name=base_url],[name=api_key]'))control.closest('label').hidden=local;for(const p of f.querySelectorAll('p'))p.hidden=local;};
          mode.addEventListener('change',renderMode);renderMode();
        }
        if(id==='search'){f.append(make('p','自动模式可直接使用公开搜索，无需密钥；入口失败或结果不相关时切换来源。聊天和各行业自主学习共用此设置。'));const l=make('label','Tavily API 密钥（可选，自动模式配置后优先使用）'),i=make('input');i.name='api_key';i.type='password';i.autocomplete='off';l.append(i);f.append(l);}
        const save=make('button','保存配置');save.type='submit';const feedback=make('p');feedback.setAttribute('role','status');f.append(save,feedback);
        f.addEventListener('submit',async e=>{e.preventDefault();save.disabled=true;const data={};for(const control of f.elements){if(control.name)data[control.name]=control.type==='checkbox'?control.checked:control.value.trim();}
          if(id==='vision' && data.provider==='local-ollama')for(const key of Object.keys(data))if(!['enabled','provider'].includes(key))delete data[key];
          try {const updated=await api('/api/tool-services/'+id,{method:'PUT',body:JSON.stringify(data)});state.textContent=statusText(id,updated[id] || updated.connectors?.[id]);feedback.textContent='配置已保存。';for(const i of f.querySelectorAll('input[type=password]'))i.value='';}
          catch(e){feedback.textContent=e.message;}finally{save.disabled=false;}});
        if(['github','notion','gmail'].includes(id)){const check=make('button','验证账号');check.type='button';check.addEventListener('click',async()=>{check.disabled=true;try{const r=await api('/api/tool-services/connectors/'+id+'/check',{method:'POST',body:'{}'});feedback.textContent='账号连接成功：'+(r.identity || id)+'。资料读取以实际工具调用为准。';}catch(e){feedback.textContent=e.message;}finally{try{const updated=await api('/api/tool-services/status');state.textContent=statusText(id,updated.connectors?.[id]);}catch{}check.disabled=false;}});f.append(check);}
        if(id==='image'){
          f.append(make('p','Images API 直接生成图片；Responses 使用主模型调用图片工具。选择后保存配置再测试。测试会向服务发送一次真实生成请求，可能产生费用，不自动重复创建。'));
          const check=make('button','生成测试图片'),preview=make('div');check.type='button';preview.className='ag-file-results';preview.style.width='100%';preview.style.minWidth='0';
          check.addEventListener('click',async()=>{
            const rid=getRoom()?.id;if(!rid){feedback.textContent='请先打开聊天。';return;}
            check.disabled=true;save.disabled=true;feedback.textContent='正在等待图片服务返回…';preview.replaceChildren();
            try{const r=await api('/api/tool-services/image/check',{method:'POST',body:JSON.stringify({room_id:rid})});feedback.textContent=r.status==='completed'?'图片生成成功，可在下方预览和下载。':r.error || '图片服务未完成生成。';for(const artifact of r.artifacts || [])appendArtifact(preview,artifact,rid);}
            catch(e){feedback.textContent=e.message;}
            finally{try{const updated=await api('/api/tool-services/status');state.textContent=statusText(id,updated.image);}catch{}check.disabled=false;save.disabled=false;}
          });f.append(check,preview);
        }
        section.append(f);dialog.append(section);
      }
    }catch(e){if(epoch===version)dialog.append(make('p',e.message));}
  }
  settings.addEventListener('click',show);dialog.addEventListener('close',()=>{version++;clearTimeout(platformTimer);});
  function renderFiles(){
    renderDraft();
    const room=getRoom();if(!room)return;
    for(const article of document.querySelectorAll('#ag-feed article.ag-message')){
      const message=room.messages?.find(m=>m.id===article.dataset.messageId);
      if(!message || article.querySelector('.ag-file-results'))continue;
      const seen=new Set(),artifacts=[...(message.files || []),...(message.workflow?.observations || []).flatMap(o=>o.result?.artifacts || [])].filter(artifact=>{
        if(!validArtifact(artifact,room.id) || seen.has(artifact.id))return false;
        seen.add(artifact.id);return true;
      });
      if(!artifacts.length)continue;
      removeRepeatedMediaLinks(article,artifacts);
      const block=make('div');block.className='ag-file-results';
      for(const artifact of artifacts){
        if([...article.querySelectorAll('.ag-browser-image')].some(image=>image.getAttribute('src')===artifact.url))continue;
        if(['audio','video'].includes(artifact.kind))appendMedia(block,artifact);
        else appendArtifact(block,artifact,room.id);
      }
      article.querySelector('.ag-message-content')?.append(block);
    }
  }
  window.openWikiTools={attachments:rid=>(drafts.get(rid)||[]).map(f=>f.id),sent:(rid,ids)=>{if(ids)drafts.set(rid,(drafts.get(rid)||[]).filter(f=>!ids.includes(f.id)));else drafts.delete(rid);renderDraft();},render:renderFiles,renderDraft};
  renderFiles();
}
