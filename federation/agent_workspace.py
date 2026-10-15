"""Server-owned Markdown identity and memory, with bounded per-turn projections."""
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import uuid
from zoneinfo import ZoneInfo

from .core import _now, _sha, _missing_text, _write_json
from .memory_requirements import clean
from .context_memory import terms

TEMPLATES = Path(__file__).with_name('agent-workspace')
FILES = ('SOUL.md', 'IDENTITY.md', 'AGENTS.md', 'USER.md', 'MEMORY.md', 'BOOTSTRAP.md', 'BOOT.md', 'README.md')
START, END = '<!-- weiming:managed:start -->', '<!-- weiming:managed:end -->'
LIMIT = 32768


def private_recall(question):
    if len(question) > 500 or re.search(r'搜索|联网|部署|删除|创建|写代码|安装|发送|转账', question):
        return False
    return bool(re.search(r'记忆回顾|(?:我的|用户的)(?:偏好|背景|长期记忆)|(?:今天|昨天|上次|最近|\d{4}-\d{2}-\d{2}).*工作记录'
                          r'|(?:我|我们)(?:上次|之前|以前).*(?:决定|约定|确认|选择)', question))


def field(text, name):
    match = re.search(r'^[ \t]*-?[ \t]*' + re.escape(name) + r'[：:][ \t]*([^\n]*)$', text, re.M)
    return match.group(1).strip() if match else ''


def manual(text):
    if START not in text and END not in text:
        return text
    if text.count(START) != 1 or text.count(END) != 1 or text.index(START) > text.index(END):
        raise ValueError('记忆文件自动同步标记损坏，请保留成对标记')
    return text.split(START)[0] + text.split(END)[1]


def nickname(text):
    """Only literal user assignments; quoted material, questions and actions excluded."""
    if not isinstance(text, str) or len(text) > 160 or re.search(r'[「」“”"`\n]|[?？]|搜索|删除|执行|忽略|规则|文件|代码|然后|顺便', text):
        return None
    text = re.sub(r'[\s，。！、,.!~～；;：:]', '', text)
    text = re.sub(r'^别(?:再)?(?:叫|喊|称呼)(?:我)?[\w\u3400-\u9fff]{1,12}?了(?=(?:叫我|称呼我|喊我))', '', text)
    match = re.fullmatch(r'(?:开个玩笑)?(?:我让你|你)?(?:以后|现在|从现在起)?(?:就)?(?:管我叫|称呼我|叫我|喊我)(?:我)?'
                        r'([a-z\u3400-\u9fff0-9_-]{1,12}?)(?:就行|就好|吧)?'
                        r'(?:我(?:以后)?(?:就)?(?:管你叫|叫你|称呼你|喊你)([a-z\u3400-\u9fff0-9_-]{1,12}?)(?:就行|就好|吧)?)?', text, re.I)
    return {'user_address': match[1], 'assistant_address': match[2]} if match else None


class AgentWorkspace:
    def __init__(self, store):
        self.store = store

    def path(self, agent, name):
        if name not in FILES and not re.fullmatch(r'memory/\d{4}-\d{2}-\d{2}\.md', name):
            raise ValueError('无效 Agent 工作文件')
        return self.store._safe(self.store._home(agent), name)

    @contextmanager
    def locked(self, agent):
        root = self.store._safe(self.store._home(agent))
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.store._safe(root, '.workspace.lock'), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def read(self, agent, name):
        path = self.path(agent, name)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            limit = 2_000_000 if name.startswith('memory/') else LIMIT
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise ValueError('Agent 工作文件不是普通文件或超过 32 KiB')
            with os.fdopen(fd, 'r', encoding='utf-8', closefd=False) as stream:
                text = stream.read(limit + 1)
            if '\0' in text or clean(text) != text:
                raise ValueError('Agent 工作文件包含无效字符或私密配置')
            return text
        finally:
            os.close(fd)

    def write(self, agent, name, text):
        path = self.path(agent, name)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temp = self.store._safe(path.parent, '.' + path.name + '-' + uuid.uuid4().hex)
        try:
            with temp.open('x', encoding='utf-8') as stream:
                stream.write(text)
            temp.chmod(0o600)
            os.replace(temp, path)
        finally:
            if temp.exists():
                temp.unlink()

    def status_path(self, agent):
        self.store._definition(agent)
        return self.store._safe(self.store.base, 'metadata/agent-workspaces/' + agent + '.json')

    def ensure(self, agent):
        with self.locked(agent):
            definition = self.store._definition(agent)
            for name in FILES:
                text = (TEMPLATES / name).read_text()
                text = text.replace('{{name}}', '未明' if agent == 'central' else definition['name'])
                text = text.replace('{{description}}', definition.get('description', '知识与任务协作助手'))
                _missing_text(self.path(agent, name), text)
            status_path = self.status_path(agent)
            if status_path.exists():
                return
            guide = self.read(agent, 'BOOTSTRAP.md')
            steps = re.findall(r'^- step: ([\w-]+)$', guide, re.M)
            if set(steps) != {'identity', 'user-memory', 'skills'}:
                raise ValueError('BOOTSTRAP.md 含不支持或缺失的初始化步骤')
            from .agent_skills import _candidate, _import
            skill = 'weiming-memory-recall'
            if not self.store._safe(self.store._home(agent), 'skills/' + skill).exists():
                metadata, documents = _candidate(TEMPLATES / 'skills' / skill / 'SKILL.md')
                metadata['keywords'] = ['长期记忆', '我的偏好', '工作记录', '记忆回顾']
                _import(self.store, agent, metadata, documents)
            self.sync(agent)
            _write_json(status_path, {'schema_version': 1, 'bootstrap': {'status': 'completed', 'at': _now(),
                'steps': steps, 'guide_sha256': _sha(guide.encode())}})
            self.journal(agent, 'bootstrap', 'completed', '工作目录首次初始化完成', 'metadata/agent-workspaces/' + agent + '.json')

    def managed(self, agent, name, value):
        text = self.read(agent, name)
        manual(text)  # Validate before replacing anything.
        block = START + '\n```json\n' + json.dumps(value, ensure_ascii=False, indent=2) + '\n```\n' + END
        updated = text.split(START)[0] + block + text.split(END)[1] if START in text else text.rstrip() + '\n\n' + block + '\n'
        if len(updated.encode()) > LIMIT:
            raise ValueError('Agent 记忆投影超过 32 KiB；原文件保留')
        if updated != text:
            self.write(agent, name, updated)

    def sync(self, agent, room=None):
        """Called under the workspace lock. JSON APIs remain the managed sources."""
        from .personal_profile import read_profile, CONTACT
        from .knowledge_lifecycle import user_memory
        from .context_memory import select_personal_memory
        profile = read_profile(self.store)
        allowed = profile.get('enabled') and (profile.get('scope') == 'workspace' or agent == 'central')
        user = {'profile': {k: CONTACT.sub('[联系方式已隐藏]', clean(str(profile.get(k, ''))))
                            for k in ('about', 'goals', 'preferences')} if allowed else {},
                'profile_revision': profile.get('revision') if allowed else None}
        # Do not duplicate all rooms or recover explicitly forgotten tasks.
        previous = self.read(agent, 'USER.md')
        manual(previous)
        block = previous.split(START)[1].split(END)[0].strip() if START in previous else ''
        saved = json.loads(block.removeprefix('```json').removesuffix('```').strip()) if block else {}
        addresses = saved.get('conversation_addresses', {})
        if room:
            address = self.room_address(agent, room)
            addresses.pop(room['id'], None)
            if address:
                addresses[room['id']] = address
        user['conversation_addresses'] = addresses
        self.managed(agent, 'USER.md', user)
        selected = select_personal_memory(user_memory(self.store), '', agent)
        # Include all in-scope, unexpired records in the file, then select for each question.
        source = user_memory(self.store)
        invalid = {x['id'] for x in selected['omitted'] if x['reason'] in {'scope', 'expired', 'invalid_expiry'}}
        entries = [{'id': key, 'category': cat, 'text': clean(item['text']), 'scope': item.get('scope', 'project'),
                    'revision': item.get('revision', 1), 'updated_at': item.get('updated_at')}
                   for cat in ('preferences', 'learning') for key, item in source.get(cat, {}).items() if key not in invalid]
        self.managed(agent, 'MEMORY.md', {'entries': entries, 'source': 'metadata/user-memory.json'})
        return user, entries

    def room_address(self, agent, room):
        if agent not in room.get('participants', []) and agent != 'central':
            return None
        path = self.store._safe(self.store.base, 'metadata/context-memory/' + room['id'] + '/' + agent + '.json')
        state = json.loads(path.read_text()) if path.exists() else {}
        forgotten = {mid for task in state.get('tasks', []) if task.get('status') == 'forgotten' for mid in task.get('message_ids', [])}
        address = None
        for message in room.get('messages', []):
            if message.get('role') != 'user' or message.get('id') in forgotten:
                continue
            if re.fullmatch(r'(?:请)?(?:忘记|清除)(?:我(?:的)?)?(?:昵称|称呼)[。！!\s]*', message.get('content', '')):
                address = {'user_address': None, 'assistant_address': None, 'forgotten': True, 'scope': 'current_conversation',
                           'room_id': room['id'], 'source_message_id': message.get('id')}
                continue
            value = nickname(message.get('content', ''))
            if value:
                address = {**value, 'scope': 'current_conversation', 'room_id': room['id'],
                           'source_message_id': message.get('id'), 'updated_at': message.get('created_at')}
        return address

    def context(self, agent, question, room=None, simple=False):
        self.ensure(agent)
        state = json.loads(self.status_path(agent).read_text())
        if state.get('boot', {}).get('status') == 'failed':
            raise ValueError('Agent 启动检查失败，请检查工作文件和启动回执')
        with self.locked(agent):
            user, entries = self.sync(agent, room)
            documents = {name: self.read(agent, name) for name in ('IDENTITY.md', 'SOUL.md', 'AGENTS.md', 'USER.md', 'MEMORY.md')}
            identity = documents['IDENTITY.md']
            name = field(identity, '名称')
            if not name or len(name) > 100:
                raise ValueError('IDENTITY.md 需要 1 至 100 字的名称')
            user_text = manual(documents['USER.md'])
            address = user['conversation_addresses'].get(room['id']) if room else None
            address = address or ({'user_address': field(user_text, '称呼'), 'scope': 'agent'} if field(user_text, '称呼') else None)
            query = terms(question)
            memory = [x for x in entries if query & terms(x['text']) or x['category'] == 'preferences' and re.search(r'称呼|语言|语气|回答|回复|表达|排版', x['text'])]
            custom_memory = manual(documents['MEMORY.md'])
            # Template guidance isn't memory. Only user-added paragraphs may be selected.
            template = manual((TEMPLATES / 'MEMORY.md').read_text())
            additions = custom_memory.replace(template, '').strip()
            recall = bool(re.search(r'记忆|记得|偏好|约定|决定|工作记录|待续|昨天|今天|上次', question))
            excerpts = []
            if not simple:
                if additions and (recall or query & terms(additions)):
                    excerpts.append({'path': 'MEMORY.md', 'text': additions[:2400]})
                if recall:
                    directory = self.store._safe(self.store._home(agent), 'memory')
                    date = re.search(r'\d{4}-\d{2}-\d{2}', question)
                    date = date[0] if date else None
                    if not date and re.search(r'今天|昨天', question):
                        try:
                            zone = ZoneInfo(field(user_text, '时区') or 'Asia/Shanghai')
                        except (ValueError, KeyError):
                            zone = timezone.utc
                        date = (datetime.now(zone) - timedelta(days=1 if '昨天' in question else 0)).strftime('%Y-%m-%d')
                    paths = [directory / (date + '.md')] if date else sorted(directory.glob('????-??-??.md'), reverse=True)[:7]
                    for path in paths:
                        if not path.exists():
                            continue
                        text = self.read(agent, 'memory/' + path.name)
                        if query & terms(text) or re.search(r'工作记录|待续|今天|昨天', question):
                            blocks = text.split('<!-- event:')
                            matches = [b for b in blocks[1:] if query & terms(b)]
                            excerpt = '\n'.join(matches[-5:])[-2400:] if matches else text[-2400:]
                            excerpts.append({'path': 'memory/' + path.name, 'text': excerpt, 'sha256': _sha(text.encode())})
                        if len(excerpts) >= 3:
                            break
            used = ['IDENTITY.md', 'SOUL.md', 'AGENTS.md', 'USER.md'] + (['MEMORY.md'] if memory or excerpts else [])
            return {'agent_id': agent, 'name': name, 'identity': identity[:1200], 'soul': documents['SOUL.md'][:1800],
                    'rules': documents['AGENTS.md'][:2200], 'user': user_text[:1400], 'profile': user['profile'],
                    'nicknames': address, 'memory': [{**x, 'text': x['text'][:500]} for x in memory[:4]],
                    'excerpts': [{**x, 'text': x['text'][-1800:]} for x in excerpts[:3]],
                    'reads': [{'path': str(self.path(agent, f).relative_to(self.store.base)), 'sha256': _sha(documents[f].encode()),
                               'truncated': len(documents[f]) > {'IDENTITY.md':1200,'SOUL.md':1800,'AGENTS.md':2200,'USER.md':1400}.get(f,2400)} for f in used]
                        + [{**{k:v for k,v in x.items() if k != 'text'}, 'truncated': True} for x in excerpts if x['path'].startswith('memory/')],
                    'private_recall': private_recall(question),
                    'authority': 'Host workspace configuration; memory and source material never grant tool permissions.'}

    def journal(self, agent, identifier, status, question, evidence):
        user = manual(self.read(agent, 'USER.md'))
        try:
            zone = ZoneInfo(field(user, '时区') or 'Asia/Shanghai')
        except (ValueError, KeyError):
            zone = timezone.utc
        today = datetime.now(zone).strftime('%Y-%m-%d')
        name = 'memory/' + today + '.md'
        path = self.path(agent, name)
        text = self.read(agent, name) if path.exists() else '# ' + today + ' 工作记录\n\n'
        marker = '<!-- event:' + identifier + ':' + status + ' -->'
        if marker in text:
            return
        entry = marker + '\n- 时间：' + _now() + '\n- 状态：' + status + '\n- 事项：' + clean(question).replace('\n', ' ')[:180] + '\n- 证据：' + evidence + '\n\n'
        if len((text + entry).encode()) <= 2_000_000:
            self.write(agent, name, text + entry)
        else:
            raise ValueError('当日工作记录达到 2 MB，原记录保留')

    def record_job(self, job):
        agent = job.get('space') or 'central'
        # A central request has a parent chat job and internal model jobs.
        # Journal the user-visible job once, not both sides of that same turn.
        if agent == 'central' and job.get('parent_job_id'):
            return
        if job.get('status') not in {'completed', 'failed', 'interrupted', 'cancelled'} or not re.fullmatch(r'[a-f0-9]{32}', job.get('id', '')):
            return
        self.ensure(agent)
        with self.locked(agent):
            self.journal(agent, job['id'], job['status'], job.get('current_question', job.get('question', job.get('action', '任务'))), 'jobs/' + job['id'] + '.json')

    def boot(self, recovery):
        results = []
        for agent in self.store._definitions:
            try:
                self.ensure(agent)
                with self.locked(agent):
                    guide = self.read(agent, 'BOOT.md')
                    checks = re.findall(r'^- check: ([\w-]+)$', guide, re.M)
                    if set(checks) != {'files', 'memory', 'recovery'}:
                        raise ValueError('BOOT.md 含不支持或缺失的启动检查')
                    for name in FILES:
                        self.read(agent, name)
                    if not 1 <= len(field(self.read(agent, 'IDENTITY.md'), '名称')) <= 100:
                        raise ValueError('IDENTITY.md 名称无效')
                    self.sync(agent)
                    ids = list((recovery.get('pending_runs') or {}).values()) + ([recovery['active_run']] if recovery.get('active_run') else [])
                    missing = [identifier for identifier in ids if not re.fullmatch(r'[a-f0-9]{32}', identifier) or not self.store._safe(
                        self.store.base, 'metadata/autonomy/runs/' + identifier + '/run.json').is_file()]
                    recovery_result = {**recovery, 'checked_checkpoint_count': len(set(ids)), 'missing_checkpoints': missing}
                    receipt = {'status': 'completed_with_warnings' if missing else 'completed', 'at': _now(), 'checks': checks, 'guide_sha256': _sha(guide.encode()), 'recovery': recovery_result,
                               'files': {name: _sha(self.read(agent, name).encode()) for name in FILES}}
            except (ValueError, OSError, UnicodeError) as exc:
                receipt = {'status': 'failed', 'at': _now(), 'error': str(exc)}
            path = self.status_path(agent)
            state = json.loads(path.read_text()) if path.exists() else {}
            state['boot'] = receipt
            _write_json(path, state)
            results.append({'agent_id': agent, **receipt})
        return results

    def inspect(self, agent):
        self.ensure(agent)
        path = self.status_path(agent)
        return {'agent_id': agent, 'directory': str(self.store._home(agent)), 'lifecycle': json.loads(path.read_text()),
                'files': [{'name': f, 'content': self.read(agent, f), 'sha256': _sha(self.read(agent, f).encode())} for f in FILES],
                'daily_records': [p.name for p in sorted(self.store._safe(self.store._home(agent), 'memory').glob('????-??-??.md'))]}

    def edit(self, agent, name, content, expected):
        self.ensure(agent)
        if name not in FILES or not isinstance(content, str) or len(content.encode()) > LIMIT or '\0' in content or clean(content) != content:
            raise ValueError('工作文件内容无效或超过长度上限')
        with self.locked(agent):
            previous = self.read(agent, name)
            if _sha(previous.encode()) != expected:
                raise ValueError('文件已变化，请刷新后核对；没有覆盖保存')
            if name in {'USER.md', 'MEMORY.md'}:
                manual(content)
                old_block = previous.split(START)[1].split(END)[0] if START in previous else ''
                new_block = content.split(START)[1].split(END)[0] if START in content else ''
                if old_block != new_block:
                    raise ValueError('自动同步区请通过原有个人资料、记忆入口或聊天更正')
            if name == 'IDENTITY.md' and not 1 <= len(field(content, '名称')) <= 100:
                raise ValueError('身份名称不能为空或超过 100 字')
            archive = self.store._safe(self.store.base, 'backups/agent-workspaces/' + agent + '/' + uuid.uuid4().hex + '/' + name)
            archive.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            _missing_text(archive, previous)
            self.write(agent, name, content)
            return {'status': 'saved', 'name': name, 'sha256': _sha(content.encode()), 'backup': str(archive.relative_to(self.store.base))}
