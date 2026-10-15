"""Personal recall is accepted locally and retains private context, not a greeting."""
import json
import subprocess
import time
from pathlib import Path

from fastapi.testclient import TestClient
from federation.app import create_app, isolated_ask_environment
from federation.personal_profile import PERSONAL_IDENTITY
from tests.test_reply_recovery import wait


def test_python_node_personal_routing_agree():
    cases = [
        ('hello Do you know me?', True), ('Hello, do you remember me?', True),
        ('What do you know about me?', True), ('Hi, who am I?', True),
        ("What's my name?", True), ('你好，你认识我吗？', True),
        ('你还记得我吗？', True), ('我是谁？我叫什么？', True),
        ('hello', False), ('Who are you?', False),
        ('Do you know me? Search for React jobs.', False),
        ('你好，你认识我吗？顺便查招聘软件', False),
        ('What do you know about memory management?', False),
    ]
    expected = [expected for _, expected in cases]
    assert [bool(PERSONAL_IDENTITY.fullmatch(q)) for q, _ in cases] == expected
    script = "import {personalIdentityQuestion} from './federation/personal-profile.mjs';console.log(JSON.stringify(JSON.parse(process.argv[1]).map(personalIdentityQuestion)));"
    actual = subprocess.check_output(['node', '--input-type=module', '-e', script,
                                     json.dumps([q for q, _ in cases])], text=True,
                                    cwd=Path(__file__).resolve().parents[1])
    assert json.loads(actual) == expected


def test_personal_send_bypasses_remote_router_preserves_profile_and_history(tmp_path):
    class Router:
        def status(self): return {'configured': True, 'enabled': True}
        async def classify(self, *args):
            raise AssertionError('Personal recall must not wait for remote intent routing')

    seen = []
    async def runner(job, store):
        isolated_ask_environment(store, job)
        seen.append(job.copy())
        job.update(answer='你叫测试林，是前端开发者。', response_origin='personal_identity_model')

    app = create_app(base=tmp_path/'data', runner=runner, decision_router=Router())
    with TestClient(app) as client:
        client.post('/api/user-profile', json={'expected_revision': 0, 'about': '我叫测试林，是前端开发者。',
                                             'resume_text': '使用 React 和 TypeScript 开发应用。'})
        room = app.state.chat.primary_room()
        app.state.chat.append_message(room, 'user', '上次聊到学习 TypeScript。', round_id='a'*32)
        app.state.chat.save_room(room)
        for question in ['hello Do you know me?', '你认识我吗？']:
            started = time.monotonic()
            response = client.post('/api/chat/rooms/'+room['id']+'/messages', json={'content': question})
            assert response.status_code == 200, response.text
            assert time.monotonic()-started < 1.5
            job = response.json()['job']
            assert job['decision']['reason'] == 'personal_recall'
            assert job['intake_kind'] == 'answer'
            assert not job.get('simple_chat') and not job.get('tool_request')
            assert wait(client, job['id'])['status'] == 'completed'
            turn = seen[-1]
            assert turn['memory_context']['profile']['required_for_question']
            assert '测试林' in json.dumps(turn['memory_context'], ensure_ascii=False)
            assert turn['conversation_window']
        assert app.state.chat.get_room(room['id'])['messages'][0]['content'] == '上次聊到学习 TypeScript。'

