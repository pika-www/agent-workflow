import asyncio
import json
import stat
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.model import ModelError
from backend.store import WikiStore

HEADERS = {"X-Wiki-Client": "local"}


class FakeModel:
    """Only used by isolated tests; never selectable in the application."""
    def __init__(self):
        self.calls = []
        self.bad = False

    async def complete(self, messages, structured=False):
        self.calls.append(messages)
        context = json.loads(messages[-1]["content"])
        if self.bad:
            return "not json", "test-double"
        if "source" in context:
            s = context["source"]
            return json.dumps({"pages": [{"slug": "deployment", "title": "测试环境启动",
                "body": s["text"], "source_ids": [s["id"]]}]}, ensure_ascii=False), "test-double"
        evidence = context["evidence"]
        return json.dumps({"answer": "启动端口为18731。[1]", "citation_ids": [evidence[0]["id"]] if evidence else []}), "test-double"


def configure(client):
    res = client.put("/api/settings", json={"provider": "ollama", "base_url": "http://localhost:11434", "model": "test-model"}, headers=HEADERS)
    assert res.status_code == 200


def add(client, text="测试环境启动使用端口18731，数据保存到本地。"):
    res = client.post("/api/sources", json={"title": "启动手册", "text": text}, headers=HEADERS)
    assert res.status_code == 200
    return res.json()


def finish(client, source_id):
    response = client.post("/api/learn", json={"source_id": source_id}, headers=HEADERS)
    assert response.status_code == 200, response.text
    job_id = response.json()["id"]
    for _ in range(100):
        job = next(j for j in client.get("/api/jobs").json() if j["id"] == job_id)
        if job["status"] in ("succeeded", "failed"):
            return job
        time.sleep(0.02)
    pytest.fail("job did not reach terminal state")


def test_unconfigured_model_never_claims_learning(tmp_path):
    with TestClient(create_app(tmp_path / "data")) as client:
        s = add(client)
        assert client.post("/api/learn", json={"source_id": s["id"]}, headers=HEADERS).status_code == 409
        assert client.post("/api/chat", json={"message": "你好"}, headers=HEADERS).status_code == 409
        state = client.get("/api/state").json()
        assert state["stats"] == {"sources": 1, "pages": 0, "jobs": 0}
        assert state["sources"][0]["status"] == "pending"


def test_cross_origin_and_host_protection(tmp_path):
    with TestClient(create_app(tmp_path / "data")) as client:
        body = {"title": "x", "text": "x"}
        assert client.post("/api/sources", json=body).status_code == 403
        assert client.post("/api/sources", json=body, headers={**HEADERS, "Origin": "https://unrelated.example"}).status_code == 403
        assert client.get("/api/state", headers={"Host": "unrelated.example"}).status_code == 400


def test_ingest_query_and_persist_with_test_double(tmp_path):
    model = FakeModel()
    root = tmp_path / "data"
    with TestClient(create_app(root, model_client=model)) as client:
        configure(client)
        s = add(client)
        assert add(client)["id"] == s["id"]
        job = finish(client, s["id"])
        assert job["status"] == "succeeded", job
        assert job["model"] == "test-double"
        page = client.get("/api/pages/deployment").json()
        assert page["source_ids"] == [s["id"]]
        assert s["id"] in (root / page["path"]).read_text()
        reply = client.post("/api/chat", json={"message": "测试环境启动端口是多少"}, headers=HEADERS)
        assert reply.status_code == 200, reply.text
        assert reply.json()["citations"][0]["id"] == "deployment"
        assert reply.json()["citations"][0]["revision"] == 1
        assert len(client.get("/api/chat").json()["messages"]) == 2
    assert WikiStore(root).get_page("deployment")["body"] == s["text"]


def test_chat_uses_immutable_page_and_source_versions(tmp_path):
    model = FakeModel()
    app = create_app(tmp_path / "data", model_client=model)
    with TestClient(app) as client:
        configure(client)
        original = add(client)
        assert finish(client, original["id"])["status"] == "succeeded"
        app.state.store.add_source("启动手册", "新资料版本，端口不同", source_id=original["id"])
        response = client.post("/api/chat", json={"message": "测试环境启动端口"}, headers=HEADERS)
        assert response.status_code == 200
        evidence = json.loads(model.calls[-1][-1]["content"])["evidence"]
        source_evidence = next(x for x in evidence if x["kind"] == "source")
        assert source_evidence["revision"] == 1
        assert source_evidence["text"] == original["text"]
        assert finish(client, original["id"])["status"] == "succeeded"
        assert client.get("/api/pages/deployment").json()["revision"] == 2
        cited = client.get("/api/pages/deployment?revision=1").json()
        assert cited["body"] == original["text"]
        assert cited["revision"] == response.json()["citations"][0]["revision"]


def test_bad_model_output_is_failed_without_pages(tmp_path):
    model = FakeModel()
    model.bad = True
    with TestClient(create_app(tmp_path / "data", model_client=model)) as client:
        configure(client)
        s = add(client)
        job = finish(client, s["id"])
        assert job["status"] == "failed"
        assert "结构化" in job["error"]
        assert client.get("/api/pages").json() == []


def test_source_revision_and_page_restore_are_lossless(tmp_path):
    store = WikiStore(tmp_path / "data")
    first = store.add_source("手册", "版本一")
    j = store.create_job(first["id"])
    payload = {"pages": [{"slug": "manual", "title": "手册", "body": "版本一", "source_ids": [first["id"]]}]}
    store.apply_learning(j["id"], first["id"], payload, "test-double")
    second = store.add_source("手册", "版本二", source_id=first["id"])
    assert store.get_source(first["id"], 1)["text"] == "版本一"
    assert any(x["kind"] == "stale_source" for x in store.lint()["issues"])
    j2 = store.create_job(first["id"])
    payload["pages"][0]["body"] = "版本二"
    store.apply_learning(j2["id"], first["id"], payload, "test-double")
    restored = store.restore_page("manual", 1)
    assert restored["revision"] == 3
    assert restored["body"] == "版本一"
    assert restored["sources"][0]["revision"] == 1
    assert store.get_source(first["id"])["revision"] == second["revision"] == 2


@pytest.mark.parametrize("slug,source_ids", [("../../outside", []), ("safe", ["invented-source"])])
def test_untrusted_model_paths_and_sources_are_rejected(tmp_path, slug, source_ids):
    store = WikiStore(tmp_path / "data")
    source = store.add_source("资料", "正文")
    job = store.create_job(source["id"])
    with pytest.raises(ValueError):
        store.apply_learning(job["id"], source["id"], {"pages": [{"slug": slug, "title": "页", "body": "文", "source_ids": source_ids}]}, "test-double")
    assert store.get_job(job["id"])["status"] == "failed"
    assert store.list_pages() == []
    assert not (tmp_path / "outside.md").exists()


def test_changed_source_cannot_publish_stale_learning(tmp_path):
    store = WikiStore(tmp_path / "data")
    source = store.add_source("资料", "第一版")
    job = store.create_job(source["id"])
    store.add_source("资料", "第二版", source_id=source["id"])
    with pytest.raises(ValueError, match="已更新"):
        store.apply_learning(job["id"], source["id"], {"pages": [{"slug": "stale", "title": "旧页", "body": "旧文"}]}, "test-double")
    assert not store.list_pages()


def test_manual_edits_are_not_overwritten(tmp_path):
    store = WikiStore(tmp_path / "data")
    source = store.add_source("资料", "正文")
    payload = {"pages": [{"slug": "manual", "title": "页", "body": "自动生成"}]}
    store.apply_learning(store.create_job(source["id"])["id"], source["id"], payload, "test-double")
    page_file = store.data_dir / "wiki" / "manual.md"
    page_file.write_text("用户修改，请保留")
    with pytest.raises(ValueError, match="手工修改"):
        store.apply_learning(store.create_job(source["id"])["id"], source["id"], payload, "test-double")
    assert page_file.read_text() == "用户修改，请保留"


def test_secret_is_not_exposed_or_erased_by_blank_input(tmp_path):
    with TestClient(create_app(tmp_path / "data")) as client:
        response = client.put("/api/settings", json={"api_key": "test-secret"}, headers=HEADERS)
        assert response.status_code == 200
        assert "test-secret" not in response.text
        assert client.get("/api/settings").json()["api_key_set"]
        client.put("/api/settings", json={"api_key": ""}, headers=HEADERS)
        assert client.get("/api/settings").json()["api_key_set"]
        assert stat.S_IMODE((tmp_path / "data/settings.json").stat().st_mode) == 0o600


def test_upload_limits_and_inbox_import_without_model(tmp_path):
    app = create_app(tmp_path / "data")
    (app.state.inbox / "资料.md").write_text("来自投递箱的知识", encoding="utf-8")
    with TestClient(app) as client:
        assert client.post("/api/upload", files={"file": ("bad.exe", b"abc")}, headers=HEADERS).status_code == 400
        assert client.post("/api/upload", files={"file": ("bad.txt", b"\xff\xfe")}, headers=HEADERS).status_code == 400
        first = client.post("/api/inbox/scan", headers=HEADERS).json()
        assert first == {"imported": 1, "queued": 0, "errors": []}
        assert client.post("/api/inbox/scan", headers=HEADERS).json()["imported"] == 0
        assert client.get("/api/state").json()["stats"]["pages"] == 0


def test_interrupted_job_is_recoverable_and_not_reported_active(tmp_path):
    store = WikiStore(tmp_path / "data")
    s = store.add_source("资料", "原文保留")
    job = store.create_job(s["id"])
    recovered = WikiStore(tmp_path / "data")
    assert recovered.get_job(job["id"])["status"] == "failed"
    assert recovered.get_source(s["id"])["text"] == "原文保留"


def test_switching_provider_does_not_leak_old_secret(tmp_path):
    with TestClient(create_app(tmp_path / "data")) as client:
        client.put("/api/settings", json={"api_key": "old-secret"}, headers=HEADERS)
        changed = client.put("/api/settings", json={"base_url": "https://different.example/v1"}, headers=HEADERS)
        assert changed.status_code == 200
        assert not changed.json()["api_key_set"]


def test_concurrent_restore_rejects_outdated_model_result(tmp_path):
    store = WikiStore(tmp_path / "data")
    s = store.add_source("并发", "原始资料")
    payload = {"pages": [{"slug": "concurrent", "title": "并发", "body": "第一版"}]}
    store.apply_learning(store.create_job(s["id"])["id"], s["id"], payload, "test-double", expected_revisions={})
    before = store.get_page("concurrent")
    store.restore_page("concurrent", 1)
    payload["pages"][0]["body"] = "过期模型输出"
    with pytest.raises(ValueError):
        store.apply_learning(store.create_job(s["id"])["id"], s["id"], payload, "test-double", expected_revisions={"concurrent": before["revision"]})
    assert store.get_page("concurrent")["body"] == "第一版"


def test_invalid_inline_citation_is_not_saved(tmp_path):
    class InvalidCitationModel:
        async def complete(self, *args, **kwargs):
            return json.dumps({"answer": "伪造的结论[99]", "citation_ids": []}), "test-double"
    with TestClient(create_app(tmp_path / "data", model_client=InvalidCitationModel())) as client:
        configure(client)
        response = client.post("/api/chat", json={"message": "有何证据"}, headers=HEADERS)
        assert response.status_code == 502
        assert client.get("/api/chat").json()["messages"] == []


def test_changed_inbox_revision_can_queue_while_old_job_is_running(tmp_path):
    class SlowModel(FakeModel):
        async def complete(self, *args, **kwargs):
            await asyncio.sleep(0.2)
            return await super().complete(*args, **kwargs)
    app = create_app(tmp_path / "data", model_client=SlowModel())
    path = app.state.inbox / "版本.md"
    path.write_text("最初版本")
    with TestClient(app) as client:
        configure(client)
        first = client.post("/api/inbox/scan", headers=HEADERS).json()
        path.write_text("第二版本")
        second = client.post("/api/inbox/scan", headers=HEADERS).json()
        assert first["queued"] == second["queued"] == 1
        jobs = client.get("/api/jobs").json()
        assert {j["source_revision"] for j in jobs} == {1, 2}
        for _ in range(100):
            newest = next(j for j in client.get("/api/jobs").json() if j["source_revision"] == 2)
            if newest["status"] in ("succeeded", "failed"):
                break
            time.sleep(0.02)
        assert newest["status"] == "succeeded", newest
