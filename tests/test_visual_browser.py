"""Real Chrome with controlled public responses; no model or external network."""
import hashlib
import tempfile
from pathlib import Path
import unittest
from unittest.mock import AsyncMock
from PIL import Image
from federation.core import FederationStore
from federation.visual_browser import parse_actions, inspect_page, browse, VIEWPORTS
from federation.web_learning import CollectionError

URL = 'https://visual-browser.example/'
PAGE = '''<!doctype html><html><head><title>浏览测试第一页</title><style>
body{margin:0;background:#f6eedc;color:#223344;font:22px sans-serif}section{height:2200px}
</style></head><body><h1>浏览测试第一页</h1><button onclick="fetch('/write',{method:'POST',body:'blocked'})">下一页</button>
<section>这是一段真实浏览器渲染的受控测试内容，不是网站调研结果。</section>
<script>addEventListener('scroll',()=>{if(!document.getElementById('lazy')){let p=document.createElement('p');p.id='lazy';p.textContent='滚动后加载的资料';document.body.append(p)}});
document.querySelector('button').addEventListener('click',()=>{document.querySelector('h1').textContent='第二页动态内容'})
</script></body></html>'''

def response(url=URL, body=PAGE):
    return {'url':url,'status':200,'headers':{'content-type':'text/html; charset=utf-8'},'body':body.encode()}

class ControlledFetcher:
    def fetch(self, url): return response(url)
    def _request(self, url, limit): return response(url, '')

class VisualBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def test_dynamic_shell_waits_for_actual_body(self):
        html='<html><body>正在加载<script>setTimeout(()=>{document.title="Loaded article";document.body.innerText="动态加载完成后的实际正文"},2200)</script></body></html>'
        with tempfile.TemporaryDirectory() as folder:
            result=await inspect_page(response(body=html),Path(folder),['read'],'desktop',ControlledFetcher())
            self.assertEqual(result['snapshots'][-1]['title'],'Loaded article')
            self.assertEqual(result['snapshots'][-1]['text'],'动态加载完成后的实际正文')

    async def test_text_read_skips_image_download_but_screenshot_keeps_it(self):
        import base64
        html='<html><body><h1>Readable article</h1><img src="/pixel.png" alt="example"></body></html>'
        class Assets(ControlledFetcher):
            def __init__(self):self.requests=[]
            def _request(self,url,limit):
                self.requests.append(url)
                return {'url':url,'status':200,'headers':{'content-type':'image/png'},
                    'body':base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a0L8AAAAASUVORK5CYII=')}
        with tempfile.TemporaryDirectory() as folder:
            read=Assets();result=await inspect_page(response(body=html),Path(folder),['read'],'desktop',read)
            self.assertEqual(read.requests,[])
            self.assertIn('Readable article',result['snapshots'][0]['text'])
            capture=Assets();result=await inspect_page(response(body=html),Path(folder),['screenshot'],'desktop',capture)
            self.assertIn(URL+'pixel.png',capture.requests)
            self.assertEqual(len(result['screenshots']),1)

    async def test_visible_public_iframe_has_its_own_source_and_pagination(self):
        html='<html><body><iframe title="正文" src="/embedded/" style="width:100%;height:600px"></iframe></body></html>'
        class Frames(ControlledFetcher):
            def fetch(self,url):
                body='<html><body><h1>第二页内容</h1></body></html>' if url.endswith('/2/') else '<html><body><h1>自助服务系统</h1><p>卡密查询和订阅信息</p><a href="/embedded/2/">Next</a></body></html>'
                return response(url,body)
        with tempfile.TemporaryDirectory() as folder:
            result=await inspect_page(response(body=html),Path(folder),['read','next_page','read','screenshot'],'desktop',Frames())
            self.assertEqual(result['errors'],[])
            self.assertTrue(any(s['url']==URL+'embedded/' and '自助服务系统' in s['text'] for s in result['snapshots']))
            self.assertEqual(result['snapshots'][-1]['url'],URL+'embedded/2/')
            self.assertEqual(result['screenshots'][0]['url'],URL+'embedded/2/')

    async def test_real_scroll_pagination_screenshots_and_denied_post(self):
        with tempfile.TemporaryDirectory() as folder:
            result = await inspect_page(response(), Path(folder),
                ['read','screenshot','scroll_down','screenshot','next_page','read'], 'desktop', ControlledFetcher())
            self.assertEqual(result['errors'], [])
            self.assertGreaterEqual(result['network']['blocked'], 1, 'POST cannot leave browser')
            self.assertEqual([a['action'] for a in result['operations']],
                ['open','read','screenshot','scroll_down','screenshot','next_page','read'])
            self.assertGreater(result['screenshots'][1]['scroll_y'], 0)
            self.assertTrue(any('滚动后加载的资料' in s['text'] for s in result['snapshots']))
            self.assertTrue(any('第二页动态内容' in s['text'] for s in result['snapshots']))
            for shot in result['screenshots']:
                with Image.open(shot['path']) as im:self.assertEqual(im.size, (1440,1000))
                self.assertEqual(hashlib.sha256(Path(shot['path']).read_bytes()).hexdigest(), shot['sha256'])

    async def test_real_browser_public_next_link_and_mobile_capture(self):
        html='<html><head><title>Page one</title></head><body><h1>First article</h1><a href="/page/2/">Next</a></body></html>'
        class Pages(ControlledFetcher):
            def fetch(self,url):return response(url,'<html><head><title>Page two</title></head><body><h1>Second article</h1></body></html>')
        with tempfile.TemporaryDirectory() as folder:
            result=await inspect_page(response(body=html),Path(folder),['next_page','read','screenshot'],'mobile',Pages())
            self.assertEqual(result['errors'],[])
            self.assertEqual(result['snapshots'][-1]['url'],URL+'page/2/')
            self.assertIn('Second article',result['snapshots'][-1]['text'])
            with Image.open(result['screenshots'][0]['path']) as im:self.assertEqual(im.size,(390,844))

    async def test_ambiguous_pagination_is_partial_and_not_guessed(self):
        html='<html><body><p>Article</p><a href="/1">Next</a><a href="/2">Next</a></body></html>'
        with tempfile.TemporaryDirectory() as folder:
            result=await inspect_page(response(body=html),Path(folder),['next_page','screenshot'],'desktop',ControlledFetcher())
            self.assertEqual(result['operations'][-1]['status'],'failed')
            self.assertIn('唯一',result['errors'][0]['error'])
            self.assertEqual(result['screenshots'],[])

    async def test_default_form_submit_button_is_not_pagination(self):
        html='<html><body><p>Article</p><form action="/write"><button>Next</button></form></body></html>'
        with tempfile.TemporaryDirectory() as folder:
            result=await inspect_page(response(body=html),Path(folder),['next_page'],'desktop',ControlledFetcher())
            self.assertIn('表单提交',result['errors'][0]['error'])
            self.assertEqual(result['operations'][-1]['status'],'failed')

    async def test_room_artifacts_and_exact_source_receipts(self):
        with tempfile.TemporaryDirectory() as folder:
            store=FederationStore(Path(folder)/'data');store.init()
            async def runner(payload):
                return await inspect_page(response(),Path(payload['directory']),payload['actions'],payload['viewport'],ControlledFetcher())
            result=await browse(store,'a'*32,URL,'read,screenshot','mobile',fetcher=ControlledFetcher(),runner=runner)
            self.assertEqual(result['status'],'completed')
            self.assertEqual(result['sources'][0]['read_method'],'visual_browser_dom')
            self.assertEqual(result['sources'][0]['sha256'],hashlib.sha256((store.base/result['sources'][0]['path']).read_bytes()).hexdigest())
            item=result['artifacts'][0]
            self.assertEqual(item['room_id'],'a'*32)
            self.assertTrue(item['generated']);self.assertEqual(item['source_url'],URL)
            self.assertEqual(len(list(store.base.glob('tool-files/'+'a'*32+'/*/data'))),1)
            self.assertEqual(store.spaces()[0]['knowledge_count'],0)

    async def test_url_and_fetch_denial_cannot_be_bypassed(self):
        with tempfile.TemporaryDirectory() as folder:
            store=FederationStore(Path(folder)/'data');store.init();runner=AsyncMock()
            for url in ['http://127.0.0.1/','file:///etc/passwd','https://user:pass@example.com/']:
                with self.assertRaises(ValueError):await browse(store,'a'*32,url,'read','desktop',runner=runner)
            class Denied(ControlledFetcher):
                def fetch(self,url):raise CollectionError('robots拒绝')
            with self.assertRaises(CollectionError):await browse(store,'a'*32,URL,'read','desktop',fetcher=Denied(),runner=runner)
            runner.assert_not_awaited()

    async def test_untitled_shell_is_not_a_successful_body_read(self):
        with tempfile.TemporaryDirectory() as folder:
            store=FederationStore(Path(folder)/'data');store.init()
            shell={'url':URL,'title':'','text':'正在加载内容','sha256':'a'*64}
            runner=AsyncMock(return_value={'snapshots':[shell],'screenshots':[], 'errors':[], 'operations':[], 'viewport':VIEWPORTS['desktop']})
            result=await browse(store,'a'*32,URL,'read',fetcher=ControlledFetcher(),runner=runner)
            self.assertEqual(result['status'],'unavailable')
            self.assertEqual(result['sources'],[])
            self.assertIn('没有读到公开正文',result['errors'][0]['error'])

    def test_action_scope(self):
        for raw in ['click','submit','read,eval','screenshot,'*4,'read,'*7,'','read,']:
            with self.assertRaises(ValueError):parse_actions(raw)
        self.assertEqual(parse_actions('read, scroll_down,screenshot'),['read','scroll_down','screenshot'])

    def test_browser_status_requires_completed_execution(self):
        from federation.tool_services import status, record_execution
        with tempfile.TemporaryDirectory() as folder:
            store=FederationStore(Path(folder)/'data');store.init()
            self.assertFalse(status(store)['browser']['verified'])
            record_execution(store,'browser',{'status':'completed','sources':[{'url':URL}]})
            self.assertTrue(status(store)['browser']['verified'])
            record_execution(store,'browser',{'status':'partial','error':'翻页未完成'})
            self.assertFalse(status(store)['browser']['verified'])
            self.assertEqual(status(store)['browser']['last_execution']['status'],'partial')
