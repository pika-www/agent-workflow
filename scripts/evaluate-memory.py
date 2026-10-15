"""Repeatable multi-turn model evaluation. Never opens or modifies user rooms."""
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

ROOT=Path(__file__).resolve().parents[1]
NETWORK=r'不.*联网|禁止联网|离线|本地|本库'

def score(report):
    for case in report['cases']:
        required=case.get('required_regex') or [key for key in case['checks'] if not key.startswith('absent:')]
        forbidden=case.get('forbidden_regex') or [key[7:] for key in case['checks'] if key.startswith('absent:')]
        # Version 1 omitted a common Chinese equivalent of "not online".
        required=[NETWORK if pattern.startswith('不.*联网|') else pattern for pattern in required]
        checks={pattern:bool(re.search(pattern,case['answer'],re.I)) for pattern in required}
        checks.update({'absent:'+pattern:not bool(re.search(pattern,case['answer'],re.I)) for pattern in forbidden})
        if case['id']=='08-after-compaction': checks['summary_saved']=case['summary_persistence']['status']=='saved'
        case.update(required_regex=required,forbidden_regex=forbidden,checks=checks,passed=all(checks.values()))
    report['passed']=sum(case['passed'] for case in report['cases']);report['total']=len(report['cases'])
    report['scoring_version']=2
    return report['passed']==report['total']

def run(output):
    output.mkdir(parents=True,exist_ok=True)
    report={'scope':'real-local-Qwen-on-synthetic-persisted-multi-turn-rooms','model':'qwen3.5:9b','cases':[]}
    with tempfile.TemporaryDirectory(prefix='memory-model-eval-') as temp:
        store=FederationStore(Path(temp)/'data');store.init();chat=ChatStore(store);manager=ContextMemory(store)
        room=chat.create_room('direct',['central'],'隔离多轮模型评估')
        def evaluate(name,question,required,forbidden=()):
            nonlocal manager
            rid=uuid.uuid4().hex;chat.append_message(room,'user',question,round_id=rid)
            context=manager.prepare(room,question,'central',rid)
            request=output/(name+'-input.json');response=output/(name+'-response.json')
            request.write_text(json.dumps({'question':question,'context':context},ensure_ascii=False))
            subprocess.run(['node',str(ROOT/'scripts/evaluate-memory-turn.mjs'),str(request),str(response)],cwd=ROOT,check=True,timeout=120)
            result=json.loads(response.read_text());answer=result['answer']
            chat.append_message(room,'assistant',answer,agent_id='central',phase='consultation',round_id=rid)
            receipt=manager.commit(room,context,result.get('memory_update'))
            manager.record_summary_attempt(context,(result.get('context_usage') or {}).get('summary',{}))
            manager.complete_turn(room,context,rid);chat.save_room(room)
            checks={pattern:bool(re.search(pattern,answer,re.I)) for pattern in required}
            checks.update({'absent:'+pattern:not bool(re.search(pattern,answer,re.I)) for pattern in forbidden})
            case={'id':name,'question':question,'answer':answer,'required_regex':required,'forbidden_regex':forbidden,'checks':checks,'passed':all(checks.values()),'response_origin':result.get('response_origin','model'),'model':result.get('model'),'context_usage':result.get('context_usage'),'summary_persistence':receipt}
            report['cases'].append(case);(output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
            print(json.dumps({'case':name,'passed':case['passed'],'answer':answer,'summary':receipt['status']},ensure_ascii=False),flush=True)
        evaluate('01-initial','设计心跳页面，使用 Vue。必须保留原始聊天记录，不联网。用一句话复述要求。',[r'Vue',r'保留',NETWORK])
        evaluate('02-correction','改用 React，其他要求不变。用一句话复述当前要求。',[r'React',r'保留'],[r'使用\s*Vue'])
        manager=ContextMemory(store)  # restart the persisted manager between real turns
        evaluate('03-restart-followup','继续，用一句话告诉我最终框架和资料范围。',[r'React',r'不.*联网|离线|本地|本库'])
        evaluate('04-new-topic','新话题：做一个列表页，使用 Vue。用一句话确认框架。',[r'Vue'],[r'心跳'])
        evaluate('05-ambiguous','这个列表页使用 React。请用两句话指出还需要我确认什么。',[r'Vue',r'React',r'确认|选择|确定|冲突|澄清'])
        state=manager.view(room,'central');task=next(t for t in state['tasks'] if t['id']==state['active_task'])
        chosen=next(r for r in task['requirement_state']['conflicts'] if r['value']=='react')
        manager.edit(room['id'],'central',task['id'],state['revision'],'resolve',room=room,requirement_id=chosen['id'])
        evaluate('06-resolved','继续，请用一句话说出已确认的框架。',[r'React'],[r'使用\s*Vue'])
        state=manager.inspect(room['id'],'central')
        manager.edit(room['id'],'central',task['id'],state['revision'],'correct_summary','列表页目前只有方案，尚未部署或发布。助手对执行的描述均未核实。')
        evaluate('07-manual-correction','继续，这个页面到底部署了吗？用一句话回答。',[r'未部署|尚未|没有部署|还没部署|未.*验证'])
        state=manager.inspect(room['id'],'central');manager.edit(room['id'],'central',task['id'],state['revision'],'clear_summary_correction')
        for i in range(12):
            rid=uuid.uuid4().hex;question=f'继续列表页第{i}条：必须保留原始聊天记录，不联网。'
            chat.append_message(room,'user',question,round_id=rid);ctx=manager.prepare(room,question,'central',rid)
            chat.append_message(room,'assistant','仅提供咨询，尚未部署。',agent_id='central',phase='consultation',round_id=rid);manager.complete_turn(room,ctx,rid)
        evaluate('08-after-compaction','继续，长对话之后最终框架和资料范围是什么？用一句话回答。',[r'React',r'不.*联网|离线|本地|本库'])
        state=manager.inspect(room['id'],'central');manager.edit(room['id'],'central',task['id'],state['revision'],'forget')
        evaluate('09-forgotten','新话题：这个列表页之前选的框架是什么？如果记忆里没有，请明确说无法确定。',[r'无法.*(?:确定|确认|判定)|没有.*(?:记忆|记录|依据)|不知道|不清楚'])
        room=chat.create_room('direct',['central'],'新隔离会话')
        evaluate('10-new-room','在这个新会话里，旧项目选了哪种框架？没依据就说无法确定。',[r'无法.*(?:确定|确认|判定)|没有.*(?:记忆|记录|依据)|不知道|不清楚'])
    score(report)
    report['total_calls']=sum((case.get('context_usage') or {}).get('total_calls',1) for case in report['cases'])
    report['total_input_tokens']=sum((case.get('context_usage') or {}).get('total_input_tokens') or 0 for case in report['cases'])
    report['total_output_tokens']=sum((case.get('context_usage') or {}).get('total_output_tokens') or 0 for case in report['cases'])
    report['limits']='有限规则信号检查，回答仍需人工阅读；不是全面语义正确率，也不是实际用户会话节省比例。'
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));return report['passed']==report['total']

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'outputs/memory-controls-20261006/model-eval');parser.add_argument('--score-only',type=Path);args=parser.parse_args()
    if args.score_only:
        report=json.loads(args.score_only.read_text());ok=score(report);args.score_only.write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({'passed':report['passed'],'total':report['total'],'scoring_version':report['scoring_version']}));raise SystemExit(0 if ok else 1)
    raise SystemExit(0 if run(args.output.resolve()) else 1)
