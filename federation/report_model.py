"""Private, report-only model configuration; ordinary Agent models stay scoped."""
import argparse
import getpass
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from urllib.parse import urlsplit

PROVIDERS = {'openai-compatible', 'openai', 'anthropic', 'gemini'}


def validate_config(value):
    if not isinstance(value, dict) or set(value) - {'provider', 'model', 'base_url', 'api_key', 'responses_api', 'reasoning_effort'}:
        raise ValueError('深度报告模型配置字段无效')
    if value.get('provider') not in PROVIDERS:
        raise ValueError('深度报告模型服务类型不支持')
    model = value.get('model', '')
    if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,159}', model):
        raise ValueError('深度报告模型名无效')
    key = value.get('api_key', '')
    if not isinstance(key, str) or not key.strip() or len(key) > 4096 or re.search(r'[\s\x00-\x1f]', key):
        raise ValueError('请在本机配置深度报告模型密钥')
    url = value.get('base_url', '')
    if url and value['provider'] == 'gemini':
        raise ValueError('Gemini 原生接口不接受自定义地址，请使用兼容服务类型连接网关')
    if url:
        if not isinstance(url, str) or len(url) > 2000:
            raise ValueError('深度报告接口地址无效')
        parsed = urlsplit(url)
        if (parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or re.search(r'[\s\x00-\x1f]', url)
                or (parsed.scheme == 'http' and parsed.hostname not in {'localhost','127.0.0.1','::1'})):
            raise ValueError('深度报告接口必须使用 HTTPS；本机接口可使用 HTTP，不允许地址中包含凭据')
        try:
            parsed.port
        except ValueError:
            raise ValueError('深度报告接口端口无效') from None
    elif value['provider'] == 'openai-compatible':
        raise ValueError('兼容服务需要配置接口地址')
    if 'responses_api' in value and not isinstance(value['responses_api'], bool):
        raise ValueError('报告接口协议配置无效')
    if value.get('reasoning_effort') not in {None,'none','low','medium','high','xhigh','max'}:
        raise ValueError('报告推理强度配置无效')
    return dict(value)


def config_path(store):
    return store._safe(store.base, 'private/report-model.json')


def _read(path):
    fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd) as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > 16000 or info.st_mode & 0o077:
            raise ValueError('报告模型配置应为本机私有文件，权限为 600')
        return json.load(handle)


def report_model_status(store):
    policy_path = store._safe(store.base, 'metadata/report-model-policy.json')
    try:
        policy = _read(policy_path) if policy_path.exists() else {}
        if not isinstance(policy, dict):
            raise ValueError('报告模型使用策略无效')
        required = policy.get('required') is True
    except (ValueError, OSError):
        return {'required':True, 'configured':False, 'scope':'product_analysis', 'fallback':'disabled',
                'error':'深度报告模型使用策略无效，请在本机检查；普通聊天仍可使用。'}
    path = config_path(store)
    result = {'required':required, 'configured':False, 'scope':'product_analysis', 'fallback':'disabled' if required else 'local',
              'note':'普通聊天继续使用各 Agent 的原有本地模型。'}
    if path.exists():
        try:
            value = validate_config(_read(path))
            result.update(configured=True, provider=value['provider'], model=value['model'], base_url=value.get('base_url',''), fallback='disabled')
            result['stream_protocol'] = 'responses_native_agent' if value.get('responses_api') else 'legacy_staged_model'
        except (ValueError, OSError, json.JSONDecodeError):
            result['error'] = '深度报告模型配置无效，请在本机检查配置，未回退为本地模型。'
    elif required:
        result['error'] = '深度报告等待强模型配置；还需要服务、模型名和本机密钥。普通聊天仍可使用。'
    return result


def report_model_environment(store):
    state = report_model_status(store)
    if state.get('error'):
        raise ValueError(state['error'])
    return ({'FEDERATION_REPORT_MODEL_CONFIG':str(config_path(store))} if state['configured'] else {}), state


def _write_private(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError('配置路径不能是符号链接')
    if path.exists():
        previous = _read(path)
        backup = path.with_name(path.stem + '-before-' + __import__('uuid').uuid4().hex + '.json')
        with open(backup, 'x') as handle:
            os.chmod(backup,0o600)
            json.dump(previous,handle,ensure_ascii=False,indent=2)
    fd, name = tempfile.mkstemp(prefix='.report-model-',dir=str(path.parent))
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,'w') as handle:
            json.dump(value,handle,ensure_ascii=False,indent=2)
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


def require_report_model(store):
    path = store._safe(store.base,'metadata/report-model-policy.json')
    if path.exists() and _read(path) == {'required':True}:
        return
    _write_private(path,{'required':True})


def main():
    parser = argparse.ArgumentParser(description='单独配置深度报告模型，密钥不经聊天或命令参数传入')
    parser.add_argument('--base', default=str(Path(__file__).resolve().parent.parent / 'openwiki-federation'))
    parser.add_argument('--provider', choices=sorted(PROVIDERS), required=True)
    parser.add_argument('--model',required=True)
    parser.add_argument('--base-url',default='')
    parser.add_argument('--responses-api',action='store_true')
    args=parser.parse_args()
    key=getpass.getpass('深度报告 API 密钥（不显示）：')
    value=validate_config({'provider':args.provider,'model':args.model,'base_url':args.base_url,'api_key':key,'responses_api':args.responses_api})
    from .core import FederationStore
    store=FederationStore(Path(args.base))
    _write_private(config_path(store),value)
    require_report_model(store)
    print('深度报告模型已配置。普通聊天模型没有改动。请在主 Agent 中重新发起产品分析以验证实际服务。')


if __name__ == '__main__':main()
