"""Replay labeled probes against server-only real history without changing it.

All earlier messages are simulated as compacted away to measure original-record
rehydration. The report contains only IDs, hashes and aggregate metrics, no text.
"""
import argparse
from contextlib import nullcontext
import hashlib
import json
import time
from types import SimpleNamespace
from pathlib import Path
from federation.context_memory import ContextMemory,estimate
from federation.conversation_window import ConversationWindow


def evaluate(base,cases):
    details=[]
    for case in cases:
        path=base/'chat/rooms'/(case['room_id']+'.json');raw=path.read_bytes();room=json.loads(raw)
        original_hash=hashlib.sha256(raw).hexdigest()
        state_path=base/'metadata/context-memory'/case['room_id']/'central.json'
        state=json.loads(state_path.read_text()) if state_path.is_file() else {'revision':0,'tasks':[]}
        forgotten={mid for task in state['tasks'] if task['status']=='forgotten' for mid in task['message_ids']}
        expected=set(case['expected_ids'])-forgotten
        source={m['id']:m for m in ContextMemory.messages(room,'central') if m['id'] not in forgotten}
        assert expected <= set(source),'Labeled message not available in this scope'
        probe='f'*32
        room['messages'].append({'id':probe,'round_id':probe,'role':'user','content':case['question']})
        memory=SimpleNamespace(messages=ContextMemory.messages,_locked=lambda *args:nullcontext((None,state)))
        window=ConversationWindow(memory)
        window._read=lambda *args:{'revision':0,'compaction_count':1,'records':{mid:{'source_hash':hashlib.sha256(m['content'].encode()).hexdigest(),'content':None} for mid,m in source.items()}}
        started=time.perf_counter();result=window.prepare(room,'central',probe);elapsed=(time.perf_counter()-started)*1000
        selected=set(result['recall']['selected_ids']);matched=selected&expected
        details.append({'label':case['label'],'source_room_sha256':original_hash,'history_messages':len(source),
                        'history_characters':sum(len(m['content']) for m in source.values()),'expected_ids':sorted(expected),'selected_ids':sorted(selected),
                        'recall_at_3':len(matched)/len(expected) if expected else None,
                        'precision_at_3':len(matched)/3,
                        'returned_precision':len(matched)/len(selected) if selected else None,
                        'selected_estimated_tokens':sum(estimate(m['content']) for m in result['messages']),
                        'retrieval_ms':round(elapsed,3),'source_unchanged':hashlib.sha256(path.read_bytes()).hexdigest()==original_hash})
    return {'evidence_class':'server-production-history-replay-with-labeled-probes','simulated_compaction':'all prior messages omitted; originals preserved',
            'cases':len(details),'recall_at_3':sum(d['recall_at_3'] for d in details if d['recall_at_3'] is not None)/sum(d['recall_at_3'] is not None for d in details),
            'precision_at_3':sum(d['precision_at_3'] for d in details)/len(details),
            'returned_precision':sum(len(set(d['selected_ids'])&set(d['expected_ids'])) for d in details)/max(1,sum(len(d['selected_ids']) for d in details)),'details':details,
            'limits':'Includes historical validation conversations. Retrieval metrics do not prove final model answer accuracy.'}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--base',type=Path,required=True);p.add_argument('--cases',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=evaluate(a.base,json.loads(a.cases.read_text()));a.output.write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k!='details'}))
