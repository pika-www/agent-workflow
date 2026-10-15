"""Versioned imports, explicit user memory, and reviewed native-answer candidates."""
import base64
import fcntl
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import uuid
from datetime import datetime
from .core import _now, _write_json, _sha

def _load(store, relative, default):
    path=store._safe(store.base,relative)
    return json.loads(path.read_text()) if path.is_file() else default

def import_text(store, space, filename, text, provenance=None, *, restoring=False):
    store._definition(space)
    if space=='central':raise ValueError('原始资料请放入专业分支，中央接收审核快照')
    if not isinstance(filename,str) or not filename or '/' in filename or '\\' in filename or filename.startswith('.') or Path(filename).suffix.lower() not in {'.md','.txt'}:raise ValueError('资料文件名无效')
    if not isinstance(text,str) or not text.strip() or '\0' in text or len(text.encode())>80000:raise ValueError('资料正文为空或超过80000字节')
    raw=text.encode();version=_sha(raw);root=store._source(space)
    for item in store.sources(space):
        if restoring and item['name']!=filename:continue
        existing=store._safe(root,item['name'])
        if _sha(existing.read_bytes())==version:return {**item,'status':'duplicate','version':version}
    path=store._safe(root,filename);index_path='metadata/imports/'+space+'.json'
    index=_load(store,index_path,{'items':{}})
    old=index['items'].get(filename,{'source_id':'source-'+_sha((space+'\0'+filename).encode())[:24],'versions':[]})
    previous=None
    if path.exists():
        previous=_sha(path.read_bytes());archive=store._safe(store.base,'metadata/import-versions/'+space+'/'+previous+'.txt')
        if not archive.exists():_atomic_text(archive,path.read_bytes())
    _atomic_text(path,raw)
    old.update(name=filename,version=version,updated_at=_now(),provenance=provenance or {'kind':'user_import'})
    old['versions'].append({'version':version,'previous':previous,'at':_now()})
    index['items'][filename]=old;_write_json(store._safe(store.base,index_path),index)
    return {'name':filename,'status':'updated' if previous else 'imported','version':version,'previous_version':previous,'bytes':len(raw),'source_id':old['source_id']}

def _atomic_text(path, raw):
    if path.is_symlink():raise ValueError('拒绝符号链接')
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.parent/('.import-'+uuid.uuid4().hex)
    try:
        fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as f:f.write(raw)
        os.replace(temp,path)
    finally:
        if temp.exists():temp.unlink()

def extract_file(filename, encoded):
    try:raw=base64.b64decode(encoded,validate=True)
    except Exception:raise ValueError('文件编码无效') from None
    if not raw or len(raw)>5_000_000:raise ValueError('文件须小于5MB')
    suffix=Path(filename).suffix.lower()
    if suffix in {'.md','.txt'}:
        try:text=raw.decode('utf-8-sig')
        except UnicodeError:raise ValueError('文本文件须使用UTF-8') from None
    elif suffix in {'.pdf','.docx'}:
        # A private worker bounds pathological document parsing and memory.
        try:
            run=subprocess.run([sys.executable,'-m','federation.document_extract',suffix],input=raw,capture_output=True,timeout=20)
        except subprocess.TimeoutExpired:raise ValueError('文档解析超过20秒，未导入') from None
        if run.returncode:raise ValueError(run.stdout.decode('utf-8',errors='replace')[:200] or '文档解析失败')
        text=run.stdout.decode()
    else:raise ValueError('支持 Markdown、TXT、PDF、Word 文件')
    if not text.strip():raise ValueError('未读到可用正文；扫描件需先做OCR，加密文件需先解密')
    if len(text.encode())>80000:raise ValueError('提取正文超过80000字节，请拆分资料')
    name=filename if suffix in {'.md','.txt'} else Path(filename).stem+'-'+suffix[1:]+'.md'
    return name,text,{'kind':'document_extract','original_name':filename,'original_sha256':_sha(raw),'method':suffix[1:],'extracted_sha256':_sha(text.encode())}

def user_memory(store):
    return _load(store,'metadata/user-memory.json',{'schema_version':1,'preferences':{},'learning':{},'history':[]})

def remember(store, text, category='preferences', forget=False, *, memory_id=None, expected_revision=None, scope='project', expires_at=None):
    lock = store._safe(store.base, 'metadata/user-memory.lock')
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        return _remember(store, text, category, forget, memory_id=memory_id, expected_revision=expected_revision, scope=scope, expires_at=expires_at)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

def _remember(store, text, category='preferences', forget=False, *, memory_id=None, expected_revision=None, scope='project', expires_at=None):
    if category not in {'preferences','learning'} or not text.strip() or len(text)>1000:raise ValueError('记忆内容无效')
    if re.search(r'api[_ -]?key|密钥|密码|sk[-_][A-Za-z0-9]|Bearer\s',text,re.I):raise ValueError('密钥和密码请放私有配置，不能保存为聊天记忆')
    if scope != 'project':store.space(scope)
    if expires_at is not None:
        try:
            if datetime.fromisoformat(expires_at).tzinfo is None:raise ValueError()
        except (ValueError,TypeError):raise ValueError('记忆到期时间须包含时区') from None
    memory=user_memory(store);key=memory_id or _sha(text.strip().encode())[:16]
    old=memory[category].get(key)
    if memory_id and not old:raise ValueError('记忆条目不存在')
    if expected_revision is not None and (old or {}).get('revision',1)!=expected_revision:raise ValueError('记忆版本已变化，请重新读取后修改')
    if forget:
        removed=[k for k,v in memory[category].items() if (k==memory_id if memory_id else text.strip() in v['text'])]
        for k in removed:memory[category].pop(k)
    else:
        versions=list((old or {}).get('versions',[]))
        if old and any(old.get(field) != value for field,value in [('text',text.strip()),('scope',scope),('expires_at',expires_at)]):
            versions.append({'text':old['text'],'scope':old.get('scope','project'),'expires_at':old.get('expires_at'),'revision':old.get('revision',1),'updated_at':old.get('updated_at')})
        memory[category][key]={'text':text.strip(),'origin':'explicit_user_message','updated_at':_now(),
            'scope':scope,'expires_at':expires_at,'revision':old.get('revision',1)+1 if old else 1,'versions':versions}
    memory['history'].append({'operation':'forget' if forget else 'remember','category':category,'key':key,'at':_now()})
    memory['history']=memory['history'][-100:]
    _write_json(store._safe(store.base,'metadata/user-memory.json'),memory)
    return {'status':'forgotten' if forget else 'remembered','category':category,'key':key}

def memory_context(store):
    memory=user_memory(store)
    return {key:[v['text'] for v in memory[key].values()][-12:] for key in ('preferences','learning')}

def wiki_relations(store, space):
    pages=store.pages(space);known={p['path'] for p in pages};edges=[]
    for page in pages:
        for match in re.finditer(r'\]\(([^)#]+\.md)(?:#[^)]*)?\)|\[\[([^\]|]+)(?:\|[^\]]+)?\]\]',page['body']):
            raw=match.group(1) or match.group(2)+( '' if match.group(2).endswith('.md') else '.md')
            if raw.startswith(('http:','https:','/')):continue
            parts=[]
            for part in (PurePosixPath(page['path']).parent/PurePosixPath(raw)).parts:
                if part=='..':
                    if parts:parts.pop()
                    else:break
                elif part!='.':parts.append(part)
            target='/'.join(parts)
            if target in known:edges.append({'source':page['path'],'target':target,'type':'wiki_link'})
    return {'space':space,'edges':edges,'backlinks':{p:[e['source'] for e in edges if e['target']==p] for p in sorted(known)}}

def candidates(store):
    root=store._safe(store.base,'metadata/knowledge-candidates');root.mkdir(parents=True,exist_ok=True)
    return [json.loads(p.read_text()) for p in sorted(root.glob('*.json')) if not p.is_symlink()]

def create_candidate(store, space, message, kind='method'):
    if kind not in {'concept','method','case'}:raise ValueError('经验类型须为概念、方法或案例')
    store._definition(space)
    if space=='central':raise ValueError('经验草稿请先进入专业分支')
    if message.get('role')!='assistant' or message.get('status')!='completed' or not message.get('model'):raise ValueError('只沉淀智能体已完成的真实模型回答')
    body=message['content'];version=_sha(body.encode())
    for previous in candidates(store):
        if previous['space']==space and previous['answer_sha256']==version and previous['status']!='stale':
            try:unchanged=all(store.page(space,p['path'])['sha256']==p['version'] for p in previous['related'])
            except (ValueError,FileNotFoundError):unchanged=False
            if unchanged:return previous
            previous['status']='stale';_write_json(store._safe(store.base,'metadata/knowledge-candidates/'+previous['id']+'.json'),previous)
    identifier=uuid.uuid4().hex
    query=set(re.findall(r'[A-Za-z]{3,}|[\u4e00-\u9fff]{2,4}',body[:2000]))
    related=[]
    for page in store.pages(space):
        if page['path'] in {'index.md','quickstart.md'}:continue
        overlap=len(query & set(re.findall(r'[A-Za-z]{3,}|[\u4e00-\u9fff]{2,4}',page['body'][:2000])))
        if overlap>=2:related.append({'path':page['path'],'version':page['sha256'],'score':overlap})
    related=sorted(related,key=lambda p:-p['score'])[:5]
    record={'id':identifier,'space':space,'kind':kind,'status':'awaiting_review','body':body,'answer_sha256':version,
      'origin':{'message_id':message['id'],'round_id':message.get('round_id'),'model':message['model']},
      'evidence':{'wiki_reads':message.get('wiki_reads',[]),'research':message.get('research',{}),'analysis_run':message.get('analysis_run',{})},
      'related':related,'conflicts':[{'path':p['path'],'status':'needs_comparison','reason':'主题重叠，需核对适用条件与结论是否冲突'} for p in related],
      'created_at':_now(),'review_token':_sha((space+version+json.dumps(related,sort_keys=True)).encode())}
    _write_json(store._safe(store.base,'metadata/knowledge-candidates/'+identifier+'.json'),record);return record

def adopt_candidate(store, identifier, token, resolve_conflicts=False):
    if not re.fullmatch(r'[a-f0-9]{32}',identifier):raise ValueError('经验编号无效')
    relative='metadata/knowledge-candidates/'+identifier+'.json';record=_load(store,relative,None)
    if not record:raise ValueError('经验草稿不存在')
    if record['review_token']!=token:raise ValueError('审核内容已变化，请重新查看')
    if _sha(record['body'].encode())!=record['answer_sha256']:raise ValueError('待采用正文发生变化，请重新沉淀')
    if record['status']=='adopted':return record
    if record['conflicts'] and not resolve_conflicts:raise ValueError('相关经验需核对冲突，确认后才能采用')
    for related in record['related']:
        if store.page(record['space'],related['path'])['sha256']!=related['version']:raise ValueError('关联页面已更新，请重新沉淀并审核')
    folder={'concept':'concepts','method':'methods','case':'cases'}[record['kind']]
    relative_page=folder+'/'+identifier[:12]+'.md';path=store._safe(store._wiki(record['space']),relative_page)
    # This is the actual native answer, retained verbatim; provenance is separate.
    body=record['body']+'\n\n## 来源与采用记录\n\n本页来自智能体回答 '+record['origin']['message_id']+'，由用户审核采用；模型输出不是独立事实证据。\n'
    for source in record['evidence']['research'].get('sources',[]):
        body+='\n- '+source.get('title','来源')+'：'+source['url']+'，版本 '+source.get('sha256','未知')
    if record['related']:body+='\n\n相关经验：'+ '、'.join('['+p['path']+'](../'+p['path']+')' for p in record['related'])+'。\n'
    if path.exists():raise ValueError('目标经验页已存在，请核对未完成的采用记录')
    index=store._safe(store._wiki(record['space']),'index.md');old=index.read_bytes() if index.exists() else '# 知识索引\n'.encode()
    index_existed=index.exists()
    new_index=old+('\n- ['+record['kind']+' · '+identifier[:12]+']('+relative_page+')\n').encode()
    record['index_before_sha256']=_sha(old)
    _atomic_text(store._safe(store.base,'metadata/candidate-backups/'+identifier+'/index.md'),old)
    try:
        _atomic_text(path,body.encode())
        _atomic_text(index,new_index)
        record['index_after_sha256']=_sha(new_index)
        origin=import_text(store,record['space'],'candidate-'+identifier+'.md',record['body'],{'kind':'reviewed_model_answer','answer_sha256':record['answer_sha256'],'model':record['origin']['model'],'message_id':record['origin']['message_id'],'evidence':record['evidence']})
        from .knowledge import record_learning, source_snapshot
        snapshot=[s for s in source_snapshot(store,record['space']) if s['name']==origin['name']]
        record['tracking']=record_learning(store,record['space'],'candidate-'+identifier+'-'+uuid.uuid4().hex,source_versions=snapshot,paths=[relative_page])
        record.update(status='adopted',page=relative_page,page_sha256=_sha(body.encode()),adopted_at=_now(),published=False)
        _write_json(store._safe(store.base,relative),record)
    except BaseException:
        # Revert only bytes written by this attempt. Retain input/evidence archives
        # so a failed adoption never discards the real model answer or audit.
        if index.exists() and _sha(index.read_bytes())==_sha(new_index):
            if index_existed:_atomic_text(index,old)
            else:index.unlink()
        if path.exists() and _sha(path.read_bytes())==_sha(body.encode()):path.unlink()
        raise
    return record

def rollback_candidate(store, identifier, token):
    if not re.fullmatch(r'[a-f0-9]{32}',identifier):raise ValueError('经验编号无效')
    relative='metadata/knowledge-candidates/'+identifier+'.json';record=_load(store,relative,None)
    if not record or record['review_token']!=token:raise ValueError('经验审核版本不匹配')
    if record['status']!='adopted':raise ValueError('该经验尚未采用')
    published=record.get('published') or record.get('page') in store._manifest(record['space']).get('files',{})
    history=store._safe(store.base,'backups/'+record['space'])
    if not published and history.exists():
        published=any(not p.is_symlink() and json.loads(p.read_text()).get('files',{}).get(record['page'])==record['page_sha256'] for p in history.glob('*.manifest.json'))
    if published:raise ValueError('已发布的经验请先按发布版本恢复审核快照')
    page=store._safe(store._wiki(record['space']),record['page']);index=store._safe(store._wiki(record['space']),'index.md')
    if _sha(page.read_bytes())!=record['page_sha256'] or _sha(index.read_bytes())!=record['index_after_sha256']:raise ValueError('采用后页面或索引已被修改，不能覆盖后续工作')
    backup=store._safe(store.base,'metadata/candidate-backups/'+identifier+'/index.md')
    _atomic_text(index,backup.read_bytes());page.unlink()
    record.update(status='rolled_back',rolled_back_at=_now());_write_json(store._safe(store.base,relative),record)
    return record

def mark_published_candidates(store,space,version):
    manifest=store._manifest(space)
    for record in candidates(store):
        if record['space']==space and record['status']=='adopted' and manifest.get('files',{}).get(record.get('page'))==record.get('page_sha256'):
            record.update(published=True,published_version=version)
            _write_json(store._safe(store.base,'metadata/knowledge-candidates/'+record['id']+'.json'),record)

def source_versions(store, space, filename):
    store._safe(store._source(space),filename)
    record=_load(store,'metadata/imports/'+space+'.json',{'items':{}})['items'].get(filename)
    if not record:raise ValueError('没有这份资料的导入版本记录')
    return record

def restore_source(store,space,filename,version,expected_version):
    if not re.fullmatch(r'[a-f0-9]{64}',version):raise ValueError('资料版本无效')
    record=source_versions(store,space,filename);current=store._safe(store._source(space),filename)
    if _sha(current.read_bytes())!=expected_version or record['version']!=expected_version:raise ValueError('资料已更新，请核对当前版本后再恢复')
    if version==expected_version:return {'status':'already_current','version':version}
    if not any(v['version']==version for v in record['versions']):raise ValueError('历史版本不属于这份资料')
    archived=store._safe(store.base,'metadata/import-versions/'+space+'/'+version+'.txt')
    if not archived.exists() or _sha(archived.read_bytes())!=version:raise ValueError('历史版本不存在或内容发生变化')
    result=import_text(store,space,filename,archived.read_text(),{'kind':'restored_import','restored_from':version},restoring=True)
    return {**result,'restored_from':version}
