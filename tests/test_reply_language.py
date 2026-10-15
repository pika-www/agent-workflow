from federation.intake import build_intake_prompt
from federation.chat import ChatStore
from federation.core import FederationStore
from federation.reply_language import REPLY_LANGUAGE_POLICY


def test_intake_does_not_force_chinese():
    for question in ['Hello!', 'Explain React hooks.', '请用英文解释闭包。']:
        for kind in ['answer', 'proposal', 'revision']:
            prompt = build_intake_prompt(question, kind=kind)
            assert REPLY_LANGUAGE_POLICY in prompt
            assert '用简体中文' not in prompt
            assert question in prompt


def test_specialist_prompt_does_not_force_chinese(tmp_path):
    store = FederationStore(tmp_path / 'data', project_root=tmp_path / 'project')
    store.init()
    chat = ChatStore(store)
    room = chat.create_room('direct', ['software'])
    chat.append_message(room, 'user', 'Explain React hooks.')
    prompt = chat.turn_prompt(room, 'software', 'discussion')
    assert REPLY_LANGUAGE_POLICY in prompt
    assert '用简体中文' not in prompt
