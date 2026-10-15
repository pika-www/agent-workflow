"""Read-only GitHub, Notion and Gmail adapters. Credentials never reach the model."""
import base64
import re
import httpx
from .tool_services import configuration

def notion_id(value):
    return isinstance(value,str) and bool(re.fullmatch(r'(?:[a-fA-F0-9]{32}|[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12})',value))

async def notion_page(config,object_id):
    """Read nested block children in document order, with explicit bounded coverage."""
    from urllib.parse import urlencode
    lines=[];visited=set();gaps=set();requests=0;blocks=0;characters=0
    async def children(parent,depth):
        nonlocal requests,blocks,characters
        if parent in visited:gaps.add('重复的子页面或块未重复读取');return
        visited.add(parent);cursor=None;seen_cursors=set()
        while True:
            if requests>=8:gaps.add('已达到8次分页读取上限');return
            requests+=1
            data=await request(config,'notion','/blocks/'+parent+'/children?'+urlencode({'page_size':100,**({'start_cursor':cursor} if cursor else {})}))
            if not isinstance(data.get('results'),list):raise ValueError('Notion返回的页面内容格式无效')
            for block in data['results']:
                if blocks>=300 or characters>=16000:gaps.add('已达到300个块或16000字内容上限');return
                if not isinstance(block,dict):raise ValueError('Notion返回的内容块格式无效')
                blocks+=1;kind=block.get('type');content=block.get(kind,{})
                if not isinstance(content,dict):raise ValueError('Notion返回的内容块格式无效')
                text=''.join(t.get('plain_text','') for t in content.get('rich_text',[]))
                if not text:text=content.get('title','') or ''.join(t.get('plain_text','') for t in content.get('caption',[]))
                if kind=='table_row':text='\t'.join(''.join(t.get('plain_text','') for t in cell) for cell in content.get('cells',[]))
                if kind in {'image','file','pdf','video','audio'}:gaps.add('页面中的媒体和文件附件尚未读取')
                if kind=='child_database':gaps.add('子数据库内容尚未读取')
                if text:
                    line=('  '*depth)+text
                    available=16000-characters
                    lines.append(line[:available]);characters+=len(line)+1
                    if len(line)+1>available:gaps.add('已达到16000字内容上限')
                if block.get('has_children') or kind=='child_page':
                    child=block.get('id')
                    if depth>=4:gaps.add('超过4层的子块未读取')
                    elif not notion_id(child):gaps.add('无效的子块编号未读取')
                    else:await children(child,depth+1)
            if not data.get('has_more'):return
            cursor=data.get('next_cursor')
            if not isinstance(cursor,str) or not cursor or len(cursor)>200 or cursor in seen_cursors:
                gaps.add('分页游标缺失或重复，后续内容未读取');return
            seen_cursors.add(cursor)
    await children(object_id,0)
    return {'status':'completed','provider':'notion','object_id':object_id,'text':'\n'.join(lines)[:16000],
            'truncated':bool(gaps),'coverage':{'requests':requests,'blocks':blocks,'gaps':sorted(gaps)},'scope':'read-only'}

async def request(config,provider,path,*,body=None):
    if provider!='github' and not config.get('enabled'):raise ValueError(provider+'尚未授权连接')
    token=(config.get('api_key') or config.get('access_token')) if config.get('enabled') else None
    if provider=='gmail' and config.get('refresh_token'):
        async with httpx.AsyncClient(timeout=20) as client:
            r=await client.post('https://oauth2.googleapis.com/token',data={'grant_type':'refresh_token','refresh_token':config['refresh_token'],'client_id':config.get('client_id',''),'client_secret':config.get('client_secret','')})
        if r.status_code!=200:raise ValueError('Gmail授权已失效，请重新授权')
        token=r.json().get('access_token')
    bases={'github':'https://api.github.com','notion':'https://api.notion.com/v1','gmail':'https://gmail.googleapis.com/gmail/v1/users/me'}
    headers={'Accept':'application/json','User-Agent':'OpenWiki-Tools/1.0'}
    if token:headers['Authorization']='Bearer '+token
    if provider=='notion':headers['Notion-Version']='2022-06-28'
    if provider!='github' and (not config.get('enabled') or not token):raise ValueError(provider+'尚未授权连接')
    async with httpx.AsyncClient(timeout=25,follow_redirects=False) as client:
        response=await (client.post(bases[provider]+path,headers=headers,json=body) if body is not None else client.get(bases[provider]+path,headers=headers))
    if response.status_code!=200:raise ValueError(provider+f'读取返回HTTP {response.status_code}')
    if len(response.content)>2_000_000:raise ValueError('第三方读取结果过大')
    return response.json()

async def execute(store,provider,query=None,object_id=None):
    if provider not in {'github','notion','gmail'}:raise ValueError('第三方服务不支持')
    config=configuration(store).get(provider,{})
    from urllib.parse import urlencode
    if query is not None:
        if provider=='github':
            data=await request(config,provider,'/search/repositories?'+urlencode({'q':query,'per_page':5}))
            items=[{'id':i['full_name'],'title':i['full_name'],'description':i.get('description'),'url':i['html_url']} for i in data.get('items',[])]
        elif provider=='notion':
            data=await request(config,provider,'/search',body={'query':query,'page_size':5})
            items=[{'id':i['id'],'title':' '.join(t.get('plain_text','') for p in i.get('properties',{}).values() for t in p.get('title',[])),'url':i.get('url')} for i in data.get('results',[])]
        else:
            data=await request(config,provider,'/messages?'+urlencode({'q':query,'maxResults':5}))
            items=data.get('messages',[])
        return {'status':'completed' if items else 'no_results','provider':provider,'items':items,'scope':'read-only'}
    if not isinstance(object_id,str) or len(object_id)>200:raise ValueError('读取对象编号无效')
    if provider=='github':
        if not re.fullmatch('[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',object_id):raise ValueError('仓库编号必须是owner/repo')
        data=await request(config,provider,'/repos/'+object_id+'/readme')
        text=base64.b64decode(data.get('content','')).decode('utf-8',errors='replace')
    elif provider=='notion':
        if not notion_id(object_id):raise ValueError('Notion页面编号无效')
        return await notion_page(config,object_id)
    else:
        if not re.fullmatch('[a-f0-9]{1,32}',object_id):raise ValueError('Gmail邮件编号无效')
        data=await request(config,provider,'/messages/'+object_id+'?format=full')
        payload=data.get('payload',{});blocks=[]
        def body(part):
            value=part.get('body',{}).get('data')
            if value and part.get('mimeType') in {'text/plain','text/html'}:blocks.append(base64.urlsafe_b64decode(value+'='*(-len(value)%4)).decode('utf-8',errors='replace'))
            for child in part.get('parts',[]):body(child)
        body(payload)
        text='\n'.join(h['name']+': '+h['value'] for h in payload.get('headers',[]) if h['name'].lower() in {'subject','from','date'})+'\n'+('\n'.join(blocks) or data.get('snippet',''))
    return {'status':'completed','provider':provider,'object_id':object_id,'text':text[:16000],'truncated':len(text)>16000,'scope':'read-only'}
