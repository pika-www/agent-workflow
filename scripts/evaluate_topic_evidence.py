"""Read actual topic pages and optionally call the configured consultation model.

Keeps model writes inside its existing per-turn isolation, never publishes pages
or creates user chat history. Structural citation checks are not semantic grades.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import uuid
import selectors
import codecs

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from federation.core import FederationStore, _write_json
from federation.knowledge import knowledge_health
from federation.app import isolated_ask_environment

def capture_model(process, payload, timeout):
    """Timestamp text as it arrives; communicate() cannot measure first text."""
    process.stdin.write(json.dumps(payload,ensure_ascii=False).encode())
    process.stdin.close()
    process.stdin=None
    decoder=codecs.getincrementaldecoder('utf-8')()
    selector=selectors.DefaultSelector();selector.register(process.stdout,selectors.EVENT_READ)
    started=time.monotonic();pending='';log=[];first_text_ms=None;first_reply_ms=None;updates=[]
    try:
        while selector.get_map():
            if time.monotonic()-started > timeout:raise subprocess.TimeoutExpired(process.args,timeout)
            for key,_ in selector.select(timeout=min(1,timeout)):
                chunk=os.read(key.fileobj.fileno(),4096)
                if not chunk:selector.unregister(key.fileobj);continue
                log.append(chunk);pending+=decoder.decode(chunk)
                while '\n' in pending:
                    line,pending=pending.split('\n',1)
                    if line.startswith('OPENWIKI_REPLY ') and first_text_ms is None:
                        if json.loads(line[len('OPENWIKI_REPLY '):]).get('text'):
                            first_text_ms=round((time.monotonic()-started)*1000)
                            if first_reply_ms is None:first_reply_ms=first_text_ms
                    if line.startswith('OPENWIKI_UPDATE '):
                        update=json.loads(line[len('OPENWIKI_UPDATE '):]);updates.append(update)
                        if update.get('text') and first_reply_ms is None:first_reply_ms=round((time.monotonic()-started)*1000)
        process.wait(timeout=5)
        return b''.join(log),first_text_ms,first_reply_ms,updates
    finally:selector.close()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--timeout',type=int,default=180)
    parser.add_argument('--output',type=Path,default=ROOT/'outputs/knowledge-evidence-20261006')
    args=parser.parse_args()
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    fixture=ROOT/'tests/fixtures/ai-product-evidence-questions.json'
    bank=json.loads(fixture.read_text());store=FederationStore(ROOT/'openwiki-federation',project_root=ROOT)
    metadata=output/'topic-evidence-snapshot.json';_write_json(metadata,knowledge_health(store,bank['space']))
    subprocess.run([store.node,str(ROOT/'scripts/evaluate_topic_evidence.mjs'),str(store._wiki(bank['space'])),
                    str(metadata),str(fixture),str(output/'topic-retrieval.json')],cwd=ROOT,check=True)
    if not args.live:return
    answers=[]
    for case in [c for c in bank['cases'] if c.get('live')]:
        print('真实模型验收：'+case['id'],flush=True)
        job={'id':'topic-eval-'+uuid.uuid4().hex,'space':bank['space'],
             'question':case['question'],'delegation_phase':'consultation'}
        environment=isolated_ask_environment(store,job)
        isolated=Path(environment['OPENWIKI_CONFIG_DIR']);result_path=isolated/'final-answer.json'
        environment['FEDERATION_CHAT_RESULT']=str(result_path)
        prompt=('仅依据本轮实际读取的 Wiki 和原文标注回答，不联网，不改文件。'
                '先直接回答问题，两个自然段以内；有依据时使用实际路径引用。没有依据就明确说明。'
                '待核对标注不能说成已核实事实，本地归档不能说成网页最新。\n'+case['question'])
        payload={'prompt':prompt,'phase':'consultation','current_question':case['question'],'retrieval_query':case['question'],
                 'tool_policy':{'network_allowed':False},'memory_context':{}}
        started=time.monotonic()
        process=subprocess.Popen([store.node,str(ROOT/'federation/agent-turn.mjs')],cwd=ROOT,env=environment,
          stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True)
        try:
            log,first_text_ms,first_reply_ms,updates=capture_model(process,payload,args.timeout)
            if process.returncode or not result_path.is_file():
                raise ValueError('原生模型路径未返回结果，退出码 '+str(process.returncode))
            result=json.loads(result_path.read_text())
            answers.append({'id':case['id'],'question':case['question'],'answer':result['answer'],
                            'elapsed_seconds':round(time.monotonic()-started,2),
                            'process_first_text_ms':first_text_ms,'process_first_reply_ms':first_reply_ms,'interim_replies':updates,
                            **{k:result.get(k) for k in ['model','wiki_reads','wiki_input','answer_check','initial_reply','wiki_citation_check','context_usage','timing']},
                            'semantic_correctness':'requires_review'})
            print(json.dumps({'id':case['id'],'elapsed_seconds':answers[-1]['elapsed_seconds'],
                              'process_first_text_ms':first_text_ms,'process_first_reply_ms':first_reply_ms,'answer_check':result.get('answer_check',{}).get('status'),
                              'citation_check':result.get('wiki_citation_check',{}).get('status')},ensure_ascii=False),flush=True)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGTERM)
            try:process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid,signal.SIGKILL);process.communicate()
            answers.append({'id':case['id'],'error':'模型超时','elapsed_seconds':round(time.monotonic()-started,2)})
        except Exception as error:
            answers.append({'id':case['id'],'error':str(error)})
        finally:
            # Only this command's newly allocated, identified disposable copy.
            if isolated.name==job['id'] and isolated.parent==store.base/'ask-runs':shutil.rmtree(isolated)
            _write_json(output/'topic-model-answers.json',{'evidence_class':'real_model_actual_topic_isolated_copy',
                        'answers':answers,'wiki_or_chats_rewritten':False,'semantic_correctness':'requires_review'})

if __name__=='__main__':main()
