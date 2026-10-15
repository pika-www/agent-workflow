import json
import uuid
from unittest.mock import patch

import pytest

from federation.app import create_app, isolated_ask_environment
from federation.report_model import _write_private
from federation.tool_services import save_service, model_config, configuration


def test_fast_model_is_scoped_and_keeps_identity_memory_and_offline_policy(tmp_path):
    app = create_app(base=tmp_path/'data')
    store = app.state.store
    _write_private(store.base/'private/report-model.json', {'provider':'openai-compatible', 'model':'main-model',
        'base_url':'https://example.com/v1', 'api_key':'test-only', 'responses_api':True})
    save_service(store, 'tool_agent', {'simple_chat_model':'fast-model'})
    assert model_config(store, 'tool_agent')['model'] == 'main-model'
    assert model_config(store, 'tool_agent', simple_chat=True)['model'] == 'fast-model'
    assert model_config(store, 'vision', simple_chat=True)['model'] == 'main-model'
    room = app.state.chat.primary_room()
    app.state.chat.append_message(room, 'user', '叫我老王', round_id='a'*32)
    app.state.chat.save_room(room)

    def prepare(question, **extra):
        job = {'id':uuid.uuid4().hex, 'space':'central', 'room_id':room['id'],
               'question':question, 'current_question':question, 'delegation_phase':'consultation', **extra}
        env = isolated_ask_environment(store, job)
        config = json.loads(open(env['FEDERATION_TOOL_AGENT_MODEL_CONFIG']).read()) if 'FEDERATION_TOOL_AGENT_MODEL_CONFIG' in env else None
        return job, config

    greeting, config = prepare('你好，你叫什么名字？你该怎么称呼我？')
    assert config['model'] == 'fast-model' and config['reasoning_effort'] == 'none'
    assert greeting['workspace_context']['name'] == '未明'
    assert greeting['workspace_context']['nicknames']['user_address'] == '老王'
    assert greeting['workspace_context']['soul'] and greeting['workspace_context']['rules']
    assert greeting['wait_for_model'] is True
    assert not greeting['tool_policy']['tools_enabled']
    for question in ('解释 RAG 原理', '你好，顺便搜索今天的新闻', '我的长期记忆有哪些？'):
        ordinary, config = prepare(question)
        assert config['model'] == 'main-model' and ordinary['wait_for_model'] is False
    assert prepare('不联网，解释 RAG')[1] is None
    with patch('federation.conversation_knowledge.policy', return_value={'default_online':False,'auto_refresh':False}):
        offline, config = prepare('你好')
        assert config is None and offline['wait_for_model'] is False
    save_service(store, 'tool_agent', {'enabled':False})
    assert prepare('你好')[1] is None
    save_service(store, 'tool_agent', {'enabled':True,'simple_chat_model':''})
    assert prepare('你好')[1]['model'] == 'main-model'
    assert 'simple_chat_model' not in configuration(store)['tool_agent']


@pytest.mark.parametrize('service,value', [('image','fast'),('tool_agent',True),('tool_agent','bad model'),('tool_agent','../bad')])
def test_fast_model_configuration_rejects_wrong_scope_and_values(tmp_path, service, value):
    store = create_app(base=tmp_path/'data').state.store
    with pytest.raises(ValueError):
        save_service(store, service, {'simple_chat_model':value})


def test_protocol_and_backup_are_scoped_to_simple_chat(tmp_path):
    app = create_app(base=tmp_path/'data')
    store = app.state.store
    _write_private(store.base/'private/report-model.json', {'provider':'openai-compatible', 'model':'main-model',
        'base_url':'https://example.com/v1', 'api_key':'test-only', 'responses_api':True})
    save_service(store, 'tool_agent', {'simple_chat_model':'primary', 'simple_chat_responses_api':False,
                                     'simple_chat_fallback_model':'backup'})
    simple = model_config(store, 'tool_agent', simple_chat=True)
    normal = model_config(store, 'tool_agent')
    assert simple['model'] == 'primary' and simple['responses_api'] is False
    assert simple['simple_chat_fallback_model'] == 'backup'
    assert normal['model'] == 'main-model' and normal['responses_api'] is True
    assert 'simple_chat_fallback_model' not in normal
    save_service(store, 'tool_agent', {'simple_chat_fallback_model':''})
    assert 'simple_chat_fallback_model' not in model_config(store, 'tool_agent', simple_chat=True)


@pytest.mark.parametrize('service,value', [('image',{'simple_chat_fallback_model':'backup'}),
    ('tool_agent',{'simple_chat_fallback_model':True}), ('tool_agent',{'simple_chat_fallback_model':'bad model'}),
    ('image',{'simple_chat_responses_api':False}), ('tool_agent',{'simple_chat_responses_api':'false'})])
def test_backup_configuration_validation(tmp_path, service, value):
    store = create_app(base=tmp_path/'data').state.store
    with pytest.raises(ValueError): save_service(store, service, value)
