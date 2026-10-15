"""Fetch a fixed public Ollama embedding artifact, verifying every layer hash.

Downloads stay in a release staging directory until verified. Existing model
layers are verified and retained; no model service is stopped or reconfigured.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import urllib.request


def fetch(models,staging,proxy):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({'https':proxy,'http':proxy}))
    base='https://registry.ollama.ai/v2/library/embeddinggemma/'
    tag='300m-qat-q4_0'
    raw=opener.open(base+'manifests/'+tag,timeout=30).read(100000)
    manifest=json.loads(raw)
    staging.mkdir(parents=True,exist_ok=True,mode=0o700)
    blobs=models/'blobs';blobs.mkdir(parents=True,exist_ok=True)
    for layer in [*manifest['layers'],manifest['config']]:
        digest=layer['digest'];algorithm,hexdigest=digest.split(':')
        if algorithm!='sha256' or len(hexdigest)!=64 or any(c not in '0123456789abcdef' for c in hexdigest):raise ValueError('Invalid public digest')
        name=digest.replace(':','-');target=blobs/name
        if target.is_file():
            if hashlib.sha256(target.read_bytes()).hexdigest()!=hexdigest:raise ValueError('Existing layer hash mismatch')
            continue
        temporary=staging/name
        with opener.open(base+'blobs/'+digest,timeout=120) as response,temporary.open('wb') as out:
            shutil.copyfileobj(response,out,1024*1024)
        if temporary.stat().st_size!=layer['size'] or hashlib.sha256(temporary.read_bytes()).hexdigest()!=hexdigest:
            raise ValueError('Downloaded layer hash mismatch')
        os.replace(temporary,target)
        print(json.dumps({'layer':hexdigest,'verified_bytes':layer['size']}),flush=True)
    destination=models/'manifests/registry.ollama.ai/library/embeddinggemma'/tag
    destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists() and destination.read_bytes()!=raw:raise ValueError('Existing tag differs')
    temporary=staging/'manifest.json';temporary.write_bytes(raw);os.replace(temporary,destination)
    print(json.dumps({'model':'embeddinggemma:'+tag,'digest':hashlib.sha256(raw).hexdigest(),'status':'verified'}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--models',type=Path,required=True);p.add_argument('--staging',type=Path,required=True);p.add_argument('--proxy',required=True);a=p.parse_args()
    fetch(a.models,a.staging,a.proxy)
