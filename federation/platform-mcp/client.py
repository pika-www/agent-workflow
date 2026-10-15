"""One bounded MCP session per read. Server code and credentials stay local."""
import asyncio
from contextlib import AsyncExitStack
from datetime import timedelta
import json
import os
from pathlib import Path
import re
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from federation.platform_mcp_registry import PROVIDERS, server_spec, credential_present
from federation.platform_content import validate
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from jsonschema import validate as validate_schema

def decode(result):
    data=getattr(result,'structuredContent',None)
    if data is None:
        text='\n'.join(c.text for c in result.content if c.type=='text')
        try: data=json.loads(text)
        except ValueError: data={'text':text}
    if result.isError: return {'status':'failed','error':'平台工具返回错误','data':data}
    if isinstance(data,dict) and (data.get('error') or data.get('ok') is False):
        if data.get('error_type')=='CookieExpiredError':return {'status':'needs_login','error':'平台登录信息缺失或已过期，请在工具与连接中登录。'}
        return {'status':'failed','error':'平台读取未成功','data':data}
    return {'status':'completed','data':data}

SECRET_KEYS={'cookie','cookies','sessdata','bili_jct','buvid3','access_token','refresh_token','client_secret','sessionid','sessionid_ss','bduss','stoken','xsec_token'}
def redact(value):
    if isinstance(value,dict):return {k:('[REDACTED]' if k.lower() in SECRET_KEYS else redact(v)) for k,v in value.items()}
    if isinstance(value,list):return [redact(v) for v in value]
    if isinstance(value,str):return re.sub(r'(?i)((?:access_token|refresh_token|xsec_token|sessionid|BDUSS|SESSDATA|bili_jct)=)[^\s&;]+',r'\1[REDACTED]',value)
    return value

def normalize(provider,tool,args,result):
    data=result.get('data')
    if provider=='bilibili' and tool=='get_comments' and result.get('status')=='completed':
        if not isinstance(data,dict) or 'replies' not in data:
            return {'status':'needs_login' if not credential_present(provider) else 'failed',
                    'error':'B站未返回可核验的评论列表，请登录后再试；这不代表没有评论。'}
        comments=data.get('replies') or []
        def item(row):
            return {'id':row.get('rpid'),'content':row.get('content',{}).get('message'),
                'author':row.get('member',{}).get('uname'),'likes':row.get('like'),
                'reply_count':row.get('rcount'),'created_at':row.get('ctime'),
                'replies':[item(r) for r in (row.get('replies') or [])[:5]]}
        result={'status':'completed' if comments else 'no_results','data':{'comments':[item(r) for r in comments[:20]],'page':data.get('page')},
                'note':'仅返回当前页评论与接口附带的部分子回复，未读取全部评论。',
                'sources':[{'url':'https://www.bilibili.com/video/av'+str(args['oid'])+'/','title':'B站视频评论'}]}
    if provider=='douyin' and tool=='check_login_status' and isinstance(data,dict) and data.get('logged_in') is False:
        result['status']='needs_login'
    return result

async def tieba_read(session,tool,args):
    request={'platform':'tieba','mode':tool,'max_items':3,'include_comments':True,'include_nested_comments':True,
             'max_comments_per_item':20,'headless':True,'browser_mode':'isolated','timeout_minutes':1}
    request.update({'query':args['query']} if tool=='search' else {'mode':'detail','targets':[args['post_id']]})
    start=decode(await session.call_tool('collect',request))
    data=start.get('data',{});run_id=data.get('run_id')
    if not run_id:return start
    try:
        for _ in range(25):
            current=decode(await session.call_tool('status',{'run_id':run_id}));state=current.get('data',{})
            if state.get('state')=='completed':
                result=decode(await session.call_tool('result',{'run_id':run_id,'limit':20}))
                result['status']='completed' if state.get('outcome')=='data_available' else 'no_results' if state.get('outcome')=='no_data' else 'failed'
                return result
            if state.get('phase')=='awaiting_user_login':return {'status':'needs_login','error':'贴吧登录已失效，请在工具与连接重新登录'}
            await asyncio.sleep(2)
        return {'status':'timeout','error':'贴吧采集未在本次时间内完成；不代表没有内容'}
    finally: await session.call_tool('stop',{'run_id':run_id})

async def main(request):
    provider=request['provider'];action=request['action']
    command,args,env=server_spec(provider)
    with open(os.devnull,'w') as err:
        async with stdio_client(StdioServerParameters(command=command,args=args,env=env),errlog=err) as (reader,writer):
            async with ClientSession(reader,writer,read_timeout_seconds=timedelta(seconds=65)) as session:
                await session.initialize()
                listing=await session.list_tools()
                schemas=[{'name':t.name,'description':t.description,'inputSchema':t.inputSchema} for t in listing.tools]
                if action=='list':return {'status':'completed','handshake_verified':True,'tools':schemas}
                if action=='check' and provider=='tieba':return decode(await session.call_tool('check',{'deep':True}))
                tool=request['tool'];arguments=validate(provider,tool,request['args'])
                if provider=='tieba':return await tieba_read(session,tool,arguments)
                schema=next((t['inputSchema'] for t in schemas if t['name']==tool),None)
                if schema is None:raise ValueError('Tool missing')
                if set(arguments)-set(schema.get('properties',{})):raise ValueError('Unknown tool parameters')
                validate_schema(arguments,schema)
                return normalize(provider,tool,arguments,decode(await session.call_tool(tool,arguments)))

if __name__=='__main__':
    try:
        raw=sys.stdin.buffer.read(12001)
        if len(raw)>12000:raise ValueError('Request too large')
        result=redact(asyncio.run(main(json.loads(raw))))
        encoded=json.dumps(result,ensure_ascii=False)
        if len(encoded)>24000 and not result.get('handshake_verified'):
            result={'status':result.get('status'),'text':json.dumps(result.get('data'),ensure_ascii=False)[:20000],
                    'truncated':True,'note':'结果超过本轮摘录范围，只能基于已返回内容作答；评论需继续分页读取。'}
        print(json.dumps(result,ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'status':'failed','error':'MCP '+type(exc).__name__+'；请检查平台登录、参数或连接状态'}))
