"""Local embedding vectors in SQLite, versioned by scope/model/source hash.

Exact cosine search suits the current small per-Agent corpus. A stale snapshot
cannot replace another snapshot: queries join their own live version manifest.
Only loopback Ollama is supported; source text never goes to a cloud provider.
"""
import hashlib
import json
import math
import sqlite3
import struct
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

CONCEPTS = json.loads(Path(__file__).with_name('retrieval-concepts.json').read_text())


def expand_query(question):
    terms = list(dict.fromkeys(term for spec in CONCEPTS.values()
                 if any(trigger in question for trigger in spec['triggers']) for term in spec['terms']))
    return question + ('\n检索概念：' + '、'.join(terms) if terms else '')


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def chunks(text):
    start=0
    while start<len(text):
        end=min(len(text),start+700)
        yield start,text[start:end]
        if end==len(text):break
        start=end-80


class LocalEmbedder:
    def __init__(self,config):
        self.config=config
        url=urlparse(config['url'])
        if url.scheme!='http' or url.hostname not in {'127.0.0.1','localhost','::1'} or url.username or url.password:
            raise ValueError('Embedding endpoint must be local loopback HTTP')
        self.version=config['model']+':'+config['digest']
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(config['url'].rstrip('/')+'/api/tags',timeout=3) as response:
            models=json.load(response)['models']
        if not any(m['name']==config['model'] and m['digest']==config['digest'] for m in models):
            raise ValueError('Embedding model digest changed; index version must be updated')

    def __call__(self,texts):
        body={'model':self.config['model'],'input':texts,'truncate':False,'keep_alive':self.config.get('keep_alive',0),
              'options':{'num_ctx':2048}}
        request=urllib.request.Request(self.config['url'].rstrip('/')+'/api/embed',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
        # Never inherit a proxy for private memory/source text.
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=self.config.get('timeout_seconds',6)) as response:
            value=json.loads(response.read(2_000_000))
        vectors=value['embeddings']
        if len(vectors)!=len(texts):raise ValueError('Embedding batch size mismatch')
        return vectors


def normalized(vector):
    if not isinstance(vector,list) or not 1<=len(vector)<=8192 or any(type(x) not in (int,float) or not math.isfinite(x) for x in vector):
        raise ValueError('Invalid embedding vector')
    norm=math.sqrt(sum(x*x for x in vector))
    if not norm:raise ValueError('Zero embedding vector')
    return [x/norm for x in vector]


class VectorIndex:
    def __init__(self,path,embed,version):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        if self.path.is_symlink():raise ValueError('Vector database cannot be a symlink')
        self.db=sqlite3.connect(self.path,timeout=2)
        self.path.chmod(0o600)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS vectors(scope TEXT,model TEXT,path TEXT,hash TEXT,start INTEGER,dimension INTEGER,vector BLOB,PRIMARY KEY(scope,model,path,hash,start))')
        self.db.execute('CREATE TABLE IF NOT EXISTS queries(model TEXT,hash TEXT,dimension INTEGER,vector BLOB,created REAL,PRIMARY KEY(model,hash))')
        self.embed=embed;self.version=version

    def close(self):self.db.close()

    def update(self,scope,documents,max_chunks=32):
        pending=[]
        for path,text in documents.items():
            version=digest(text)
            for start,chunk in chunks(text):
                if not self.db.execute('SELECT 1 FROM vectors WHERE scope=? AND model=? AND path=? AND hash=? AND start=?',(scope,self.version,path,version,start)).fetchone():
                    pending.append((path,version,start,chunk))
                    if len(pending)>=max_chunks:break
            if len(pending)>=max_chunks:break
        if not pending or max_chunks<=0:return 0
        vectors=self.embed(['title: '+p+' | text: '+t for p,h,s,t in pending])
        if len(vectors)!=len(pending):raise ValueError('Embedding batch size mismatch')
        rows=[]
        for (path,version,start,_),raw in zip(pending,vectors):
            vector=normalized(raw)
            rows.append((scope,self.version,path,version,start,len(vector),struct.pack('<'+'f'*len(vector),*vector)))
        if len({r[5] for r in rows})!=1:raise ValueError('Embedding dimensions changed within batch')
        with self.db:
            self.db.executemany('INSERT OR IGNORE INTO vectors VALUES(?,?,?,?,?,?,?)',rows)
        return len(rows)

    def search(self,scope,documents,question,k=8,min_score=.35):
        live={path:digest(text) for path,text in documents.items()}
        rows=[r for r in self.db.execute('SELECT path,hash,start,dimension,vector FROM vectors WHERE scope=? AND model=?',(scope,self.version)) if live.get(r[0])==r[1]]
        if not rows:return {'matches':[],'indexed_chunks':0,'reason':'index_missing_or_stale'}
        expanded=expand_query(question)
        qhash=digest(expanded)
        cached=self.db.execute('SELECT dimension,vector FROM queries WHERE model=? AND hash=?',(self.version,qhash)).fetchone()
        if cached:
            query=struct.unpack('<'+'f'*cached[0],cached[1])
        else:
            query=normalized(self.embed(['task: search result | query: '+expanded])[0])
            with self.db:
                self.db.execute('INSERT OR REPLACE INTO queries VALUES(?,?,?,?,?)',(self.version,qhash,len(query),struct.pack('<'+'f'*len(query),*query),time.time()))
                self.db.execute('DELETE FROM queries WHERE rowid IN (SELECT rowid FROM queries ORDER BY created DESC LIMIT -1 OFFSET 512)')
        scored=[]
        for path,version,start,dim,blob in rows:
            if dim!=len(query):raise ValueError('Embedding model dimension changed; rebuild with new model digest')
            score=sum(a*b for a,b in zip(query,struct.unpack('<'+'f'*dim,blob)))
            if score>=min_score:
                scored.append({'path':path,'sha256':version,'start':start,'offset':documents[path][:start].count('\n'),'score':score})
        scored.sort(key=lambda r:(-r['score'],r['path'],r['start']))
        unique={}
        for row in scored:unique.setdefault(row['path'],row)
        total=sum(sum(1 for _ in chunks(text)) for text in documents.values())
        return {'matches':list(unique.values())[:k],'indexed_chunks':len(rows),'total_chunks':total,'complete':len(rows)==total,'model_version':self.version,
                'query_expanded':expanded!=question}


def load_documents(root):
    root=Path(root).resolve(strict=True);documents={};size=0
    for path in sorted(root.rglob('*.md')):
        relative=path.relative_to(root)
        if any(part.startswith('_') or part.startswith('.') for part in relative.parts):continue
        if path.is_symlink() or not path.is_file() or path.resolve().parent!=path.parent:continue
        if path.stat().st_size>1_000_000:continue
        text=path.read_text(encoding='utf-8');size+=len(text)
        if size>8_000_000 or len(documents)>=1000:break
        documents['/'+relative.as_posix()]=text
    return documents


def status(base):
    config_path=base/'metadata/embedding.json';database=base/'metadata/vectors.sqlite3'
    if not config_path.is_file():return {'configured':False,'indexed_chunks':0}
    try:
        config=json.loads(config_path.read_text());count=0
        if database.is_file():
            with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as db:
                count=db.execute('SELECT count(*) FROM vectors WHERE model=?',(config['model']+':'+config['digest'],)).fetchone()[0]
        return {'configured':bool(config.get('enabled')),'model':config['model'],'model_digest':config['digest'],'indexed_chunks':count,
                'storage':'SQLite exact cosine','fallback':'keyword on timeout, missing or stale versions'}
    except (ValueError,OSError,sqlite3.Error):return {'configured':False,'indexed_chunks':0,'reason':'invalid_index_configuration'}


def main():
    payload=json.loads(sys.stdin.buffer.read(64000))
    config=json.loads(Path(payload['config']).read_text())
    if not config.get('enabled'):return {'matches':[],'reason':'disabled'}
    embed=LocalEmbedder(config);index=VectorIndex(payload['database'],embed,embed.version)
    try:
        documents=load_documents(payload['root'])
        updated=index.update(payload['scope'],documents,max_chunks=payload.get('update_max',2))
        result=index.search(payload['scope'],documents,payload['question'],min_score=config.get('min_score',.35)) if payload.get('question') else {'matches':[]}
        return {**result,'updated_chunks':updated,'method':'sqlite-cosine-local-embedding'}
    finally:index.close()


if __name__=='__main__':
    try:print(json.dumps(main(),ensure_ascii=False))
    except Exception as exc:print(json.dumps({'matches':[],'reason':'embedding_unavailable','error_type':type(exc).__name__}))
