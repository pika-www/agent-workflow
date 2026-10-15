"""Pinned project-local platform tools. No account data is exposed by discovery."""
import json
import os
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / '.runtime/platform-mcp'
CODE = ROOT / 'federation/platform-mcp'
PROVIDERS = {
    'bilibili': {'name': 'B站', 'source': 'bilibili', 'env': 'bilibili',
                 'tools': ['search_video', 'get_video_info', 'get_video_subtitle', 'get_comments']},
    'douyin': {'name': '抖音', 'source': 'douyin-reader', 'env': 'douyin-reader',
               'tools': ['check_login_status', 'search_videos', 'get_video_detail', 'get_video_comments', 'get_sub_comments', 'get_user_info', 'get_user_posts']},
    'tieba': {'name': '百度贴吧', 'source': 'mediacrawler-mcp', 'env': 'mediacrawler-mcp',
              'tools': ['search', 'detail']},
    'douyin-openapi': {'name': '抖音开放接口', 'source': 'douyin-openapi',
                       'tools': ['auth_status', 'userinfo', 'comment_list', 'comment_replies']},
}

def private_path(name):
    path = RUNTIME / 'private' / name
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path

def write_private(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w') as out: json.dump(value, out, ensure_ascii=False)
        os.replace(temp, path)
        path.chmod(0o600)
    finally:
        if os.path.exists(temp): os.unlink(temp)

def load_json(path):
    try: return json.loads(path.read_text())
    except (OSError, ValueError): return {}

def login_state(provider):
    path = private_path(provider + '-login-status.json')
    state = load_json(path)
    if state.get('state') in {'starting', 'waiting'}:
        try: expired = time.time() - path.stat().st_mtime > 420
        except OSError: expired = True
        if expired: return {'state': 'failed', 'message': '登录已超时，请重新点击登录。'}
    return state

def credential_present(provider):
    if provider == 'bilibili': return bool(load_json(private_path('bilibili.json')).get('sessdata'))
    if provider == 'douyin':
        path = private_path('douyin-cookies.txt')
        return path.is_file() and path.stat().st_size > 0
    if provider == 'tieba': return load_json(private_path('tieba-login.json')).get('saved') is True
    data=load_json(RUNTIME / 'private/douyin-openapi/config/settings.json')
    return bool(data.get('openapi',{}).get('accessToken'))

def installed(provider):
    spec = PROVIDERS[provider]
    executable = RUNTIME / ('bin/douyin' if provider == 'douyin-openapi' else 'envs/' + spec['env'] + '/bin/python')
    return executable.is_file() and (RUNTIME / 'sources' / spec['source']).is_dir()

def catalog(provider=None):
    if provider is not None and provider not in PROVIDERS: raise ValueError('平台不支持')
    sources = {x['id']: x for x in load_json(CODE / 'sources.lock.json')}
    entries = []
    for key, spec in PROVIDERS.items():
        if provider and key != provider: continue
        check = load_json(RUNTIME / 'checks' / (key + '.json'))
        session = login_state(key)
        receipt = load_json(private_path(key + '-last-read.json'))
        source = sources.get(spec['source'], {})
        saved = credential_present(key)
        schemas=[t for t in check.get('tools', []) if t['name'] in spec['tools']]
        if key=='tieba':
            schemas=[{'name':name,'inputSchema':{'type':'object','properties':{field:{'type':'string'}},'required':[field],'additionalProperties':False}} for name,field in [('search','query'),('detail','post_id')]]
        if key=='douyin-openapi':
            schemas=json.loads(json.dumps(schemas))
            for tool in schemas:
                for field in ('token','open_id'):tool['inputSchema'].get('properties',{}).pop(field,None)
        entries.append({'id': key, 'name': spec['name'], 'installed': installed(key),
            'repository': source.get('repository'), 'commit': source.get('commit'),
            'handshake_verified': bool(check.get('handshake_verified') and check.get('commit') == source.get('commit')),
            'credentials_saved': saved, 'status': 'not_installed' if not installed(key) else 'login_saved' if saved else 'needs_login',
            'login': session, 'last_read': receipt, 'scope': 'read-only', 'tools': spec['tools'],
            'schemas': schemas,
            'login_hint': '需要开放平台应用 Client Key / Secret 及 OAuth 授权；普通扫码不能替代。' if key == 'douyin-openapi' else '在工具与连接中点击登录，在独立窗口完成扫码；凭据只保存在本项目。',
            'note': '依赖 MediaCrawler 的非商业学习许可证，仅用于个人学习研究。' if key == 'tieba' else ''})
    return {'platforms': entries}

def runtime_environment():
    env = {k: os.environ[k] for k in ('PATH', 'LANG', 'TZ', 'WEIMING_CHROME_PATH', 'LD_LIBRARY_PATH') if k in os.environ}
    if env.get('WEIMING_CHROME_PATH'):
        # Only the reviewed adapter is inherited by crawler subprocesses.
        env['PYTHONPATH'] = str(ROOT / 'deploy/server/playwright_override')
    return env


def server_spec(provider):
    spec = PROVIDERS[provider]
    env = runtime_environment()
    env.update(PYTHONUNBUFFERED='1', DO_NOT_TRACK='1', FASTMCP_CHECK_FOR_UPDATES='off')
    if provider == 'douyin-openapi':
        env['DOUYIN_HOME'] = str(RUNTIME / 'private/douyin-openapi')
        return str(RUNTIME / 'bin/douyin'), ['mcp'], env
    env['DOUYIN_COOKIE_PATH'] = str(private_path('douyin-cookies.txt'))
    env['DOUYIN_DOWNLOAD_DIR'] = str(RUNTIME / 'downloads')
    env['DOUYIN_TRANSCRIPT_DIR'] = str(RUNTIME / 'transcripts')
    env['MEDIACRAWLER_ROOT'] = str(RUNTIME / 'sources/mediacrawler')
    env['MEDIACRAWLER_PYTHON'] = str(RUNTIME / 'envs/mediacrawler/bin/python')
    env['DSH_MEDIACRAWLER_STATE_DIR'] = str(RUNTIME / 'private/mediacrawler')
    if provider == 'tieba' and env.get('WEIMING_CHROME_PATH'):
        env['WEIMING_TIEBA_COOKIES'] = str(private_path('tieba-cookies.json'))
        env['WEIMING_TIEBA_PROFILE'] = str(RUNTIME / 'private/mediacrawler/browser_profiles/tieba_user_data_dir')
    return str(RUNTIME / 'envs' / spec['env'] / 'bin/python'), [str(CODE / 'serve.py'), provider], env
