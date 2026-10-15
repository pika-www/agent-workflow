"""Read existing per-Agent Wiki pages and build only the additive vector cache."""
import argparse
import json
import time
from pathlib import Path
from federation.core import FederationStore
from federation.vector_index import LocalEmbedder,VectorIndex,load_documents,chunks


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--project',type=Path,required=True);p.add_argument('--config',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    store=FederationStore(args.project/'openwiki-federation',project_root=args.project)
    config=json.loads(args.config.read_text());embed=LocalEmbedder(config)
    index=VectorIndex(store.base/'metadata/vectors.sqlite3',embed,embed.version)
    started=time.monotonic();reports=[]
    try:
        for identifier in store._definitions:
            documents=load_documents(store._wiki(identifier));updated=0
            while True:
                count=index.update(identifier,documents,max_chunks=24);updated+=count
                if count==0:break
            reports.append({'agent_id':identifier,'documents':len(documents),'chunks':sum(sum(1 for _ in chunks(text)) for text in documents.values()),'updated_chunks':updated})
            print(json.dumps(reports[-1]),flush=True)
        result={'model':config['model'],'model_digest':config['digest'],'elapsed_seconds':round(time.monotonic()-started,3),'scopes':reports,'total_chunks':sum(x['chunks'] for x in reports)}
        args.output.write_text(json.dumps(result,indent=2))
    finally:index.close()
