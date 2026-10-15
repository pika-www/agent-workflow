import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import patch,AsyncMock
import pytest
from federation.platform_content import execute,validate
from federation import platform_mcp_registry as registry

@pytest.mark.parametrize('platform,tool,args',[
    ('bilibili','send_comment',{'text':'no'}),('douyin','logout',{}),
    ('douyin-openapi','openapi_request',{'path':'/anything'}),('tieba','delete_run',{}),
    ('tieba','detail',{'post_id':'../../etc/passwd'}),('douyin','get_video_comments',{'aweme_id':'123','count':500}),
    ('douyin-openapi','userinfo',{'token':'not-a-model-parameter'}),
    ('bilibili','search_video',{'keyword':'用户邮箱 user@example.com'}),
])
def test_reject_writes_paths_unbounded_queries_and_credentials(platform,tool,args):
    with pytest.raises(ValueError):validate(platform,tool,args)

def test_missing_login_is_fast_and_does_not_start_process():
    with patch('federation.platform_content.installed',return_value=True),patch('federation.platform_content.credential_present',return_value=False),patch('federation.platform_content.worker',new_callable=AsyncMock) as worker:
        result=asyncio.run(execute('douyin','get_video_comments',{'aweme_id':'123'}))
        assert result['status']=='needs_login';worker.assert_not_called()

def test_expired_login_does_not_block_public_reads_after_restart(tmp_path):
    import os,time
    with patch.object(registry,'RUNTIME',tmp_path):
        path=registry.private_path('bilibili-login-status.json')
        registry.write_private(path,{'state':'waiting'})
        assert registry.login_state('bilibili')['state']=='waiting'
        old=time.time()-421;os.utime(path,(old,old))
        assert registry.login_state('bilibili')['state']=='failed'
        with patch('federation.platform_content.installed',return_value=True),patch('federation.platform_content.credential_present',return_value=False),patch('federation.platform_content.worker',new_callable=AsyncMock,return_value={'status':'completed'}) as worker,patch('federation.platform_content.private_path',registry.private_path):
            result=asyncio.run(execute('bilibili','get_video_info',{'bvid':'BV1xx411c7mD'}))
            assert result['status']=='completed';worker.assert_awaited_once()

def test_parallel_private_receipts_are_atomic(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    path=tmp_path/'receipt.json'
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i:registry.write_private(path,{'value':i,'text':'x'*1000}),range(32)))
    result=json.loads(path.read_text())
    assert result['value'] in range(32) and result['text']=='x'*1000
    assert list(tmp_path.iterdir())==[path]

def test_catalog_separates_install_handshake_login_and_read_proof(tmp_path):
    with patch.object(registry,'RUNTIME',tmp_path):
        env=tmp_path/'envs/bilibili/bin/python';env.parent.mkdir(parents=True);env.touch()
        (tmp_path/'sources/bilibili').mkdir(parents=True)
        registry.write_private(registry.private_path('bilibili.json'),{'sessdata':'PRIVATE-TEST-SECRET'})
        value=registry.catalog('bilibili')['platforms'][0]
        assert value['installed'] and value['credentials_saved']
        assert not value['handshake_verified'] and not value['last_read']
        assert 'PRIVATE-TEST-SECRET' not in json.dumps(value)
        assert 'send_comment' not in value['tools']
        assert registry.private_path('bilibili.json').stat().st_mode & 0o777 == 0o600

def test_offline_host_rejects_platform_access(tmp_path):
    from federation.workflow_tools import execute as host
    with pytest.raises(ValueError,match='未开放'):
        asyncio.run(host({'base':str(tmp_path),'room_id':'a'*32,'tools_enabled':True,'network_allowed':False},'platform_tools',{'platform':'bilibili'}))

def test_login_api_blocks_cross_origin_and_unknown_provider(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from federation.tool_api import install
    from types import SimpleNamespace
    app=FastAPI();install(app,None,SimpleNamespace(get_room=lambda _:{}),lambda:None)
    client=TestClient(app)
    with patch('subprocess.Popen') as spawn:
        assert client.post('/api/platform-mcp/bilibili/login',headers={'Origin':'https://unrelated.example'}).status_code==403
        assert client.post('/api/platform-mcp/arbitrary/login').status_code==400
        spawn.assert_not_called()
def test_server_browser_environment_does_not_inherit_unrelated_secrets(monkeypatch):
    from federation.platform_mcp_registry import runtime_environment, ROOT
    monkeypatch.setenv('WEIMING_CHROME_PATH', '/operator/chrome')
    monkeypatch.setenv('LD_LIBRARY_PATH', '/operator/libs')
    monkeypatch.setenv('SAMPLE_PRIVATE_TOKEN', 'must-not-inherit')
    monkeypatch.setenv('PYTHONPATH', '/unreviewed')
    env = runtime_environment()
    assert env['PYTHONPATH'] == str(ROOT / 'deploy/server/playwright_override')
    assert env['WEIMING_CHROME_PATH'] == '/operator/chrome'
    assert env['LD_LIBRARY_PATH'] == '/operator/libs'
    assert 'SAMPLE_PRIVATE_TOKEN' not in env

