"""User-turn focus must survive a failed attachment read and summary eviction."""
import base64
import json
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient
from federation.app import create_app, isolated_ask_environment
from federation.chat_stream import ReplyStreams
from federation.turn_focus import continuation_focus
from tests.test_reply_recovery import wait


def test_focus_uses_latest_user_source_and_stops_at_new_topic():
    old = {'id': 'old', 'role': 'user', 'content': '旧文件', 'files': [{'id': 'a'*32}]}
    new = {'id': 'new', 'role': 'user', 'content': '这里面是什么？', 'files': [{'id': 'b'*32, 'name': 'Flux.json'}]}
    room = {'messages': [old, new, {'id': 'error', 'role': 'assistant', 'content': '旧附件答案', 'status': 'failed'}]}
    focus = continuation_focus(room, '继续')
    assert focus['source_message_id'] == 'new' and focus['files'][0]['id'] == 'b'*32
    room['messages'].append({'id': 'legacy', 'role': 'user', 'content': '继续'})
    assert continuation_focus(room, '继续')['source_message_id'] == 'new'
    room['messages'].append({'id': 'followup', 'role': 'user', 'content': '继续', 'turn_focus': focus})
    assert continuation_focus(room, '继续')['source_message_id'] == 'new'
    assert continuation_focus(room, '继续', ['c'*32]) is None
    assert continuation_focus(room, '继续', excluded_ids=['new']) is None
    assert continuation_focus(room, '继续讨论数据库') is None
    room['messages'].append({'id': 'topic', 'role': 'user', 'content': '解释数据库索引'})
    assert continuation_focus(room, '继续')['files'] == []
    assert continuation_focus(room, '这里面是什么？') is None


def test_failed_attachment_then_continue_and_resume_keep_scope(tmp_path):
    turns = []
    async def runner(turn, store):
        isolated_ask_environment(store, turn)
        turns.append(json.loads(json.dumps(turn)))
        if len(turns) == 1:
            raise RuntimeError('连接中断')
        turn['answer'] = '已读取当前 Flux 附件。'
    app = create_app(base=tmp_path/'data', runner=runner)
    with TestClient(app) as client:
        room = client.post('/api/chat/primary', json={}).json()
        url = '/api/chat/rooms/'+room['id']
        def upload(name, content):
            return client.post(url+'/files', json={'filename': name, 'data_base64': base64.b64encode(content.encode()).decode()}).json()
        old = upload('旧文件.txt', '旧附件无关内容')
        current = upload('Flux.json', '{"nodes":["Flux","中文提示词"]}')
        # A long unrelated completed answer and a stale task summary reproduce
        # the old-file bias without sending private user data to any provider.
        stored = app.state.chat.get_room(room['id'])
        app.state.chat.append_message(stored, 'user', '旧附件是什么？', round_id='a'*32)['files'] = [old]
        app.state.chat.append_message(stored, 'assistant', '旧附件内容。'*4000, agent_id='central', round_id='a'*32, phase='consultation')
        app.state.chat.save_room(stored)
        original = client.post(url+'/messages', json={'content': '这里面是什么？', 'file_ids': [current['id']]}).json()['job']['id']
        assert wait(client, original)['status'] == 'failed'
        continued = client.post(url+'/messages', json={'content': '继续'}).json()['job']['id']
        assert wait(client, continued)['status'] == 'completed'
        turn = turns[-1]
        assert turn['tool_policy']['selected_file_ids'] == [current['id']]
        assert turn['tool_policy']['has_attachments'] and not turn['tool_policy']['use_tool_model']
        assert turn['context_memory']['turn_focus']['question'] == '这里面是什么？'
        assert turn['context_memory']['turn_focus']['files'][0]['id'] == current['id']
        assert turn['context_memory']['goal'] == '这里面是什么？'
        again = client.post(url+'/messages', json={'content': '继续'}).json()['job']['id']
        assert wait(client, again)['status'] == 'completed'
        assert turns[-1]['tool_policy']['selected_file_ids'] == [current['id']]
        assert turns[-1]['context_memory']['turn_focus']['files'][0]['id'] == current['id']
        resumed = client.post(url+'/jobs/'+original+'/resume', json={})
        assert resumed.status_code == 200
        assert wait(client, resumed.json()['job']['id'])['status'] == 'completed'
        assert turns[-1]['tool_policy']['selected_file_ids'] == [current['id']]
        assert app.state.store.space('central')['knowledge_count'] == 0


def test_stream_accepts_every_registered_native_tool_but_not_unknown_tools():
    source = Path(__file__).resolve().parents[1]
    result = subprocess.run(['node', '--input-type=module', '-e',
        "import {NATIVE_TOOL_NAMES} from './federation/native-agent.mjs'; console.log(JSON.stringify(NATIVE_TOOL_NAMES));"],
        cwd=source, capture_output=True, text=True, check=True)
    hub = ReplyStreams(); hub.start('room', 'job')
    for name in json.loads(result.stdout):
        event = {'origin':'host_tool','protocol':'responses','type':'agent.tool.started','call_id':name,'name':name}
        hub.native_event('room','job',event)
        hub.native_event('room','job',{**event,'type':'agent.tool.completed','status':'completed'})
    assert all(item['status']=='completed' for item in hub.snapshot('room','job')['operations'])


def test_checkpoint_keeps_ninth_through_32nd_attachment_reads(tmp_path):
    hub=ReplyStreams(tmp_path);hub.start('a'*32,'b'*32)
    state={'schema_version':1,'kind':'native_agent','fingerprint':'c'*64,'protocol':'responses',
           'input':[{'role':'user','content':'当前附件'}], 'turn_index':32,'visible_count':1,'answer':'',
           'observations':[{'tool':'file_read'} for _ in range(32)],
           'receipts':[{'call_id':str(i),'tool':'file_read'} for i in range(32)],
           'message_items':[], 'usage':[{} for _ in range(32)], 'completed':False}
    hub.checkpoint('a'*32,'b'*32,state)
    assert hub.load_saved('b'*32)['checkpoint'] == state
