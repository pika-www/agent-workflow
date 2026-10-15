import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import httpx
from federation.core import FederationStore
from federation.public_search import search

class PublicSearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_url_search_normalizes_and_discards_unrelated_protocol_results(self):
        with tempfile.TemporaryDirectory() as folder:
            store=FederationStore(Path(folder)/'data');store.init();queries=[]
            def handler(request):
                queries.append(request.url.params['q'])
                return httpx.Response(200,text='<rss><channel><item><link>https://en.wikipedia.org/wiki/HTTPS</link><title>HTTPS</title><description>Protocol background</description></item></channel></rss>')
            real=httpx.AsyncClient
            with patch('federation.tool_services.configuration',return_value={'search':{'provider':'bing-rss'}}), patch('httpx.AsyncClient',side_effect=lambda **kwargs:real(transport=httpx.MockTransport(handler))):
                result=await search(store,'https://site.example/')
            self.assertEqual(queries,['site:site.example "site.example"'])
            self.assertEqual(result['status'],'no_related_results');self.assertEqual(result['sources'],[])
            self.assertEqual(result['discarded_unrelated_count'],1)
            self.assertEqual(result['query'],'https://site.example/')

    async def test_relevant_site_and_external_domain_mention_remain_snippets(self):
        with tempfile.TemporaryDirectory() as folder:
            store=FederationStore(Path(folder)/'data');store.init()
            def handler(request):
                return httpx.Response(200,text='<rss><channel><item><link>https://site.example/about</link><title>Site</title><description>Public page</description></item><item><link>https://news.example/article</link><title>site.example review</title><description>Review excerpt</description></item></channel></rss>')
            real=httpx.AsyncClient
            with patch('federation.tool_services.configuration',return_value={'search':{'provider':'bing-rss'}}), patch('httpx.AsyncClient',side_effect=lambda **kwargs:real(transport=httpx.MockTransport(handler))):result=await search(store,'https://site.example/')
            self.assertEqual(result['status'],'completed');self.assertEqual(len(result['sources']),2)
            self.assertTrue(all(s['read_method']=='search_result_snippet' for s in result['sources']))

    async def test_auto_search_unwraps_links_and_falls_back_on_unrelated_results(self):
        with tempfile.TemporaryDirectory() as folder:
            store=FederationStore(Path(folder)/'data');store.init(); calls=[]
            def handler(request):
                calls.append(request.url.host)
                if request.url.host=='html.duckduckgo.com':
                    return httpx.Response(200,text='<div class="result"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fmusic">Music channel</a><p class="result__snippet">Listen to music</p></div>')
                return httpx.Response(200,text='<rss><channel><item><link>https://playwright.dev/docs/locators</link><title>Playwright locators</title><description>Use getByRole to find elements</description></item></channel></rss>')
            real=httpx.AsyncClient
            with patch('httpx.AsyncClient',side_effect=lambda **kwargs:real(transport=httpx.MockTransport(handler))), patch('federation.web_learning._search_key',return_value=''):
                result=await search(store,'Playwright getByRole locators')
            self.assertEqual(calls,['html.duckduckgo.com','www.bing.com'])
            self.assertEqual(result['provider'],'bing-rss')
            self.assertEqual(result['attempts'][0]['status'],'no_related_results')
            self.assertEqual(result['sources'][0]['url'],'https://playwright.dev/docs/locators')

    async def test_ddg_results_are_decoded_deduplicated_and_site_path_filtered(self):
        with tempfile.TemporaryDirectory() as folder:
            store=FederationStore(Path(folder)/'data');store.init();calls=[]
            def handler(request):
                calls.append(request.url.host)
                return httpx.Response(200,text=''.join('<div class="result"><a class="result__a" href="'+link+'">Playwright locators</a><span class="result__snippet">Locate elements by role</span></div>' for link in ['https://playwright.dev/java/docs/locators','//duckduckgo.com/l/?uddg=https%3A%2F%2Fplaywright.dev%2Fdocs%2Flocators','https://playwright.dev/docs/locators']))
            real=httpx.AsyncClient
            with patch('httpx.AsyncClient',side_effect=lambda **kwargs:real(transport=httpx.MockTransport(handler))), patch('federation.web_learning._search_key',return_value=''):
                result=await search(store,'site:playwright.dev/docs locators')
            self.assertEqual(calls,['html.duckduckgo.com'])
            self.assertEqual(result['discarded_unrelated_count'],1)
            self.assertEqual(len(result['sources']),1)
            self.assertEqual(result['sources'][0]['read_method'],'search_result_snippet')

    async def test_challenge_falls_back_without_solving_and_disabled_never_requests(self):
        with tempfile.TemporaryDirectory() as folder:
            store=FederationStore(Path(folder)/'data');store.init();calls=[]
            def handler(request):
                calls.append(str(request.url))
                return httpx.Response(200,text='<form action="/anomaly.js">captcha</form>') if request.url.host=='html.duckduckgo.com' else httpx.Response(503)
            real=httpx.AsyncClient
            with patch('httpx.AsyncClient',side_effect=lambda **kwargs:real(transport=httpx.MockTransport(handler))), patch('federation.web_learning._search_key',return_value=''):
                result=await search(store,'Playwright locators')
                with patch('federation.tool_services.configuration',return_value={'search':{'enabled':False}}):
                    disabled=await search(store,'Playwright locators')
            self.assertEqual(len(calls),2)
            self.assertEqual(result['status'],'blocked')
            self.assertIn('人工验证',result['attempts'][0]['error'])
            self.assertEqual(disabled['status'],'unavailable')

    def test_tavily_requires_key_and_implementation_change_invalidates_verification(self):
        from federation.tool_services import save_service,record_execution,status
        with tempfile.TemporaryDirectory() as folder:
            store=FederationStore(Path(folder)/'data');store.init()
            with patch('federation.web_learning._search_key',return_value=''):
                self.assertFalse(save_service(store,'search',{'provider':'tavily'})['search']['configured'])
                self.assertTrue(save_service(store,'search',{'provider':'auto'})['search']['configured'])
            record_execution(store,'search',{'status':'completed'})
            self.assertTrue(status(store)['search']['verified'])
            read=Path.read_bytes
            with patch.object(Path,'read_bytes',lambda p: b'changed implementation' if p.name=='public_search.py' else read(p)):
                self.assertFalse(status(store)['search']['verified'])
