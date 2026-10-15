import asyncio
import base64
from io import BytesIO
import json
from pathlib import Path
import tempfile
import time
import unittest
import uuid
from fastapi.testclient import TestClient
from federation.app import create_app
from federation.core import FederationStore
from federation.knowledge_lifecycle import (import_text,extract_file,remember,memory_context,create_candidate,
    adopt_candidate,rollback_candidate,wiki_relations,restore_source,source_versions)
from unittest.mock import patch
from federation.knowledge import source_snapshot,knowledge_health
from federation.workflow_tools import profit_calculate,execute
from federation.orchestration import run_orchestration

class LifecycleTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=FederationStore(Path(self.temp.name)/'data');self.store.init()
    def tearDown(self):self.temp.cleanup()

    def test_dedup_update_versions_and_provenance(self):
        first=import_text(self.store,'software','经验.md','原始资料一')
        duplicate=import_text(self.store,'software','重复.md','原始资料一')
        self.assertEqual(duplicate['status'],'duplicate');self.assertEqual(len(self.store.sources('software')),1)
        second=import_text(self.store,'software','经验.md','资料二，更新版本')
        self.assertEqual(second['previous_version'],first['version']);self.assertEqual(first['source_id'],second['source_id'])
        self.assertEqual((self.store.base/'metadata/import-versions/software'/ (first['version']+'.txt')).read_text(),'原始资料一')
        actual=source_snapshot(self.store,'software')[0];self.assertEqual(actual['source_id'],first['source_id']);self.assertEqual(len(actual['source_versions']),2)
        with self.assertRaises(ValueError):import_text(self.store,'software','../x.md','bad')
        with self.assertRaises(ValueError):import_text(self.store,'central','x.md','bad')

    def test_file_parser_pdf_word_empty_and_invalid(self):
        from docx import Document
        doc=Document();doc.add_paragraph('测试文档正文，不是事实案例。');stream=BytesIO();doc.save(stream)
        name,text,proof=extract_file('测试.docx',base64.b64encode(stream.getvalue()).decode())
        self.assertIn('测试文档正文',text);self.assertEqual(name,'测试-docx.md');self.assertEqual(proof['method'],'docx')
        from pypdf import PdfWriter
        writer=PdfWriter();writer.add_blank_page(width=300,height=300);stream=BytesIO();writer.write(stream)
        with self.assertRaisesRegex(ValueError,'OCR'):extract_file('扫描.pdf',base64.b64encode(stream.getvalue()).decode())
        with self.assertRaises(ValueError):extract_file('x.pdf','invalid')
        from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
        page=writer.pages[0]
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
        content=DecodedStreamObject();content.set_data(b'BT /F1 12 Tf 20 200 Td (Evidence text) Tj ET')
        page[NameObject('/Contents')]=writer._add_object(content);stream=BytesIO();writer.write(stream)
        _,text,_=extract_file('正文.pdf',base64.b64encode(stream.getvalue()).decode());self.assertIn('Evidence text',text)

    def test_restore_preserves_source_identity_even_if_other_file_matches(self):
        first=import_text(self.store,'software','资料.md','旧正文')
        second=import_text(self.store,'software','资料.md','新正文')
        import_text(self.store,'software','另一份.md','旧正文')
        with self.assertRaises(ValueError):restore_source(self.store,'software','资料.md',first['version'],first['version'])
        restored=restore_source(self.store,'software','资料.md',first['version'],second['version'])
        self.assertEqual(restored['status'],'updated');self.assertEqual((self.store._source('software')/'资料.md').read_text(),'旧正文')
        self.assertEqual(source_versions(self.store,'software','资料.md')['source_id'],first['source_id'])

    def test_adoption_failure_reverts_only_its_own_wiki_bytes(self):
        before=self.store.page('software','index.md')['sha256']
        message={'id':uuid.uuid4().hex,'role':'assistant','status':'completed','content':'这是一条可核对的测试经验。','model':'controlled-model'}
        candidate=create_candidate(self.store,'software',message)
        with patch('federation.knowledge.record_learning',side_effect=ValueError('受控登记失败')):
            with self.assertRaisesRegex(ValueError,'受控登记失败'):adopt_candidate(self.store,candidate['id'],candidate['review_token'])
        self.assertEqual(self.store.page('software','index.md')['sha256'],before)
        self.assertEqual(self.store.space('software')['knowledge_count'],0)
        adopted=adopt_candidate(self.store,candidate['id'],candidate['review_token'])
        self.assertEqual(adopted['status'],'adopted')
        self.store.publish('software',self.store.review('software')['token'])
        with self.assertRaisesRegex(ValueError,'已发布'):rollback_candidate(self.store,candidate['id'],candidate['review_token'])

    def test_followup_context_accepts_chat_history_and_keeps_review_lightweight(self):
        from federation.template_context import prepare_template_context
        from federation.skill_context import select_skills,prepare_skill_context
        from federation.agent_templates import initialize_standards
        initialize_standards(self.store)
        root=self.store.base/'test-wiki';root.mkdir()
        job={'space':'software','question':'继续分析','template_history':[{'role':'user','content':'Java'}]}
        prepare_template_context(self.store,job,root)
        self.assertEqual(select_skills([{'id':'java','display_name':'Java','keywords':['Java']}],job),[])
        self.assertEqual(prepare_template_context(self.store,{**job,'delegation_phase':'review'},root),([],''))
        self.assertEqual(prepare_skill_context(self.store,{**job,'delegation_phase':'review'},root),([],''))

    def test_candidate_adopt_links_scope_and_safe_rollback(self):
        before=self.store.page('software','index.md')['sha256'];central=self.store.page('central','index.md')['sha256']
        message={'id':uuid.uuid4().hex,'role':'assistant','status':'completed','content':'# 测试案例\n\n来源不足时先明确缺口，再决定是否补查。','model':'controlled-test-model','round_id':uuid.uuid4().hex}
        candidate=create_candidate(self.store,'software',message,'case')
        self.assertEqual(create_candidate(self.store,'software',message,'case')['id'],candidate['id'])
        self.assertEqual(candidate['status'],'awaiting_review');self.assertEqual(self.store.space('software')['knowledge_count'],0)
        with self.assertRaises(ValueError):adopt_candidate(self.store,candidate['id'],'stale')
        receipt=adopt_candidate(self.store,candidate['id'],candidate['review_token'])
        self.assertEqual(receipt['status'],'adopted');self.assertFalse(receipt['published'])
        self.assertIn('用户审核采用',self.store.page('software',receipt['page'])['body'])
        self.assertEqual(self.store.page('central','index.md')['sha256'],central)
        relations=wiki_relations(self.store,'software');self.assertIn('index.md',relations['backlinks'][receipt['page']])
        self.assertEqual(knowledge_health(self.store,'software')['pages'][0].get('space_id','software'),'software')
        rollback_candidate(self.store,candidate['id'],candidate['review_token'])
        self.assertEqual(self.store.page('software','index.md')['sha256'],before)
        self.assertEqual(self.store.space('software')['knowledge_count'],0)

    def test_memory_is_explicit_and_separate(self):
        before=self.store.page('central','index.md')['sha256']
        remember(self.store,'说话直接一点');remember(self.store,'已学完用户任务','learning')
        self.assertEqual(memory_context(self.store)['preferences'],['说话直接一点'])
        remember(self.store,'说话直接',forget=True);self.assertEqual(memory_context(self.store)['preferences'],[])
        self.assertEqual(self.store.page('central','index.md')['sha256'],before)
        with self.assertRaises(ValueError):remember(self.store,'密码：不要存这个')

    def test_profit_math_and_network_permission(self):
        c=profit_calculate({'price':'49','discount':'0.8','units':'100','unit_cost':'12.3','fixed_cost':'2000'})
        self.assertEqual(c['profit'],'690.0');self.assertEqual(c['break_even_units'],'75')
        c=profit_calculate({'price':'10','units':'100','unit_cost':'12','fixed_cost':'20'});self.assertIsNone(c['break_even_units'])
        for v in ('NaN','Infinity','-1','1e100'):
            with self.assertRaises(ValueError):profit_calculate({'price':v,'units':'1','unit_cost':'1','fixed_cost':'1'})
        with self.assertRaises(ValueError):asyncio.run(execute({'network_allowed':False},'web_read',{'url':'https://example.com'}))

class ReplanTest(unittest.IsolatedAsyncioTestCase):
    async def test_actual_gap_causes_bounded_replan(self):
        agents=[{'id':'central','name':'主','parent_id':None,'depth':0},{'id':'software','name':'软件','parent_id':'central','depth':1}]
        room={'delegations':[],'participants':['central']};calls=[];checks=0;results=0
        async def invoke(agent,prompt,phase,task):
            nonlocal checks,results
            calls.append((agent,phase))
            if phase=='plan':return json.dumps({'action':'delegate','tasks':[{'agent_id':'software','task':'分析用户任务'}]})
            if phase=='execute':results+=1;return '用户任务说明' if results==1 else '异常处理补充说明'
            if phase=='summary':return '已覆盖用户任务'+('和异常处理' if results==2 else '')
            if phase=='review':
                checks+=1
                return json.dumps({'complete':checks==2,'gaps':[] if checks==2 else ['缺异常处理'],'tasks':[] if checks==2 else [{'agent_id':'software','task':'只补异常处理'}]})
        result=await run_orchestration(room,agents,'分析用户任务和异常处理',[],invoke,lambda:None,uuid.uuid4().hex,verify_results=True)
        self.assertFalse(result['failed']);self.assertIn('异常处理',result['answer']);self.assertEqual(checks,2);self.assertEqual(results,2)
        self.assertEqual(len(room['delegations'][0]['plan_revisions']),1);self.assertEqual(room['delegations'][0]['phase'],'checked')

    async def test_no_capability_to_close_gap_is_partial(self):
        agents=[{'id':'central','name':'主','parent_id':None,'depth':0}];room={'delegations':[],'participants':[]}
        async def invoke(a,p,phase,t):return json.dumps({'complete':False,'gaps':['没有市场数据'],'tasks':[]}) if phase=='review' else '明确的一般分析'
        result=await run_orchestration(room,agents,'分析市场',[],invoke,lambda:None,uuid.uuid4().hex,verify_results=True)
        self.assertTrue(result['failed']);self.assertIn('一般分析',result['answer']);self.assertIn('没有市场数据',result['answer'])

class CompletionAPITest(unittest.TestCase):
    def test_chat_commands_imports_and_native_answer_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            async def runner(job,store):job.update(answer='这是由测试模型生成的经验，先识别用户任务，再检查证据。',model='controlled-model')
            app=create_app(Path(temp)/'data',runner=runner)
            with TestClient(app) as client:
                room=client.post('/api/chat/primary',json={}).json();rid=room['id']
                result=client.post('/api/chat/rooms/'+rid+'/messages',json={'content':'/记住 说话直接一点'}).json()
                self.assertEqual(result['job']['status'],'completed');self.assertTrue(client.get('/api/user-memory').json()['preferences'])
                imp=client.post('/api/spaces/software/imports',json={'filename':'体验.md','text':'测试资料'});self.assertEqual(imp.status_code,200)
                self.assertEqual(client.post('/api/spaces/software/imports',json={'filename':'另一份.md','text':'测试资料'}).json()['status'],'duplicate')
                status=client.get('/api/agent-system/status').json();self.assertTrue(status['plan_execute']['result_review'])
                job=client.post('/api/chat/rooms/'+rid+'/messages',json={'content':'请直接解释用户任务'}).json()['job']
                for _ in range(100):
                    if client.get('/api/jobs/'+job['id']).json()['status'] not in {'queued','running'}:break
                    time.sleep(.01)
                room=client.get('/api/chat/rooms/'+rid).json();message=next(m for m in reversed(room['messages']) if m.get('model'))
                candidate=client.post('/api/knowledge/candidates',json={'room_id':rid,'message_id':message['id'],'space':'software','kind':'method'}).json()
                adopted=client.post('/api/knowledge/candidates/'+candidate['id']+'/adopt',json={'token':candidate['review_token']})
                self.assertEqual(adopted.status_code,200,adopted.text)
                self.assertEqual(client.get('/api/federation').json()['central']['knowledge_count'],0)
                review=client.get('/api/spaces/software/review').json()
                published=client.post('/api/spaces/software/publish',json={'token':review['token']})
                self.assertEqual(published.status_code,200,published.text)
                saved=next(c for c in client.get('/api/knowledge/candidates').json()['candidates'] if c['id']==candidate['id'])
                self.assertTrue(saved['published'])
