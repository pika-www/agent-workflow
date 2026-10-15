"""Explicit project snapshots and per-room, per-Agent task bindings."""
import fcntl
import json
import os
import uuid
from contextlib import contextmanager

from .core import _now, _sha, _write_json
from .memory_requirements import clean, claims


class ProjectMemory:
    def __init__(self, store, chat, memory):
        self.store, self.chat, self.memory = store, chat, memory
        self.path = store._safe(store.base, 'metadata/project-memory.json')

    def read(self):
        return json.loads(self.path.read_text()) if self.path.exists() else {'schema_version': 1, 'revision': 0, 'projects': {}, 'bindings': {}}

    @contextmanager
    def locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path.with_suffix('.lock'), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield self.read()
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    @staticmethod
    def binding(state, room_id, agent_id):
        return state['bindings'].get(room_id, {}).get(agent_id, {'project_id': None, 'task_id': None, 'revision': 0})

    def fingerprint(self, source):
        room = self.chat.get_room(source['room_id'])
        state = self.memory.inspect(room['id'], source['agent_id'])
        task = next((t for t in state['tasks'] if t['id'] == source['task_id']), None)
        if not task or task['status'] == 'forgotten': return None
        sentences = sorted({(slot, value, text) for m in room['messages'] if m['id'] in task['message_ids'] and m['role'] == 'user'
                            for slot, value, text in claims(m['content'])})
        material = {'goal': task['goal'], 'requirements': sentences, 'resolutions': task.get('resolutions'),
                    'manual_summary': (task.get('manual_summary') or {}).get('text')}
        return _sha(json.dumps(material, ensure_ascii=False, sort_keys=True).encode())

    def source_status(self, project):
        try:
            fingerprint = self.fingerprint(project['source'])
        except (ValueError, FileNotFoundError): return 'missing'
        if fingerprint is None: return 'forgotten'
        return 'current' if fingerprint == project['source']['fingerprint'] else 'changed'

    def capture(self, room, agent_id, task_id, expected_revision):
        state = self.memory.view(room, agent_id)
        if state['revision'] != expected_revision: raise ValueError('任务记忆版本已变化，请刷新核对')
        task = next((t for t in state['tasks'] if t['id'] == task_id and t['status'] != 'forgotten'), None)
        if not task: raise ValueError('请先完成普通咨询，再选择任务作为项目来源')
        ledger = task['requirement_state']
        if ledger['conflicts']: raise ValueError('来源任务仍有要求冲突，请先选择当前要求')
        source = {'room_id': room['id'], 'agent_id': agent_id, 'task_id': task_id, 'revision': state['revision']}
        source['fingerprint'] = self.fingerprint(source)
        # Only source-linked user requirements and explicitly edited notes are shared.
        # Automatic summaries and assistant execution claims are not project facts.
        requirements = list({(r['slot'], r['value']): r for r in ledger['active']}.values())
        return {'source': source, 'original_goal': clean(task['goal']), 'requirements': requirements,
                'manual_summary': clean((task.get('manual_summary') or {}).get('text', ''))}

    def public(self, project):
        result = json.loads(json.dumps(project))
        status = self.source_status(project)
        result['source_status'] = status
        if status == 'forgotten' or status == 'missing':
            result.pop('requirements', None); result.pop('original_goal', None); result.pop('manual_summary', None)
            result.pop('versions', None)
        return result

    def view(self, room_id, agent_id):
        state = self.read()
        return {'revision': state['revision'], 'binding': self.binding(state, room_id, agent_id),
                'projects': [self.public(p) for p in state['projects'].values() if p['status'] != 'forgotten' and agent_id in p['allowed_agents']],
                'notice': '选择项目后仅用于关联任务的续聊。项目记录不构成事实验证或执行授权。'}

    def context(self, room, agent_id, task_id, boundary=False, bind=False):
        state = self.read(); selected = self.binding(state, room['id'], agent_id)
        project = state['projects'].get(selected['project_id'])
        if not project or project['status'] != 'active' or agent_id not in project['allowed_agents'] or boundary: return None
        if selected['task_id'] is None and bind:
            with self.locked() as latest:
                current = self.binding(latest, room['id'], agent_id)
                if current != selected: return None
                project = latest['projects'].get(current['project_id'])
                if not project or project['status'] != 'active' or agent_id not in project['allowed_agents']: return None
                current = {**current, 'task_id': task_id, 'revision': current['revision'] + 1}
                latest['bindings'].setdefault(room['id'], {})[agent_id] = current
                latest['revision'] += 1; _write_json(self.path, latest); selected = current
        if selected['task_id'] != task_id: return None
        status = self.source_status(project)
        result = {'id': project['id'], 'title': project['title'], 'revision': project['revision'], 'source_status': status,
                  'source': {k: project['source'][k] for k in ['room_id', 'agent_id', 'task_id', 'fingerprint']},
                  'notice': '用户选择的项目记录；当前问题及本会话的最新要求优先。进度与下一步是用户记录，不是执行回执。'}
        if status == 'current':
            result.update(original_goal=project['original_goal'], requirements=project['requirements'],
                          progress=project['progress'], next_steps=project['next_steps'], manual_summary=project['manual_summary'])
        else: result['notice'] = '项目来源已变化或被忘记，暂不提供旧项目内容；请在记忆面板核对后同步。'
        return result

    @staticmethod
    def seeds(project):
        if not project or project['source_status'] != 'current': return []
        return [{'id': 'project:' + project['id'] + ':' + _sha(text.encode())[:16], 'role': 'user', 'content': text,
                 'origin': 'explicit_project_snapshot'} for text in dict.fromkeys(r['text'] for r in project['requirements'])]

    def edit(self, room, agent_id, data):
        action = data['action']; project_id = data.get('project_id')
        if agent_id not in room['participants']: raise ValueError('该 Agent 不在当前会话中')
        if action in {'create', 'sync', 'attach'}:
            current = self.memory.inspect(room['id'], agent_id)
            if current['revision'] != data.get('expected_task_revision'): raise ValueError('任务记忆版本已变化，请刷新核对')
            if action == 'attach' and data.get('task_id') and not any(t['id'] == data['task_id'] and t['status'] != 'forgotten' for t in current['tasks']):
                raise ValueError('关联的任务不存在或已忘记')
        snapshot = self.capture(room, agent_id, data.get('task_id'), data.get('expected_task_revision')) if action in {'create', 'sync'} else None
        with self.locked() as state:
            project = state['projects'].get(project_id)
            binding = self.binding(state, room['id'], agent_id)
            if action == 'detach':
                if binding['revision'] != data.get('binding_revision'): raise ValueError('项目关联已变化，请刷新')
                state['bindings'].setdefault(room['id'], {})[agent_id] = {'project_id': None, 'task_id': None, 'revision': binding['revision'] + 1}
            else:
                if action == 'create':
                    if data.get('expected_revision') != state['revision']: raise ValueError('项目列表已变化，请刷新')
                    project_id = uuid.uuid4().hex
                    project = {'id': project_id, 'revision': 0, 'status': 'active', 'created_at': _now(), 'versions': []}
                    state['projects'][project_id] = project
                elif not project or project['status'] == 'forgotten': raise ValueError('项目记忆不存在或已忘记')
                elif agent_id not in project['allowed_agents']: raise ValueError('这个项目未开放给当前 Agent')
                elif project['revision'] != data.get('expected_revision'): raise ValueError('项目记忆版本已变化，请刷新核对')
                if action in {'create', 'update'}:
                    fields = {}
                    for key, limit in [('title', 80), ('progress', 2000), ('next_steps', 2000)]:
                        value = data.get(key, '')
                        if not isinstance(value, str) or len(value) > limit or '\0' in value or (key == 'title' and not value.strip()): raise ValueError('项目记录内容无效')
                        fields[key] = clean(value.strip())
                    agents = data.get('allowed_agents') or [agent_id]
                    if not isinstance(agents, list) or not agents or len(agents) > 26: raise ValueError('项目 Agent 范围无效')
                    for member in agents: self.store.space(member)
                    if agent_id not in agents: raise ValueError('须保留当前 Agent 的项目范围')
                    if project['revision']: project['versions'].append({key: project[key] for key in ['revision', 'title', 'progress', 'next_steps', 'allowed_agents']})
                    project.update(fields, allowed_agents=list(dict.fromkeys(agents)))
                if action in {'create', 'sync'}:
                    if action == 'sync': project['versions'].append({'revision': project['revision'], 'source': project['source'], 'requirements': project['requirements']})
                    project.update(snapshot)
                if action in {'create', 'attach', 'sync'}:
                    if agent_id not in project['allowed_agents']: raise ValueError('这个项目未开放给当前 Agent')
                    if binding['revision'] != data.get('binding_revision', 0): raise ValueError('项目关联已变化，请刷新')
                    state['bindings'].setdefault(room['id'], {})[agent_id] = {'project_id': project_id, 'task_id': data.get('task_id'), 'revision': binding['revision'] + 1}
                elif action == 'forget':
                    revision = project['revision']; project.clear(); project.update(id=project_id, status='forgotten', revision=revision)
                    for members in state['bindings'].values():
                        for member, old in list(members.items()):
                            if old['project_id'] == project_id: members[member] = {'project_id': None, 'task_id': None, 'revision': old['revision'] + 1}
                elif action != 'update': raise ValueError('项目记忆操作无效')
                project['revision'] += 1; project['updated_at'] = _now()
            state['revision'] += 1; _write_json(self.path, state)
        return {'status': action, 'project_id': project_id, 'revision': state['revision']}
