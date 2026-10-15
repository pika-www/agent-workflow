"""Read-only handshake and local readiness checks, no automatic account login."""
import asyncio
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from federation.platform_content import worker
from federation.platform_mcp_registry import PROVIDERS,RUNTIME,catalog

async def main():
    for provider in PROVIDERS:
        result=await worker(provider,'list',timeout=40)
        result['commit']=catalog(provider)['platforms'][0]['commit']
        dest=RUNTIME/'checks'/f'{provider}.json';dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_text(json.dumps(result,ensure_ascii=False,indent=2))
        print(provider,result.get('status'),'tools:',','.join(t['name'] for t in result.get('tools',[])),flush=True)
    print('tieba local readiness:',json.dumps(await worker('tieba','check',timeout=65),ensure_ascii=False))

if __name__=='__main__':asyncio.run(main())
