import base64
import json
from io import BytesIO
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from federation.app import create_app, isolated_ask_environment
from federation.core import FederationStore
from federation.personal_profile import read_profile, save_profile, profile_context
from tests.test_reply_recovery import wait


@pytest.fixture
def store(tmp_path):
    store = FederationStore(tmp_path/'data');store.init();return store


def test_explicit_profile_persistence_revision_scope_and_clear(store):
    assert read_profile(store)['revision'] == 0
    saved = save_profile(store, {'expected_revision': 0, 'about': '测试用户，从事前端开发', 'goals': '转向 AI 应用开发', 'preferences': '回答简短直接'})
    assert read_profile(FederationStore(store.base)) == saved
    assert (store.base/'private/user-profile.json').stat().st_mode & 0o777 == 0o600
    assert profile_context(store, '今天学什么', 'central')['sections'][0]['text'] == saved['about']
    assert profile_context(store, '今天学什么', 'software-frontend') is None
    with pytest.raises(ValueError, match='其他页面'):
        save_profile(store, {'expected_revision': 0, 'about': '不会覆盖'})
    assert read_profile(store) == saved
    saved = save_profile(store, {**saved, 'expected_revision': 1, 'scope': 'workspace'})
    assert profile_context(store, '学习', 'software-frontend')
    save_profile(store, {**saved, 'expected_revision': 2, 'enabled': False})
    assert profile_context(store, '学习', 'central') is None
    save_profile(store, {'expected_revision': 3, 'enabled': False})
    assert not read_profile(store)['about']
    assert '测试用户' not in (store.base/'private/user-profile.json').read_text()


def test_resume_selection_redacts_contacts_and_never_publishes(store):
    resume = '测试资料\n电话 13800138000 邮箱 sample@example.com\n擅长 React 和 TypeScript。\n' + '其他经历。'*500 + '\nFlutter 移动端项目，负责播放器。'
    save_profile(store, {'expected_revision': 0, 'resume_name': '测试简历.txt', 'resume_text': resume})
    everyday = profile_context(store, '今天该学什么', 'central')
    assert len(everyday['sections']) == 1
    assert 'React' in everyday['sections'][0]['text']
    assert 'Flutter' not in everyday['sections'][0]['text']
    context = profile_context(store, '我的 Flutter 项目经历是什么', 'central')
    assert context['required_for_question'] is True
    assert profile_context(store, '我是谁？我叫什么？', 'central')['required_for_question'] is True
    assert everyday['required_for_question'] is False
    assert any('Flutter' in s['text'] for s in context['sections'])
    assert len(context['sections']) <= 3
    contact_context = json.dumps(profile_context(store, '总结我的简历', 'central'), ensure_ascii=False)
    assert '13800138000' not in contact_context and 'sample@example.com' not in contact_context
    assert read_profile(store)['resume_text'] == resume
    assert store.space('central')['knowledge_count'] == 0
    with pytest.raises(ValueError, match='密码'):
        save_profile(store, {'expected_revision': 1, 'about': '密码：do-not-store'})


def test_english_identity_keeps_resume_even_with_short_about(store):
    save_profile(store, {'expected_revision': 0, 'about': '前端开发者', 'resume_text': '测试林\nReact 开发。电话13800138000'})
    for question in ['hello Do you know me？', 'Who am I?', 'Do you remember me?', "What's my name?", 'What do you know about me?']:
        context = profile_context(store, question, 'central')
        assert context['required_for_question']
        assert any('测试林' in section['text'] for section in context['sections'])
        assert '13800138000' not in json.dumps(context)
    assert not profile_context(store, 'Do you know the song Do You Know Me?', 'central')['required_for_question']


def test_local_document_preview_does_not_save(tmp_path):
    app = create_app(base=tmp_path/'data')
    with TestClient(app) as client:
        before = client.get('/api/user-profile').json()
        for filename, raw in [('测试.txt', '测试用户，React 开发。'.encode()), ('测试.docx', docx_bytes())]:
            response = client.post('/api/user-profile/preview', json={'filename': filename, 'data_base64': base64.b64encode(raw).decode()})
            assert response.status_code == 200, response.text
            assert response.json()['saved'] is False
            assert 'React' in response.json()['text']
            assert client.get('/api/user-profile').json() == before
        invalid = client.post('/api/user-profile/preview', json={'filename': 'x.pdf', 'data_base64': 'invalid'})
        assert invalid.status_code == 400
        saved = client.post('/api/user-profile', json={'expected_revision': 0, 'about': '测试用户'})
        assert saved.status_code == 200
        assert client.post('/api/user-profile', json={'expected_revision': 0, 'about': 'stale'}).status_code == 400


def docx_bytes():
    from docx import Document
    document = Document();document.add_paragraph('测试简历 React 前端开发');output = BytesIO();document.save(output);return output.getvalue()


def test_new_room_automatically_receives_explicit_profile(tmp_path):
    seen = []
    async def runner(turn, store):
        isolated_ask_environment(store, turn);seen.append(turn)
        turn['answer'] = '按你提供的背景，你有前端经验，目标是 AI 应用开发。'
    class Router:
        def status(self): return {'configured': False, 'enabled': False}
        async def classify(self, *args): return {'provider': 'host-rules', 'status': 'bypassed'}
    app = create_app(base=tmp_path/'data', runner=runner, decision_router=Router())
    with TestClient(app) as client:
        assert client.post('/api/user-profile', json={'expected_revision': 0, 'about': '测试用户，有前端经验', 'goals': 'AI 应用开发', 'resume_text': '掌握 React 和 TypeScript'}).status_code == 200
        for _ in range(2):
            room = client.post('/api/chat/rooms', json={'mode': 'direct', 'participants': ['central'], 'title': '测试新会话'}).json()
            result = client.post('/api/chat/rooms/'+room['id']+'/messages', json={'content': '我适合往哪个方向发展？'})
            assert result.status_code == 200, result.text
            assert wait(client, result.json()['job']['id'])['status'] == 'completed'
            profile = seen[-1]['memory_context']['profile']
            assert '必须明确说明这一点' not in seen[-1]['question']
            assert '前端经验' in json.dumps(profile, ensure_ascii=False)
            assert 'React' in json.dumps(profile, ensure_ascii=False)
        assert app.state.store.space('central')['knowledge_count'] == 0
