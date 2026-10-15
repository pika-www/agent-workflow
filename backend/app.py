"""Local-only personal knowledge agent. Run with python -m backend.app."""
import asyncio
import json
import os
import re
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .model import CHAT_SYSTEM, LEARN_SYSTEM, ModelClient, ModelError, parse_json
from .settings import Settings
from .store import WikiStore

ROOT = Path(__file__).resolve().parent.parent
MAX_TEXT = 20000


class SourceInput(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=MAX_TEXT)
    origin: str = Field(default="manual", max_length=1000)


class LearnInput(BaseModel):
    source_id: str


class ChatInput(BaseModel):
    message: str = Field(min_length=1, max_length=3000)


class RestoreInput(BaseModel):
    revision: int = Field(ge=1)


class SettingsInput(BaseModel):
    name: Optional[str] = Field(default=None, max_length=60)
    provider: Optional[str] = None
    base_url: Optional[str] = Field(default=None, max_length=500)
    model: Optional[str] = Field(default=None, max_length=160)
    api_key: Optional[str] = Field(default=None, max_length=4000)
    clear_api_key: bool = False
    watch_inbox: Optional[bool] = None
    purpose: Optional[str] = Field(default=None, max_length=2000)


def create_app(data_dir=None, model_client=None):
    root = Path(data_dir or os.environ.get("WIKI_DATA_DIR", str(ROOT / "data"))).resolve()
    if (ROOT / ".runtime/server-connection.json").is_file() and root == (ROOT / "data").resolve():
        raise RuntimeError("知识数据已迁移到服务器；请使用启动行业知识中枢.command。开发测试请显式指定独立的临时数据目录。")
    inbox = root.parent / "inbox" if data_dir else ROOT / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    store = WikiStore(root)
    settings = Settings(root)
    model = model_client or ModelClient(settings)
    queue = None
    scan_lock = None
    chat_lock = None
    runtime = {"worker_running": False, "last_error": None, "watch_error": None}

    async def enqueue(source_id):
        if not settings.public()["configured"]:
            raise HTTPException(409, "资料可以先保存；请在设置中连接模型后再学习。")
        source = store.get_source(source_id)
        if not source:
            raise HTTPException(404, "资料不存在")
        existing_job = store.find_source_job(source_id, source["revision"], ("queued", "running"))
        if existing_job:
            return existing_job
        job = store.create_job(source_id)
        await queue.put(job["id"])
        return job

    async def process(job_id):
        try:
            job = store.get_job(job_id)
            if not job:
                return
            source = store.get_source(job["source_id"], job["source_revision"])
            if not source:
                raise ValueError("学习任务对应的资料版本不存在。")
            current = store.get_source(job["source_id"])
            if current["revision"] != job["source_revision"]:
                raise ValueError("资料已有新版本，旧任务未调用模型；请学习最新版本。")
            store.update_job(job_id, status="running")
            existing = store.search(source["title"] + " " + source["text"][:1000], limit=4)
            pages = [store.get_page(x["id"]) for x in existing]
            pages = [p for p in pages if p]
            context = {"source": {k: source[k] for k in ("id", "title", "text", "revision")},
                       "existing_pages": [{"slug": p["slug"], "title": p["title"], "body": p["body"], "source_ids": p["source_ids"]} for p in pages],
                       "page_index": [{"slug": p["slug"], "title": p["title"]} for p in store.list_pages()[:100]]}
            content, actual_model = await model.complete([
                {"role": "system", "content": LEARN_SYSTEM},
                {"role": "user", "content": json.dumps(context, ensure_ascii=False)}
            ], structured=True)
            payload = parse_json(content)
            updates = payload.get("pages")
            if not isinstance(updates, list) or not 1 <= len(updates) <= 4:
                raise ModelError("模型需要返回1至4个知识页面；未修改 Wiki。")
            visible_ids = {source["id"]}
            editable_slugs = {p["slug"] for p in pages}
            for p in pages:
                visible_ids.update(p["source_ids"])
            for p in updates:
                if not isinstance(p, dict) or not isinstance(p.get("body"), str) or not p["body"].strip() or len(p["body"]) > 24000:
                    raise ModelError("模型页面正文为空或过长；未修改 Wiki。")
                if not set(p.get("source_ids", [])).issubset(visible_ids):
                    raise ModelError("模型引用了本次未提供的资料；未修改 Wiki。")
                previous = store.get_page(p.get("slug", ""))
                if previous and p["slug"] not in editable_slugs:
                    raise ModelError("模型尝试修改本次未读取的已有页面；未修改 Wiki。")
            store.apply_learning(job_id, source["id"], payload, actual_model,
                                 expected_revisions={p["slug"]: p["revision"] for p in pages})
        except Exception as exc:
            message = str(exc) if isinstance(exc, (ModelError, ValueError)) else "学习任务执行失败，请检查资料和模型连接后重试。"
            store.update_job(job_id, status="failed", error=message)

    async def worker():
        runtime["worker_running"] = True
        try:
            while True:
                job_id = await queue.get()
                try:
                    await process(job_id)
                except Exception:
                    runtime["last_error"] = "任务存储发生异常，请检查磁盘空间和学习记录。"
                    with suppress(Exception):
                        store.update_job(job_id, status="failed", error=runtime["last_error"])
                finally:
                    queue.task_done()
        finally:
            runtime["worker_running"] = False

    async def scan():
        async with scan_lock:
            result = {"imported": 0, "queued": 0, "errors": []}
            known = {s["origin"]: s for s in store.list_sources()}
            for path in sorted(inbox.iterdir())[:100]:
                if path.is_symlink() or not path.is_file() or path.suffix.lower() not in (".txt", ".md", ".markdown"):
                    continue
                try:
                    if path.stat().st_size > 120000:
                        raise ValueError("超过120KB，请拆分文件")
                    content = path.read_text(encoding="utf-8-sig")
                    if not content.strip() or len(content) > MAX_TEXT:
                        raise ValueError("资料为空或超过20000字符，请拆分文件")
                    origin = "inbox/" + path.name
                    old = known.get(origin)
                    if old and old["text"] == content:
                        source = old
                    else:
                        source = store.add_source(path.stem, content, origin=origin, source_id=old["id"] if old else None)
                        result["imported"] += not source.get("deduplicated", False)
                    already = store.find_source_job(source["id"], source["revision"])
                    if not already and settings.public()["configured"]:
                        await enqueue(source["id"])
                        result["queued"] += 1
                except (ValueError, UnicodeError, OSError) as exc:
                    result["errors"].append({"file": path.name, "error": str(exc)})
            return result

    async def watcher():
        while True:
            await asyncio.sleep(15)
            if settings.public()["watch_inbox"]:
                try:
                    await scan()
                    runtime["watch_error"] = None
                except Exception:
                    runtime["watch_error"] = "自动扫描未完成，请手动扫描查看错误。"

    @asynccontextmanager
    async def lifespan(app):
        nonlocal queue, scan_lock, chat_lock
        # Python 3.9 binds these primitives at construction, so create in the running loop.
        queue, scan_lock, chat_lock = asyncio.Queue(), asyncio.Lock(), asyncio.Lock()
        for job in store.list_jobs():
            if job["status"] in ("queued", "running"):
                store.update_job(job["id"], status="failed", error="上次运行中断，资料已保留；请重新学习。")
        runner = asyncio.create_task(worker())
        watch = asyncio.create_task(watcher())
        await asyncio.sleep(0)
        yield
        for task in (runner, watch):
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="知行 · 我的知识智能体", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver", "[::1]"])
    app.state.store, app.state.settings, app.state.model = store, settings, model
    app.state.process_job = process
    app.state.inbox = inbox

    @app.middleware("http")
    async def protect_local(request: Request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if request.headers.get("X-Wiki-Client") != "local" or (origin and urlsplit(origin).netloc != request.headers.get("host")):
                return JSONResponse({"detail": "请从本机智能体页面执行操作。"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
        return response

    @app.exception_handler(ValueError)
    async def validation_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(ModelError)
    async def model_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=502)

    @app.get("/api/health")
    async def health():
        return {"ok": runtime["worker_running"], "service": "zhixing-wiki", "model_configured": settings.public()["configured"], **runtime}

    @app.get("/api/state")
    async def state():
        sources, pages, jobs = store.list_sources(), store.list_pages(), store.list_jobs()
        for s in sources:
            matching = store.find_source_job(s["id"], s["revision"])
            s["status"] = matching["status"] if matching else "pending"
            s.pop("text", None)
        return {"agent": settings.public(), "runtime": runtime, "stats": {"sources": len(sources), "pages": len(pages), "jobs": len(jobs)},
                "sources": sources, "pages": pages, "jobs": jobs}

    @app.get("/api/settings")
    async def get_settings():
        return settings.public()

    @app.put("/api/settings")
    async def save_settings(body: SettingsInput):
        return settings.update(body.model_dump(exclude_none=True))

    @app.post("/api/model/check")
    async def check_model():
        text, actual_model = await model.complete([{"role": "user", "content": "请只回复：连接成功"}])
        return {"ok": True, "detail": "模型已真实响应：" + text[:80], "model": actual_model}

    @app.post("/api/sources")
    async def add_source(body: SourceInput):
        return store.add_source(body.title.strip(), body.text, body.origin)

    @app.get("/api/sources/{source_id}")
    async def get_source(source_id: str, revision: Optional[int] = None):
        source = store.get_source(source_id, revision)
        if not source:
            raise HTTPException(404, "资料不存在")
        return source

    @app.post("/api/upload")
    async def upload(file: UploadFile = File(...)):
        name = Path(file.filename or "资料.txt").name
        if Path(name).suffix.lower() not in (".md", ".txt", ".markdown"):
            raise HTTPException(400, "第一版支持 UTF-8 的 Markdown 和 TXT，请先将其他格式转换为文本。")
        raw = await file.read(120001)
        if len(raw) > 120000:
            raise HTTPException(400, "文件超过120KB，请拆分后导入。")
        try:
            content = raw.decode("utf-8-sig")
        except UnicodeError:
            raise HTTPException(400, "文件不是 UTF-8 编码，请另存为 UTF-8 后重试。")
        if not content.strip() or len(content) > MAX_TEXT:
            raise HTTPException(400, "资料为空或超过20000字符，请拆分后导入。")
        return store.add_source(Path(name).stem, content, origin="upload/" + name)

    @app.post("/api/learn")
    async def learn(body: LearnInput):
        return await enqueue(body.source_id)

    @app.post("/api/inbox/scan")
    async def scan_inbox():
        return await scan()

    @app.get("/api/jobs")
    async def jobs():
        return store.list_jobs()

    @app.get("/api/pages")
    async def pages(q: str = ""):
        return store.list_pages(q)

    @app.get("/api/pages/{page_id}/revisions")
    async def revisions(page_id: str):
        return store.list_revisions(page_id)

    @app.post("/api/pages/{page_id}/restore")
    async def restore(page_id: str, body: RestoreInput):
        return store.restore_page(page_id, body.revision)

    @app.get("/api/pages/{page_id}")
    async def page(page_id: str, revision: Optional[int] = None):
        found = store.get_revision(page_id, revision) if revision is not None else store.get_page(page_id)
        if not found:
            raise HTTPException(404, "页面不存在")
        return found

    @app.get("/api/chat")
    async def chat_history():
        return {"messages": store.list_chat()}

    @app.post("/api/chat")
    async def chat(body: ChatInput):
        if not settings.public()["configured"]:
            raise HTTPException(409, "尚未连接模型。请在设置中填写模型连接信息。")
        async with chat_lock:
            hits = store.search(body.message, limit=6)
            evidence = []
            for hit in hits:
                p = store.get_page(hit["id"])
                evidence.append({"id": p["id"], "title": p["title"], "kind": "page", "text": p["body"][:5000], "revision": p["revision"], "sources": p["sources"]})
            history = store.list_chat()[-8:]
            source_context = []
            for p in evidence:
                for ref in p["sources"]:
                    if ref["id"] not in {s["id"] for s in source_context}:
                        s = store.get_source(ref["id"], ref["revision"])
                        if s:
                            source_context.append({"id": s["id"], "title": s["title"], "kind": "source", "text": s["text"][:4000], "revision": s["revision"]})
            all_evidence = evidence + source_context[:4]
            context = [{**p, "number": i + 1} for i, p in enumerate(all_evidence)]
            user_input = {"question": body.message, "evidence": context, "agent_purpose": settings.read()["purpose"]}
            messages = [{"role": "system", "content": CHAT_SYSTEM}] + [{"role": m["role"], "content": m["content"]} for m in history]
            messages.append({"role": "user", "content": json.dumps(user_input, ensure_ascii=False)})
            content, actual_model = await model.complete(messages, structured=True)
            result = parse_json(content)
            answer = result.get("answer")
            ids = result.get("citation_ids", [])
            if not isinstance(answer, str) or not answer.strip() or not isinstance(ids, list):
                raise ModelError("模型回答格式不正确，未保存为知识。")
            allowed = {p["id"]: p for p in context}
            if any(not isinstance(i, str) or i not in allowed for i in ids):
                raise ModelError("模型返回了无法核对的来源，请重试。")
            citations = [{k: allowed[i][k] for k in ("id", "title", "kind", "number", "revision")} for i in dict.fromkeys(ids)]
            numbers = {int(n) for n in re.findall(r"\[(\d+)\]", answer)}
            if numbers != {c["number"] for c in citations}:
                raise ModelError("回答中的引用编号与来源列表不一致，请重试。")
            store.log_chat("user", body.message, [])
            store.log_chat("assistant", answer, citations)
            return {"answer": answer, "citations": citations, "model": actual_model}

    @app.post("/api/lint")
    async def lint():
        return store.lint()

    @app.get("/")
    async def index():
        return FileResponse(ROOT / "frontend" / "index.html")

    app.mount("/static", StaticFiles(directory=str(ROOT / "frontend"), check_dir=False), name="static")
    return app


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(create_app(), host="127.0.0.1", port=int(os.environ.get("WIKI_PORT", "18731")))
