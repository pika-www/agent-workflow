"""Owned isolated UI fixture; never reads or modifies the user's chat store."""
import json
import sys
import tempfile
import uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uvicorn
from federation.app import create_app

ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='project-memory-ui-') as root:
    app=create_app(base=Path(root)/'data');chat=app.state.chat;memory=app.state.context_memory
    room=chat.primary_room()
    room['title']='隔离测试 · 心跳页面项目'
    for i in range(3):
        rid=uuid.uuid4().hex;question='心跳页面使用 React，不联网，必须保留原始聊天记录。' if i==0 else '继续这个心跳页面。'
        chat.append_message(room,'user',question,round_id=rid);ctx=memory.prepare(room,question,'central',rid)
        message=chat.append_message(room,'assistant','仅提供设计咨询，尚未部署。',agent_id='central',phase='consultation',round_id=rid)
        if i<2:
            message['context_usage']={'enabled':True,'task_id':ctx['task_id'],'total_calls':2,'total_input_tokens':520+i*30,'total_output_tokens':90,'total_input_tokens_estimated':600,'reply':{'input_tokens':400+i*30,'output_tokens':70,'cached_tokens':128},'summary':{'calls':0,'input_tokens':0,'output_tokens':0,'status':'not_needed'}}
            message['answer_check']={'model_usage':[{'input_tokens':120,'output_tokens':20}]}
            message['timing']={'request_first_text_ms':1800+i*800}
        memory.complete_turn(room,ctx,rid)
    chat.save_room(room)
    target=chat.create_room('direct',['central'],'隔离测试 · 新会话续接')
    (ROOT/'outputs/project-memory-20261006/ui-fixture.json').write_text(json.dumps({'port':18744,'room':room['id'],'target':target['id'],'scope':'synthetic isolated UI fixture'},indent=2))
    uvicorn.run(app,host='127.0.0.1',port=18744,log_level='warning')
