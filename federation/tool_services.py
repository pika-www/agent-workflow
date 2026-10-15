"""Private tool service configuration and truthful runtime capabilities."""
import importlib.util
import importlib.metadata
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import urlsplit
from datetime import datetime,timezone
from .report_model import _read, _write_private, validate_config
from .browser_runtime import executable as browser_executable

SERVICES = {'search', 'vision', 'audio', 'video', 'image', 'tool_agent', 'github', 'notion', 'gmail'}

def tool_request(question,has_files=False):
    if has_files:return True
    if re.search(r'(?:服务器|服务端|/home/|/etc/|/var/|/tmp/).{0,100}(?:文件|目录|读取|查看|删除|写入|执行|命令)|(?:读取|查看|列出|创建|写入|删除|移动|复制|执行).{0,100}(?:服务器|/home/|/etc/|/var/|/tmp/)',question,re.S):return True
    if re.search(r'(?:联网|上网).{0,8}(?:搜索|查询|查找)|(?:使用|调用|用)\s*web_search\b', question, re.I):return True
    if re.match(r'\s*(?:如何|怎么|为什么|什么是|解释|介绍|有哪些|你支持)',question):return False
    return bool(re.search(r'(?:用|运行|执行).{0,12}(?:Python|python|代码)|(?:生成|画|绘制|做).{0,10}(?:图表|柱状图|折线图|图片|插画)|(?:计算|分析).{0,15}(?:数据|表格|平方和)|(?:搜索|查找|查询|读取).{0,15}(?:Notion|Gmail|GitHub)|(?:联网|上网).{0,8}(?:搜索|查询|查找)',question,re.I))

def capability_question(question):
    return bool(re.search(r'(?:你|当前系统|这个系统|自带|这些).{0,45}(?:工具|功能|解释器|文件检索|看图|画图|第三方).{0,20}(?:有哪些|支持|有吗|有没有|具备)|(?:你|当前系统|这个系统).{0,12}(?:有哪些|支持哪些).{0,12}(?:工具|功能)',question,re.S))

def capability_answer(store):
    current=status(store)
    def state(service):
        s=current[service]
        return '已通过实际调用验证' if s['verified'] else '上次调用失败' if s.get('last_execution',{}).get('status')=='failed' else '已配置，等待实际调用验证' if s['configured'] else '需要配置服务'
    accounts='、'.join(name for key,name in [('github','GitHub 私有仓库'),('notion','Notion'),('gmail','Gmail')] if not current['connectors'][key]['configured'])
    return ('当前已接入联网搜索、公开网页浏览、隔离 Python 执行与图表、聊天附件检索、图片分析和图片生成接口，以及 GitHub、Notion、Gmail 的只读连接。Agent 会根据任务自主调用工具，并把结果接回同一轮回复。\n\n'
            +(f"服务器文件与终端：可读取 {current['server_files']['account']} 账号有权访问的文件；文件更改和命令需在聊天确认区逐项确认后执行，不自动提权。\n\n" if current['server_files']['configured'] else '')
            +'联网搜索：'+state('search')+'。代码与图表：'+state('code')+'。看图：'+state('vision')+'。生成图片：'+state('image')+'。\n\n'
            +'PDF、Word、PPT/PPTX、文本、CSV、Excel、图片及音视频可上传；支持全文/分段读取、本地看图、时间戳转写及视频抽样分析。也可在“工具与连接”中只读导入指定本地文件。图表和转写文字可下载。GitHub 公共仓库可直接读取。'
            +(accounts+'仍需账号授权。' if accounts else '第三方账号已配置；成功读取以实际回执为准。')
            +'工具配置和已验证能力分别显示在“工具与连接”中。')

def configuration(store):
    path = store._safe(store.base, 'private/tool-services.json')
    return _read(path) if path.exists() else {}

def save_service(store, service, value):
    if service not in SERVICES or not isinstance(value, dict):
        raise ValueError('工具服务无效')
    allowed = {'enabled', 'api_key', 'base_url', 'model', 'reuse_report', 'access_token', 'refresh_token', 'client_id', 'client_secret', 'provider', 'responses_api', 'image_api', 'response_model', 'simple_chat_model', 'simple_chat_responses_api', 'simple_chat_fallback_model'}
    if set(value) - allowed: raise ValueError('工具服务配置字段无效')
    for field in ('simple_chat_model', 'simple_chat_fallback_model'):
        if field in value:
            model = value[field]
            if service != 'tool_agent' or not isinstance(model, str) or model and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,159}', model):
                raise ValueError('寒暄模型只用于对话服务，且必须是合法模型名')
    if 'simple_chat_responses_api' in value and (service != 'tool_agent' or not isinstance(value['simple_chat_responses_api'], bool)):
        raise ValueError('寒暄协议只用于对话服务，且必须为布尔值')
    if service != 'image' and {'image_api','response_model'} & set(value): raise ValueError('图片协议只用于图片服务')
    if any(not isinstance(v, (str, bool)) for v in value.values()): raise ValueError('配置类型无效')
    current = configuration(store)
    entry = {**current.get(service, {}), **{k:v for k,v in value.items() if v != ''}}
    for field in ('simple_chat_model', 'simple_chat_fallback_model'):
        if value.get(field) == '': entry.pop(field, None)
    for field in ('enabled','reuse_report','responses_api'):
        if field in entry and not isinstance(entry[field], bool): raise ValueError('启用状态无效')
    for field in ('api_key','access_token','refresh_token','client_id','client_secret','model','response_model'):
        if field in entry and (len(entry[field]) > 4096 or any(c.isspace() for c in entry[field])): raise ValueError('密钥或模型格式无效')
    if service == 'image':
        if entry.get('image_api','images') not in {'images','responses'}: raise ValueError('图片接口协议不支持')
        if entry.get('response_model') and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,159}',entry['response_model']): raise ValueError('Responses 主模型名无效')
        if entry.get('image_api')=='responses' and entry.get('reuse_report') is False and not entry.get('response_model'): raise ValueError('Responses 图片服务需要填写主模型')
    if service in {'vision','image','tool_agent'} and not (service=='vision' and entry.get('provider')=='local-ollama') and not entry.get('reuse_report',True) and entry.get('enabled') is not False:
        validate_config({'provider':'openai-compatible', 'base_url':entry.get('base_url',''), 'api_key':entry.get('api_key',''), 'model':entry.get('model','')})
    if service == 'search' and entry.get('provider','auto') not in {'auto','duckduckgo','bing-rss','tavily'}: raise ValueError('搜索服务不支持')
    if service=='vision' and entry.get('provider') not in {None,'local-ollama','remote'}:raise ValueError('看图模式不支持')
    if service in {'audio','video'} and set(value)-{'enabled'}:raise ValueError('音视频使用本机模型，只接受启用开关')
    current[service] = entry
    _write_private(store._safe(store.base,'private/tool-services.json'), current)
    return status(store)

def model_config(store, service, *, simple_chat=False):
    entry = configuration(store).get(service, {})
    if entry.get('enabled') is False: return None
    if service=='vision' and entry.get('provider')=='local-ollama':
        from .local_models import local_config
        return {'provider':'local-ollama',**local_config(),'responses_api':False}
    if entry.get('reuse_report', True):
        path=store._safe(store.base, 'private/report-model.json')
        if not path.exists(): return None
        base=validate_config(_read(path))
        if base['provider'] not in {'openai','openai-compatible'}: return None
        result={'provider':base['provider'],'base_url':base.get('base_url') or 'https://api.openai.com/v1', 'api_key':base['api_key'],
                'model':entry.get('model') or ('gpt-image-1' if service == 'image' else base['model']),'responses_api':base.get('responses_api',False)}
        default_response_model=base['model']
    else:
        if not entry.get('api_key'): return None
        result={'provider':'openai-compatible','base_url':entry['base_url'], 'api_key':entry['api_key'], 'model':entry['model'],'responses_api':entry.get('responses_api',False)}
        default_response_model=None
    if simple_chat and service == 'tool_agent' and entry.get('simple_chat_model'):
        model = entry['simple_chat_model']
        if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,159}', model):
            raise ValueError('寒暄模型配置无效')
        result['model'] = model
    if simple_chat and service == 'tool_agent':
        if 'simple_chat_responses_api' in entry:
            if not isinstance(entry['simple_chat_responses_api'], bool): raise ValueError('寒暄协议配置无效')
            result['responses_api'] = entry['simple_chat_responses_api']
        if entry.get('simple_chat_fallback_model'):
            fallback = entry['simple_chat_fallback_model']
            if not isinstance(fallback, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,159}', fallback): raise ValueError('备用寒暄模型配置无效')
            result['simple_chat_fallback_model'] = fallback
    if service=='image':result.update(image_api=entry.get('image_api','images'),response_model=entry.get('response_model') or default_response_model)
    return result

def fingerprint(store,service):
    if service == 'browser':
        chrome = browser_executable() or Path('/nonexistent/google-chrome')
        try: version = importlib.metadata.version('playwright')
        except importlib.metadata.PackageNotFoundError: version = None
        value = {'implementation': hashlib.sha256(Path(__file__).with_name('visual_browser.py').read_bytes()).hexdigest(),
                 'playwright': version, 'chrome': str(chrome), 'chrome_mtime': chrome.stat().st_mtime_ns if chrome.is_file() else None}
    elif service == 'code':
        import os
        value = {'platform': sys.platform, 'python': sys.version,
                 'sandbox_image': os.environ.get('WEIMING_SANDBOX_IMAGE', ''),
                 'implementation': {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                    for name in ('code_sandbox.py', 'linux_sandbox.py')}}
    elif service in {'files','audio','video'}:
        modules=['tool_files.py','document_tools.py'] if service=='files' else ['audio_video.py','media_worker.py','local_models.py']
        value={'config':configuration(store).get(service,{}),'implementation':{n:hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in modules}}
        if service in {'audio','video'}:
            from .audio_video import MODEL_PATH,availability
            value.update(ready=availability(),model_mtime=(MODEL_PATH/'model.bin').stat().st_mtime_ns if (MODEL_PATH/'model.bin').is_file() else None)
    elif service == 'search':
        value = {'config': configuration(store).get('search', {}),
                 'implementation': hashlib.sha256(Path(__file__).with_name('public_search.py').read_bytes()).hexdigest()}
    else:
        value=model_config(store,service) if service in {'vision','image','tool_agent'} else configuration(store).get(service,{})
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()

def record_execution(store,service,result):
    path=store._safe(store.base,'private/tool-checks.json')
    checks=_read(path) if path.exists() else {}
    check={'fingerprint':fingerprint(store,service),'status':result.get('status','failed'),
           'checked_at':datetime.now(timezone.utc).isoformat()}
    if result.get('scope')=='connection_identity':
        checks[service]={**checks.get(service,{}),'identity':check}
    else:
        checks[service]={**check,**({'identity':checks[service]['identity']} if checks.get(service,{}).get('identity') else {})}
    _write_private(path,checks)

def status(store):
    from .server_files import capability as server_capability
    config=configuration(store)
    from .web_learning import _search_key
    search_config=config.get('search',{})
    search_ready=search_config.get('enabled',True) and (search_config.get('provider','auto')!='tavily' or bool(search_config.get('api_key') or _search_key(store)))
    from .code_sandbox import sandbox_status
    from .linux_sandbox import available as linux_sandbox_available
    sandbox = sandbox_status()
    libs = all(importlib.util.find_spec(n) for n in ['numpy','pandas','matplotlib','PIL','openpyxl'])
    models={s:model_config(store,s) for s in ['vision','image','tool_agent']}
    from .audio_video import availability
    from .tool_files import FORMATS
    result={
      'server_files':server_capability(),
      'search':{'implemented':True,'configured':bool(search_ready),'provider':search_config.get('provider','auto')},
      'code':{'implemented':True,'configured':sandbox and libs,'isolation':'Linux Docker (no network, read-only runtime)' if linux_sandbox_available() else 'macOS Seatbelt','network':False,'timeout_seconds':30,'libraries':['numpy','pandas','matplotlib','pillow','openpyxl']},
      'files':{'implemented':True,'configured':True,'formats':sorted(s[1:] for s in FORMATS),'max_bytes':10000000,'media_max_bytes':50000000,'full_read':True,'local_import':'explicit-current-user-path-read-only',
               'runtime_location':os.environ.get('WEIMING_RUNTIME_LOCATION','local'),'path_hint':str(Path.home()/'资料')},
      'audio':{'implemented':True,'configured':availability(),'model':'faster-whisper-small/int8','provider':'local-cpu','window_seconds':300,'max_duration_seconds':7200,'timestamps':True},
      'video':{'implemented':True,'configured':availability(),'provider':'local-ollama + local-cpu','window_seconds':300,'frames_per_window':6,'sampling':True},
      'browser':{'implemented':True,'configured':bool(importlib.util.find_spec('playwright')) and bool(browser_executable()),
                 'scope':'public-read-only','actions':['open','read','scroll_down','scroll_up','next_page','previous_page','screenshot'],
                 'viewports':['desktop','mobile'],'max_steps':6,'max_screenshots':3,'user_profile':False,'verification':'requires_successful_execution'},
      **{s:{'implemented':True,'configured':bool(models[s]),'model':models[s]['model'] if models[s] else None,'verification':'requires_successful_execution'} for s in models},
      'connectors':{s:{'implemented':True,'configured':bool(config.get(s,{}).get('enabled') and (config[s].get('api_key') or config[s].get('access_token') or config[s].get('refresh_token'))),
                        'scope':'read-only','public_access':s=='github'} for s in ['github','notion','gmail']},
      'agent':{'native_tool_loop':True,'max_actions':8,'max_turns':10,'attachment_max_actions':32,'attachment_max_turns':34,'completed_tools_replayed':False,'attachment_host_fallback':True}
    }
    result['tool_agent']['simple_chat_model'] = config.get('tool_agent', {}).get('simple_chat_model') or result['tool_agent']['model']
    result['tool_agent']['simple_chat_responses_api'] = config.get('tool_agent', {}).get('simple_chat_responses_api', (models.get('tool_agent') or {}).get('responses_api', False))
    result['tool_agent']['simple_chat_fallback_model'] = config.get('tool_agent', {}).get('simple_chat_fallback_model') or None
    from .platform_mcp_registry import catalog
    result['platform_mcp']={'implemented':True,'configured':True,'enabled':True,'scope':'read-only',
        'platforms':[{k:p[k] for k in ('id','status','installed','handshake_verified','credentials_saved','tools')} for p in catalog()['platforms']]}
    checks_path=store._safe(store.base,'private/tool-checks.json')
    checks=_read(checks_path) if checks_path.exists() else {}
    for service in ['search','code','files','browser','vision','audio','video','image','tool_agent','github','notion','gmail']:
        entry=result.get(service) or result['connectors'].get(service)
        entry['enabled']=config.get(service,{}).get('enabled',service not in {'github','notion','gmail'})
        check=checks.get(service,{})
        entry['verified']=check.get('fingerprint')==fingerprint(store,service) and check.get('status')=='completed'
        if check.get('fingerprint')==fingerprint(store,service):entry['last_execution']={k:v for k,v in check.items() if k not in {'fingerprint','identity'}}
        if service in {'github','notion','gmail'}:
            identity=check.get('identity',{})
            entry['identity_verified']=identity.get('fingerprint')==fingerprint(store,service) and identity.get('status')=='completed'
            if identity.get('fingerprint')==fingerprint(store,service):
                entry['identity_check']={k:v for k,v in identity.items() if k!='fingerprint'}
                if identity.get('status')=='failed' and identity.get('checked_at','')>=check.get('checked_at',''):entry['verified']=False
        if service in {'vision','image','tool_agent'}:
            entry.update(reuse_report=config.get(service,{}).get('reuse_report',True),
                         base_url=(models[service] or {}).get('base_url'),responses_api=(models[service] or {}).get('responses_api',False),provider=(models[service] or {}).get('provider'))
        if service=='image':entry.update(image_api=(models[service] or {}).get('image_api',config.get(service,{}).get('image_api','images')),response_model=(models[service] or {}).get('response_model'))
    return result
