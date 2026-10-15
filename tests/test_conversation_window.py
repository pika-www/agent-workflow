import json
import uuid
from pathlib import Path
from federation.core import FederationStore
from federation.chat import ChatStore
from federation.context_memory import ContextMemory
from federation.conversation_window import ConversationWindow, MARKER


def test_window_accumulates_across_topics_and_preserves_originals(tmp_path):
    store=FederationStore(tmp_path/'data');store.init();chat=ChatStore(store)
    room=chat.create_room('direct',['central'],'window test');memory=ContextMemory(store);windows=ConversationWindow(memory)
    def add(text, role='user'):
        result=chat.append_message(room,role,text,agent_id='central' if role=='assistant' else None,
                                  phase='consultation',round_id=uuid.uuid4().hex)
        chat.save_room(room);return result
    first=add('首段'+'原始中段'*1000+'尾段')
    reply=add('这是此前的完整回复。','assistant')
    current=add('换个话题，聊招聘软件')
    memory.prepare(room,current['content'],round_id=current['round_id'])
    before=(chat.root/(room['id']+'.json')).read_bytes()
    prepared=windows.prepare(room,'central',current['round_id'])
    assert [m['id'] for m in prepared['messages']]==[first['id'],reply['id']]
    assert prepared['messages'][0]['content']==first['content']
    projected=first['content'][:100]+MARKER+first['content'][-100:]
    update={'revision':0,'compactions':1,'messages':[{'id':first['id'],'content':projected},{'id':reply['id'],'content':reply['content']}]}
    assert windows.commit(room,prepared,update)['status']=='saved'
    add('软件可以按使用人群区分。','assistant')
    next_question=add('我是干啥的？')
    restored=ConversationWindow(ContextMemory(store)).prepare(room,'central',next_question['round_id'])
    assert restored['compaction_count']==1
    assert restored['messages'][0]['content']==projected
    assert len(restored['messages'])==4
    assert first['content'].encode() in before
    assert room['messages'][0]['content']==first['content']
    assert windows.commit(room,prepared,update)['status']=='stale'
    other=chat.create_room('direct',['central'],'other')
    assert not windows.prepare(other,'central',uuid.uuid4().hex)['messages']


def test_window_rejects_invented_projection_and_honors_forgetting(tmp_path):
    store=FederationStore(tmp_path/'data');store.init();chat=ChatStore(store)
    room=chat.create_room('direct',['central'],'forget');memory=ContextMemory(store);windows=ConversationWindow(memory)
    message=chat.append_message(room,'user','这是必须保留的原话。',round_id=uuid.uuid4().hex)
    context=memory.prepare(room,message['content'],round_id=message['round_id'])
    prepared=windows.prepare(room,'central',uuid.uuid4().hex)
    assert windows.commit(room,prepared,{'revision':0,'compactions':1,'messages':[{'id':message['id'],'content':'伪造的摘要'}]})['status']=='rejected'
    memory.edit(room['id'],'central',context['task_id'],context['revision'],'forget')
    assert not windows.prepare(room,'central',uuid.uuid4().hex)['messages']
    assert len(room['messages'])==1
