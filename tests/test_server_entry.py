import io
import json

import pytest
from federation import server_entry


def config(tmp_path, monkeypatch):
    path = tmp_path / 'connection.json'
    path.write_text(json.dumps({'instance': '/server/data', 'host': 'test-host', 'local_port': 18732}))
    monkeypatch.setattr(server_entry, 'CONFIG', path)
    return path


def test_check_refuses_other_instance_without_starting_local_service(tmp_path, monkeypatch):
    config(tmp_path, monkeypatch)
    class HTTP:
        def open(self, *args, **kwargs):
            return io.BytesIO(b'{"instance":"/different/data"}')
    monkeypatch.setattr(server_entry, 'build_opener', lambda _: HTTP())
    monkeypatch.setattr(server_entry.subprocess, 'run', lambda *a, **k: pytest.fail('must not start or stop services'))
    with pytest.raises(RuntimeError, match='不匹配'):
        server_entry.main(check=True)


def test_offline_check_fails_without_local_database_fallback(tmp_path, monkeypatch):
    config(tmp_path, monkeypatch)
    class HTTP:
        def open(self, *args, **kwargs):
            raise OSError('offline')
    monkeypatch.setattr(server_entry, 'build_opener', lambda _: HTTP())
    monkeypatch.setattr(server_entry.subprocess, 'run', lambda *a, **k: pytest.fail('must not start local database'))
    with pytest.raises(RuntimeError, match='未启用另一份本机数据库'):
        server_entry.main(check=True)
