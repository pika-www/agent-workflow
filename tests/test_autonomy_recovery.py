"""Failure recovery must finish the original goal without weakening evidence gates."""
import asyncio
import json

import pytest

from federation.autonomy import read_json, digest
from federation.core import _write_json, _now
from test_autonomy import setup_manager, TEXT


def run(manager, sid='software'):
    return asyncio.run(manager.learn(manager.store.space(sid)))


def test_explicit_resume_uses_next_idle_slot_without_losing_other_queue_entries(tmp_path):
    manager, _ = setup_manager(tmp_path)
    manager.request('software')
    manager.request('software-app')
    assert manager.due()['id'] == 'software-app'
    result = run(manager, 'software-app')
    assert result['status'] == 'completed'
    assert manager.due()['id'] == 'software'


def test_missing_body_researches_same_goal_then_publishes(tmp_path):
    manager, calls = setup_manager(tmp_path)
    model, collect = manager.model, manager.collect
    plans, drafts = [], []
    async def collecting(store, agent, plan, directory, limit):
        plans.append(dict(plan))
        return await collect(store, agent, plan, directory, limit)
    async def repairing(store, purpose, payload):
        if purpose == '修订学习路径':
            assert payload['original_goal'] == plans[0]['goal']
            return {'action': 'research', 'query': 'site:example.org/guide task owner completion ' * 8,
                    'urls': ['https://example.org/guide'], 'reason': '补读缺少的具体章节'}, {}
        if purpose == '有依据的知识整理':
            drafts.append(payload)
            if len(drafts) == 1:
                return {'insufficient_evidence': True, 'reason': '只有目录',
                        'missing_questions': ['如何记录完成结果']}, {}
        return await model(store, purpose, payload)
    manager.model, manager.collect = repairing, collecting
    result = run(manager)
    assert result['status'] == 'completed', result
    assert len(plans) == 2 and plans[0]['goal'] == plans[1]['goal']
    assert 'site:example.org/guide' in plans[1]['query']
    assert len(plans[1]['query']) <= 180
    assert calls.count('行业学习选题') == 1
    assert result['verification']['goal_complete'] is True
    assert (manager.root / 'runs' / result['id'] / 'attempts/1/source-1.txt').read_text() == TEXT
    assert (manager.root / 'runs' / result['id'] / 'attempts/2/source-1.txt').read_text() == TEXT


def test_semantic_conflict_is_revised_and_reviewed_again(tmp_path):
    manager, calls = setup_manager(tmp_path)
    model = manager.model
    reviews = []
    async def checking(store, purpose, payload):
        data, receipt = await model(store, purpose, payload)
        if purpose == '独立来源与冲突核对':
            reviews.append(payload)
            if len(reviews) == 1:
                data.update(approved=False, conflicts=['需要区分旧版本适用条件'])
        if purpose == '有依据的知识整理' and reviews:
            assert payload['repair_feedback']['detail']['conflicts']
            data['limitations'] = '仅适用于本次读取的版本，旧版本条件未知。'
        return data, receipt
    manager.model = checking
    result = run(manager)
    assert result['status'] == 'completed', result
    assert len(reviews) == 2
    assert '旧版本' in reviews[-1]['draft']['limitations']
    assert calls.count('行业学习选题') == 1


def test_incomplete_goal_never_passes_by_approved_flag_alone(tmp_path):
    manager, calls = setup_manager(tmp_path)
    model = manager.model
    async def incomplete(store, purpose, payload):
        data, receipt = await model(store, purpose, payload)
        if purpose == '独立来源与冲突核对':
            data['goal_complete'] = False
        return data, receipt
    manager.model = incomplete
    result = run(manager)
    assert result['status'] == 'retry_pending'
    assert len(calls) == 9  # plan, three drafts/reviews, two bounded repairs
    assert not result['changed_pages']
    assert manager.states()['software']['pending_run'] == result['id']
    assert manager.states()['software']['retry_count'] == 1


@pytest.mark.parametrize('call_limit,expected_step,remaining', [(1, 'draft', 2), (2, 'review', 1)])
def test_budget_resume_reuses_original_goal_and_saved_step(tmp_path, call_limit, expected_step, remaining):
    manager, calls = setup_manager(tmp_path)
    manager.configure({'daily_model_calls': call_limit})
    first = run(manager)
    assert first['status'] == 'budget_wait' and first['cursor'] == expected_step
    assert len(calls) == call_limit
    # Only the controlled fixture budget is replenished; no live usage is reset.
    _write_json(manager.root / 'budget.json', {'date': '2000-01-01', 'calls': 0})
    manager.configure({'daily_model_calls': 96})
    second = run(manager)
    assert second['status'] == 'completed', second
    assert second['resumed_from'] == first['id']
    assert second['original_goal'] == first['original_goal']
    assert calls.count('行业学习选题') == 1
    assert len(calls) == call_limit + remaining


def test_restart_restores_interrupted_review(tmp_path):
    manager, calls = setup_manager(tmp_path)
    manager.configure({'daily_model_calls': 2})
    first = run(manager)
    manager.save(first, status='reviewing')
    manager.recover()
    assert manager.states()['software']['pending_run'] == first['id']
    manager.configure({'daily_model_calls': 96})
    second = run(manager)
    assert second['status'] == 'completed', second
    assert calls == ['行业学习选题', '有依据的知识整理', '独立来源与冲突核对']


def test_recovery_does_not_replace_newer_success_with_an_old_abandoned_run(tmp_path):
    manager, _ = setup_manager(tmp_path)
    completed = run(manager)
    stale = {'id': '9' * 32, 'agent_id': 'software', 'kind': 'learning',
             'status': 'reviewing', 'started_at': '2000-01-01T00:00:00+00:00'}
    manager.save(stale)
    manager.recover()
    state = manager.states()['software']
    assert state['status'] == 'completed' and state['last_run'] == completed['id']
    assert not state.get('pending_run')


def test_tampered_saved_sources_are_reread_before_resume(tmp_path):
    manager, calls = setup_manager(tmp_path)
    manager.configure({'daily_model_calls': 2})
    first = run(manager)
    folder = manager.root / 'runs' / first['id']
    source = read_json(folder / 'sources.json', {})['sources'][0]
    (folder / source['file']).write_text('tampered')
    manager.configure({'daily_model_calls': 96})
    second = run(manager)
    assert second['status'] == 'completed', second
    assert second['source_attempt'] == 1
    assert calls.count('行业学习选题') == 1
    assert calls.count('有依据的知识整理') == 2


@pytest.mark.parametrize('destination', ['central', 'published'])
def test_edited_mirrors_are_preserved_as_reviewed_version_is_created(tmp_path, destination):
    manager, _ = setup_manager(tmp_path)
    first = run(manager)
    relative = first['changed_pages'][0]
    if destination == 'central':
        page = manager.store._wiki('central') / ('autonomous/software/' + relative.split('/')[-1])
    else:
        page = manager.store.base / ('published/software/' + relative)
    page.write_text(page.read_text() + '\n用户独立修改。')
    before = page.read_bytes()
    second = run(manager)
    assert second['status'] == 'completed', second
    assert second['publication']['conflict_resolution']['strategy'] == 'preserve_and_version'
    assert page.read_bytes() == before
    assert second['changed_pages'] != first['changed_pages']


def test_concurrent_knowledge_edit_requires_another_review(tmp_path):
    manager, calls = setup_manager(tmp_path)
    model = manager.model
    changed = manager.store._wiki('software') / 'manual.md'
    changed.write_text('# 人工说明\n旧条件。')
    count = 0
    async def concurrent(store, purpose, payload):
        nonlocal count
        data, receipt = await model(store, purpose, payload)
        if purpose == '独立来源与冲突核对':
            count += 1
            if count == 1:
                changed.write_text('# 人工说明\n刚刚修改的适用条件。')
            else:
                assert any('刚刚修改' in p['body'] for p in payload['existing_knowledge'])
        return data, receipt
    manager.model = concurrent
    result = run(manager)
    assert result['status'] == 'completed', result
    assert count == 2 and '刚刚修改' in changed.read_text()


def test_long_document_excerpt_reaches_requested_section_without_splicing():
    from federation.autonomy_sources import _excerpt
    text = ('Unrelated introduction. ' * 1000 + '\nAppLifecycleListener onResume dispose\n' + 'Details. ' * 2000)
    excerpt = _excerpt(text, 'AppLifecycleListener onResume dispose')
    assert 'AppLifecycleListener' in excerpt and excerpt in text
    assert len(excerpt.encode()) <= 14000


def test_nested_documentation_table_keeps_literal_commands():
    from federation.autonomy_sources import _plain_document
    raw = '''<html><article><h1>Environment guide</h1><p>Create an isolated environment for dependencies.
    Use the command corresponding to your platform and shell in the following table.</p>
    <table><tr><th>Platform</th><th>Shell</th><th>Command</th></tr>
    <tr><td><p>POSIX</p></td><td><p>bash/zsh</p></td><td><p><code class="samp docutils literal notranslate"><span class="pre">source</span> <em><span class="pre">&lt;venv&gt;</span></em><span class="pre">/bin/activate</span></code></p></td></tr>
    <tr><td><p>Windows</p></td><td><p>cmd.exe</p></td><td><p><code><span>&lt;venv&gt;</span><span>\\Scripts\\activate.bat</span></code></p></td></tr></table>
    <p>Deactivate your environment when the work is complete. These instructions apply to an existing environment.</p>
    <script>hidden_secret()</script></article></html>'''
    text = _plain_document({'body': raw.encode(), 'url': 'https://example.org/guide'})
    assert 'source <venv>/bin/activate' in text
    assert '<venv>\\Scripts\\activate.bat' in text
    assert 'hidden_secret' not in text


def test_large_standard_uses_a_bounded_contiguous_passage_with_explicit_scope():
    from federation.autonomy_sources import _read_document, _plain_document
    paragraphs = ''.join('<p>Section ' + str(i) + ': A general background explanation about document organization '
                         'and application behavior unrelated to the selected learning topic.</p>' for i in range(1400))
    raw = ('<html><head><title>Example standard</title></head><body><article><h1>Example standard</h1>' + paragraphs +
           '<p>requestSubmit uses novalidate and formnovalidate when determining constraint validation behavior.</p>' +
           '</article></body></html>').encode()
    response = {'url': 'https://example.org/standard', 'body': raw, 'headers': {'content-type': 'text/html'}}
    full = _plain_document(response)
    result = _read_document(response, 'requestSubmit novalidate formnovalidate validation')
    assert len(full.encode()) > 80000
    assert result['archive_scope'] == 'selected_passage'
    assert result['full_text_sha256'] == digest(full)
    assert result['text'] in full and 'requestSubmit' in result['text']
    assert len(result['text'].encode()) <= 14000


def test_failed_short_toc_reader_still_follows_topic_link(tmp_path, monkeypatch):
    from federation import autonomy_sources as sources
    manager, _ = setup_manager(tmp_path)
    visited = []
    async def searching(store, query):
        return {'sources': [{'url': 'https://example.org/docs'}]}
    async def ranking(store, name, **kwargs):
        return kwargs['candidates']
    class Fetcher:
        def __init__(self, **kwargs): pass
        def fetch(self, url):
            visited.append(url)
            return {'url': url}
    def extracting(response):
        if response['url'].endswith('/docs'): raise ValueError('目录正文不足')
        return {'title': 'Specific guide', 'text': TEXT}
    monkeypatch.setattr(sources, 'search', searching)
    monkeypatch.setattr(sources, 'strategy', ranking)
    monkeypatch.setattr(sources, 'SafeFetcher', Fetcher)
    monkeypatch.setattr(sources, 'extract_document', extracting)
    monkeypatch.setattr(sources, 'official_sites', lambda *args: ['https://unrelated.example/'])
    monkeypatch.setattr(sources, '_related_links', lambda r, q: ['https://example.org/guide'] if r['url'].endswith('/docs') else [])
    directory = tmp_path / 'sources'; directory.mkdir()
    result = asyncio.run(sources.discover(manager.store, manager.store.space('software'),
        {'query': 'site:example.org task owner'}, directory, 1))
    assert visited == ['https://example.org/docs', 'https://example.org/guide']
    assert result[0]['url'] == 'https://example.org/guide'
    assert read_json(directory / 'sources.json', {})['discovered_links'] == ['https://example.org/guide']


def test_short_specific_api_page_is_kept_instead_of_following_navigation(tmp_path, monkeypatch):
    from federation import autonomy_sources as sources
    manager, _ = setup_manager(tmp_path)
    visited = []
    async def searching(store, query): return {'sources': [{'url': 'https://example.org/catalog'}]}
    async def ranking(store, name, **kwargs): return list(reversed(kwargs['candidates']))
    class Fetcher:
        def __init__(self, **kwargs): pass
        def fetch(self, url):
            visited.append(url)
            return {'url': url}
    monkeypatch.setattr(sources, 'search', searching)
    monkeypatch.setattr(sources, 'strategy', ranking)
    monkeypatch.setattr(sources, 'SafeFetcher', Fetcher)
    monkeypatch.setattr(sources, 'extract_document', lambda r: {'title': 'requestSubmit() method', 'text': TEXT})
    monkeypatch.setattr(sources, '_related_links', lambda r, q: ['https://example.org/requestSubmit/contributors.txt'])
    directory = tmp_path / 'sources'; directory.mkdir()
    result = asyncio.run(sources.discover(manager.store, manager.store.space('software'),
        {'query': 'site:example.org requestSubmit', 'urls': ['https://example.org/requestSubmit']}, directory, 1))
    assert visited == ['https://example.org/requestSubmit']
    assert result[0]['url'] == visited[0]
