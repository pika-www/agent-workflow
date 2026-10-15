"""Local preparation records, separate from credentials and verified connections.

Nothing in this module performs OAuth or a platform operation. User-declared
application approval is never promoted to a verified account or granted scope.
"""
import copy
from datetime import datetime, timezone
import json
import re
import threading
import uuid

from .core import _write_json
from .social_catalog import get_provider, list_providers
from .social_observations import SocialObservationStore


CAPABILITIES = ('read', 'publish', 'comments', 'messages')
APPLICATION_STATUSES = ('unknown', 'not_created', 'applied', 'approved')
STATUS = {
    'unknown': ('awaiting_application', '待确认应用情况 · 未连接'),
    'not_created': ('awaiting_application', '待申请应用 · 未连接'),
    'applied': ('awaiting_review', '申请审核中 · 未连接'),
    'approved': ('awaiting_authorization', '自报应用已获批 · 待核验及授权'),
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{32}', value):
        raise ValueError('账号准备记录编号无效。')
    return value


def _fields(data, creating=False):
    allowed = {'label', 'application_status', 'requested_capabilities'}
    if creating:
        allowed.add('provider_id')
    if not isinstance(data, dict) or set(data) - allowed or not data:
        raise ValueError('仅可保存账号别名、应用申请进度和所需功能；本接口不接收凭据或连接状态。')
    result = {}
    if creating:
        result['provider_id'] = get_provider(data.get('provider_id'))['id']
    if 'label' in data or creating:
        label = data.get('label', '')
        if not isinstance(label, str) or not 1 <= len(label.strip()) <= 60 or re.search(r'[\x00-\x1f\x7f]', label):
            raise ValueError('请填写 1 至 60 字的账号别名，不支持换行或控制字符。')
        result['label'] = label.strip()
    if 'application_status' in data or creating:
        value = data.get('application_status', 'unknown')
        if not isinstance(value, str) or value not in APPLICATION_STATUSES:
            raise ValueError('应用申请状态无效。')
        result['application_status'] = value
    if 'requested_capabilities' in data or creating:
        values = data.get('requested_capabilities', list(CAPABILITIES))
        if not isinstance(values, list) or not 1 <= len(values) <= 4 or any(not isinstance(x, str) or x not in CAPABILITIES for x in values):
            raise ValueError('请从读取分析、发布、评论、私信中选择所需功能。')
        if len(set(values)) != len(values):
            raise ValueError('所需功能不能重复。')
        result['requested_capabilities'] = [x for x in CAPABILITIES if x in values]
    return result


class SocialAccountStore:
    """Bounded, atomic metadata; no token store or model-readable credentials."""

    def __init__(self, store):
        self.store = store
        self.lock = threading.RLock()
        self.observations = SocialObservationStore(store)

    def _path(self):
        return self.store._safe(self.store.base, 'social-accounts/registry.json')

    def _read(self):
        path = self._path()
        if not path.exists():
            return []
        if not path.is_file() or path.stat().st_size > 256000:
            raise ValueError('社交账号准备记录无法读取；已保留原文件。')
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(payload, dict) or set(payload) != {'version', 'accounts'} or payload['version'] != 1:
                raise ValueError()
            records = payload['accounts']
            if not isinstance(records, list) or len(records) > 100:
                raise ValueError()
            ids, names = set(), set()
            for record in records:
                if not isinstance(record, dict) or set(record) != {'id', 'provider_id', 'label', 'application_status', 'requested_capabilities', 'created_at', 'updated_at'}:
                    raise ValueError()
                _identifier(record['id'])
                fields = _fields({k: record[k] for k in ('provider_id', 'label', 'application_status', 'requested_capabilities')}, creating=True)
                if any(record[k] != v for k, v in fields.items()):
                    raise ValueError()
                name = (record['provider_id'], record['label'].casefold())
                if record['id'] in ids or name in names:
                    raise ValueError()
                ids.add(record['id']); names.add(name)
                for key in ('created_at', 'updated_at'):
                    if not isinstance(record[key], str) or datetime.fromisoformat(record[key]).tzinfo is None:
                        raise ValueError()
            return records
        except (ValueError, TypeError, KeyError):
            raise ValueError('社交账号准备记录格式无效；已保留原文件，未自动重置。') from None

    def _write(self, records):
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.parent.chmod(0o700)
        _write_json(self._path(), {'version': 1, 'accounts': records})

    @staticmethod
    def _public(record):
        item = copy.deepcopy(record)
        item['status'], item['status_label'] = STATUS[item['application_status']]
        item.update(connected=False, granted_capabilities=[], connection_verified_at=None)
        return item

    def snapshot(self):
        with self.lock:
            accounts = [self._public(record) for record in self._read()]
        observations = self.observations.snapshot()
        return {'providers': list_providers(), 'accounts': accounts,
                'summary': {'connected': 0, 'total': len(accounts)},
                'observations': observations,
                'policy': {'mode': 'preparation', 'note': '本页管理接入准备与已保存的只读快照；API 授权与持续同步尚未完成。'}}

    def create(self, data):
        fields = _fields(data, creating=True)
        with self.lock:
            records = self._read()
            existing = next((x for x in records if x['provider_id'] == fields['provider_id'] and x['label'].casefold() == fields['label'].casefold()), None)
            if existing:
                return {'account': self._public(existing), 'created': False}
            if len(records) >= 100:
                raise ValueError('最多保存 100 条账号准备记录。')
            timestamp = _now()
            record = dict(fields, id=uuid.uuid4().hex, created_at=timestamp, updated_at=timestamp)
            records.append(record)
            self._write(records)
            return {'account': self._public(record), 'created': True}

    def update(self, identifier, data):
        _identifier(identifier)
        fields = _fields(data)
        with self.lock:
            records = self._read()
            record = next((x for x in records if x['id'] == identifier), None)
            if record is None:
                raise FileNotFoundError('账号准备记录不存在。')
            label = fields.get('label', record['label'])
            if any(x['id'] != identifier and x['provider_id'] == record['provider_id'] and x['label'].casefold() == label.casefold() for x in records):
                raise ValueError('该平台已有同名账号准备记录，请使用不同别名。')
            record.update(fields, updated_at=_now())
            self._write(records)
            return {'account': self._public(record)}

    def status_answer(self, question):
        snapshot = self.snapshot()
        providers = snapshot['providers']
        aliases = {'douyin': ('抖音',), 'xiaohongshu': ('小红书',), 'bilibili': ('B站', 'b站', '哔哩哔哩'),
                   'weibo': ('微博',), 'wechat_official': ('公众号',), 'wechat_channels': ('视频号',)}
        selected = [p for p in providers if any(name in question for name in aliases[p['id']])]
        selected = selected or providers
        lines = ['当前没有经过真实授权核验的社交 API 连接，尚未建立持续同步。',
                 '', '接入准备情况：']
        for provider in selected:
            records = [x for x in snapshot['accounts'] if x['provider_id'] == provider['id']]
            states = '；'.join(sorted({x['status_label'] for x in records})) if records else '尚未登记应用情况'
            lines.append('- ' + provider['name'] + '：' + states + ('（' + str(len(records)) + ' 个准备记录）' if records else '') + '。')
        observations = snapshot['observations']
        selected_ids = {provider['id'] for provider in selected}
        if any(item['provider_id'] in selected_ids for item in observations['snapshots']):
            lines.extend(['', '本地已有抖音只读数据快照，可说“查看我的抖音数据”读取。快照只反映记录时可见的数据，不代表当前浏览器仍登录或自动同步。'])
        if any(item['provider_id'] in selected_ids for item in observations['errors']):
            lines.append('部分本地快照不可用，原文件已保留；请在社交账号中心查看错误提示。')
        lines.extend(['', '在顶栏或主 Agent 窗口打开“社交账号”，可查看各平台官方入口、申请条件和能力范围，保存账号别名与申请进度。',
                      '记录“应用已获批”仍需后续核验权限并完成账号授权；本地准备记录不代表已连接。本次没有调用任何社交平台接口。'])
        return '\n'.join(lines)


def is_social_status_request(question):
    """Narrow status intent; ordinary social-content questions keep model flow."""
    text = re.sub(r'\s+', '', str(question)).rstrip('。！？!?')
    # Match complete short requests, never keywords embedded in an article,
    # technical question, troubleshooting request or compound instruction.
    platform = r'(?:抖音|小红书|B站|b站|哔哩哔哩|微博|微信公众号|公众号|视频号)(?:账号|帐号)?'
    owner = r'(?:(?:我的|我们的|我所有的|我们所有的|当前的?|现在的?|这些|这六个?|所有的?|全部的?))*'
    target = owner + r'(?:社交账号|社交媒体|' + platform + r'(?:[、，,和及与]' + platform + r')*)'
    prefix = r'(?:请)?(?:帮我|我要|我想|我希望)?(?:先)?'
    lookup = r'(?:查看|看看|查询|检查|列出)'
    connection = r'(?:连接|接入|授权|绑定|接上|接好)'
    status = (r'(?:(?:连接|接入|授权|绑定)?(?:情况|状态|进度|列表)(?:怎么样|如何|呢)?|'
              + connection + r'(?:好|成功|完成)?(?:了吗|了没|了没有|没有)|'
              + connection + r'(?:是否成功|是否完成)|'
              r'(?:是否|有没有|是不是已经)' + connection + r'(?:好|成功|完成)?了?)')
    if re.fullmatch(prefix + r'(?:接入|连接|绑定|管理)' + target + r'(?:吧)?', text):
        return True
    status_lookup = re.fullmatch(prefix + lookup + r'?(?P<target>' + target + r')(?:的)?(?P<status>' + status + r')', text)
    if status_lookup:
        return bool(re.search(r'账号|帐号', status_lookup['target']) or
                    re.search(connection, status_lookup['status']))
    bare_lookup = re.fullmatch(prefix + lookup + r'(?P<target>' + target + r')', text)
    if bare_lookup and re.search(r'账号|帐号|社交媒体', bare_lookup['target']):
        return True
    return bool(re.fullmatch(owner + r'社交账号', text))
