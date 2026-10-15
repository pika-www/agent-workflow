import importlib.util
import json
from pathlib import Path


def test_relocation_preserves_history_permissions_and_originals(tmp_path):
    module_path = Path(__file__).resolve().parents[1] / 'deploy/server/relocate.py'
    spec = importlib.util.spec_from_file_location('server_relocate', module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    project, backup = tmp_path / 'project', tmp_path / 'originals'
    state = project / 'openwiki-federation/central/state'
    connector = state / 'connectors/custom-mcp/config.json'
    connector.parent.mkdir(parents=True)
    original = json.dumps({'transport': {'command': '/old/node', 'args': ['/old/project/inbox']},
                           'allowedTools': ['read_text_file']})
    connector.write_text(original)
    connector.chmod(0o600)
    history = project / 'openwiki-federation/chat/room.json'
    history.parent.mkdir()
    history.write_text('{"original_path":"/old/project/inbox"}')
    before = history.read_bytes()
    result = module.relocate(project, '/old/project', '/old/node', '/new/node', backup)
    assert result == ['openwiki-federation/central/state/connectors/custom-mcp/config.json']
    updated = json.loads(connector.read_text())
    assert updated['transport'] == {'command': '/new/node', 'args': [str(project / 'inbox')]}
    assert updated['allowedTools'] == ['read_text_file']
    assert connector.stat().st_mode & 0o777 == 0o600
    assert (backup / result[0]).read_text() == original
    assert history.read_bytes() == before
    assert module.relocate(project, '/old/project', '/old/node', '/new/node', backup) == []
    assert (backup / result[0]).read_text() == original
