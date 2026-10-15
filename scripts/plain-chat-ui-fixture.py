"""Owned disposable chat store; real ordinary reply, external routing disabled."""
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uvicorn
from federation.app import create_app

ROOT=Path(__file__).resolve().parents[1]
class NoExternalRouter:
    def status(self):return {'provider':'isolated-fixture','configured':False,'enabled':False}
    async def classify(self,*args):raise RuntimeError('This fixture only accepts host-routed ordinary chat.')

with tempfile.TemporaryDirectory(prefix='plain-chat-ui-') as folder:
    app=create_app(base=Path(folder)/'data',decision_router=NoExternalRouter())
    chat=app.state.chat;room=chat.primary_room();room['title']='隔离测试 · 普通对话'
    # A separate archived turn checks that old topic/requirements stay out of a greeting.
    chat.append_message(room,'user','这个旧项目使用React，预算300元。',round_id='a'*32)
    context=app.state.context_memory.prepare(room,room['messages'][-1]['content'],'central','a'*32)
    example=chat.append_message(room,'assistant','这里只记录旧项目要求。',agent_id='central',phase='consultation',round_id='a'*32)
    example['context_usage']={'enabled':True,'total_calls':1,'total_input_tokens':300,'total_output_tokens':30,'input_tokens_estimated':320,
        'total_input_tokens_estimated':320,'budget':12000,'output_reserve':4096,'reply':{'input_tokens':300,'output_tokens':30},
        'summary':{'status':'not_needed','calls':0},'included':[],'omitted':[]}
    app.state.context_memory.complete_turn(room,context,'a'*32)
    chat.save_room(room)
    info={'port':18744,'room':room['id'],'temporary_root':folder,'scope':'disposable synthetic history; one real ordinary model reply; external router disabled'}
    (ROOT/'outputs/plain-chat-repair-20261008/ui-fixture.json').write_text(json.dumps(info,ensure_ascii=False,indent=2))
    uvicorn.run(app,host='127.0.0.1',port=18744,log_level='warning')
