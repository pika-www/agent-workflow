"""Host tools run in their own bounded scopes; model input never selects a process."""
import asyncio
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import json
import os
from pathlib import Path
import sys
import signal
import uuid
from .tool_contracts import validate_contract, ToolContractError, MAX_REQUEST_BYTES
from .core import FederationStore
from .project_research import research_project

def profit_calculate(args):
    if set(args) - {'price','unit_cost','fixed_cost','units','discount'}:
        raise ValueError('不支持的盈利计算参数')
    values={}
    for key in ('price','unit_cost','fixed_cost','units','discount'):
        raw=str(args.get(key, '1' if key=='discount' else ''))
        if len(raw)>30: raise ValueError('计算数值过长')
        try: value=Decimal(raw)
        except InvalidOperation: raise ValueError('计算参数不是有效数字') from None
        if not value.is_finite() or value<0 or value>Decimal('1e12'):raise ValueError('计算参数超出范围')
        values[key]=value
    if values['discount']>1 or values['units']!=values['units'].to_integral_value():raise ValueError('折扣须为0至1，销量须为整数')
    price=values['price']*values['discount'];margin=price-values['unit_cost']
    revenue=price*values['units'];variable=values['unit_cost']*values['units']
    break_even=(values['fixed_cost']/margin).to_integral_value(rounding=ROUND_CEILING) if margin>0 else None
    return {'status':'completed','kind':'hypothetical_calculation','inputs':{k:str(v) for k,v in values.items()},
            'revenue':str(revenue),'variable_cost':str(variable),'total_cost':str(variable+values['fixed_cost']),
            'profit':str(revenue-variable-values['fixed_cost']),'unit_margin':str(margin),
            'break_even_units':str(break_even) if break_even is not None else None,
            'formula':'收入=单价×折扣×销量；利润=收入−单位变动成本×销量−固定成本',
            'note':'只核对假设数字的算术，不证明销量、市场需求或目标产品的成本。'}

async def execute(context, tool, args):
    validate_contract(tool, args)
    if tool=='profit_calculate': return profit_calculate(args)
    store=FederationStore(context['base'])
    room_id=context.get('room_id')
    if tool=='server_files':
        from .server_files import tool as server_tool
        if set(args)!={'action','parameters'}:raise ValueError('服务器工具参数无效')
        return await asyncio.to_thread(server_tool,store,context,args['action'],args['parameters'])
    if tool in {'platform_tools','platform_read'}:
        if not context.get('tools_enabled') or not context.get('network_allowed') or not room_id:raise ValueError('本轮未开放平台读取工具')
        from .platform_mcp_registry import catalog
        if tool=='platform_tools':return {'status':'completed',**catalog(args['platform'])}
        from .tool_contracts import validate_dynamic_schema
        entries=catalog(args['platform'])['platforms']
        schema=next((t.get('inputSchema') for entry in entries for t in entry['schemas'] if t['name']==args['tool']),None)
        if schema is None:
            raise ToolContractError('tool','unknown_tool_schema','先连接平台并获取实际工具定义，不能猜测参数')
        validate_dynamic_schema(schema,json.loads(args['arguments']))
        from .platform_content import execute as platform_read
        return await platform_read(args['platform'],args['tool'],json.loads(args['arguments']))
    if tool=='visual_browser':
        if not context.get('network_allowed'): raise ValueError('本轮未授权公开浏览')
        if not isinstance(args,dict) or set(args)!={'url','actions','viewport'}: raise ValueError('浏览参数无效')
        from .visual_browser import browse
        return await browse(store,room_id,args['url'],args['actions'],args['viewport'])
    if tool in {'file_search','file_read','audio_transcribe','video_analyze','code_interpreter','image_analyze','image_generate','connector_search','connector_read'}:
        if not room_id: raise ValueError('本轮缺少附件与执行会话范围')
        if not context.get('tools_enabled'): raise ValueError('本轮未授权执行工具')
        if tool=='file_search':
            from .tool_files import search_files
            return await asyncio.to_thread(search_files,store,room_id,args['query'],args['file_ids'])
        if tool=='file_read':
            from .document_tools import read_document
            return await read_document(store,room_id,args['file_id'],args['question'],args['start'],args['limit'])
        if tool in {'audio_transcribe','video_analyze'}:
            from .tool_services import configuration
            service='audio' if tool=='audio_transcribe' else 'video'
            if configuration(store).get(service,{}).get('enabled') is False:return {'status':'unavailable','error':'该媒体工具已关闭'}
            from .audio_video import transcribe,analyze_video
            if tool=='audio_transcribe':return await transcribe(store,room_id,args['file_id'],args['start'],args['duration'],args['language'])
            return await analyze_video(store,room_id,args['file_id'],args['question'],args['start'],args['duration'])
        if tool=='code_interpreter':
            from .code_sandbox import run_code
            return await run_code(store,room_id,args['code'],args['file_ids'])
        if tool=='image_analyze':
            from .media_tools import analyze
            return await analyze(store,room_id,args['file_id'],args['question'],args.get('start','1'),args.get('count','8'),local_only=not context.get('network_allowed'))
        if not context.get('network_allowed'):raise ValueError('本轮禁止访问外部服务')
        if tool=='image_generate':
            from .media_tools import generate
            return await generate(store,room_id,args['prompt'],args['size'])
        from .connector_tools import execute as connector
        return await connector(store,args['provider'],**({'query':args['query']} if tool=='connector_search' else {'object_id':args['object_id']}))
    if tool not in {'web_read','web_search'} or not context.get('network_allowed'): raise ValueError('本轮未授权联网工具')
    if not isinstance(args,dict) or set(args)!={'url' if tool=='web_read' else 'query'}:raise ValueError('网页工具参数无效')
    query=args.get('url' if tool=='web_read' else 'query')
    if not isinstance(query,str) or not query.strip() or len(query)>1000 or '\0' in query:raise ValueError('查询参数无效')
    if tool=='web_read' and not query.startswith(('https://','http://')):raise ValueError('必须提供实际公开网址')
    if tool=='web_search':
        from .public_search import search
        return await search(store,query)
    profile=context.get('research_profile')
    if profile not in {None,'product-analysis'}:raise ValueError('公开读取配置无效')
    excerpt_query=context.get('excerpt_query')
    return await research_project(store,query,uuid.uuid4().hex,store.spaces(),profile=profile,
                                  **({'excerpt_query':excerpt_query} if excerpt_query else {}))

def main():
    path=Path(os.environ['FEDERATION_TOOL_CONTEXT'])
    if path.is_symlink() or not path.is_file() or path.stat().st_size>20000:raise ValueError('工具上下文无效')
    context=json.loads(path.read_text())
    raw=sys.stdin.buffer.read(MAX_REQUEST_BYTES+1)
    if len(raw)>MAX_REQUEST_BYTES:raise ValueError('工具输入过长')
    request=json.loads(raw)
    # Local excerpt selection only. Never append private dialogue to a URL,
    # search query, network request, or the worker's permission fields.
    excerpt_query=request.get('excerpt_query','')
    if not isinstance(excerpt_query,str) or len(excerpt_query)>2000 or '\0' in excerpt_query:raise ValueError('摘录问题无效')
    context={**context,'excerpt_query':excerpt_query}
    async def run():
        task=asyncio.current_task()
        for sig in (signal.SIGTERM,signal.SIGINT):asyncio.get_running_loop().add_signal_handler(sig,task.cancel)
        return await execute(context,request['tool'],request['args'])
    try:result=asyncio.run(run())
    except asyncio.CancelledError:result={'status':'cancelled','error':'工具执行已取消'}
    except ToolContractError as exc:
        result={'status':'failed','error':str(exc),'error_detail':exc.detail,'executed':False}
    except Exception as exc:
        from .web_learning import public_read_error
        result=({'status':'failed','error':str(exc)[:500],'scope':'server-account'} if request['tool']=='server_files'
                else {'status':'failed',**public_read_error(exc)})
    service={'web_search':'search','visual_browser':'browser','code_interpreter':'code','file_search':'files','file_read':'files','audio_transcribe':'audio','video_analyze':'video','image_analyze':'vision','image_generate':'image'}.get(request['tool'])
    if request['tool'] in {'connector_read','connector_search'}:service=request['args'].get('provider')
    if service:
        from .tool_services import record_execution
        record_execution(FederationStore(context['base']),service,result)
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__': main()
