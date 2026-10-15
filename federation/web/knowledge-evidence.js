(() => {
  'use strict';
  const $=id=>document.getElementById(id), state={space:null,page:null,pages:[],data:null,revision:0,drafts:new Map()};
  const make=(tag,text)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;return node;};
  const labels={current:'版本一致',review_due:'需复查',stale:'来源或知识页已变化',pending:'含义待核对',approved:'用户已核对',rejected:'用户已否定',unchanged:'正文未变',changed:'正文有变化',unavailable:'本次未能读取'};
  async function api(path,body){const response=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'操作失败，请检查输入');return data;}
  const root=()=>`/api/spaces/${encodeURIComponent(state.space)}/evidence`;
  function notice(text,error=false){$('status').textContent=text;$('status').classList.toggle('error',error);}
  function safeURL(value){try{const url=new URL(value);return ['http:','https:'].includes(url.protocol)&&!url.username&&!url.password?url.href:null;}catch{return null;}}
  function link(label,url){const href=safeURL(url),node=make(href?'a':'span',label);if(href){node.href=href;node.target='_blank';node.rel='noopener noreferrer';}return node;}
  async function action(button,work){button.disabled=true;try{await work();}catch(error){notice(error.message,true);}finally{button.disabled=false;}}
  function button(label,work){const node=make('button',label);node.type='button';node.addEventListener('click',()=>action(node,work));return node;}
  function saveDraft(){if(state.space&&state.page)state.drafts.set(state.space+':'+state.page.path,{body:$('revision-body').value,text:$('claim-text').value,quote:$('claim-quote').value,kind:$('claim-kind').value,document:$('claim-document').value});}
  function renderPages(){const term=$('filter').value.trim().toLowerCase();$('pages').replaceChildren(...state.pages.filter(p=>(p.title+' '+p.path).toLowerCase().includes(term)).map(page=>{
    const node=button(page.title||page.path,async()=>{saveDraft();state.page=page;renderPages();renderPage();});node.setAttribute('aria-current',String(page.path===state.page?.path));
    const count=state.data.claims.filter(c=>c.path===page.path).length,meta=make('span',`${count} 条原文标注`);meta.className='count';node.append(meta);return node;
  }));}
  function renderPage(){const page=state.page;$('page-title').textContent=page?.title||'选择一篇知识页';$('page-body').textContent=page?.body||'';$('claim-editor').hidden=!page;$('page-preview').hidden=!page;
    const draft=state.drafts.get(state.space+':'+page?.path);$('revision-editor').hidden=!page||state.space==='central';$('revision-body').value=draft?.body??page?.body??'';
    $('claim-text').value=draft?.text||'';$('claim-quote').value=draft?.quote||'';$('claim-kind').value=draft?.kind||'fact';if(draft?.document && state.data.documents.some(d=>d.id===draft.document))$('claim-document').value=draft.document;
    $('document-preview').hidden=true;
    const claims=state.data.claims.filter(c=>c.path===page?.path);$('page-state').textContent=page?`${page.path} · ${claims.length} 条结论标注`:'导入并整理资料后，可以在这里给结论补原文依据。';
    $('claims').replaceChildren(...(claims.length?claims.map(claim=>{
      const section=make('section');section.className='claim';const status=make('p',`${claim.kind==='inference'?'整理者推断':'来源事实'} · ${labels[claim.semantic_review]} · ${labels[claim.status]}`);status.className='claim-state';section.append(status,make('p',claim.text));
      for(const ref of claim.references){section.append(link(ref.title||'原文',ref.url),make('blockquote',ref.quote));const meta=make('p',`原文第 ${ref.start_line}—${ref.end_line} 行 · ${ref.freshness==='online_checked'?'已比对网页正文':ref.freshness==='local_only'?'仅核对本地归档':'来源时效待复查'}`);meta.className='muted';section.append(meta);}
      const actions=make('div');actions.className='actions';
      if(!claim.superseded_by && claim.status!=='stale' && claim.semantic_review==='pending')for(const [decision,title] of [['approved','我已核对原文与结论的含义'],['rejected','原文不能支持这个结论']])actions.append(button(title,async()=>{const space=state.space;await api(root()+`/claims/${claim.id}/review`,{token:claim.review_token,decision});if(space!==state.space)return;await load();notice('已保存你对这个版本的核对结果。');}));
      if(claim.superseded_by)actions.append(make('p','已由本页的新标注替代，旧原文与核对历史继续保留。'));
      else if(claim.status==='stale' || claim.semantic_review==='rejected'){
        actions.append(make('p','请对照原文重新标注；新标注核对后，可以替代这条旧记录。'));
        const replacements=claims.filter(c=>c.id!==claim.id&&!c.superseded_by&&c.status==='current'&&c.semantic_review==='approved');
        if(replacements.length){const select=make('select');select.setAttribute('aria-label','替代这条旧记录的新标注');select.append(...replacements.map(c=>{const option=make('option',c.text.slice(0,80));option.value=c.id;return option;}));actions.append(select,button('采用新标注，保留旧记录',async()=>{const replacement=replacements.find(c=>c.id===select.value),revision=state.revision;await api(root()+`/claims/${claim.id}/supersede`,{token:claim.review_token,replacement_id:replacement.id,replacement_token:replacement.review_token});if(revision!==state.revision)return;await load();notice('已采用新标注；旧记录已从待处理队列移出，历史仍可查看。');}));}
      }
      section.append(actions);return section;
    }):[make('p','这页还没有逐条原文标注。可以展开下面的表单补充。')]));
  }
  function renderDocuments(){const docs=state.data.documents;$('claim-document').replaceChildren(...docs.map(doc=>{const option=make('option',doc.title);option.value=doc.id;return option;}));
    $('documents').replaceChildren(...(docs.length?docs.map(doc=>{
      const section=make('section');section.className='source';section.append(make('h3',doc.title),link(doc.url||'本地原文',doc.url));const check=doc.pending_change||doc.last_check;
      const meta=make('p',check?`${labels[check.status]||check.status} · ${check.scope==='online'?'网页正文比对':'本地版本核对'} · ${check.checked_at}`:'已保存原文；核验时间未登记');meta.className='muted';section.append(meta);
      const actions=make('div');actions.className='actions';actions.append(button('查看归档原文',async()=>{const result=await api(root()+`/documents/${doc.id}`);let pre=section.querySelector('pre');if(!pre){pre=make('pre');section.append(pre);}pre.textContent=result.text;pre.hidden=false;}));
      for(const online of doc.url?[false,true]:[false])actions.append(button(online?'比对网页正文':'核对本地归档',async()=>{const space=state.space,revision=state.revision;notice(online?'正在读取公开网页并比对正文…':'正在核对原文归档…');const result=await api(root()+`/documents/${doc.id}/check`,{expected_version:doc.version,online});if(space!==state.space||revision!==state.revision)return;await load();notice(`${labels[result.status]}；关联 ${result.affected_pages.length} 篇知识页。${result.note}`);}));
      section.append(actions);
      if(check?.status==='changed'){const affected=state.data.claims.filter(c=>c.references.some(r=>r.document_id===doc.id)).map(c=>c.path);section.append(make('p',`待修订页面：${[...new Set(affected)].join('、')||'尚未标注关联页面'}`));const details=make('details');details.append(make('summary','查看本次原文差异'),make('pre',check.diff||'无可展示差异'));const adopt=button('已核对差异，采用新原文版本',async()=>{const revision=state.revision;await api(root()+`/documents/${doc.id}/adopt`,{expected_version:doc.version,check_id:check.id});if(revision!==state.revision)return;await load();notice('已采用新原文，旧版继续保留；关联知识页和结论仍需修订审核。');});details.append(adopt);section.append(details);}
      if(doc.pending_change && doc.last_check?.id!==doc.pending_change.id)section.append(make('p',`最近一次核对：${labels[doc.last_check.status]||doc.last_check.status}；此前发现的网页变化仍待处理。`));
      if(doc.last_check?.error)section.append(make('p',doc.last_check.error));return section;
    }):[make('p','还没有原文归档。添加资料正文后，再给知识页标注引用。')]));
  }
  async function load(){saveDraft();const space=$('space').value,revision=++state.revision;state.space=space;notice('正在读取知识页、原文与复查记录…');const [pages,data]=await Promise.all([api(`/api/spaces/${encodeURIComponent(space)}/pages`),api(root())]);if(revision!==state.revision)return;
    state.pages=pages.pages.filter(p=>!['index.md','quickstart.md','INSTRUCTIONS.md','_发布说明.md'].includes(p.path.split('/').at(-1))&&!p.path.split('/').some(part=>part.startsWith('.')||part.startsWith('_agent_')));state.data=data;const old=state.page?.path;state.page=state.pages.find(p=>p.path===old)||state.pages.find(p=>data.claims.some(c=>c.path===p.path))||state.pages[0]||null;
    $('summary').textContent=`${state.pages.length} 篇知识页 · ${data.summary.documents} 份原文 · ${data.summary.claims} 条结论 · ${data.summary.pending} 条待处理`;renderPages();renderDocuments();renderPage();notice('已读取当前记录。原文匹配后仍需核对结论含义。');
  }
  $('reload').addEventListener('click',()=>action($('reload'),load));$('space').addEventListener('change',()=>{saveDraft();state.page=null;$('claim-text').value='';$('claim-quote').value='';$('document-preview').hidden=true;load().catch(e=>notice(e.message,true));});$('filter').addEventListener('input',renderPages);
  $('read-document').addEventListener('click',()=>action($('read-document'),async()=>{const revision=state.revision,id=$('claim-document').value;const doc=await api(root()+`/documents/${encodeURIComponent(id)}`);if(revision!==state.revision||id!==$('claim-document').value)return;$('document-preview').textContent=doc.text;$('document-preview').hidden=false;}));
  $('claim-form').addEventListener('submit',event=>{event.preventDefault();action(event.submitter,async()=>{const doc=state.data.documents.find(d=>d.id===$('claim-document').value);if(!doc||!state.page)throw new Error('先选择知识页和原文');const revision=state.revision;await api(root()+'/claims',{path:state.page.path,page_version:state.page.sha256,text:$('claim-text').value,kind:$('claim-kind').value,references:[{document_id:doc.id,version:doc.version,quote:$('claim-quote').value}]});if(revision!==state.revision)return;await load();notice('已保存原文匹配标注，含义仍待你核对。');});});
  $('revision-form').addEventListener('submit',event=>{event.preventDefault();action(event.submitter,async()=>{if(!state.page)throw new Error('先选择知识页');const revision=state.revision,key=state.space+':'+state.page.path;const result=await api(root()+'/revisions',{path:state.page.path,expected_version:state.page.sha256,body:$('revision-body').value});if(revision!==state.revision)return;state.drafts.delete(key);$('revision-body').value=result.status==='unchanged'?state.page.body:$('revision-body').value;await load();notice(result.note||'正文未变化。');});});
  $('document-form').addEventListener('submit',event=>{event.preventDefault();action(event.submitter,async()=>{const revision=state.revision;await api(root()+'/documents',{title:$('document-title').value,text:$('document-text').value,url:$('document-url').value||null});if(revision!==state.revision)return;event.target.reset();await load();notice('已保存原文；没有自动批准结论或发布知识。');});});
  api('/api/federation').then(async data=>{const spaces=[data.central,...data.branches];$('space').replaceChildren(...spaces.map(space=>{const option=make('option',space.name);option.value=space.id;return option;}));$('space').value=spaces.find(s=>s.name==='AI 产品思维')?.id||'central';await load();}).catch(error=>notice(error.message,true));
})();
