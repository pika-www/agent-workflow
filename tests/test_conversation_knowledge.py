"""Controlled adjudication, real persistence, source/version and publication boundaries."""
import asyncio
import json
from pathlib import Path
from unittest.mock import patch
import pytest
from federation.core import FederationStore,_write_json,_now
from federation.autonomy import Autonomy,digest,read_json
from federation.conversation_knowledge import policy,enqueue,pending,refresh

OLD='Playwright 定位器只在创建时查找一次 DOM 元素。'
NEW='Playwright 定位器在每次执行动作前重新查找当前 DOM 元素。'
QUOTE='Every time a locator is used for an action, an up-to-date DOM element is located in the page.'

class Lock:
 async def __aenter__(self):return self
 async def __aexit__(self,*args):pass

def setup(tmp_path,verdict='local_outdated',approve=True,publish=True):
 store=FederationStore(tmp_path/'data');store.init();sid='software-testing';path='locator.md'
 body='# 定位器\n\n'+OLD+'\n\n用户的独立备注：保持原样。\n'
 target=store._wiki(sid)/path;target.write_text(body)
 if publish:
  p=store._safe(store.base,'published/'+sid+'/'+path);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(body)
  c=store._safe(store._wiki('central'),sid+'/'+path);c.parent.mkdir(parents=True,exist_ok=True);c.write_text(body)
  _write_json(store.base/'metadata'/ (sid+'.json'),{'files':{path:digest(body)},'knowledge':{'pages':[]}})
 calls=[]
 async def model(store,purpose,payload):
  calls.append(purpose)
  value={'verdict':verdict,'old_quote':OLD,'replacement':NEW,'source_id':'1','source_quote':QUOTE,'reason':'原文明确说明每次操作前重新定位','version_basis':'当前定位器规范明确描述动作前查找，而旧笔记描述创建时一次查找','scope':'Playwright JavaScript Locator','same_scope':True,'primary_source':True} if purpose=='对话知识新旧核对' else {'approved':approve,'old_is_outdated':True,'new_supported':True,'same_scope':True,'primary_source':True,'issues':[] if approve else ['无法证明适用范围相同'],'reason':'独立检查结果'}
  return value,{'model':'controlled-fixture','purpose':purpose}
 manager=Autonomy(store,lambda:True,Lock(),model=model)
 manager.configure({'enabled':True,'conversation_refresh':True,'authorization':'Test-only authorized correction'})
 job={'id':'1'*32,'space':sid,'current_question':'定位器每次操作前会重新查找吗？','tool_policy':{'auto_refresh':True}}
 result={'wiki_input':{'inputs':[{'path':'/'+path,'page_version':digest(body),'text':body}]},'workflow':{'observations':[{'tool':'web_read','result':{'status':'completed','sources':[{'url':'https://playwright.dev/docs/locators','title':'Locators','excerpt':QUOTE,'read_method':'http_text','sha256':digest(QUOTE),'fetched_at':_now()}]}}]}}
 return manager,job,result,target,body,calls

def test_default_online_and_explicit_offline_or_no_write(tmp_path):
 m,j,r,p,b,c=setup(tmp_path)
 assert policy(m.store,'Playwright 的定位器怎么用？')=={'default_online':True,'auto_refresh':True}
 for q in ('不要联网，解释定位器','离线回答','只根据知识库回答','no network please'):
  assert policy(m.store,q)=={'default_online':False,'auto_refresh':False}
 assert policy(m.store,'只分析，不更新知识库')['auto_refresh'] is False
 assert policy(m.store,'联网查证',True)['auto_refresh'] is False

def test_queue_is_idempotent_and_requires_actual_body_and_authorized_write(tmp_path):
 m,j,r,p,b,c=setup(tmp_path)
 ids=enqueue(m,j,r);assert enqueue(m,j,r)==ids;assert len(ids)==1
 assert pending(m)['id']==ids[0]
 r['workflow']['observations'][0]['result']['sources'][0]['read_method']='search_result_snippet'
 assert enqueue(m,{**j,'id':'2'*32},r)==[]
 j['current_question']='不要更新知识库';assert enqueue(m,j,r)==[]

def test_confirmed_revision_updates_matching_snapshots_preserves_history_and_replays_once(tmp_path):
 m,j,r,p,b,c=setup(tmp_path)
 ident=enqueue(m,j,r)[0];run=pending(m);run['error']='previous transient failure';asyncio.run(refresh(m,run))
 assert run['status']=='completed',run
 assert run['error'] is None
 assert OLD not in p.read_text();assert NEW in p.read_text();assert '用户的独立备注：保持原样。' in p.read_text()
 assert p.read_bytes()==(m.store._wiki('central')/'software-testing/locator.md').read_bytes()
 assert p.read_bytes()==(m.store.base/'published/software-testing/locator.md').read_bytes()
 assert (m.root/'runs'/ident/'before.md').read_text()==b
 assert len(c)==2
 assert read_json(m.store.base/'metadata/software-testing.json',{})['files']['locator.md']==digest(p.read_bytes())
 asyncio.run(refresh(m,run));assert len(c)==2
 assert read_json(m.root/'runs'/ident/'transaction.json',{})['status']=='committed'
 assert 'changed_quote_only' in (m.store.base/'metadata/knowledge/software-testing.json').read_text()

@pytest.mark.parametrize('verdict',['consistent','different_scope','web_outdated','unrelated'])
def test_differences_do_not_automatically_overwrite_local_knowledge(tmp_path,verdict):
 m,j,r,p,b,c=setup(tmp_path,verdict=verdict);enqueue(m,j,r);run=pending(m)
 asyncio.run(refresh(m,run));assert run['status']=='unchanged';assert p.read_text()==b;assert len(c)==1

def test_independent_reviewer_can_reject_and_requeue(tmp_path):
 m,j,r,p,b,c=setup(tmp_path,approve=False);enqueue(m,j,r);run=pending(m)
 asyncio.run(refresh(m,run));assert run['status']=='retry_pending';assert p.read_text()==b;assert len(c)==2

def test_unquoted_or_nonprimary_evidence_cannot_update(tmp_path):
 m,j,r,p,b,c=setup(tmp_path);model=m.model
 async def invalid(*args):
  value,receipt=await model(*args);value['source_quote']='not present';return value,receipt
 m.model=invalid;enqueue(m,j,r);run=pending(m);asyncio.run(refresh(m,run))
 assert run['status']=='retry_pending';assert p.read_text()==b;assert len(c)==1

def test_concurrent_edit_survives_and_source_tampering_is_detected(tmp_path):
 m,j,r,p,b,c=setup(tmp_path);model=m.model
 async def concurrent(store,purpose,payload):
  value,receipt=await model(store,purpose,payload)
  if purpose=='独立复核知识纠错':p.write_text(b+'人工并发编辑')
  return value,receipt
 m.model=concurrent;enqueue(m,j,r);run=pending(m);asyncio.run(refresh(m,run))
 assert run['status']=='retry_pending';assert p.read_text()==b+'人工并发编辑'
 (m.root/'runs'/run['id']/'source-1.txt').write_text('tampered')
 asyncio.run(refresh(m,run));assert '原文归档已变化' in run['error']

def test_failed_transaction_restores_all_original_bytes(tmp_path):
 m,j,r,p,b,c=setup(tmp_path);enqueue(m,j,r);run=pending(m);original=m.atomic_bytes
 central=m.store._wiki('central')/'software-testing/locator.md'
 failed=False
 def write(path,raw):
  nonlocal failed
  if path==central and not failed:failed=True;raise OSError('controlled disk failure')
  return original(path,raw)
 with patch.object(m,'atomic_bytes',side_effect=write):asyncio.run(refresh(m,run))
 assert run['status']=='retry_pending';assert p.read_text()==b;assert central.read_text()==b
 assert read_json(m.root/'runs'/run['id']/'transaction.json',{})['status']=='rolled_back'

def test_central_read_is_routed_back_to_owning_industry(tmp_path):
 m,j,r,p,b,c=setup(tmp_path);j['space']='central';r['wiki_input']['inputs'][0]['path']='/software-testing/locator.md'
 enqueue(m,j,r);assert pending(m)['agent_id']=='software-testing'

def test_nested_change_is_normalized_but_conflicting_fields_are_rejected():
 from federation.conversation_knowledge import normalize_proposal
 assert normalize_proposal({'verdict':'local_outdated','change':{'old_quote':OLD}})['old_quote']==OLD
 with pytest.raises(ValueError,match='相互矛盾'):
  normalize_proposal({'old_quote':'conflict','change':{'old_quote':OLD}})

def test_both_central_copy_paths_keep_their_lineage_in_one_transaction(tmp_path):
 m,j,r,p,b,c=setup(tmp_path,publish=False)
 relative='autonomous/locator.md'
 p.unlink();p=m.store._safe(m.store._wiki(j['space']),relative);p.parent.mkdir(parents=True);p.write_text(b)
 r['wiki_input']['inputs'][0]['path']='/'+relative
 paths=['software-testing/'+relative,'autonomous/software-testing/locator.md']
 for path in paths:
  central=m.store._safe(m.store._wiki('central'),path);central.parent.mkdir(parents=True,exist_ok=True);central.write_text(b)
 enqueue(m,j,r);run=pending(m);asyncio.run(refresh(m,run))
 assert run['status']=='completed',run
 records=read_json(m.store.base/'metadata/knowledge/central.json',{})
 for path in paths:
  assert (m.store._wiki('central')/path).read_bytes()==p.read_bytes()
  assert records['pages'][path][-1]['version']==digest(p.read_bytes())
 assert len(records['runs'])==2
