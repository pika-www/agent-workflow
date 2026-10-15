"""Local API lifecycle with controlled network/model; never fetch real URLs."""
import asyncio
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest

from fastapi.testclient import TestClient
from federation.app import create_app
from federation.chat import ChatStore


class WebLearningAPITest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.calls, self.collections = [], []
        self.fail_learning = False
        self.fail_collection = False
        self.no_change = False
        self.warnings = False
        self.local_conflict = False

        async def runner(job, store):
            self.calls.append(dict(job))
            await asyncio.sleep(0.001)
            phase, space = job.get("delegation_phase"), job["space"]
            if job["action"] == "learn":
                if self.fail_learning:
                    raise ValueError("受控模型学习失败")
                if not self.no_change:
                    (Path(store.space(space)["wiki_dir"]) / "form-validation.md").write_text(
                        "---\ntitle: 表单验证\n---\n# 表单验证\n来源：https://example.org/form\n原生表单约束支持 required。")
                job["source_reads"] = 1
            elif phase == "plan":
                child = "software" if space == "central" else "software-frontend"
                job["answer"] = json.dumps({"action": "delegate", "tasks": [{"agent_id": child, "task": "自主学习 HTML 表单验证"}]})
            elif phase == "research":
                job["answer"] = json.dumps({"queries": ["HTML form validation"]})
            else:
                job["answer"] = "专业分支已交回处理记录；中央未发布。"

        async def collector(store, space, goal, urls=None, max_pages=2, run_id=None, queries=None, progress=None):
            self.collections.append({"space": space, "queries": queries, "urls": urls, "max_pages": max_pages})
            errors = [{"url": "https://example.org/missing", "error": "受控抓取失败"}] if self.warnings or self.fail_collection else []
            if self.local_conflict:
                errors.append({"url": "https://example.org/modified", "error": "人工修改的来源", "code": "local_source_conflict"})
            if self.fail_collection:
                return {"sources": [], "errors": errors, "provider": "official-sites", "changed_count": 0}
            names = [s["name"] for s in store.sources(space)]
            status = "unchanged" if "source.md" in names else "new"
            if status == "new":
                store.add_source(space, "source.md", "受控来源：HTML required 表单验证。")
            report = {"sources": [{"url": "https://example.org/form", "title": "Forms", "filename": "source.md", "status": status,
                                   "sha256": hashlib.sha256(b"fixture").hexdigest()}], "errors": errors,
                      "provider": "official-sites", "changed_count": int(status == "new")}
            if progress:
                progress(dict(report, status="collecting"))
            return report

        self.app = create_app(base=Path(self.temp.name) / "data", runner=runner, collector=collector)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.room = self.client.post("/api/chat/rooms", json={"mode": "orchestrated", "participants": ["central"]}).json()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def run_round(self, **kwargs):
        request = {"content": "让前端 Agent 自己寻找资料学习表单验证", "learning": True, "max_pages": 1, **kwargs}
        response = self.client.post('/api/chat/rooms/' + self.room['id'] + '/messages', json=request)
        self.assertEqual(response.status_code, 200, response.text)
        identifier = response.json()['job']['id']
        for _ in range(500):
            job = self.client.get('/api/jobs/' + identifier).json()
            if job['status'] not in {'running', 'queued'}:
                return job, self.client.get('/api/chat/rooms/' + self.room['id']).json()
            time.sleep(.01)
        self.fail('Controlled learning timed out')

    def test_autonomous_sources_persist_only_in_selected_child_and_have_receipts(self):
        store = self.app.state.store
        before = {s['id']: [(p['path'], p['sha256']) for p in store.pages(s['id'])] for s in store.spaces()}
        job, room = self.run_round()
        self.assertEqual(job['status'], 'completed', job)
        self.assertEqual(self.collections, [{'space': 'software-frontend', 'queries': ['HTML form validation'], 'urls': [], 'max_pages': 1}])
        self.assertEqual([(c['space'], c.get('delegation_phase'), c['action']) for c in self.calls], [
            ('central', 'plan', 'ask'), ('software', 'plan', 'ask'), ('software-frontend', 'research', 'ask'),
            ('software-frontend', None, 'learn'), ('software', 'summary', 'ask'), ('central', 'summary', 'ask')])
        for space, signature in before.items():
            after = [(p['path'], p['sha256']) for p in store.pages(space)]
            self.assertEqual(after == signature, space != 'software-frontend')
        leaf = room['delegations'][-1]
        self.assertEqual(leaf['web_learning']['status'], 'completed')
        self.assertFalse(leaf['web_learning']['published'])
        self.assertIn('form-validation.md', [p['path'] for p in leaf['web_learning']['changed_pages']])
        self.assertEqual(leaf['web_learning']['knowledge_tracking']['recorded_count'], 1)
        health = self.client.get('/api/spaces/software-frontend/knowledge-health').json()
        tracked = next(page for page in health['pages'] if page['path'] == 'form-validation.md')
        self.assertEqual(tracked['status'], 'review_due')  # controlled local source has no web-check timestamp
        self.assertEqual(tracked['evidence'][0]['relation'], 'run_inputs')
        self.assertEqual(tracked['evidence'][0]['name'], 'source.md')
        self.assertIn('【系统核对的学习记录】', room['messages'][-1]['content'])
        self.assertIn('https://example.org/form', room['messages'][-1]['content'])
        self.assertEqual(store.space('central')['knowledge_count'], 0)
        self.assertFalse(list((store.base / 'published').rglob('*.md')))
        saved = json.loads((store.base / 'chat/rooms' / (room['id']+'.json')).read_text())
        self.assertEqual(saved, room)

    def test_repeat_only_skips_after_success_and_identical_wiki(self):
        self.assertEqual(self.run_round()[0]['status'], 'completed')
        count = sum(c['action'] == 'learn' for c in self.calls)
        job, room = self.run_round()
        self.assertEqual(job['status'], 'completed')
        self.assertEqual(sum(c['action'] == 'learn' for c in self.calls), count)
        self.assertEqual(room['delegations'][-1]['web_learning']['status'], 'unchanged')

    def test_failed_learning_is_retryable_even_when_sources_unchanged(self):
        self.fail_learning = True
        job, room = self.run_round()
        self.assertEqual(job['status'], 'failed')
        self.assertEqual(room['delegations'][-1]['web_learning']['status'], 'failed')
        self.fail_learning = False
        job, room = self.run_round()
        self.assertEqual(job['status'], 'completed', job)
        self.assertEqual(room['delegations'][-1]['web_learning']['sources'][0]['status'], 'unchanged')
        self.assertEqual(sum(c['action'] == 'learn' for c in self.calls), 2)

    def test_no_collected_body_never_runs_learner(self):
        self.fail_collection = True
        job, room = self.run_round()
        self.assertEqual(job['status'], 'failed')
        self.assertFalse(any(c['action'] == 'learn' for c in self.calls))
        self.assertIn('没有成功取得', room['messages'][-1]['content'])

    def test_no_changed_knowledge_is_not_falsely_marked_learned(self):
        self.no_change = True
        job, room = self.run_round()
        self.assertEqual(job['status'], 'failed')
        self.assertEqual(room['delegations'][-1]['web_learning']['changed_pages'], [])

    def test_partial_collection_errors_remain_visible(self):
        self.warnings = True
        job, room = self.run_round()
        self.assertEqual(job['status'], 'completed')
        self.assertTrue(room['delegations'][-1]['web_learning']['errors'])
        self.assertIn('采集缺口', room['messages'][-1]['content'])

    def test_local_source_conflict_blocks_learning_even_with_other_good_sources(self):
        self.local_conflict = True
        job, room = self.run_round()
        self.assertEqual(job['status'], 'failed')
        self.assertFalse(any(c['action'] == 'learn' for c in self.calls))
        self.assertTrue(room['delegations'][-1]['web_learning']['sources'])
        self.assertIn('人工修改冲突', room['messages'][-1]['content'])

    def test_ordinary_chat_never_fetches_or_learns(self):
        job, room = self.run_round(learning=False)
        self.assertEqual(job['status'], 'completed')
        self.assertEqual(self.collections, [])
        self.assertFalse(any(c['action'] == 'learn' for c in self.calls))
        self.assertTrue(all('web_learning' not in t for t in room['delegations']))

    def test_command_and_validation(self):
        self.assertEqual(self.run_round(content='/学习 前端表单验证', learning=False)[0]['status'], 'completed')
        url = '/api/chat/rooms/' + self.room['id'] + '/messages'
        for request in [{'content': '/学习'}, {'content': 'x', 'learning': True, 'max_pages': 6},
                        {'content': 'x', 'urls': ['https://example.org']}, {'content': 'x', 'learning': True, 'urls': ['file:///tmp/test']}]:
            self.assertIn(self.client.post(url, json=request).status_code, {400, 422})
        room = self.client.post('/api/chat/rooms', json={'mode': 'direct', 'participants': ['software']}).json()
        self.assertEqual(self.client.post('/api/chat/rooms/'+room['id']+'/messages', json={'content':'x','learning':True}).status_code,400)
        status = self.client.get('/api/web-learning/status').json()
        self.assertFalse(status['requires_user_urls'])
        self.assertEqual(status['publish_policy'], 'reviewed-publish')

    def test_restart_marks_unfinished_learning_receipt_failed(self):
        job, room = self.run_round()
        room.update(status='running', active_job_id=job['id'])
        room['delegations'][-1]['status'] = 'running'
        room['delegations'][-1]['web_learning']['status'] = 'learning'
        self.app.state.chat.save_room(room)
        recovered = ChatStore(self.app.state.store).get_room(room['id'])
        self.assertEqual(recovered['status'], 'failed')
        self.assertIsNone(recovered['active_job_id'])
        self.assertEqual(recovered['delegations'][-1]['web_learning']['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
