"""Import local Skills as verified, role-scoped reference packages.

Importing preserves their source text and resources. It never installs packages,
executes scripts, connects an external app, or grants an Agent additional tools.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid

from .core import _now, _write_json
from .skill_assignments import assigned_roles, skill_keywords

MAX_FILES = 512
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_SKILL_BYTES = 2 * 1024 * 1024
MAX_PACKAGE_BYTES = 32 * 1024 * 1024
SKIP_DIRECTORIES = {'.git', 'node_modules', '.venv', 'venv', '__pycache__', '.pytest_cache', '.mypy_cache', '.DS_Store'}
SKIP_FILES = {'.DS_Store', '.env', '.netrc', '.npmrc', '.pypirc', 'credentials.json', 'credential.json', 'token.json', 'tokens.json', 'cookies.json', 'secrets.json', 'id_rsa', 'id_ed25519'}
SENSITIVE_SUFFIXES = {'.pem', '.key', '.p12', '.pfx', '.keystore', '.pyc', '.pyo'}
ID_PATTERN = r'[a-z][a-z0-9-]{0,95}'


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def default_roots():
    home = Path.home()
    return [home / '.codex/skills', home / '.codex/plugins/cache', home / 'Documents/projects/skill']


def _source_kind(path):
    value = path.as_posix()
    if '/.codex/skills/' in value:
        return 'local_installed'
    if '/.codex/plugins/cache/' in value:
        return 'plugin_cache'
    if '/Documents/projects/skill/' in value:
        return 'delivery_copy'
    return 'local_directory'


def _reject_symlinks(path):
    for entry in [path, *path.parents]:
        if entry.is_symlink():
            raise ValueError('拒绝符号链接来源：' + str(entry))


def _read_file(path, limit=MAX_FILE_BYTES):
    _reject_symlinks(path)
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, 'rb') as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise ValueError('来源必须是限制大小内的普通文件：' + str(path))
        value = source.read(limit + 1)
        after = os.fstat(source.fileno())
        if len(value) > limit or (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValueError('读取期间来源文件发生变化：' + str(path))
    _reject_symlinks(path)
    if path.stat().st_ino != before.st_ino:
        raise ValueError('读取期间来源被替换：' + str(path))
    return value


def _scalar(text):
    text = text.strip()
    if text.startswith('"') and text.endswith('"'):
        try:
            return json.loads(text)
        except ValueError:
            return text[1:-1]
    if text.startswith("'") and text.endswith("'"):
        return text[1:-1].replace("''", "'")
    return text


def _yaml_field(text, field, indent=None):
    """Read a bounded YAML scalar, including |/> blocks; never interpret tags."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = re.match(r'^(\s*)' + re.escape(field) + r':\s*(.*)$', line)
        if not match or (indent is not None and len(match.group(1)) != indent):
            continue
        level, value = len(match.group(1)), match.group(2)
        if value.strip() in ('|', '|-', '|+', '>', '>-', '>+'):
            block = []
            for following in lines[index + 1:]:
                if following.strip() and len(following) - len(following.lstrip()) <= level:
                    break
                block.append(following.strip())
            return ('\n' if value.startswith('|') else ' ').join(block).strip()
        return _scalar(value)
    return ''


def _excluded(path):
    name = path.name.lower()
    return (name in SKIP_FILES or path.suffix.lower() in SENSITIVE_SUFFIXES or
            (name.startswith('.env.') and not name.endswith(('.example', '.sample', '.template'))) or
            bool(re.search(r'(?:^|[-_.])(credentials?|secrets?|cookies?)(?:[-_.]|$)', name)))


def _source_files(root):
    _reject_symlinks(root)
    documents, excluded = {}, []
    total = 0
    for current, directories, filenames in os.walk(root, followlinks=False):
        for name in directories + filenames:
            if (Path(current) / name).is_symlink():
                raise ValueError('Skill 包含符号链接，未导入：' + str(Path(current) / name))
        for name in list(directories):
            if name in SKIP_DIRECTORIES:
                directories.remove(name)
                excluded.append((Path(current) / name).relative_to(root).as_posix() + '/')
        for name in sorted(filenames):
            file = Path(current) / name
            relative = file.relative_to(root).as_posix()
            if _excluded(file):
                excluded.append(relative)
                continue
            if relative == 'manifest.json':
                raise ValueError('来源占用了导入清单名称 manifest.json，需人工处理。')
            value = _read_file(file, MAX_SKILL_BYTES if relative == 'SKILL.md' else MAX_FILE_BYTES)
            documents[relative] = value
            total += len(value)
            if len(documents) >= MAX_FILES or total > MAX_PACKAGE_BYTES:
                raise ValueError('Skill 文件总数或容量超过导入限制。')
    if 'SKILL.md' not in documents:
        raise ValueError('缺少 SKILL.md。')
    return documents, sorted(excluded)


def _dependencies(skill_id, text, files, plugin):
    deps = []
    # These strings describe requirements, not tools available to this runtime.
    if skill_id.startswith('figma-'):
        deps += ['Figma MCP / 账号与文件访问权限']
    if skill_id.startswith('google-'):
        deps += ['Google Drive 连接器 / 账号与文件访问权限']
    if skill_id.startswith('sites-'):
        deps += ['Sites MCP / 站点运行与发布环境']
    if skill_id in {'write-page', 'organize-space', 'maintain-space', 'manage-schedules'}:
        deps += ['ChatGPT Pages / Spaces 连接器']
    if skill_id in {'create-pet', 'pets', 'update-pet'}:
        deps += ['ChatGPT Work Pets 工具']
    if 'apifox' in skill_id:
        deps += ['Apifox 项目、登录态与接口访问权限']
    if skill_id == 'agent-device':
        deps += ['agent-device CLI / 设备或模拟器连接']
    if skill_id == 'flutter-add-integration-test':
        deps += ['Flutter SDK / 设备或模拟器 / 测试执行环境']
    if skill_id in {'imagegen', 'hatch-pet'}:
        deps += ['图像生成工具 / 图像检查工具']
    if skill_id == 'excel-live-control':
        deps += ['Microsoft Excel 加载项 / 已连接的工作簿会话']
    if skill_id in {'documents', 'spreadsheets', 'presentations', 'pdf', 'template-creator'} or skill_id.startswith('artifact-template-'):
        deps += ['文档/表格/演示文稿运行时与渲染工具']
    if any(name.endswith(('.py', '.sh', '.mjs', '.js', '.ts')) for name in files) or re.search(r'\b(Bash|exec_command|subprocess|terminal)\b', text):
        deps += ['本地脚本执行与文件写入适配器（本 Agent 未连接）']
    if plugin:
        deps += ['原插件运行环境：' + plugin]
    if re.search(r'container_tools/|/mnt/|/tmp/|/Users/|\$CODEX_HOME|\$HOME|\.\./', text):
        deps += ['原文含包外路径或运行环境引用，需接入工具后核验']
    if skill_id in {'skill-installer', 'plugin-management', 'computer-history', 'openai-docs', 'visualize', 'review-agent'}:
        deps += ['原 Codex 工具/会话环境；导入不授予对应权限']
    return list(dict.fromkeys(deps))


def _candidate(skill_file):
    documents, excluded = _source_files(skill_file.parent)
    text = documents['SKILL.md'].decode('utf-8')
    if not text.startswith('---\n') or '\n---' not in text[4:]:
        raise ValueError('SKILL.md 缺少有效 frontmatter。')
    frontmatter = text.split('---', 2)[1]
    name = _yaml_field(frontmatter, 'name', 0)
    if not isinstance(name, str) or not name or len(name) > 128:
        raise ValueError('Skill 机器 name 无效。')
    skill_id = re.sub(r'[^a-z0-9]+', '-', name.casefold()).strip('-')
    if not re.fullmatch(ID_PATTERN, skill_id):
        raise ValueError('Skill 机器 name 无法映射为安全标识。')
    description = _yaml_field(frontmatter, 'description', 0)
    if not description or len(description) > 16000:
        raise ValueError('Skill 描述缺失或过长。')
    yaml = documents.get('agents/openai.yaml', b'').decode('utf-8')
    display_name = _yaml_field(yaml, 'display_name') or name
    source_kind = _source_kind(skill_file)
    plugin, upstream_version = '', ''
    parts = skill_file.parts
    if source_kind == 'plugin_cache':
        index = parts.index('cache')
        if len(parts) > index + 3:
            plugin, upstream_version = parts[index + 2], parts[index + 3]
    hashes = {key: _hash(value) for key, value in sorted(documents.items())}
    version = _hash(_canonical(hashes))
    metadata = {
        'id': skill_id, 'name': name, 'display_name': str(display_name), 'description': description,
        'keywords': skill_keywords(skill_id, name, str(display_name)),
        'source_path': str(skill_file.parent), 'source_kind': source_kind,
        'source_skill_path': str(skill_file), 'plugin': plugin, 'upstream_version': upstream_version,
        'version': version, 'source_version': 'sha256:' + version,
        'files': hashes, 'file_count': len(hashes), 'total_bytes': sum(map(len, documents.values())),
        'dependencies': _dependencies(skill_id, text, documents, plugin),
        'dependency_status': 'not_connected', 'execution_status': 'reference_only',
        'execution_note': '已导入技能说明与资源；当前只可按任务读取，不执行脚本、不代表外部应用已连接。',
        'excluded_files': excluded, 'assigned_agents': list(assigned_roles(skill_id)),
    }
    return metadata, documents


def _discover(roots=None):
    candidates, errors, source_hashes, visited = [], [], {}, set()
    for root_value in roots if roots is not None else default_roots():
        root = Path(root_value).expanduser().absolute()
        if not root.exists():
            errors.append({'source_path': str(root), 'error': '来源目录不存在。'})
            continue
        try:
            _reject_symlinks(root)
            for current, directories, filenames in os.walk(root, followlinks=False):
                directories[:] = sorted(name for name in directories if name not in SKIP_DIRECTORIES and not (Path(current) / name).is_symlink())
                if 'SKILL.md' not in filenames:
                    continue
                skill_file = Path(current) / 'SKILL.md'
                if str(skill_file) in visited:
                    continue
                visited.add(str(skill_file))
                try:
                    metadata, documents = _candidate(skill_file)
                    candidates.append((metadata, documents))
                    source_hashes.update({str(skill_file.parent / name): digest for name, digest in metadata['files'].items()})
                except (ValueError, OSError, UnicodeError) as error:
                    errors.append({'source_path': str(skill_file), 'error': str(error)})
        except (ValueError, OSError) as error:
            errors.append({'source_path': str(root), 'error': str(error)})
    groups = {}
    for candidate in candidates:
        groups.setdefault(candidate[0]['id'], []).append(candidate)
    priority = {'local_installed': 0, 'plugin_cache': 1, 'delivery_copy': 2, 'local_directory': 3}
    selected = []
    for skill_id, copies in sorted(groups.items()):
        copies.sort(key=lambda pair: (priority[pair[0]['source_kind']],
                                      tuple(-int(part) for part in re.findall(r'\d+', pair[0].get('upstream_version', '')))
                                      if pair[0]['source_kind'] == 'plugin_cache' else (),
                                      pair[0]['source_path']))
        original_names = {pair[0]['name'].casefold() for pair in copies}
        if len(original_names) > 1:
            errors.append({'id': skill_id, 'error': '多个不同机器 name 映射到相同 id，已跳过。'})
            continue
        metadata, documents = copies[0]
        metadata['selection_reason'] = {
            'local_installed': '优先本机技能目录；目录存在不等于当前会话已加载。',
            'plugin_cache': '优先插件缓存中数字版本最高的副本；缓存版本不等于当前已加载版本。',
            'delivery_copy': '没有已安装来源时使用固定交付副本；交付副本不等于已安装。',
            'local_directory': '来自显式指定的本地来源目录。',
        }[metadata['source_kind']]
        metadata['source_duplicates'] = [{
            'source_path': other['source_path'], 'source_kind': other['source_kind'],
            'name': other['name'], 'version': other['version'],
            'same_content': other['version'] == metadata['version'],
            'different_files': sorted(key for key in set(other['files']) | set(metadata['files']) if other['files'].get(key) != metadata['files'].get(key)),
        } for other, _ in copies[1:]]
        selected.append((metadata, documents))
    return selected, {'scanned_skill_files': len(visited), 'valid_source_copies': len(candidates),
                      'unique_skills': len(selected), 'source_errors': errors, 'source_hashes': source_hashes}


def inventory_local_skills(roots=None):
    """Read-only deduplicated inventory, suitable for review before importing."""
    candidates, report = _discover(roots)
    catalog = [metadata for metadata, _ in candidates]
    report.update({'catalog': catalog,
                   'unassigned': [item['id'] for item in catalog if not item['assigned_agents']],
                   'agent_counts': {agent: sum(agent in item['assigned_agents'] for item in catalog) for item in catalog for agent in item['assigned_agents']},
                   'assignment_count': sum(len(item['assigned_agents']) for item in catalog),
                   'execution_status': 'reference_only'})
    return report


def _paths(store, space, skill_id):
    store.space(space)
    if not re.fullmatch(ID_PATTERN, skill_id):
        raise ValueError('技能标识无效。')
    root = store._safe(store._home(space), 'skills')
    return root, store._safe(root, skill_id), store._safe(root, '.' + skill_id + '-state.json')


def skill_root(store, space, skill_id):
    return _paths(store, space, skill_id)[1]


def validate_skill(store, space, skill_id):
    _, target, state_file = _paths(store, space, skill_id)
    manifest_file = store._safe(target, 'manifest.json')
    if not manifest_file.is_file() or not state_file.is_file():
        raise ValueError('技能文件或完整性登记缺失。')
    state = json.loads(state_file.read_text())
    raw = manifest_file.read_bytes()
    if not isinstance(state, dict) or _hash(raw) != state.get('manifest_sha256'):
        raise ValueError('技能清单已被修改，已保留当前文件。')
    manifest = json.loads(raw)
    if not isinstance(manifest, dict) or manifest.get('space_id') != space or manifest.get('id') != skill_id or manifest.get('execution_status') != 'reference_only':
        raise ValueError('技能归属或执行范围不一致。')
    files = manifest.get('files')
    if not isinstance(files, dict) or 'SKILL.md' not in files or not 1 <= len(files) < MAX_FILES:
        raise ValueError('技能文件清单无效。')
    actual_files, actual_directories = set(), set()
    for current, directories, filenames in os.walk(target, followlinks=False):
        for name in directories + filenames:
            store._safe(target, (Path(current) / name).relative_to(target).as_posix())
        actual_files.update((Path(current) / name).relative_to(target).as_posix() for name in filenames)
        actual_directories.update((Path(current) / name).relative_to(target).as_posix() for name in directories)
    expected_directories = {parent.as_posix() for name in files for parent in Path(name).parents if parent.as_posix() != '.'}
    if actual_files != set(files) | {'manifest.json'} or actual_directories != expected_directories:
        raise ValueError('技能出现新增或删除的文件/目录，已保留人工修改。')
    total = 0
    for name, digest in files.items():
        if not re.fullmatch(r'[a-f0-9]{64}', str(digest)):
            raise ValueError('技能文件哈希无效。')
        path = store._safe(target, name)
        value = _read_file(path, MAX_SKILL_BYTES if name == 'SKILL.md' else MAX_FILE_BYTES)
        total += len(value)
        if total > MAX_PACKAGE_BYTES or _hash(value) != digest:
            raise ValueError('技能文件已修改或超过限制，已保留：' + name)
    return manifest


def list_skills(store, space):
    store.space(space)
    root = store._safe(store._home(space), 'skills')
    if not root.exists():
        return []
    result = []
    identifiers = set()
    for entry in root.iterdir():
        name = entry.name
        if name.startswith('.') and name.endswith('-state.json'):
            name = name[1:-len('-state.json')]
        if re.fullmatch(ID_PATTERN, name):
            identifiers.add(name)
    for skill_id in sorted(identifiers):
        path = root / skill_id
        try:
            result.append({**validate_skill(store, space, path.name), 'status': 'ready'})
        except (ValueError, OSError) as error:
            fallback = {'name': path.name, 'display_name': path.name, 'description': '', 'keywords': [], 'dependencies': []}
            try:
                state_file = _paths(store, space, path.name)[2]
                state = json.loads(_read_file(state_file, 1_000_000))
                saved = state.get('selection_metadata', {}) if isinstance(state, dict) else {}
                if isinstance(saved, dict):
                    fallback.update({key: value for key, value in saved.items() if key in fallback})
            except (ValueError, OSError, UnicodeError):
                pass
            result.append({**fallback, 'id': path.name, 'space_id': space, 'files': {},
                           'execution_status': 'reference_only', 'status': 'conflict', 'error': str(error)})
    return result


def _import(store, space, metadata, documents):
    skill_id = metadata['id']
    root, target, state_file = _paths(store, space, skill_id)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with store._safe(root, '.' + skill_id + '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous = validate_skill(store, space, skill_id) if target.exists() else None
        if not target.exists() and state_file.exists():
            raise ValueError('已登记技能的目录缺失，已保留登记以便恢复。')
        metadata_digest = _hash(_canonical(metadata))
        if previous and previous.get('metadata_sha256') == metadata_digest:
            return {'id': skill_id, 'space_id': space, 'status': 'unchanged', 'revision': previous['revision']}
        revision = previous.get('revision', 0) + 1 if previous else 1
        manifest = {**metadata, 'space_id': space, 'revision': revision, 'updated_at': _now(), 'metadata_sha256': metadata_digest}
        stage = store._safe(root, '.skill-next-' + uuid.uuid4().hex)
        stage.mkdir(mode=0o700)
        for name, value in documents.items():
            file = store._safe(stage, name)
            file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            file.write_bytes(value)
            file.chmod(0o600)
        _write_json(stage / 'manifest.json', manifest)
        archive, promoted = None, False
        try:
            if previous:
                archive = store._safe(root, '.archives/' + skill_id + '/' + str(previous['revision']) + '-' + uuid.uuid4().hex)
                archive.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                os.replace(target, archive)
            os.replace(stage, target)
            promoted = True
            _write_json(state_file, {'manifest_sha256': _hash((target / 'manifest.json').read_bytes()), 'revision': revision,
                                     'selection_metadata': {key: manifest[key] for key in ('name', 'display_name', 'description', 'keywords', 'dependencies')}})
        except BaseException:
            if promoted and target.exists():
                os.replace(target, store._safe(root, '.skill-uncommitted-' + uuid.uuid4().hex))
            if archive and archive.exists():
                os.replace(archive, target)
            raise
        return {'id': skill_id, 'space_id': space, 'status': 'updated' if previous else 'imported',
                'revision': revision, 'archive_path': str(archive) if archive else None}


def sync_local_skills(store, roots=None):
    """Explicit sync: copy verified source snapshots; preserve every local edit."""
    candidates, report = _discover(roots)
    known = {space['id'] for space in store.spaces()}
    results, unassigned = [], []
    for metadata, documents in candidates:
        roles = [space for space in metadata['assigned_agents'] if space in known]
        if not roles:
            unassigned.append(metadata['id'])
        for space in roles:
            try:
                results.append(_import(store, space, metadata, documents))
            except (ValueError, OSError) as error:
                results.append({'id': metadata['id'], 'space_id': space, 'status': 'conflict', 'error': str(error)})
    report.update({'generated_at': _now(), 'catalog': [metadata for metadata, _ in candidates],
                   'results': results, 'unassigned': unassigned,
                   'assignment_count': len(results),
                   'agent_counts': {space: sum(item['space_id'] == space for item in results) for space in sorted(known)},
                   'status_counts': {status: sum(item['status'] == status for item in results) for status in ('imported', 'updated', 'unchanged', 'conflict')},
                   'execution_status': 'reference_only',
                   'source_policy': '原 Skill 仅读取；导入不执行脚本，不修改原技能，不安装依赖，不授予外部工具权限。'})
    return report
