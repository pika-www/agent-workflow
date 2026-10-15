"""Immutable task outputs, scoped to one room and round; no model-supplied paths."""
import hashlib
import re
from pathlib import Path


class DelegationArtifacts:
    def __init__(self, base, room_id, round_id):
        for identifier in (room_id, round_id):
            if not re.fullmatch('[a-f0-9]{32}', identifier):
                raise ValueError('Invalid delegation scope')
        self.root = Path(base)/'metadata'/'delegation-results'/room_id/round_id

    def save(self, task_id, text):
        if not re.fullmatch('[a-f0-9]{32}',task_id):
            raise ValueError('Invalid task ID')
        raw = text.encode('utf-8')
        digest = hashlib.sha256(raw).hexdigest()
        name = task_id+'-'+digest+'.md'
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        path = self.root/name
        try:
            with path.open('xb') as out:
                out.write(raw)
            path.chmod(0o600)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes() != raw:
                raise ValueError('Artifact version conflict')
        return {'task_id':task_id, 'sha256':digest, 'characters':len(text),
                'path':'/_delegation_results/'+name, 'version':digest}

    def read(self, reference):
        name=reference['task_id']+'-'+reference['sha256']+'.md'
        if not re.fullmatch(r'[a-f0-9]{32}-[a-f0-9]{64}\.md',name):
            raise ValueError('Invalid artifact reference')
        path=self.root/name
        if path.is_symlink():
            raise ValueError('Invalid artifact file')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=reference['sha256']:
            raise ValueError('Artifact version changed')
        return raw.decode('utf-8')
