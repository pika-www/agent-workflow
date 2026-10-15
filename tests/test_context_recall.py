import uuid
from federation.core import FederationStore
from federation.chat import ChatStore
from federation.context_memory import ContextMemory
from federation.conversation_window import ConversationWindow, MARKER
from federation.context_extract import literal_excerpt, is_literal_projection


def test_middle_constraints_and_original_recall(tmp_path):
    store=FederationStore(tmp_path/'data');store.init();chat=ChatStore(store)
    room=chat.create_room('direct',['central']);memory=ContextMemory(store);window=ConversationWindow(memory)
    text='日常无关内容。'*300+'退款预算必须保留 37 元。'+'日常无关内容。'*300
    original=chat.append_message(room,'user',text,round_id=uuid.uuid4().hex)
    memory.prepare(room,text,round_id=original['round_id'])
    prepared=window.prepare(room,'central',uuid.uuid4().hex)
    assert window.commit(room,prepared,{'revision':0,'compactions':1,'messages':[{'id':original['id'],'content':None}]})['status']=='saved'
    question=chat.append_message(room,'user','退款预算是多少？',round_id=uuid.uuid4().hex)
    recalled=window.prepare(room,'central',question['round_id'])
    assert recalled['recall']['selected_ids']==[original['id']]
    assert '37 元' in recalled['messages'][0]['content']
    assert room['messages'][0]['content']==text
    projected=literal_excerpt(text,320,question['content'])
    assert len(projected)<=320 and '37 元' in projected
    assert is_literal_projection(text,projected)
    assert not is_literal_projection(text,projected+'伪造')


def test_explicit_user_constraints_beat_long_assistant_and_ties_use_recency():
    from federation.context_extract import rank_originals, relevance_score
    messages=[{'id':'old','role':'user','content':'预约付款功能不要开启。'},
              {'id':'long','role':'assistant','content':('预约付款要求用户注册等产品功能一般讨论。'*500)},
              {'id':'new','role':'user','content':'预约付款功能不要开启。'}]
    selected=rank_originals(messages,'之前预约付款功能要求是什么？')
    assert [row[2] for row in selected]==['new','old']
    assert relevance_score('支付功能关闭','付款功能')>=2


def test_compound_project_query_keeps_other_project_original_within_budget(tmp_path):
    store=FederationStore(tmp_path/'data');store.init();chat=ChatStore(store)
    room=chat.create_room('direct',['central']);memory=ContextMemory(store);window=ConversationWindow(memory)
    texts=['岚桥项目预算上限23800元，交付日2026年12月2日。',
           '南岬项目的预算是99000元，仅适用于南岬，与岚桥无关。',
           '纠正：岚桥预算上限改为21700元，交付日改为2026年12月5日。',
           '岚桥三条保护限制：禁止上传云端、恢复前人工确认、不得覆盖历史。',
           '最早归档暗号是 ZM-84629。']
    for text in texts:chat.append_message(room,'user',text,round_id=uuid.uuid4().hex)
    prepared=window.prepare(room,'central',uuid.uuid4().hex)
    assert window.commit(room,prepared,{'revision':0,'compactions':1,'messages':[{'id':m['id'],'content':None} for m in prepared['messages']]})['status']=='saved'
    q=chat.append_message(room,'user','分别说出岚桥和南岬当前预算，再给岚桥交付日期、三条保护限制和最早归档暗号。',round_id=uuid.uuid4().hex)
    recalled=window.prepare(room,'central',q['round_id'])
    recovered=[m for m in recalled['messages'] if m['rehydrated']]
    assert any('99000' in m['content'] for m in recovered)
    assert any('ZM-84629' in m['content'] for m in recovered)
    assert sum(len(m['content']) for m in recovered)<=5400
    assert len(recovered)<=6
