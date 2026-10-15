"""Read local observations without claiming OAuth or a continuing connection.

The host imports observations separately after reading the user's creator page.
This module neither writes files nor accesses browsers, credentials or networks.
"""
from datetime import datetime
import json
import os
import re
import stat
from urllib.parse import urlsplit


MAX_BYTES = 256000
MAX_FILES = 100
MAX_ANSWER_CHARS = 15999
_FILENAME = re.compile(r'[a-f0-9]{32}\.json')


def _object(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError('快照字段不符合只读数据格式。')
    return value


def _text(value, limit, *, nullable=False, multiline=False):
    if value is None and nullable:
        return value
    controls = r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]' if multiline else r'[\x00-\x1f\x7f]'
    if not isinstance(value, str) or not value.strip() or len(value) > limit or re.search(controls, value):
        raise ValueError('快照文字字段无效。')
    return value


def _list(value, maximum, minimum=0):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValueError('快照列表长度无效。')
    return value


def _captured_at(value):
    _text(value, 80)
    if not re.match(r'^\d{4}-\d{2}-\d{2}T', value):
        raise ValueError('读取时间必须使用带时区的 ISO 格式。')
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError('读取时间必须带时区。')
    return stamp


def _validate(value):
    _object(value, ('schema_version', 'provider_id', 'capture_method', 'captured_at',
                    'account', 'sources', 'period', 'metrics', 'works', 'limitations'))
    if type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise ValueError('快照版本无效。')
    if value['provider_id'] != 'douyin' or value['capture_method'] != 'creator_center_browser_read':
        raise ValueError('快照来源类型无效。')
    _captured_at(value['captured_at'])
    account = _object(value['account'], ('display_name', 'account_identifier'))
    _text(account['display_name'], 160)
    _text(account['account_identifier'], 120, nullable=True)
    for source in _list(value['sources'], 20, 1):
        _object(source, ('url', 'title'))
        _text(source['title'], 200)
        url = _text(source['url'], 1000)
        parts = urlsplit(url)
        if (parts.scheme != 'https' or parts.netloc != 'creator.douyin.com' or
                parts.query or parts.fragment or '?' in url or '#' in url or
                '\\' in url or re.search(r'\s', url)):
            raise ValueError('来源只允许不含凭据和查询参数的抖音创作者中心 HTTPS 地址。')
    period = _object(value['period'], ('label', 'start', 'end'))
    _text(period['label'], 250)
    for key in ('start', 'end'):
        # Preserve what the page actually displayed; do not infer dates.
        _text(period[key], 120, nullable=True)
    for metric in _list(value['metrics'], 100):
        _object(metric, ('label', 'display_value', 'scope'))
        _text(metric['label'], 160)
        _text(metric['display_value'], 160)
        _text(metric['scope'], 300)
    for work in _list(value['works'], 100):
        _object(work, ('description', 'published_at', 'visibility', 'format', 'duration'))
        _text(work['description'], 3000, multiline=True)
        for key in ('published_at', 'visibility', 'format', 'duration'):
            _text(work[key], 160)
    for limitation in _list(value['limitations'], 30, 1):
        _text(limitation, 1000, multiline=True)
    return value


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('快照包含重复字段。')
        value[key] = item
    return value


def _literal(value):
    """Render page text as inert Markdown, never instructions or HTML."""
    value = str(value).replace('\r', ' ').replace('\n', ' ').replace('\t', ' ')
    value = value.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return re.sub(r'([\\`*_{}\[\]()#+.!|~\-])', r'\\\1', value)


def _bounded_section(title, items, budget, category):
    """Keep whole items and reserve room to disclose every omitted item."""
    def notice(count):
        return f'另有 {count} 项{category}未在聊天中展开；请到“社交账号”中心查看完整快照。'

    selected = []
    # Reserve the maximum count notice before accepting any complete item.
    reserved = len(title) + len(notice(len(items))) + 2
    remaining = budget - reserved
    for item in items:
        if len(item) + 1 <= remaining:
            selected.append(item)
            remaining -= len(item) + 1
    omitted = len(items) - len(selected)
    if omitted:
        selected.append(notice(omitted))
    return '\n'.join([title, *selected])


class SocialObservationStore:
    def __init__(self, store):
        self.store = store

    def snapshot(self):
        result = {'snapshots': [], 'errors': [], 'mode': 'local_snapshot'}

        def failed(message):
            result['errors'].append({'provider_id': 'douyin', 'message': message})

        try:
            directory = self.store._safe(self.store.base, 'social-observations/douyin')
            if not directory.exists():
                return result
            if not directory.is_dir():
                raise ValueError('抖音快照目录无效；已保留原文件。')
            entries = []
            with os.scandir(directory) as iterator:
                for entry in iterator:
                    entries.append(entry.name)
                    if len(entries) > MAX_FILES:
                        raise ValueError('抖音快照目录超过 100 项上限；未读取，已保留原文件。')
        except (ValueError, OSError):
            failed('抖音快照目录无法安全读取或超过 100 项上限；已保留原文件。')
            return result

        valid = []
        for name in sorted(entries):
            if not _FILENAME.fullmatch(name):
                failed('存在不符合 UUID 文件名的抖音快照条目；已跳过并保留。')
                continue
            try:
                path = self.store._safe(self.store.base, 'social-observations/douyin/' + name)
                # Refuse a symlink even if it appeared between path validation
                # and open; read a bounded number of bytes from regular files.
                descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
                with os.fdopen(descriptor, 'rb') as source:
                    metadata = os.fstat(source.fileno())
                    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_BYTES:
                        raise ValueError('快照必须是大小不超过 256 KB 的普通文件。')
                    data = source.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    raise ValueError('快照超出大小上限。')
                payload = json.loads(data.decode('utf-8'), object_pairs_hook=_unique_object)
                valid.append((name, _validate(payload)))
            except (ValueError, OSError, TypeError, KeyError, RecursionError):
                failed('抖音快照 ' + name + ' 格式无效或无法安全读取；已保留原文件。')
        if valid:
            # Actual instants, rather than ISO strings, determine recency when
            # captures use different timezone offsets. Filename breaks ties.
            _, latest = max(valid, key=lambda item: (_captured_at(item[1]['captured_at']), item[0]))
            result['snapshots'].append(latest)
        return result

    def read_answer(self, question):
        state = self.snapshot()
        if not state['snapshots']:
            if state['errors']:
                return ('抖音本地快照读取失败，当前没有可用的只读数据；原文件已保留。'
                        '\n这不代表抖音账号没有数据。本次没有访问抖音，也没有执行任何平台操作。')
            return ('尚未取得抖音只读数据快照，当前无法报告账号指标。'
                    '\n需要在本人登录的抖音创作者中心完成一次只读采集；本次没有访问抖音或执行任何平台操作。')
        snapshot = state['snapshots'][0]
        account = snapshot['account']
        lines = ['以下是本地保存的抖音只读快照，非实时数据，未自动同步；API 尚未授权。', '',
                 '账号：' + _literal(account['display_name'])]
        if account['account_identifier'] is not None:
            lines.append('页面账号标识：' + _literal(account['account_identifier']))
        lines.extend(['读取时间：' + _literal(snapshot['captured_at']),
                      '统计周期：' + _literal(snapshot['period']['label'])])
        if snapshot['period']['start'] is not None:
            lines.append('页面显示起点：' + _literal(snapshot['period']['start']))
        if snapshot['period']['end'] is not None:
            lines.append('页面显示终点：' + _literal(snapshot['period']['end']))
        metadata = '\n'.join(lines)
        metric_items = []
        for metric in snapshot['metrics']:
            metric_items.append('- ' + _literal(metric['label']) + '：' + _literal(metric['display_value']) +
                                '（口径：' + _literal(metric['scope']) + '）')
        if not snapshot['metrics']:
            metric_items.append('本次快照未包含可报告的指标，不能据此推断为零。')
        work_items = []
        for work in snapshot['works']:
            work_items.append('- ' + _literal(work['description']) + '；发布时间：' + _literal(work['published_at']) +
                              '；可见范围：' + _literal(work['visibility']) + '；形式：' + _literal(work['format']) +
                              '；时长：' + _literal(work['duration']))
        if not snapshot['works']:
            work_items.append('本次快照未包含作品列表，不能据此推断账号没有作品。')
        source_items = []
        for source in snapshot['sources']:
            # The URL host and absence of credentials/query were checked on
            # load. Use angle brackets so a page path cannot end the link.
            url = source['url'].replace('<', '%3C').replace('>', '%3E')
            source_items.append('- [' + _literal(source['title']) + '](<' + url + '>)')
        # Provenance and scope get dedicated budgets before metrics/works.
        # Each budget fits the largest permitted single item even after
        # Markdown/HTML escaping. Long sections retain at least one complete
        # source/limitation and direct the reader to the complete snapshot.
        sources = _bounded_section('数据来源：', source_items, 4500, '来源')
        limitations = _bounded_section('快照范围：', ['- ' + _literal(item) for item in snapshot['limitations']], 5500, '范围说明')
        footer = []
        if state['errors']:
            footer.append('另有快照文件未能读取；以上为可读取文件中时间最近的一份，可能不是最后一次采集。')
        footer.append('本次仅查询本地快照，没有重新访问抖音，没有发布、修改、删除、评论或私信操作。')
        footer = '\n'.join(footer)
        fixed = '\n\n'.join((metadata, sources, limitations, footer))
        # Inserting two more sections adds two separators (four characters).
        available = MAX_ANSWER_CHARS - len(fixed) - 4
        metrics = _bounded_section('已读取指标：', metric_items, min(3500, available - 200), '指标')
        works = _bounded_section('当次读取到的作品：', work_items, available - len(metrics), '作品')
        return '\n\n'.join((metadata, metrics, works, sources, limitations, footer))


def is_social_data_request(question):
    """Recognize only complete, short requests to inspect Douyin observations."""
    if not isinstance(question, str) or len(question) > 100:
        return False
    text = re.sub(r'\s+', '', question).rstrip('。！？!?')
    prefix = r'(?:请)?(?:帮我|给我|我要|我想)?(?:先)?'
    read = r'(?:查看|看看|查询|读取|显示|展示)'
    target = r'(?:(?:我的|我|当前|本地)(?:的)?)*抖音(?:账号|帐号)?(?:的)?'
    data = r'(?:(?:最近|最新)(?:读取的|保存的|一次的|的)?|已读取的|已保存的)?(?:数据快照|数据|快照|统计数据|账号数据)'
    return bool(re.fullmatch(prefix + r'(?:' + read + r')?' + target + data + r'(?:情况|有哪些|呢|吧)?', text))
