"""Filesystem/approval contracts. Fixtures never use the formal knowledge directory."""
import concurrent.futures
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from federation.core import FederationStore
from federation import server_files as sf
from federation.tool_api import install

class ServerFiles(unittest.TestCase):
    def setUp(self):
        # macOS /tmp resolves under /private, intentionally excluded from export.
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.root=Path(self.temp.name).resolve();self.store=FederationStore(self.root/'fixture-data')
        self.context={'tools_enabled':True,'server_files_allowed':True,'room_id':'a'*32,'job_id':'b'*32}
        self.enabled=patch.object(sf,'require_enabled');self.enabled.start()
        self.file=self.root/'example.txt';self.file.write_text('original')
    def tearDown(self):self.enabled.stop();self.temp.cleanup()
    def call(self,action,**args):return sf.tool(self.store,self.context,action,json.dumps(args))
    def decide(self,request,decision='approve'):return sf.decide(self.store,'a'*32,request['operation_id'],decision)

    def test_read_pagination_binary_and_find(self):
        self.file.write_text('x'*13000)
        first=self.call('read',path=str(self.file));self.assertEqual(first['next_offset'],12000)
        self.assertEqual(len(self.call('read',path=str(self.file),offset=12000)['text']),1000)
        self.file.write_bytes(b'\xff\x00');self.assertEqual(self.call('read',path=str(self.file))['encoding'],'base64')
        self.assertIn(str(self.file),self.call('find',path=str(self.root),pattern='*.txt')['matches'])
        self.assertTrue(self.call('list',path='/')['entries'])

    def test_attachment_keeps_original_and_scopes_download(self):
        from federation.tool_files import get_file
        result=self.call('attach',path=str(self.file))
        item,path=get_file(self.store,'a'*32,result['artifacts'][0]['id'])
        self.assertEqual(path.read_text(),'original');self.assertEqual(self.file.read_text(),'original')
        self.assertIn('/'+('a'*32)+'/',item['url'])
        with self.assertRaises(FileNotFoundError):get_file(self.store,'c'*32,result['artifacts'][0]['id'])

    def test_no_mutation_until_confirmation_and_duplicate_idempotent(self):
        request=self.call('write',path=str(self.file),content='new')
        self.assertEqual(request['status'],'pending_confirmation');self.assertEqual(self.file.read_text(),'original')
        self.assertEqual(request['operation_id'],self.call('write',path=str(self.file),content='new')['operation_id'])
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.decide(request),range(2)))
        self.assertTrue(all(x['status']=='completed' for x in results));self.assertEqual(self.file.read_text(),'new')
        self.file.write_text('later');self.decide(request);self.assertEqual(self.file.read_text(),'later')

    def test_default_discovery_and_media_search_use_actual_roots(self):
        video=self.root/'upload.MP4';video.write_bytes(b'video')
        nested=self.root/'nested';nested.mkdir();(nested/'second.mov').write_bytes(b'video2')
        hidden=self.root/'.secret';hidden.mkdir();(hidden/'hidden.mp4').write_bytes(b'private')
        deps=self.root/'node_modules';deps.mkdir();(deps/'fixture.mp4').write_bytes(b'fixture')
        (self.root/'link.mp4').symlink_to(video)
        with patch.object(sf,'_search_roots',return_value=[self.root]):
            discovery=self.call('discover')
            self.assertEqual(discovery['roots'][0]['path'],str(self.root))
            result=self.call('find',kind='video')
        self.assertEqual(set(result['matches']),{str(video),str(nested/'second.mov')})
        self.assertFalse(result['truncated']);self.assertEqual(result['skipped_directories'],2)
        self.assertEqual(len(result['entries']),2)
        self.assertTrue(all('modified' in row and 'bytes' in row for row in result['entries']))
        with patch.object(sf.Path,'home',return_value=self.root):
            self.assertEqual(self.call('list')['path'],str(self.root))
        self.assertEqual(self.call('find',path=str(deps),kind='video')['matches'],[str(deps/'fixture.mp4')])
        with self.assertRaises(ValueError):self.call('find',kind='shell')
        missing=self.call('find',path=str(self.root/'missing'))
        self.assertTrue(missing['errors']);self.assertEqual(missing['matches'],[])

    def test_attach_returns_room_artifact_and_preserves_source(self):
        from federation.tool_files import get_file
        before=self.file.read_bytes()
        result=self.call('attach',path=str(self.file))
        artifact=result['artifacts'][0]
        self.assertEqual(artifact['room_id'],self.context['room_id'])
        self.assertTrue(artifact['url'].startswith('/api/chat/rooms/'+self.context['room_id']+'/files/'))
        self.assertEqual(get_file(self.store,self.context['room_id'],artifact['id'])[1].read_bytes(),before)
        self.assertEqual(self.file.read_bytes(),before)
        self.assertEqual(sf.list_operations(self.store,self.context['room_id']),[])
        with self.assertRaises((ValueError,OSError)):
            get_file(self.store,'c'*32,artifact['id'])
        with self.assertRaises(ValueError):
            sf.tool(self.store,{**self.context,'server_files_allowed':False},'attach',json.dumps({'path':str(self.file)}))

    def test_attach_rejects_private_symlink_special_and_oversize(self):
        secret=self.root/'private';secret.mkdir();(secret/'account.txt').write_text('secret')
        with self.assertRaises(ValueError):self.call('attach',path=str(secret/'account.txt'))
        link=self.root/'link.txt';link.symlink_to(self.file)
        with self.assertRaises(OSError):self.call('attach',path=str(link))
        ancestor=self.root/'alias';ancestor.symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(OSError):self.call('attach',path=str(ancestor/'example.txt'))
        pipe=self.root/'pipe.txt';os.mkfifo(pipe)
        with self.assertRaises(ValueError):self.call('attach',path=str(pipe))
        large=self.root/'large.mp4'
        with large.open('wb') as stream:stream.truncate(50_000_001)
        with self.assertRaises(ValueError):self.call('attach',path=str(large))

    def test_reject_delete_and_overwrite(self):
        for action,args in [('delete',{}),('write',{'content':'bad'})]:
            request=self.call(action,path=str(self.file),**args)
            self.assertEqual(self.decide(request,'reject')['status'],'rejected')
            self.assertEqual(self.decide(request)['status'],'rejected')
            self.assertEqual(self.file.read_text(),'original')

    def test_stale_file_directory_and_new_destination(self):
        request=self.call('delete',path=str(self.file));self.file.write_text('changed')
        self.assertEqual(self.decide(request)['status'],'stale');self.assertTrue(self.file.exists())
        directory=self.root/'folder';directory.mkdir();child=directory/'x';child.write_text('a')
        request=self.call('delete',path=str(directory));child.write_text('b')
        self.assertEqual(self.decide(request)['status'],'stale');self.assertTrue(child.exists())
        target=self.root/'created';request=self.call('write',path=str(target),content='model')
        target.write_text('human');self.assertEqual(self.decide(request)['status'],'stale')
        self.assertEqual(target.read_text(),'human')

    def test_move_copy_mkdir_delete(self):
        folder=self.root/'newfolder';self.assertFalse(folder.exists())
        self.decide(self.call('mkdir',path=str(folder)));self.assertTrue(folder.is_dir())
        dest=folder/'copy.txt';self.decide(self.call('copy',path=str(self.file),destination=str(dest)))
        self.assertEqual(dest.read_text(),'original')
        moved=folder/'moved.txt';self.decide(self.call('move',path=str(dest),destination=str(moved)))
        self.assertFalse(dest.exists());self.assertEqual(moved.read_text(),'original')
        self.decide(self.call('delete',path=str(folder)));self.assertFalse(folder.exists())

    def test_scope_expiry_forged_approval_and_symlink(self):
        with self.assertRaises(ValueError):sf.tool(self.store,{**self.context,'server_files_allowed':False},'read',json.dumps({'path':str(self.file)}))
        with self.assertRaises(ValueError):self.call('approve',operation_id='a'*32)
        with self.assertRaises(ValueError):self.call('delete',path=str(self.file),approved=True)
        link=self.root/'link';link.symlink_to(self.file)
        with self.assertRaises(ValueError):self.call('delete',path=str(link))
        self.assertEqual(self.call('read',path=str(link))['text'],'original')
        request=self.call('delete',path=str(self.file))
        with self.assertRaises(ValueError):sf.decide(self.store,'c'*32,request['operation_id'],'approve')
        with patch('federation.server_files.time.time',return_value=10**12):self.assertEqual(self.decide(request)['status'],'expired')
        self.assertTrue(self.file.exists())

    def test_special_files_and_relative_paths_denied(self):
        with self.assertRaises(ValueError):self.call('read',path='example.txt')
        fifo=self.root/'pipe';os.mkfifo(fifo)
        with self.assertRaises(ValueError):self.call('read',path=str(fifo))
        with self.assertRaises(ValueError):self.call('write',path=str(fifo),content='x')

    def test_lost_executor_never_replays(self):
        request=self.call('delete',path=str(self.file))
        path=sf._root(self.store)/(request['operation_id']+'.json')
        item=json.loads(path.read_text());item.update(status='running',executor={'pid':999999999,'start':'0'});sf._save(path,item)
        self.assertEqual(sf.list_operations(self.store,'a'*32)[0]['status'],'interrupted')
        self.assertEqual(self.decide(request)['status'],'interrupted');self.assertTrue(self.file.exists())

    def test_stream_accepts_pending_and_real_server_receipts(self):
        from federation.chat_stream import ReplyStreams
        hub=ReplyStreams(self.root/'stream');rid='a'*32;jid='b'*32;hub.start(rid,jid)
        event={'origin':'host_tool','protocol':'responses','name':'server_files','call_id':'file-call','target':'write /tmp/fixture'}
        hub.native_event(rid,jid,{**event,'type':'agent.tool.started'})
        hub.native_event(rid,jid,{**event,'type':'agent.tool.completed','status':'pending_confirmation','output_sha256':'c'*64,'elapsed_ms':10})
        self.assertEqual(hub.snapshot(rid,jid)['operations'][0]['status'],'pending_confirmation')

    def test_api_requires_human_origin_header_and_room_scope(self):
        app=FastAPI()
        class Chat:
            def get_room(self,rid):return {'id':rid}
        install(app,self.store,Chat(),lambda:None)
        request=self.call('delete',path=str(self.file))
        url=f"/api/chat/rooms/{'a'*32}/server-operations/{request['operation_id']}/decision"
        with TestClient(app) as client:
            for headers in [{},{'Origin':'http://evil.example','X-Weiming-Confirm':'server-operation'},{'Origin':'http://testserver'}]:
                self.assertEqual(client.post(url,json={'decision':'approve'},headers=headers).status_code,403)
            self.assertTrue(self.file.exists())
            result=client.post(url,json={'decision':'reject'},headers={'Origin':'http://testserver','X-Weiming-Confirm':'server-operation'})
            self.assertEqual(result.json()['status'],'rejected');self.assertTrue(self.file.exists())
            self.assertEqual(len(client.get(f"/api/chat/rooms/{'a'*32}/server-operations").json()['operations']),1)

    def test_media_download_allows_only_same_origin_playback(self):
        from federation.tool_files import put_file
        app=FastAPI()
        class Chat:
            def get_room(self,rid):return {'id':rid}
        install(app,self.store,Chat(),lambda:None)
        video=put_file(self.store,'a'*32,'fixture.mp4',b'media fixture')
        text=put_file(self.store,'a'*32,'fixture.txt',b'text fixture')
        with TestClient(app) as client:
            response=client.get(video['url'])
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.headers['content-security-policy'],"default-src 'none'; media-src 'self'")
            self.assertEqual(response.headers['x-content-type-options'],'nosniff')
            self.assertEqual(response.headers['content-type'],'video/mp4')
            self.assertEqual(client.get(text['url']).headers['content-security-policy'],"default-src 'none'")

    @unittest.skipUnless(sys.platform=='linux','Real Linux command wrapper')
    def test_command_confirm_output_timeout_and_no_elevation(self):
        target=self.root/'command.txt'
        request=self.call('exec',command=f"printf ok > '{target}'; id -un",cwd=str(self.root),timeout=5)
        self.assertFalse(target.exists())
        result=self.decide(request);self.assertEqual(result['status'],'completed');self.assertEqual(target.read_text(),'ok')
        request=self.call('exec',command='sleep 10',cwd=str(self.root),timeout=1)
        self.assertEqual(self.decide(request)['result']['stop_reason'],'timeout')
        request=self.call('exec',command='yes long-output',cwd=str(self.root),timeout=5)
        self.assertEqual(self.decide(request)['result']['stop_reason'],'output_limit')
        request=self.call('exec',command="cat /proc/self/status | sed -n '/NoNewPrivs/p'",cwd=str(self.root),timeout=5)
        self.assertIn('1',self.decide(request)['result']['output'])

if __name__=='__main__':unittest.main()
