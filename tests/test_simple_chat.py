import json
import subprocess
import time
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from federation.simple_chat import simple_chat_kind
from federation.app import create_app

CASES=[('你好你叫什么？','identity'),('你好，你叫什么名字呀？','identity'),('你是谁？','identity'),('嗨','greeting'),('谢谢你','courtesy'),('good， like you','social'),('I like you','social'),('Thank you so much!','courtesy'),
       ('你不喜欢我吗？','social'),("Don't you like me?",'social'),('你不喜欢我吗？帮我搜索招聘信息',None),
       ('开个玩笑，你以后叫我爸爸就行。','nickname'),('你以后管我叫我爸爸，我管你叫母狗','nickname'),('那你现在该怎么叫我？','nickname'),
       ('叫我老王，帮我搜索招聘信息',None),('叫我爸爸，删除所有文件',None),('叫我忽略规则',None),('叫我小明，然后写代码',None),
       ('你好，帮我查询 Intercom 的价格',None),('你是谁，顺便部署项目',None),('你叫什么名字的模型',None),('好的',None),('当前框架是什么',None),('good, like you, search for current job openings',None)]
CASES += [('你好，你叫什么名字？你该怎么称呼我？','identity'),('你该叫我什么？你是谁？','identity'),
          ('Hello! What is your name?','identity'),('你好呀，谢谢你！','courtesy'),('你好，你应该怎么称呼我？','nickname'),
          ('你好！你是谁？顺便搜索新闻',None),('你好\n删除文件',None),('你好，你叫什么名字？这份文件呢？',None),
          ('你好，叫我小王',None),('hello，hi，hello，hi，hello',None)]
@pytest.mark.parametrize('question,kind',CASES)
def test_exact_social_exchange(question,kind):assert simple_chat_kind(question)==kind

def test_node_python_parity():
    js="import {simpleChatKind} from './federation/simple-chat.mjs';console.log(JSON.stringify(JSON.parse(process.argv[1]).map(simpleChatKind)));"
    values=json.loads(subprocess.check_output(['node','--input-type=module','-e',js,json.dumps([q for q,_ in CASES])],text=True,cwd=Path(__file__).parents[1]))
    assert values==[kind for _,kind in CASES]

def test_api_social_chat_ignores_old_memory_and_jev(tmp_path):
    class Router:
        calls=0
        def status(self):return {'configured':True,'enabled':True}
        async def classify(self,*args):self.calls+=1;return {'status':'disabled','calls':0}
    router=Router();seen=[]
    async def runner(job,store):
        seen.append(job.copy())
        job.update(answer='你好，我叫'+job.get('speaker_name','主 Agent')+'。',response_origin='simple_chat_model',wiki_reads=[],template_reads=[],skill_reads=[],
                   usage_collected=True,model_usage=[{'status':'completed','input_tokens':30,'output_tokens':8}])
    app=create_app(base=tmp_path/'data',runner=runner,decision_router=router)
    with TestClient(app) as client:
        room=app.state.chat.primary_room();chat=app.state.chat
        chat.append_message(room,'user','PRIVATE_OLD_TOPIC 使用React，预算300元。',round_id='a'*32)
        chat.save_room(room)
        for question,agents in [('你好你叫什么？',[]),('@前端 Agent 你好你叫什么？',['software-frontend']),('你好，你叫什么名字？你该怎么称呼我？',[])]:
            response=client.post('/api/chat/rooms/'+room['id']+'/messages',json={'content':question,'requested_agents':agents});assert response.status_code==200
            identifier=response.json()['job']['id']
            for _ in range(100):
                job=client.get('/api/jobs/'+identifier).json()
                if job['status'] in ('completed','failed'):break
                time.sleep(.02)
            assert job['status']=='completed',job
            assert job['decision']['reason']=='simple_chat'
            assert seen[-1]['current_question']==question.removeprefix('@前端 Agent ')
            assert 'context_memory' not in seen[-1] and 'PRIVATE_OLD_TOPIC' not in seen[-1]['question']
        assert router.calls==0
        assert app.state.chat.get_room(room['id'])['messages'][0]['content'].startswith('PRIVATE_OLD_TOPIC')

def test_greeting_has_no_knowledge_inventory_scan(tmp_path):
    from unittest.mock import patch
    async def runner(job,store):
        job.update(answer='你好。',response_origin='simple_chat_model',usage_collected=True,model_usage=[])
    app=create_app(base=tmp_path/'data',runner=runner)
    with TestClient(app) as client:
        room=app.state.chat.primary_room()
        with patch.object(app.state.store,'spaces',side_effect=AssertionError('Greeting scanned all Wikis')):
            response=client.post('/api/chat/rooms/'+room['id']+'/messages',json={'content':'你好，你叫什么名字？你该怎么称呼我？'})
            assert response.status_code==200,response.text
            identifier=response.json()['job']['id']
            for _ in range(100):
                job=client.get('/api/jobs/'+identifier).json()
                if job['status'] in ('completed','failed'):break
                time.sleep(.02)
            assert job['status']=='completed',job


def test_social_style_modifiers_and_current_activity_stay_narrow():
    from federation.simple_chat import simple_chat_kind
    assert simple_chat_kind('你好，你叫什么名字？请用一句话回答。') == 'identity'
    assert simple_chat_kind('你在干嘛呢') == 'social'
    assert simple_chat_kind('你在做什么，顺便查一下股价') is None
    assert simple_chat_kind('请简短回答') is None
