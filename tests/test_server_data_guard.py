"""A migrated checkout must not silently recreate its former data stores."""
from pathlib import Path

import pytest

from backend import app as legacy
from federation import app as federation


@pytest.mark.parametrize("module,argument,folder", [
    (federation, "base", "openwiki-federation"),
    (legacy, "data_dir", "data"),
])
def test_migrated_default_store_is_rejected_before_writing(tmp_path, monkeypatch, module, argument, folder):
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.delenv("WIKI_DATA_DIR", raising=False)
    (tmp_path / ".runtime").mkdir()
    (tmp_path / ".runtime/server-connection.json").write_text("{}")
    for kwargs in ({}, {argument: tmp_path / folder}):
        with pytest.raises(RuntimeError, match="服务器"):
            module.create_app(**kwargs)
    assert not (tmp_path / folder).exists()
    assert not (tmp_path / "inbox").exists()


@pytest.mark.parametrize("module,argument,constructor", [
    (federation, "base", "FederationStore"),
    (legacy, "data_dir", "WikiStore"),
])
def test_explicit_isolated_test_store_remains_allowed(tmp_path, monkeypatch, module, argument, constructor):
    monkeypatch.setattr(module, "ROOT", tmp_path)
    (tmp_path / ".runtime").mkdir()
    (tmp_path / ".runtime/server-connection.json").write_text("{}")
    class IsolatedStoreReached(Exception):
        pass
    def isolated_store(*args, **kwargs):
        selected = kwargs.get("base", args[0] if args else None)
        assert Path(selected) == tmp_path / "isolated-test-data"
        raise IsolatedStoreReached
    monkeypatch.setattr(module, constructor, isolated_store)
    with pytest.raises(IsolatedStoreReached):
        module.create_app(**{argument: tmp_path / "isolated-test-data"})
