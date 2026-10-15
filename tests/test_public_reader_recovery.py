"""Controlled transport tests; public-site verification is kept in outputs separately."""
import asyncio
import json
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
import pytest
from federation.web_learning import SafeFetcher, PublicReadError, CollectionError, extract_document
from federation.visual_browser import browse
from federation.core import FederationStore
from federation.chat_stream import ReplyStreams

URL='https://reader.example/article'
ROBOTS='https://reader.example/robots.txt'
BODY=b'<html><body><main>'+b'Public article facts and sources. '*30+b'</main></body></html>'
def response(url=URL,status=200,body=BODY,headers=None):
    return {'url':url,'status':status,'body':body,'headers':headers or {'content-type':'text/html'}}
def rule(body=b'User-agent: *\nAllow: /',status=200,headers=None):
    return response(ROBOTS,status,body,headers or {'content-type':'text/plain'})


def test_robots_403_does_not_mislabel_article():
    for article_status in [200,403,404]:
        fetcher=SafeFetcher()
        with patch.object(fetcher,'_request',side_effect=[rule(status=403),response(status=article_status)]) as req:
            if article_status==200:
                assert extract_document(fetcher.fetch(URL))['text']
            else:
                with pytest.raises(PublicReadError) as failure:fetcher.fetch(URL)
                assert failure.value.stage=='article'
                assert failure.value.http_status==article_status
                assert failure.value.code==('access_restricted' if article_status==403 else 'article_http_error')
            assert [c.args[0] for c in req.call_args_list]==[ROBOTS,URL]


def test_transient_retry_and_shared_negative_cache(tmp_path):
    first=SafeFetcher(cache_dir=tmp_path)
    with patch.object(first,'_request',return_value=rule(status=500)) as req, patch('federation.web_learning.time.sleep'):
        with pytest.raises(PublicReadError) as failure:first.fetch(URL)
        assert failure.value.receipt()['attempts']==3
        assert failure.value.code=='robots_check_failed'
        assert failure.value.retry_after==60
        assert [c.args[0] for c in req.call_args_list]==[ROBOTS]*3
    second=SafeFetcher(cache_dir=tmp_path)
    with patch.object(second,'_request') as req:
        with pytest.raises(PublicReadError) as failure:second.fetch(URL)
        assert failure.value.stage=='robots'
        req.assert_not_called()


def test_recover_from_transient_and_retry_article():
    fetcher=SafeFetcher()
    with patch.object(fetcher,'_request',side_effect=[rule(status=503),rule(),response(status=502),response()]) as req, patch('federation.web_learning.time.sleep'):
        assert fetcher.fetch(URL)['status']==200
        assert [c.args[0] for c in req.call_args_list]==[ROBOTS,ROBOTS,URL,URL]


def test_cached_rules_survive_process_instances_and_concurrent_reads(tmp_path):
    calls=[]
    def request(self,url,limit):
        calls.append(url)
        return rule() if url==ROBOTS else response(url)
    def read(i):return SafeFetcher(cache_dir=tmp_path).fetch(URL+str(i))
    with patch.object(SafeFetcher,'_request',request):
        with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(read,range(3)))
    assert len(results)==3
    assert calls.count(ROBOTS)==1
    assert len(calls)==4


@pytest.mark.parametrize('refresh_status',[403,500])
def test_expired_but_recent_disallow_retained_on_errors(tmp_path,refresh_status):
    first=SafeFetcher(cache_dir=tmp_path)
    with patch.object(first,'_request',return_value=rule(b'User-agent: *\nDisallow: /article')) as req:
        with pytest.raises(PublicReadError) as failure:first.fetch(URL)
        assert failure.value.code=='robots_blocked'
        assert req.call_count==1
    cache=next(tmp_path.glob('*.json'));data=json.loads(cache.read_text());data['expires_at']=0;cache.write_text(json.dumps(data))
    second=SafeFetcher(cache_dir=tmp_path)
    with patch.object(second,'_request',return_value=rule(status=refresh_status)) as req,patch('federation.web_learning.time.sleep'):
        with pytest.raises(PublicReadError) as failure:second.fetch(URL)
        assert failure.value.code=='robots_blocked'
        assert all(c.args[0]==ROBOTS for c in req.call_args_list)


def test_expired_cache_revalidates_new_deny_rule(tmp_path):
    first=SafeFetcher(cache_dir=tmp_path)
    with patch.object(first,'_request',side_effect=[rule(),response()]):first.fetch(URL)
    cache=next(tmp_path.glob('*.json'));data=json.loads(cache.read_text());data['expires_at']=0;cache.write_text(json.dumps(data))
    with patch.object(SafeFetcher,'_request',return_value=rule(b'User-agent: *\nDisallow: /')) as req:
        with pytest.raises(PublicReadError) as failure:SafeFetcher(cache_dir=tmp_path).fetch(URL)
        assert failure.value.code=='robots_blocked';assert req.call_count==1


def test_retry_after_prevents_early_retry(tmp_path):
    reader=SafeFetcher(cache_dir=tmp_path)
    with patch.object(reader,'_request',return_value=rule(status=429,headers={'retry-after':'120'})) as req,patch('federation.web_learning.time.sleep') as sleep:
        with pytest.raises(PublicReadError) as failure:reader.fetch(URL)
        assert failure.value.retry_after==120
        assert req.call_count==1
        sleep.assert_not_called()


def test_html_robot_challenge_is_not_permission():
    reader=SafeFetcher()
    with patch.object(reader,'_request',return_value=rule(b'<html>login required</html>')) as req:
        with pytest.raises(PublicReadError) as failure:reader.fetch(URL)
        assert failure.value.code=='robots_check_failed';assert req.call_count==1


def test_network_error_is_retried_and_stage_preserved():
    reader=SafeFetcher()
    with patch.object(reader,'_request',side_effect=CollectionError('网页连接失败：TimeoutError')) as req,patch('federation.web_learning.time.sleep'):
        with pytest.raises(PublicReadError) as failure:reader.fetch(URL)
        assert failure.value.stage=='robots';assert failure.value.attempts==3;assert req.call_count==3


def test_new_failure_detail_survives_sse_and_is_host_only():
    hub=ReplyStreams();hub.start('room','job')
    event={'origin':'host_tool','protocol':'responses','type':'agent.tool.completed','call_id':'read','name':'web_read',
           'status':'robots_check_failed','failure_detail':'robots.txt 检查异常（HTTP 500，已尝试 3 次）；尚未请求文章正文'}
    hub.native_event('room','job',event)
    assert hub.snapshot('room','job')['operations'][0]['failure_detail']==event['failure_detail']
    with pytest.raises(ValueError):hub.native_event('room','job',{**event,'failure_detail':'x'*201})
    with pytest.raises(ValueError):hub.native_event('room','job',{'origin':'provider','protocol':'responses','type':'response.completed','failure_detail':'untrusted'})


def test_dynamic_document_real_browser_and_cached_permission(tmp_path):
    store=FederationStore(tmp_path/'data');store.base.mkdir(parents=True)
    reader=SafeFetcher(cache_dir=store.base/'.cache/robots')
    text='受控浏览器验证：这些文字由网页脚本生成，用于确认公开正文回退读取。'*12
    html=('<html><head><title>动态正文验证</title></head><body><main id="content"></main><script>document.getElementById("content").textContent='+json.dumps(text)+';</script></body></html>').encode()
    with patch.object(reader,'_request',side_effect=[rule(),response(body=html)]) as req:
        raw=reader.fetch(URL)
        with pytest.raises(PublicReadError) as failure:extract_document(raw)
        assert failure.value.code=='no_readable_body'
    with patch.object(reader,'_request',return_value=response(body=html)) as req:
        result=asyncio.run(browse(store,'a'*32,URL,'read',fetcher=reader))
        assert result['status']=='completed'
        assert result['sources'][0]['read_method']=='visual_browser_dom'
        assert text in result['sources'][0]['excerpt']
        assert [c.args[0] for c in req.call_args_list]==[URL]
        assert any(d.get('cache')=='hit' for d in result['read_diagnostics'])


def test_no_store_invalidates_old_allow_cache(tmp_path):
    first=SafeFetcher(cache_dir=tmp_path)
    with patch.object(first,'_request',side_effect=[rule(),response()]):first.fetch(URL)
    cache=next(tmp_path.glob('*.json'));data=json.loads(cache.read_text());data['expires_at']=0;cache.write_text(json.dumps(data))
    deny=rule(b'User-agent: *\nDisallow: /',headers={'cache-control':'no-store','content-type':'text/plain'})
    with patch.object(first,'_request',return_value=deny):
        with pytest.raises(PublicReadError):first.fetch(URL)
    assert not cache.exists()
    second=SafeFetcher(cache_dir=tmp_path)
    with patch.object(second,'_request',return_value=deny) as req:
        with pytest.raises(PublicReadError):second.fetch(URL)
        assert req.call_count==1


def test_broken_cache_refetches_instead_of_failing(tmp_path):
    first=SafeFetcher(cache_dir=tmp_path)
    with patch.object(first,'_request',side_effect=[rule(),response()]):first.fetch(URL)
    cache=next(tmp_path.glob('*.json'));cache.write_text('[]')
    with patch.object(SafeFetcher,'_request',side_effect=[rule(),response()]) as req:
        assert SafeFetcher(cache_dir=tmp_path).fetch(URL)['status']==200
        assert req.call_count==2
