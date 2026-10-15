"""Real local persistence/API with controlled source and model boundaries."""
import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from federation.autonomy import Autonomy, digest, read_json
from federation.core import FederationStore, _write_json, _now
from federation.knowledge import knowledge_health
from federation.autonomy_upgrade import evaluate_candidate, recover_upgrades, capability_check
from federation.autonomy_strategy import strategy, sandbox_node


TEXT = 'The fixture guide requires one owner for every task and a recorded completion result. ' * 5


class TestWriteLock:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def setup_manager(tmp_path, review_ok=True):
    store = FederationStore(base=tmp_path / 'data')
    store.init()
    calls = []

    async def model(store, purpose, payload):
        calls.append(purpose)
        if purpose == '行业学习选题':
            data = {'query': 'official task ownership guide', 'goal': '学习任务归属与完成记录', 'reason': '当前缺少任务管理知识'}
        elif purpose == '有依据的知识整理':
            data = {'title': '任务归属与完成记录', 'claims': [{'text': '测试资料要求每项任务有负责人并记录完成结果。',
                    'source_id': '1', 'quote': 'one owner for every task and a recorded completion result'}],
                    'application': '建议在任务登记时填写负责人。', 'limitations': '仅为受控测试来源，不代表生产行业规则。',
                    'questions': ['任务应该分配给谁？', '完成时应该记录什么？']}
        elif purpose == '修订学习路径':
            data = {'action': 'revise', 'reason': '按核对反馈修正草稿'}
        else:
            data = {'goal_complete': True, 'approved': review_ok, 'role_relevant': True, 'goal_relevant': True, 'claims_supported': [review_ok],
                    'conflicts': [], 'issues': [] if review_ok else ['没有依据'],
                    'answers': ['有明确负责人。', '记录完成结果。']}
        return data, {'model': 'controlled-fixture', 'purpose': purpose}

    async def collect(store, agent, plan, directory, limit):
        (directory / 'source-1.txt').write_text(TEXT)
        return [{'id': '1', 'url': 'https://example.org/guide', 'title': 'Fixture guide',
                 'file': 'source-1.txt', 'excerpt': TEXT, 'sha256': digest(TEXT), 'checked_at': _now()}]

    manager = Autonomy(store, lambda: True, TestWriteLock(), model=model, collect=collect)
    manager.configure({'enabled': True, 'authorization': 'controlled-test-only'})
    return manager, calls


def test_each_agent_has_own_scope_and_fair_rotation(tmp_path):
    manager, _ = setup_manager(tmp_path)
    spaces = manager.store.spaces()
    assert len(manager.snapshot()['agents']) == len(spaces)
    first = manager.due()['id']
    _write_json(manager.root / 'agents.json', {first: {'last_attempt': _now(), 'next_at': _now()}})
    assert manager.due()['id'] != first
    manager.configure({'disabled_agents': [manager.due()['id']]})
    assert manager.due()['id'] not in manager.settings()['disabled_agents']


def test_learning_promotes_only_own_page_and_is_retrievable_with_lineage(tmp_path):
    manager, calls = setup_manager(tmp_path)
    store = manager.store
    legacy = store._wiki('software-frontend') / 'manual-draft.md'
    legacy.write_text('# 用户尚未审核的草稿\n不能自动夹带。')
    before = legacy.read_bytes()
    run = asyncio.run(manager.learn(store.space('software-frontend')))
    assert run['status'] == 'completed', run
    assert len(calls) == 3
    assert legacy.read_bytes() == before
    manifest = store._manifest('software-frontend')
    assert 'manual-draft.md' not in manifest['files']
    page = run['changed_pages'][0]
    assert store.page('software-frontend', page)['body'] == store.page('central', 'autonomous/software-frontend/' + Path(page).name)['body']
    assert run['verification']['human_reviewed'] is False
    for sid in ('central', 'software-frontend'):
        health = knowledge_health(store, sid)
        result = next(p for p in health['pages'] if p['path'].endswith(Path(page).name))
        assert result['status'] == 'current', result
        assert result['evidence'][0]['check_basis'] == 'autonomous_public_read'
    second = asyncio.run(manager.learn(store.space('software-frontend')))
    assert second['status'] == 'unchanged'
    assert len(calls) == 4


def test_bad_review_leaves_real_knowledge_untouched(tmp_path):
    manager, _ = setup_manager(tmp_path, False)
    run = asyncio.run(manager.learn(manager.store.space('business-projects')))
    assert run['status'] == 'retry_pending'
    assert len(run['model_calls']) == 9
    assert not list(manager.store._wiki('business-projects').glob('autonomous/*.md'))
    assert not list((manager.store.base / 'published').rglob('*.md'))
    assert (manager.root / 'runs' / run['id'] / 'draft.json').is_file()


def test_same_source_can_answer_a_new_question_without_replacing_old_topic(tmp_path):
    manager, _ = setup_manager(tmp_path)
    first = asyncio.run(manager.learn(manager.store.space('software')))
    model = manager.model
    async def new_topic(store, purpose, payload):
        data, receipt = await model(store, purpose, payload)
        if purpose == '行业学习选题':
            data['goal'] = '学习任务完成记录的用途'
        elif purpose == '有依据的知识整理':
            data['title'] = '完成记录的用途'
        return data, receipt
    manager.model = new_topic
    second = asyncio.run(manager.learn(manager.store.space('software')))
    assert second['status'] == 'completed'
    assert second['changed_pages'] != first['changed_pages']
    assert len(list(manager.store._wiki('software').glob('autonomous/*.md'))) == 2


def test_manual_edit_is_preserved(tmp_path):
    manager, _ = setup_manager(tmp_path)
    run = asyncio.run(manager.learn(manager.store.space('software')))
    page = manager.store._wiki('software') / run['changed_pages'][0]
    page.write_text(page.read_text() + '\n用户增加的内容。')
    before = page.read_bytes()
    next_run = asyncio.run(manager.learn(manager.store.space('software')))
    assert next_run['status'] == 'completed', next_run
    assert next_run['publication']['conflict_resolution']['strategy'] == 'preserve_and_version'
    assert next_run['changed_pages'] != run['changed_pages']
    assert page.read_bytes() == before


def test_quote_must_exist_in_actual_excerpt():
    with pytest.raises(ValueError, match='片段不在'):
        Autonomy.validate_draft({'title': '标题', 'application': '建议', 'limitations': '未知',
            'questions': ['一', '二'], 'claims': [{'text': '事实', 'source_id': '1', 'quote': '不存在的引文'}]},
            [{'id': '1', 'excerpt': TEXT}])


def test_invalid_quote_gets_one_bounded_repair_and_keeps_original(tmp_path):
    manager, _ = setup_manager(tmp_path)
    model = manager.model
    purposes = []
    async def repair_model(store, purpose, payload):
        purposes.append(purpose)
        data, receipt = await model(store, '有依据的知识整理' if purpose == '修正知识草稿格式与逐字引用' else purpose, payload)
        if purpose == '有依据的知识整理':
            data['claims'][0]['quote'] = 'unsupported original quote'
        return data, receipt
    manager.model = repair_model
    run = asyncio.run(manager.learn(manager.store.space('software')))
    assert run['status'] == 'completed', run
    assert purposes.count('修正知识草稿格式与逐字引用') == 1
    assert manager.budget()['calls'] == 4
    original = read_json(manager.root / 'runs' / run['id'] / 'draft-before-repair.json', {})
    assert original['claims'][0]['quote'] == 'unsupported original quote'


def test_search_results_from_unrelated_domains_are_not_read(tmp_path, monkeypatch):
    from federation import autonomy_sources as sources
    manager, _ = setup_manager(tmp_path)
    read_urls = []
    async def search(store, query):
        return {'sources': [{'url': 'https://unrelated.example/restaurant'}]}
    class Fetcher:
        def __init__(self, **kwargs):
            pass
        def fetch(self, url):
            read_urls.append(url)
            return {'url': url}
    monkeypatch.setattr(sources, 'search', search)
    monkeypatch.setattr(sources, 'SafeFetcher', Fetcher)
    monkeypatch.setattr(sources, '_related_links', lambda response, goal: [])
    monkeypatch.setattr(sources, 'extract_document', lambda response: {'text': TEXT, 'title': 'Official fixture'})
    directory = tmp_path / 'sources'; directory.mkdir()
    result = asyncio.run(sources.discover(manager.store, manager.store.space('software-testing'),
        {'query': 'site:playwright.dev testing'}, directory, 1))
    assert result and all(url.startswith('https://playwright.dev/') for url in read_urls)
    assert 'unrelated.example' not in str(read_urls)


def test_budget_is_durable_and_bounds_calls(tmp_path):
    manager, calls = setup_manager(tmp_path)
    manager.configure({'daily_model_calls': 1})
    run = asyncio.run(manager.learn(manager.store.space('commerce')))
    assert run['status'] == 'budget_wait'
    assert len(calls) == 1
    assert manager.budget()['calls'] == 1
    assert manager.due() is None
    manager.configure({'enabled': False})
    assert manager.due() is None


def test_partial_transaction_rolls_back_and_keeps_foreign_edits(tmp_path):
    manager, _ = setup_manager(tmp_path)
    a, b = manager.store.base / 'a.txt', manager.store.base / 'b.txt'
    a.write_text('old-a'); b.write_text('old-b')
    directory = manager.root / 'runs' / ('1' * 32)
    original = manager.atomic_bytes
    calls = []
    def fail_once(path, raw):
        calls.append(path.name)
        if path == b and len(calls) == 2:
            raise OSError('controlled disk failure')
        original(path, raw)
    with patch.object(manager, 'atomic_bytes', side_effect=fail_once):
        with pytest.raises(OSError):
            manager.commit_transaction(directory, {'a.txt': b'new-a', 'b.txt': b'new-b'})
    assert a.read_text() == 'old-a' and b.read_text() == 'old-b'
    assert read_json(directory / 'transaction.json', {})['status'] == 'rolled_back'


def test_recover_interrupted_transaction(tmp_path):
    manager, _ = setup_manager(tmp_path)
    directory = manager.root / 'runs' / ('2' * 32)
    manager.commit_transaction(directory, {'test.txt': b'written'})
    tx = read_json(directory / 'transaction.json', {})
    tx['status'] = 'prepared'; _write_json(directory / 'transaction.json', tx)
    manager.recover()
    assert not (manager.store.base / 'test.txt').exists()


def test_source_archive_tamper_marks_knowledge_stale(tmp_path):
    manager, _ = setup_manager(tmp_path)
    run = asyncio.run(manager.learn(manager.store.space('software')))
    directory = manager.root / 'runs' / run['id']
    source = read_json(directory / 'sources.json', {})['sources'][0]
    (directory / source['file']).write_text('Changed outside learning')
    health = knowledge_health(manager.store, 'software')
    assert next(p for p in health['pages'] if p['path'] == run['changed_pages'][0])['status'] == 'stale'


def test_api_default_off_and_no_credentials_in_status(tmp_path):
    from federation.app import create_app
    app = create_app(base=tmp_path / 'app')
    with TestClient(app) as client:
        result = client.get('/api/autonomy').json()
        assert result['settings']['enabled'] is False
        assert result['worker_running'] is True
        assert 'api_key' not in json.dumps(result)
        assert client.post('/api/autonomy/run', json={}).status_code == 409
        assert client.get('/autonomy').status_code == 200
        assert client.put('/api/autonomy/settings', json={'enabled': False, 'code_enabled': True,
            'daily_model_calls': 0}).status_code == 422
        assert client.get('/api/autonomy/runs/not-a-run').status_code == 404


def test_single_worker_lock(tmp_path):
    async def scenario():
        first, _ = setup_manager(tmp_path)
        first.configure({'enabled': False})
        second = Autonomy(first.store, lambda: False, asyncio.Lock())
        first.start(); second.start()
        assert first.task is not None and second.task is None
        await first.close(); await second.close()
    asyncio.run(scenario())


@pytest.mark.skipif(not Path('/usr/bin/sandbox-exec').exists(), reason='Requires macOS Seatbelt')
def test_real_policy_sandbox_and_code_validation(tmp_path):
    manager, _ = setup_manager(tmp_path)
    result = asyncio.run(strategy(manager.store, 'rankSources', candidates=['https://example.org/a'], hosts=[], query='test'))
    assert result == ['https://example.org/a']
    bad = tmp_path / 'bad.mjs'; bad.write_text('export const bad = process.env;')
    with pytest.raises(ValueError, match='能力检查'):
        asyncio.run(capability_check(manager.store, bad))
    probe = tmp_path / 'probe.mjs'
    secret = tmp_path.parent / ('secret-' + tmp_path.name)
    secret.write_text('private fixture')
    probe.write_text("import fs from 'node:fs'; let denied=false;try{fs.readFileSync(" + json.dumps(str(secret)) + ")}catch{denied=true}if(!denied)throw Error('read escaped');")
    try:
        code, _, err = asyncio.run(sandbox_node(manager.store.node, tmp_path, probe))
        assert code == 0, err
    finally:
        secret.unlink()


@pytest.mark.skipif(not Path('/usr/bin/sandbox-exec').exists(), reason='Requires macOS Seatbelt')
def test_code_upgrade_requires_measured_regression_improvement(tmp_path):
    manager, _ = setup_manager(tmp_path)
    proposal = {'reason': '官方域名的子域名应保留优先级', 'edits': [{
        'path': 'federation/learning-strategy.mjs', 'old': 'preferredHosts.includes(parsed.hostname)',
        'new': "preferredHosts.some(host => parsed.hostname === host || parsed.hostname.endsWith('.' + host))"}],
        'regression_test': "import assert from 'node:assert/strict';\nimport {rankSources} from '../federation/learning-strategy.mjs';\nassert.deepEqual(rankSources(['https://other.org/a','https://docs.example.org/a'],['example.org'],'guide'),['https://docs.example.org/a','https://other.org/a']);"}
    # This test uses a frozen defective policy; an actual autonomous improvement
    # to the live policy must not invalidate the test's original failing case.
    fixture = Path(__file__).parent / 'fixtures/autonomy-learning-baseline.mjs'
    original_read = Path.read_text
    policy = manager.store.project_root / 'federation/learning-strategy.mjs'
    def read_fixture(path, *args, **kwargs):
        return original_read(fixture) if path == policy else original_read(path, *args, **kwargs)
    with patch.object(Path, 'read_text', new=read_fixture):
        before, after, tests = asyncio.run(evaluate_candidate(manager.store, tmp_path / 'check', proposal))
    assert tests['baseline_regression']['exit_code'] != 0
    assert tests['trial_regression']['exit_code'] == 0
    assert before != after


def test_industry_search_can_read_relevant_source_outside_official_catalog(tmp_path,monkeypatch):
    from federation import autonomy_sources as sources
    manager,_=setup_manager(tmp_path)
    url='https://industry-source.example/testing/locators';reads=[]
    async def search(*args):return {'status':'completed','sources':[{'url':url}]}
    class Fetcher:
        def __init__(self,**kwargs):pass
        def fetch(self,target):reads.append(target);return {'url':target}
    monkeypatch.setattr(sources,'search',search)
    monkeypatch.setattr(sources,'SafeFetcher',Fetcher)
    monkeypatch.setattr(sources,'_related_links',lambda *args:[])
    monkeypatch.setattr(sources,'extract_document',lambda response:{'text':TEXT,'title':'Industry article fixture'})
    directory=tmp_path/'sources';directory.mkdir()
    result=asyncio.run(sources.discover(manager.store,manager.store.space('software-testing'),{'query':'testing locators'},directory,1))
    assert reads==[url]
    assert result[0]['url']==url
    assert result[0]['read_method']=='public_page_text'
