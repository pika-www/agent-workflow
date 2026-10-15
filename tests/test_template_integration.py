"""API and learning lifecycle checks with controlled external dependencies."""
import asyncio
import json
from pathlib import Path
import tempfile
import time
import unittest

from fastapi.testclient import TestClient
from federation.app import create_app, isolated_ask_environment


class TemplateIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.template_calls = []
        self.template_failure = False

        async def runner(job, store):
            await asyncio.sleep(.001)
            phase = job.get('delegation_phase')
            if job['action'] == 'learn':
                (store._wiki(job['space']) / 'vue-guideline.md').write_text('# Vue 规范\n受控例：组件使用 TypeScript。')
                job['source_reads'] = 1
            elif phase == 'plan':
                member = 'software' if job['space'] == 'central' else 'software-frontend'
                job['answer'] = json.dumps({'action':'delegate','tasks':[{'agent_id':member,'task':'学习 Vue 规范并维护模板'}]})
            elif phase == 'research':
                job['answer'] = json.dumps({'queries':['Vue component TypeScript guidelines']})
            else:
                job['answer'] = '受控汇总，具体结果以执行回执为准。'

        async def collector(store, space, goal, **kwargs):
            store.add_source(space, 'vue-source.md', '# Vue 原文\n这是受控采集正文，用于模板生命周期测试。')
            return {'sources':[{'url':'https://example.org/vue','filename':'vue-source.md','status':'new'}],
                    'errors':[], 'provider':'controlled', 'changed_count':1}

        async def maintainer(store, space, frameworks=None):
            self.template_calls.append((space, frameworks))
            if self.template_failure:
                return {'templates':[{'id':'vue-ts','status':'conflict'}], 'errors':['controlled manual change']}
            return {'templates':[{'id':'vue-ts','framework':'vue','status':'updated','source_version':'fixture',
                                  'upstream_commit':'a'*40}], 'errors':[]}

        self.app = create_app(base=Path(self.temp.name) / 'data', runner=runner, collector=collector,
                              template_maintainer=maintainer)
        self.client = TestClient(self.app); self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None,None,None); self.temp.cleanup()

    def learning(self):
        room = self.client.post('/api/chat/rooms', json={'mode':'orchestrated','participants':['central']}).json()
        job = self.client.post('/api/chat/rooms/'+room['id']+'/messages', json={'content':'让前端学习 Vue 并维护模板','learning':True}).json()['job']
        for _ in range(250):
            result = self.client.get('/api/jobs/'+job['id']).json()
            if result['status'] not in {'running','queued'}:
                return result
            time.sleep(.02)
        self.fail('controlled template learning did not finish')

    def test_every_agent_exposes_scoped_files_and_downloads(self):
        for space in self.app.state.store.spaces():
            response = self.client.get('/api/spaces/'+space['id']+'/templates')
            self.assertEqual(response.status_code, 200, response.text)
            templates = response.json()['templates']; self.assertGreaterEqual(len(templates), 2)
            for template in templates:
                self.assertEqual(template['space_id'], space['id'])
        download = self.client.get('/api/spaces/software-backend/templates/agent-standard/files/GUIDELINES.md')
        self.assertEqual(download.status_code, 200)
        self.assertIn('服务端', download.text)
        self.assertIn('attachment', download.headers['content-disposition'])
        self.assertEqual(self.client.get('/api/spaces/central/templates/vue-ts/files/template/package.json').status_code,400)
        self.assertEqual(self.client.get('/api/spaces/software-backend/templates/agent-standard/files/manifest.json').status_code,404)

    def test_native_isolation_receives_owned_standard_and_professional_code(self):
        store = self.app.state.store
        job = {'id':'controlled-template-ask','space':'software-backend','question':'设计 OpenAPI 接口', 'template_query':'设计 OpenAPI 接口'}
        environment = isolated_ask_environment(store,job)
        selected = json.loads(environment['FEDERATION_TEMPLATE_SELECTION'])
        self.assertEqual(selected[0]['id'],'agent-standard'); self.assertEqual(len(selected),2)
        self.assertTrue(any(p.suffix in {'.yaml','.yml','.json'} for p in (Path(environment['OPENWIKI_CONFIG_DIR'])/'wiki/_agent_templates').rglob('*')))
        self.assertEqual(store.space('software-backend')['knowledge_count'],0)

    def test_teaching_keeps_catalog_metadata_without_claiming_template_reads(self):
        store = self.app.state.store
        job = {'id': 'teaching-capability-catalog', 'space': 'software-frontend',
               'question': '你只会 HTML JS 和 CSS 吗？', 'delegation_phase': 'consultation', 'teaching': True}
        environment = isolated_ask_environment(store, job)
        inventory = json.loads(environment['FEDERATION_TEMPLATE_INVENTORY'])
        self.assertIn({'id': 'angular-ts', 'framework': 'angular'}, inventory)
        self.assertIn({'id': 'wechat-miniprogram', 'framework': 'wechat'}, inventory)
        self.assertEqual(job['template_inventory'], inventory)
        self.assertTrue(all(set(item) == {'id', 'framework'} for item in inventory))
        self.assertEqual(json.loads(environment['FEDERATION_TEMPLATE_SELECTION']), [])
        self.assertFalse((Path(environment['OPENWIKI_CONFIG_DIR'])/'wiki/_agent_templates').exists())
        self.assertNotIn('openapi', {item['framework'] for item in inventory})
        self.assertEqual(job['template_selection_reason'], 'conversational-teaching')

    def test_learning_maintains_framework_and_all_local_rule_packs(self):
        job = self.learning(); self.assertEqual(job['status'],'completed',job)
        self.assertEqual(self.template_calls,[('software-frontend',['vue'])])
        report = job['learning_reports'][0]
        self.assertIn('vue-ts',[t['id'] for t in report['templates']])
        self.assertIn('agent-standard',[t['id'] for t in report['templates']])
        stored = self.client.get('/api/spaces/software-frontend/templates').json()['templates']
        self.assertTrue(all(t['revision'] == 2 for t in stored))
        self.assertTrue(all('vue-guideline.md' in t['knowledge_signature'] for t in stored))
        central = self.client.get('/api/spaces/central/templates').json()['templates']
        self.assertTrue(all(t['revision'] == 1 for t in central))

    def test_template_conflict_stops_learning_with_visible_error(self):
        self.template_failure = True
        result = self.learning(); self.assertEqual(result['status'],'failed')
        self.assertEqual(self.app.state.store.space('software-frontend')['knowledge_count'],0)
        receipt = result['learning_reports'][0]
        self.assertEqual(receipt['status'],'failed')
        self.assertTrue(receipt['template_errors'])

    def test_new_branch_gets_local_specialist_templates(self):
        r=self.client.post('/api/branches',json={'name':'可靠性专项','description':'故障演练','parent_id':'software-devops'})
        self.assertEqual(r.status_code,200,r.text)
        result=self.client.get('/api/spaces/'+r.json()['id']+'/templates')
        self.assertGreaterEqual(len(result.json()['templates']),2)


if __name__ == '__main__':
    unittest.main()
