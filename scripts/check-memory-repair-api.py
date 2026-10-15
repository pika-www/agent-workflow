"""Real local model through the Python API, using disposable chat/config data."""
import json,os,sys,tempfile,time,uuid
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from federation.app import create_app
OUT=Path(__file__).resolve().parents[1]/'outputs/memory-repair-20261006/runtime-model-api.json'
with tempfile.TemporaryDirectory(prefix='memory-api-eval-') as root,patch.dict(os.environ,{'JEV_AI_ENABLED':'false'}):
 app=create_app(base=Path(root)/'data')
 state=app.state.store._state('central')
 (state/'.env').write_text('OPENWIKI_PROVIDER=openai-compatible\nOPENAI_COMPATIBLE_BASE_URL=http://127.0.0.1:11436/v1\nOPENAI_COMPATIBLE_API_KEY=ollama\nOPENWIKI_MODEL_ID=qwen3.5:9b\nOPENWIKI_REASONING_EFFORT=none\nOPENWIKI_OPENAI_COMPATIBLE_REASONING_EFFORT_SUPPORTED=true\nJEV_AI_ENABLED=false\n')
 with TestClient(app) as client:
  chat=app.state.chat;memory=app.state.context_memory;room=chat.primary_room();rid=uuid.uuid4().hex
  chat.append_message(room,'user','这个页面使用React。预算为300元。',round_id=rid);ctx=memory.prepare(room,'这个页面使用React。预算为300元。','central',rid)
  chat.append_message(room,'assistant','仅记录要求，尚未执行。',agent_id='central',phase='consultation',round_id=rid);memory.complete_turn(room,ctx,rid);chat.save_room(room)
  response=client.post('/api/chat/rooms/'+room['id']+'/messages',json={'content':'继续，用一句话复述当前框架和预算，不推测执行状态。'})
  response.raise_for_status();job_id=response.json()['job']['id'];deadline=time.monotonic()+180
  while True:
   job=client.get('/api/jobs/'+job_id).json()
   if job['status'] in ['completed','failed'] or time.monotonic()>deadline:break
   time.sleep(1)
  usage=client.get('/api/chat/rooms/'+room['id']+'/context-usage').json()
  saved=chat.get_room(room['id']);answer=saved['messages'][-1]['content']
  persisted=[json.loads(p.read_text()) for p in (app.state.store.base/'jobs').glob('*.json')]
  children=[j for j in persisted if j.get('parent_job_id')==job_id]
  calls=[r for j in children for r in j.get('model_usage',[])]
  report={'scope':'real local Qwen via Python API and native child; isolated data; Jev disabled','status':job['status'],'error':job.get('error'),'answer':answer,'model_calls':calls,'operations':usage['operations'],
          'checks':{'completed':job['status']=='completed','requirements':'React' in answer and '300' in answer,'tracked_calls':bool(calls),'tokens_returned':any(r.get('input_tokens') is not None for r in calls),
                    'deduplication':usage['operations']['calls']==len(calls),
                    'known_input_total':usage['operations']['input']==sum(r.get('input_tokens') or 0 for r in calls)}}
  OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report['checks'],ensure_ascii=False),flush=True)
  if not all(report['checks'].values()):raise SystemExit(1)
