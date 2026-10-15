"""Bounded local inference. No model-supplied endpoint, executable or credential."""
import base64
import os
from urllib.parse import urlsplit
import httpx

def local_config():
    base=os.environ.get('OPENAI_COMPATIBLE_BASE_URL','http://127.0.0.1:11436/v1')
    url=urlsplit(base)
    if url.scheme!='http' or url.hostname not in {'127.0.0.1','localhost'} or url.port not in {11434,11436} or url.username or url.password:
        raise ValueError('本地读取需要已配置的本机 Ollama 服务')
    model=os.environ.get('OPENWIKI_LOCAL_VISION_MODEL','qwen3.5:9b')
    if not model or len(model)>160 or any(c.isspace() for c in model):raise ValueError('本地模型名无效')
    return {'base_url':f'http://{url.hostname}:{url.port}','model':model}

async def local_reply(question,images=(),*,max_tokens=1600):
    config=local_config()
    message={'role':'user','content':question}
    if images:message['images']=[base64.b64encode(raw).decode() for raw in images]
    async with httpx.AsyncClient(timeout=180,trust_env=False,follow_redirects=False) as client:
        response=await client.post(config['base_url']+'/api/chat',json={'model':config['model'],'messages':[message],
            'think':False,'stream':False,'options':{'temperature':0,'num_predict':max_tokens,'num_ctx':32768}})
    if response.status_code!=200:raise ValueError(f'本地模型读取失败（HTTP {response.status_code}）')
    data=response.json(); text=data.get('message',{}).get('content')
    if data.get('done') is not True or not isinstance(text,str) or not text.strip():raise ValueError('本地模型没有完成读取')
    return {'text':text[:14000],'model':config['model'],'provider':'local-ollama',
            'usage':{'input_tokens':data.get('prompt_eval_count'),'output_tokens':data.get('eval_count')}}
