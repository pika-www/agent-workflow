import asyncio
import hashlib
import json
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from fastapi.testclient import TestClient
from federation.app import create_app
from federation.chat_stream import ReplyStreams


def checkpoint():
    return {'schema_version':1, 'kind':'consultation', 'fingerprint':'a'*64,
            'preliminary_reply':{'text':'一般建议：先写清要完成的结果。', 'receipt':{'status':'generated','calls':1}}}


def wait(client, job):
    for _ in range(200):
        result=client.get('/api/jobs/'+job).json()
        if result['status'] in {'completed','failed'}: return result
        time.sleep(.01)
    raise AssertionError('fixture job did not finish')


class ReplyRecoveryTests(unittest.TestCase):
    def test_private_journal_preserves_completed_initial_and_partial_output(self):
        with tempfile.TemporaryDirectory() as root:
            room,job=uuid.uuid4().hex,uuid.uuid4().hex
            streams=ReplyStreams(root);streams.start(room,job)
            streams.update(room,job,{'id':'first-answer','title':'初答','text':'一般建议：先写结果。','status':'completed'})
            streams.checkpoint(room,job,checkpoint());streams.progress(room,job,'checking_evidence','比对结论与原文')
            streams.append(room,job,'尚未完成的正文');streams.clear(room,job)
            saved=ReplyStreams(root).load_saved(job)
            self.assertFalse(saved['active']);self.assertEqual(saved['preview']['text'],'尚未完成的正文')
            self.assertEqual(saved['checkpoint'],checkpoint());self.assertEqual(saved['processing_stage']['stage'],'checking_evidence')
            self.assertEqual((Path(root)/(job+'.json')).stat().st_mode & 0o777,0o600)

    def test_hash_corruption_symlink_and_oversized_checkpoint_are_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            room,job=uuid.uuid4().hex,uuid.uuid4().hex
            streams=ReplyStreams(root);streams.start(room,job);path=Path(root)/(job+'.json')
            data=json.loads(path.read_text());data['payload']['room_id']=uuid.uuid4().hex;path.write_text(json.dumps(data))
            self.assertIsNone(streams.load_saved(job))
            path.unlink();outside=Path(root)/'outside';outside.write_text('untouched');path.symlink_to(outside)
            self.assertIsNone(streams.load_saved(job))
            with self.assertRaises(ValueError):streams.checkpoint(room,job,checkpoint())
            self.assertEqual(outside.read_text(),'untouched')
            with self.assertRaises(ValueError):streams.checkpoint(room,job,{**checkpoint(),'preliminary_reply':{'text':'x'*1801,'receipt':{}}})
            with self.assertRaises(ValueError):streams.checkpoint(room,job,{**checkpoint(),'execute':'rm something'})

    def test_startup_restores_interrupted_preview_once_without_model_or_wiki_write(self):
        with tempfile.TemporaryDirectory() as root:
            base=Path(root)/'data';app=create_app(base=base);room=app.state.chat.primary_room();job=uuid.uuid4().hex
            app.state.chat.append_message(room,'user','请解释任务拆解。',round_id=job)
            room.update(status='running',active_job_id=job);app.state.chat.save_room(room)
            (base/'jobs'/(job+'.json')).write_text(json.dumps({'id':job,'action':'chat','space':'central','room_id':room['id'],
                'status':'running','intake_kind':'answer','question':'请解释任务拆解。','created_at':'2026-10-06T00:00:00+00:00'}))
            streams=app.state.reply_streams;streams.start(room['id'],job)
            streams.update(room['id'],job,{'id':'first-answer','title':'初答','text':'一般建议：先定义结果。','status':'completed'})
            streams.checkpoint(room['id'],job,checkpoint());streams.progress(room['id'],job,'checking_evidence','核对原文')
            # A new app reading the same files models a hard exit before clear().
            recovered=create_app(base=base)
            with TestClient(recovered) as client:
                current=client.get('/api/chat/rooms/'+room['id']).json();last=current['messages'][-1]
                self.assertEqual(last['status'],'failed');self.assertEqual(last['recoverable_job_id'],job)
                self.assertEqual(last['interim_replies'][0]['text'],'一般建议：先定义结果。')
                self.assertEqual(current['active_job_id'],None);self.assertEqual(current['task_groups'],[])
                self.assertEqual(client.get('/api/jobs/'+job).json()['status'],'failed')
            again=create_app(base=base)
            self.assertEqual(len(again.state.chat.get_room(room['id'])['messages']),len(current['messages']))
            self.assertEqual(again.state.store.space('central')['knowledge_count'],0)

    def test_failed_reply_resumes_idempotently_with_original_question_and_checkpoint(self):
        with tempfile.TemporaryDirectory() as root:
            turns=[]
            async def runner(turn,store):
                turns.append(dict(turn));streams=app.state.reply_streams
                if len(turns)==1:
                    streams.update(turn['room_id'],turn['parent_job_id'],{'id':'first-answer','title':'初答','text':'一般建议：先定义结果。','status':'completed'})
                    streams.checkpoint(turn['room_id'],turn['parent_job_id'],checkpoint());raise RuntimeError('连接中断')
                self.assertEqual(turn['resume_checkpoint'],checkpoint());turn['answer']='建议按验收标准补充步骤。'
            app=create_app(base=Path(root)/'data',runner=runner)
            with TestClient(app) as client:
                room=client.post('/api/chat/primary',json={}).json();url='/api/chat/rooms/'+room['id']
                sent=client.post(url+'/messages',json={'content':'请解释任务拆解。'}).json();job=sent['job']['id'];self.assertEqual(wait(client,job)['status'],'failed')
                self.assertEqual(client.get(url).json()['messages'][-1]['recoverable_job_id'],job)
                resumed=client.post(url+'/jobs/'+job+'/resume',json={});self.assertEqual(resumed.status_code,200)
                new=resumed.json()['job']['id'];self.assertNotEqual(new,job);self.assertEqual(wait(client,new)['status'],'completed')
                repeated=client.post(url+'/jobs/'+job+'/resume',json={}).json();self.assertEqual(repeated['job']['id'],new)
                current=client.get(url).json();self.assertEqual(len([m for m in current['messages'] if m['role']=='user']),1)
                self.assertEqual(len(turns),2);self.assertEqual(turns[-1]['current_question'],'请解释任务拆解。');self.assertFalse(turns[-1]['network_allowed'])
                self.assertEqual(current['task_groups'],[]);self.assertEqual(current['messages'][-1]['content'],'建议按验收标准补充步骤。')
                other=client.post('/api/chat/rooms',json={'mode':'direct','participants':['central']}).json()
                self.assertEqual(client.post('/api/chat/rooms/'+other['id']+'/jobs/'+job+'/resume',json={}).status_code,404)

    def test_resume_reuses_archived_research_and_excludes_execution_jobs(self):
        with tempfile.TemporaryDirectory() as root:
            reads=[];turns=[]
            async def research(*args):
                reads.append(1);return {'status':'completed','sources':[{'url':'https://example.com/app','title':'公开页','sha256':'a'*64,'excerpt':'公开应用目录提供节点编辑器。'}],'errors':[]}
            async def runner(turn,store):
                turns.append(dict(turn))
                if len(turns)==1:raise RuntimeError('中断')
                turn['answer']='公开页提供应用目录，内部细节尚不能确认。'
            app=create_app(base=Path(root)/'data',runner=runner,researcher=research)
            with TestClient(app) as client:
                room=client.post('/api/chat/primary',json={}).json();url='/api/chat/rooms/'+room['id']
                sent=client.post(url+'/messages',json={'content':'只查询 https://example.com/app，不学习不开发。','research':True}).json();job=sent['job']['id'];wait(client,job)
                resumed=client.post(url+'/jobs/'+job+'/resume',json={}).json();wait(client,resumed['job']['id']);self.assertEqual(len(reads),1)
                current=client.get(url).json();self.assertIn('未重新读取网页',current['messages'][-1]['research']['note'])
                path=Path(root)/'data/jobs'/(job+'.json');original=json.loads(path.read_text());original['dispatch_confirmed']=True;path.write_text(json.dumps(original))
                # Fresh app reads the persisted execution boundary.
            blocked=create_app(base=Path(root)/'data')
            with TestClient(blocked) as client:self.assertEqual(client.post(url+'/jobs/'+job+'/resume',json={}).status_code,409)
