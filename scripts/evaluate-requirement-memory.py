"""Isolated real Qwen checks of explicit budget/date/platform corrections."""
import argparse,json,re,subprocess,sys,tempfile,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from federation.chat import ChatStore
from federation.context_memory import ContextMemory
from federation.core import FederationStore
from federation.project_memory import ProjectMemory
ROOT=Path(__file__).resolve().parents[1]

def run(out):
 out.mkdir(parents=True,exist_ok=True);cases=[]
 with tempfile.TemporaryDirectory(prefix='requirement-eval-') as directory:
  store=FederationStore(Path(directory)/'data');store.init();chat=ChatStore(store);memory=ContextMemory(store);projects=ProjectMemory(store,chat,memory);memory.projects=projects
  room=chat.create_room('direct',['central'],'隔离多要求验收')
  def prepare(text):
   rid=uuid.uuid4().hex;chat.append_message(room,'user',text,round_id=rid);return rid,memory.prepare(room,text,'central',rid)
  def finish(rid,context,answer):
   chat.append_message(room,'assistant',answer,agent_id='central',phase='consultation',round_id=rid);memory.complete_turn(room,context,rid);chat.save_room(room)
  for i in range(50):
   text='页面使用Vue。预算为500元。截止日期为2026-10-20。目标平台为Android和iOS。交付格式为PDF。' if i==0 else ('改用React。预算从500元改到300元。截止日期改为2026-10-25。改为只做Android，iOS暂缓。交付格式改为Markdown。' if i==35 else f'继续这个页面，讨论第{i}个细节。')
   rid,ctx=prepare(text);finish(rid,ctx,'仅讨论方案，尚未执行。')
  def evaluate(name,text,patterns,forbidden=()):
   rid,ctx=prepare(text);request=out/(name+'-input.json');response=out/(name+'-response.json');request.write_text(json.dumps({'question':text,'context':ctx},ensure_ascii=False))
   subprocess.run(['node',str(ROOT/'scripts/evaluate-memory-turn.mjs'),str(request),str(response)],check=True,cwd=ROOT,timeout=180)
   result=json.loads(response.read_text());answer=result['answer'];checks={p:bool(re.search(p,answer,re.I)) for p in patterns};checks.update({'absent:'+p:not re.search(p,answer,re.I) for p in forbidden})
   persistence=memory.commit(room,ctx,result.get('memory_update'));memory.record_summary_attempt(ctx,(result.get('context_usage') or {}).get('summary',{}));finish(rid,ctx,answer)
   cases.append({'id':name,'answer':answer,'checks':checks,'passed':all(checks.values()),'model':result.get('model'),'context_usage':result.get('context_usage'),'summary_persistence':persistence})
   print(json.dumps({'id':name,'passed':cases[-1]['passed'],'answer':answer},ensure_ascii=False),flush=True)
  evaluate('01-current-rules','继续，用两句话复述当前框架、预算、截止日期、目标平台和交付格式；仅复述用户记录，不推测执行状态。',[r'React',r'300',r'10[-月/ ]?25',r'Android',r'Markdown'],[r'500元|采用Vue|使用Vue|已部署'])
  evaluate('02-hypothetical','如果预算改为200元会怎样？先用一句话说明目前确认的预算是多少，再说明这是假设。',[r'300',r'假设|尚未|没有.*(?:确认|更改)|仍'],[r'当前.*预算.*(?:已改为|确定为)200'])
  evaluate('03-conflict','继续这个页面。预算为200元。请确认当前任务。',[r'300',r'200',r'确认|选择'])
 report={'scope':'50 synthetic rounds; 2 local model questions plus host conflict guard','cases':cases,'passed':sum(c['passed'] for c in cases),'total':len(cases),'limits':'限定中文规则及信号检查；不代表全面语义正确率或真实用户节省比例。'}
 (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));return report['passed']==len(cases)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=ROOT/'outputs/memory-repair-20261006/model-eval');args=p.parse_args();raise SystemExit(0 if run(args.output.resolve()) else 1)
