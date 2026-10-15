"""Local API for attachments, service configuration and read-only connection checks."""
import asyncio
import base64
import httpx
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import Request,HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel,Field
from .tool_files import put_file,get_file,list_files
from .tool_services import status,save_service

class FileUpload(BaseModel):
    filename:str=Field(min_length=1,max_length=160)
    data_base64:str=Field(min_length=1,max_length=66_666_672)

class LocalImport(BaseModel):
    path:str=Field(min_length=1,max_length=2000)

class ImageCheck(BaseModel):
    room_id:str=Field(pattern=r'^[a-f0-9]{32}$')

class ServerDecision(BaseModel):
    decision:str=Field(pattern=r'^(approve|reject)$')

def install(app,store,chat,check_writable):
    login_processes = {}
    def room(room_id):return chat.get_room(room_id)
    def same_origin(request,require_idle=True):
        origin=request.headers.get('origin')
        if origin and urlsplit(origin).netloc!=request.headers.get('host'):raise HTTPException(403,'只允许本机页面配置工具')
        if require_idle:check_writable()

    @app.get('/api/tool-services/status')
    async def tool_status():return status(store)

    @app.get('/api/tool-services/metrics')
    async def reliability_metrics():
        from .tool_metrics import summary
        return await asyncio.to_thread(summary,store.base)

    @app.get('/api/chat/rooms/{room_id}/server-operations')
    async def server_operations(room_id:str):
        room(room_id)
        from .server_files import list_operations
        return {'operations':await asyncio.to_thread(list_operations,store,room_id)}

    @app.post('/api/chat/rooms/{room_id}/server-operations/{operation_id}/decision')
    async def server_decision(room_id:str,operation_id:str,data:ServerDecision,request:Request):
        same_origin(request,require_idle=False);room(room_id)
        # A model tool has no decision method. Reject cross-origin and non-UI requests.
        if not request.headers.get('origin') or request.headers.get('x-weiming-confirm')!='server-operation':
            raise HTTPException(403,'请在当前聊天界面确认此操作')
        from .server_files import decide
        try:return await asyncio.to_thread(decide,store,room_id,operation_id,data.decision)
        except (OSError,ValueError) as error:raise HTTPException(409,str(error)[:400]) from None

    @app.get('/server-operations.js')
    async def server_operations_client():
        return FileResponse(Path(__file__).parent/'web/server-operations.js',media_type='text/javascript')

    @app.get('/api/platform-mcp/status')
    async def platform_status():
        from .platform_mcp_registry import catalog,load_json,private_path,write_private
        for provider,process in list(login_processes.items()):
            if process.poll() is not None:
                previous=load_json(private_path(provider+'-login-status.json'))
                if previous.get('state') in {'starting','waiting'}:
                    write_private(private_path(provider+'-login-status.json'),{'state':'failed','message':'登录进程已结束，请重新登录。'})
                del login_processes[provider]
        return catalog()

    @app.post('/api/platform-mcp/{provider}/login')
    async def platform_login(provider:str,request:Request):
        same_origin(request)
        import subprocess,os
        from .platform_mcp_registry import RUNTIME,CODE,installed,private_path,write_private
        if provider not in {'bilibili','douyin','tieba'}:raise HTTPException(400,'此平台需要开发者应用 OAuth 授权，不能普通扫码登录')
        if not installed(provider):raise HTTPException(409,'平台 MCP 尚未安装')
        import sys
        if provider in {'douyin','tieba'} and sys.platform == 'linux' and not os.environ.get('DISPLAY'):
            raise HTTPException(409,'服务器没有交互桌面。抖音与贴吧的扫码登录需在 Mac 独立浏览器完成；已有凭据会继续用于读取。详见 deploy/server/README.md。')
        process=login_processes.get(provider)
        if process and process.poll() is None:return {'status':'waiting'}
        env_name={'bilibili':'bilibili','douyin':'douyin-reader','tieba':'mediacrawler'}[provider]
        env={k:os.environ[k] for k in ('PATH','LANG','TZ') if k in os.environ}
        write_private(private_path(provider+'-login-status.json'),{'state':'starting','message':'正在准备登录入口…'})
        process=subprocess.Popen([str(RUNTIME/'envs'/env_name/'bin/python'),str(CODE/'login.py'),provider],
            cwd=CODE,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        login_processes[provider]=process
        return {'status':'waiting'}

    @app.get('/api/platform-mcp/bilibili/login-qr')
    async def platform_login_qr():
        from .platform_mcp_registry import private_path,login_state
        path=private_path('bilibili-login.png')
        if not path.is_file() or login_state('bilibili').get('state')!='waiting':raise HTTPException(404,'二维码尚未生成或已失效')
        return FileResponse(path,media_type='image/png',headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})

    @app.put('/api/tool-services/{service}')
    async def configure(service:str,value:dict,request:Request):
        same_origin(request)
        try:return save_service(store,service,value)
        except ValueError as e:raise HTTPException(400,str(e)) from None

    @app.post('/api/tool-services/connectors/{provider}/check')
    async def check_connector(provider:str,request:Request):
        same_origin(request)
        from .connector_tools import request as read
        from .tool_services import configuration
        if provider not in {'github','notion','gmail'}:raise HTTPException(400,'服务不支持')
        paths={'github':'/user','notion':'/users/me','gmail':'/profile'}
        try:
            data=await read(configuration(store).get(provider,{}),provider,paths[provider])
            from .tool_services import record_execution
            record_execution(store,provider,{'status':'completed','scope':'connection_identity'})
            return {'status':'completed','provider':provider,'identity':data.get('login') or data.get('name') or data.get('emailAddress'),'scope':'connection_identity','read_verified':False}
        except (ValueError,httpx.HTTPError) as e:
            from .tool_services import record_execution
            record_execution(store,provider,{'status':'failed','scope':'connection_identity'})
            raise HTTPException(409,str(e) if isinstance(e,ValueError) else '账号连接请求失败，请检查网络与授权') from None

    @app.post('/api/tool-services/image/check')
    async def check_image(data:ImageCheck,request:Request):
        same_origin(request)
        current=room(data.room_id)
        if current.get('status') in {'queued','running'}:raise HTTPException(409,'请等本轮结束后测试图片服务')
        from .media_tools import generate
        from .tool_services import record_execution
        try:result=await generate(store,data.room_id,'Generate one minimal illustration: a blue circle on a plain white background. No text.','1024x1024')
        except (ValueError,OSError):result={'status':'failed','error':'图片服务未返回有效图片，未自动重复创建'}
        record_execution(store,'image',result)
        return result

    @app.post('/api/chat/rooms/{room_id}/files')
    async def upload(room_id:str,data:FileUpload,request:Request):
        same_origin(request,require_idle=False)
        current=room(room_id)
        if current.get('status') in {'queued','running'}:
            raise HTTPException(409,'请等当前会话本轮结束后添加附件')
        try:
            raw=base64.b64decode(data.data_base64,validate=True)
            return await asyncio.to_thread(put_file,store,room_id,data.filename,raw)
        except (ValueError,TypeError,OSError) as e:raise HTTPException(400,'附件格式或内容无效：'+str(e)[:160]) from None

    @app.get('/api/chat/rooms/{room_id}/files')
    async def files(room_id:str):
        room(room_id);return {'files':list_files(store,room_id)}

    @app.post('/api/chat/rooms/{room_id}/local-files')
    async def local_files(room_id:str,data:LocalImport,request:Request):
        same_origin(request)
        current=room(room_id)
        if current.get('status') in {'queued','running'}:raise HTTPException(409,'请等当前回复结束后导入本地资料')
        from .local_files import import_local
        try:return await asyncio.to_thread(import_local,store,room_id,data.path)
        except (ValueError,OSError):raise HTTPException(400,'本地资料无法导入：请检查路径、支持格式、大小与读取权限；不读取凭据或符号链接') from None

    @app.get('/api/chat/rooms/{room_id}/files/{file_id}')
    async def download(room_id:str,file_id:str):
        room(room_id)
        try:item,path=get_file(store,room_id,file_id)
        except (ValueError,OSError):raise HTTPException(404,'附件不存在') from None
        # A standalone media document loads this same URL into its player.
        # Keep scripts/default sources blocked, allow only same-origin media.
        csp="default-src 'none'"+("; media-src 'self'" if item['kind'] in {'audio','video'} else '')
        return FileResponse(path,media_type=item['media_type'],filename=item['name'],content_disposition_type='inline' if item['kind'] in {'image','audio','video'} else 'attachment',
                            headers={'X-Content-Type-Options':'nosniff','Cache-Control':'private, no-store','Content-Security-Policy':csp})

    @app.get('/agent-tools.js')
    async def client():return FileResponse(Path(__file__).parent/'web/agent-tools.js',media_type='text/javascript')
