"""Real local model over synthetic 100-round histories and explicit project links."""
import argparse
import json
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from federation.chat import ChatStore
from federation.context_memory import ContextMemory
from federation.core import FederationStore
from federation.project_memory import ProjectMemory

ROOT=Path(__file__).resolve().parents[1]


def run(output):
    output.mkdir(parents=True,exist_ok=True)
    report={'scope':'isolated-synthetic-100-round-multi-topic-history-with-real-local-Qwen','model':'qwen3.5:9b','synthetic_history_rounds':100,'cases':[]}
    with tempfile.TemporaryDirectory(prefix='project-memory-eval-') as root:
        store=FederationStore(Path(root)/'data');store.init();chat=ChatStore(store)
        memory=ContextMemory(store);projects=ProjectMemory(store,chat,memory);memory.projects=projects
        source=chat.create_room('direct',['central'],'隔离长历史来源')
        def prepared(room,question):
            rid=uuid.uuid4().hex;chat.append_message(room,'user',question,round_id=rid)
            return rid,memory.prepare(room,question,'central',rid)
        def finish(room,rid,context,answer):
            chat.append_message(room,'assistant',answer,agent_id='central',phase='consultation',round_id=rid)
            memory.complete_turn(room,context,rid);chat.save_room(room)
        for i in range(100):
            text='心跳页面使用 Vue，不联网，必须保留原始聊天记录。' if i==0 else ('改用 React，其他要求不变。' if i==27 else ('改用 Angular，其他要求不变。' if i==75 else f'继续这个心跳页面，讨论第{i}个细节。'))
            rid,context=prepared(source,text);finish(source,rid,context,'这是方案咨询，尚未部署。')
        def evaluate(name,room,question,required,forbidden=()):
            rid,context=prepared(room,question)
            request=output/(name+'-input.json');response=output/(name+'-response.json')
            request.write_text(json.dumps({'question':question,'context':context},ensure_ascii=False))
            subprocess.run(['node',str(ROOT/'scripts/evaluate-memory-turn.mjs'),str(request),str(response)],cwd=ROOT,check=True,timeout=120)
            result=json.loads(response.read_text());answer=result['answer']
            persistence=memory.commit(room,context,result.get('memory_update'))
            memory.record_summary_attempt(context,(result.get('context_usage') or {}).get('summary',{}))
            finish(room,rid,context,answer)
            checks={p:bool(re.search(p,answer,re.I)) for p in required};checks.update({'absent:'+p:not bool(re.search(p,answer,re.I)) for p in forbidden})
            case={'id':name,'question':question,'answer':answer,'checks':checks,'passed':all(checks.values()),'model':result.get('model'),'response_origin':result.get('response_origin','model'),'context_usage':result.get('context_usage'),'summary_persistence':persistence}
            report['cases'].append(case);(output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
            print(json.dumps({'case':name,'passed':case['passed'],'answer':answer,'summary_persistence':persistence},ensure_ascii=False),flush=True)
        evaluate('01-after-100-rounds',source,'继续，用一句话说出最终框架、资料范围和历史处理要求。',[r'Angular',r'不.*联网|本地|本库|离线',r'保留'])
        state=memory.inspect(source['id'],'central')
        result=projects.edit(source,'central',{'action':'create','expected_revision':0,'expected_task_revision':state['revision'],'task_id':state['active_task'],'binding_revision':0,'title':'隔离心跳项目','progress':'当前只有设计方案，尚未部署。','next_steps':'先核对曲线交互。','allowed_agents':['central']})
        project_id=result['project_id']
        evaluate('02-other-topic',source,'新话题：一个热点列表使用 Vue。用一句话确认这个新任务的框架。',[r'Vue'],[r'Angular|心跳'])
        target=chat.create_room('direct',['central'],'隔离新会话')
        evaluate('03-no-project-selection',target,'这个新会话里之前项目选的框架是什么？没有记忆就说无法确定。',[r'无法.*(?:确定|确认)|没有.*(?:记忆|记录|依据)|不知道|不清楚'])
        current=memory.inspect(target['id'],'central');project=projects.read()['projects'][project_id]
        projects.edit(target,'central',{'action':'attach','project_id':project_id,'expected_revision':project['revision'],'expected_task_revision':current['revision'],'task_id':current['active_task'],'binding_revision':0})
        memory=ContextMemory(store);projects.memory=memory;memory.projects=projects
        evaluate('04-selected-project-after-restart',target,'继续项目，用两句话复述框架、资料范围、历史处理，以及记录的部署状态。',[r'Angular',r'不.*联网|本地|本库|离线',r'保留',r'未部署|尚未|还没.*部署|没有.*部署'])
        evaluate('05-local-correction',target,'改用 React，其他要求不变。用一句话复述当前框架和资料范围。',[r'React',r'不.*联网|本地|本库|离线'],[r'使用\s*Angular'])
        third=chat.create_room('direct',['central'],'隔离遗忘验证');project=projects.read()['projects'][project_id]
        projects.edit(third,'central',{'action':'attach','project_id':project_id,'expected_revision':project['revision'],'expected_task_revision':0,'task_id':None,'binding_revision':0})
        rid,ctx=prepared(third,'继续这个项目。');finish(third,rid,ctx,'尚未部署。')
        state=memory.inspect(source['id'],'central');source_task=projects.read()['projects'][project_id]['source']['task_id']
        memory.edit(source['id'],'central',source_task,state['revision'],'forget')
        evaluate('06-source-forgotten',third,'继续，旧项目的框架是什么？若来源已忘记，不要从旧助手回复推断，直接说明无法确定。',[r'无法.*(?:确定|确认)|已.*忘记|没有.*(?:依据|记录|记忆)'])
    report.update(passed=sum(c['passed'] for c in report['cases']),total=len(report['cases']),real_model_cases=sum(c.get('model') is not None for c in report['cases']),limits='有限已知信号检查；100 轮历史为合成数据，普通验收问题调用真实本地模型，失效项目框架问题由宿主拦截且零次模型调用。不是完整语义正确率、实际用户节省比例或外部 API 验证。')
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));return report['passed']==report['total']


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'outputs/project-memory-20261006/model-eval');args=parser.parse_args()
    raise SystemExit(0 if run(args.output.resolve()) else 1)
