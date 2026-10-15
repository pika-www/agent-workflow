"""SQLite-backed, versioned Markdown wiki with recoverable file publication.

SQLite is the authoritative record. Every filesystem change is first added to an
outbox in the same transaction as its record. A failed write stays in the outbox
and can be retried by initialize(). Raw source snapshots and revision snapshots
are immutable. User edits to generated pages are detected before replacement.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
from typing import Any, Dict, List, Optional
import uuid


_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")
_STATUSES = {"queued", "running", "succeeded", "failed"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _slug(value: str) -> str:
    if not isinstance(value, str) or not _SLUG.fullmatch(value):
        raise ValueError("页面 slug 只能包含小写英文字母、数字、下划线或连字符，长度为 1–80，且以字母或数字开头。")
    return value


class WikiStore:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.db_path = self.data_dir / "wiki.sqlite3"
        self._lock = threading.RLock()
        self.initialize()

    @contextmanager
    def _db(self):
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        with self._lock:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            for name in ("raw", "wiki", "revisions"):
                (self.data_dir / name).mkdir(exist_ok=True)
            with self._db() as db:
                db.execute("PRAGMA journal_mode=WAL")
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS sources (
                        id TEXT PRIMARY KEY, title TEXT NOT NULL,
                        origin TEXT NOT NULL, content_hash TEXT NOT NULL,
                        revision INTEGER NOT NULL, created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS sources_hash ON sources(content_hash);
                    CREATE TABLE IF NOT EXISTS source_versions (
                        source_id TEXT NOT NULL REFERENCES sources(id),
                        revision INTEGER NOT NULL, title TEXT NOT NULL,
                        origin TEXT NOT NULL, content_hash TEXT NOT NULL,
                        text TEXT NOT NULL, created_at TEXT NOT NULL,
                        PRIMARY KEY(source_id, revision)
                    );
                    CREATE TABLE IF NOT EXISTS pages (
                        id TEXT PRIMARY KEY, title TEXT NOT NULL,
                        body TEXT NOT NULL, markdown TEXT NOT NULL,
                        source_ids TEXT NOT NULL, sources TEXT NOT NULL,
                        revision INTEGER NOT NULL, model TEXT NOT NULL,
                        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS page_revisions (
                        page_id TEXT NOT NULL REFERENCES pages(id),
                        revision INTEGER NOT NULL, snapshot TEXT NOT NULL,
                        PRIMARY KEY(page_id, revision)
                    );
                    CREATE TABLE IF NOT EXISTS jobs (
                        id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id),
                        source_revision INTEGER NOT NULL, status TEXT NOT NULL,
                        model TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '',
                        result TEXT NOT NULL DEFAULT '{}', page_ids TEXT NOT NULL DEFAULT '[]',
                        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                        started_at TEXT, finished_at TEXT
                    );
                    CREATE TABLE IF NOT EXISTS chat (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT NOT NULL,
                        content TEXT NOT NULL, citations TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS file_outbox (
                        path TEXT PRIMARY KEY, content TEXT NOT NULL,
                        immutable INTEGER NOT NULL DEFAULT 0,
                        expected_hash TEXT NOT NULL DEFAULT ''
                    );
                """)
                if "expected_hash" not in {row["name"] for row in db.execute("PRAGMA table_info(file_outbox)")}:
                    db.execute("ALTER TABLE file_outbox ADD COLUMN expected_hash TEXT NOT NULL DEFAULT ''")
                # Restore missing generated files from authoritative snapshots.
                for row in db.execute("SELECT * FROM source_versions").fetchall():
                    rel = self._raw_path(row["source_id"], row["revision"])
                    if not (self.data_dir / rel).exists():
                        self._queue_file(db, rel, row["text"], True)
                for row in db.execute("SELECT * FROM pages").fetchall():
                    rel = "wiki/{}.md".format(row["id"])
                    if not (self.data_dir / rel).exists():
                        self._queue_file(db, rel, row["markdown"])
                for row in db.execute("SELECT * FROM page_revisions").fetchall():
                    rel = self._revision_path(row["page_id"], row["revision"])
                    if not (self.data_dir / rel).exists():
                        self._queue_file(db, rel, row["snapshot"], True)
            self._flush_files()
            # No worker survives a process restart. Never leave an apparent
            # active job forever or silently call an interrupted run successful.
            with self._db() as db:
                db.execute(
                    "UPDATE jobs SET status='failed', error=?, updated_at=?, finished_at=? "
                    "WHERE status IN ('queued','running')",
                    ("上次运行被中断，请重新学习该资料。", _now(), _now()),
                )

    @staticmethod
    def _raw_path(source_id: str, revision: int) -> str:
        return "raw/{}/{:06d}.txt".format(source_id, revision)

    @staticmethod
    def _revision_path(page_id: str, revision: int) -> str:
        return "revisions/{}/{:06d}.json".format(page_id, revision)

    def _safe_path(self, relative: str) -> Path:
        path = self.data_dir / relative
        if not path.resolve().is_relative_to(self.data_dir):
            raise ValueError("文件路径超出了知识库目录。")
        return path

    def _queue_file(self, db, path: str, content: str, immutable: bool = False):
        target = self._safe_path(path)
        expected_hash = _hash(target.read_text(encoding="utf-8")) if target.exists() else ""
        db.execute(
            "INSERT INTO file_outbox(path,content,immutable,expected_hash) VALUES(?,?,?,?) "
            "ON CONFLICT(path) DO UPDATE SET content=excluded.content, immutable=excluded.immutable",
            (path, content, int(immutable), expected_hash),
        )

    def _flush_files(self) -> None:
        with self._db() as db:
            rows = db.execute("SELECT * FROM file_outbox ORDER BY immutable DESC,path").fetchall()
            for row in rows:
                path = self._safe_path(row["path"])
                path.parent.mkdir(parents=True, exist_ok=True)
                if row["immutable"] and path.exists():
                    if path.read_text(encoding="utf-8") != row["content"]:
                        raise ValueError("不可变历史文件与数据库不一致，已保留原文件：{}".format(row["path"]))
                else:
                    if path.exists():
                        current = path.read_text(encoding="utf-8")
                        if current != row["content"] and _hash(current) != row["expected_hash"]:
                            raise ValueError("待恢复页面存在手工修改，已保留文件：{}".format(row["path"]))
                    fd, temporary = tempfile.mkstemp(prefix=".wiki-", dir=str(path.parent))
                    try:
                        with os.fdopen(fd, "w", encoding="utf-8") as stream:
                            stream.write(row["content"])
                            stream.flush()
                            os.fsync(stream.fileno())
                        os.replace(temporary, path)
                    finally:
                        if os.path.exists(temporary):
                            os.unlink(temporary)
                db.execute("DELETE FROM file_outbox WHERE path=?", (row["path"],))

    def _source(self, db, source_id: str) -> Optional[Dict[str, Any]]:
        row = db.execute(
            "SELECT s.*,v.text FROM sources s JOIN source_versions v "
            "ON s.id=v.source_id AND s.revision=v.revision WHERE s.id=?",
            (source_id,),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["path"] = self._raw_path(result["id"], result["revision"])
        return result

    def add_source(self, title: str, text: str, origin: str = "manual", source_id: Optional[str] = None) -> Dict[str, Any]:
        if not isinstance(title, str) or not title.strip():
            raise ValueError("资料标题不能为空。")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("资料正文不能为空。")
        if not isinstance(origin, str):
            raise ValueError("资料来源必须是文本。")
        if len(title) > 300 or len(text) > 2_000_000 or len(origin) > 4096:
            raise ValueError("资料超出长度限制。")
        digest = _hash(text)
        with self._lock:
            self._flush_files()
            with self._db() as db:
                existing = self._source(db, source_id) if source_id else None
                if source_id and existing is None:
                    raise ValueError("要更新的资料不存在。")
                if existing is None:
                    duplicate = db.execute("SELECT id FROM sources WHERE content_hash=? ORDER BY created_at LIMIT 1", (digest,)).fetchone()
                    if duplicate:
                        result = self._source(db, duplicate["id"])
                        return dict(result, deduplicated=True, updated=False)
                if existing and all((existing["content_hash"] == digest, existing["title"] == title.strip(), existing["origin"] == origin)):
                    return dict(existing, deduplicated=True, updated=False)
                stamp = _now()
                if existing:
                    revision = existing["revision"] + 1
                    db.execute("UPDATE sources SET title=?,origin=?,content_hash=?,revision=?,updated_at=? WHERE id=?", (title.strip(), origin, digest, revision, stamp, source_id))
                else:
                    source_id = "src_" + digest[:24]
                    # A source can have moved away from its original content.
                    if db.execute("SELECT 1 FROM sources WHERE id=?", (source_id,)).fetchone():
                        source_id = "src_" + uuid.uuid4().hex[:24]
                    revision = 1
                    db.execute("INSERT INTO sources VALUES(?,?,?,?,?,?,?)", (source_id, title.strip(), origin, digest, revision, stamp, stamp))
                db.execute("INSERT INTO source_versions VALUES(?,?,?,?,?,?,?)", (source_id, revision, title.strip(), origin, digest, text, stamp))
                self._queue_file(db, self._raw_path(source_id, revision), text, True)
                result = self._source(db, source_id)
            self._flush_files()
            return dict(result, deduplicated=False, updated=existing is not None)

    def list_sources(self) -> List[Dict[str, Any]]:
        with self._db() as db:
            ids = db.execute("SELECT id FROM sources ORDER BY updated_at DESC,id").fetchall()
            return [self._source(db, row["id"]) for row in ids]

    def get_source(self, source_id: str, revision: Optional[int] = None) -> Optional[Dict[str, Any]]:
        with self._db() as db:
            if revision is None:
                return self._source(db, source_id)
            row = db.execute("SELECT * FROM source_versions WHERE source_id=? AND revision=?", (source_id, revision)).fetchone()
            if row is None:
                return None
            result = dict(row)
            result["id"] = result.pop("source_id")
            result["updated_at"] = result["created_at"]
            result["path"] = self._raw_path(source_id, revision)
            return result

    @staticmethod
    def _job(row) -> Optional[Dict[str, Any]]:
        if row is None:
            return None
        result = dict(row)
        for key in ("result", "page_ids"):
            result[key] = json.loads(result[key])
        return result

    def create_job(self, source_id: str) -> Dict[str, Any]:
        with self._lock, self._db() as db:
            source = self._source(db, source_id)
            if source is None:
                raise ValueError("资料不存在。")
            job_id = "job_" + uuid.uuid4().hex
            stamp = _now()
            db.execute("INSERT INTO jobs(id,source_id,source_revision,status,created_at,updated_at) VALUES(?,?,?,'queued',?,?)", (job_id, source_id, source["revision"], stamp, stamp))
            return self._job(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def update_job(self, job_id: str, **fields) -> Dict[str, Any]:
        allowed = {"status", "model", "error", "result", "page_ids", "started_at", "finished_at"}
        if not set(fields).issubset(allowed):
            raise ValueError("不支持的任务字段。")
        if "status" in fields and fields["status"] not in _STATUSES:
            raise ValueError("不支持的任务状态。")
        with self._lock, self._db() as db:
            current = self._job(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
            if current is None:
                raise ValueError("学习任务不存在。")
            if fields.get("status") == "running" and not current["started_at"]:
                fields.setdefault("started_at", _now())
            if fields.get("status") in {"succeeded", "failed"}:
                fields.setdefault("finished_at", _now())
            fields["updated_at"] = _now()
            encoded = {k: _json(v) if k in {"result", "page_ids"} else v for k, v in fields.items()}
            columns = ",".join("{}=?".format(k) for k in encoded)
            db.execute("UPDATE jobs SET {} WHERE id=?".format(columns), tuple(encoded.values()) + (job_id,))
            return self._job(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def list_jobs(self) -> List[Dict[str, Any]]:
        with self._db() as db:
            return [self._job(row) for row in db.execute("SELECT * FROM jobs ORDER BY created_at DESC,id LIMIT 200").fetchall()]

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._db() as db:
            return self._job(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def find_source_job(self, source_id: str, revision: int, statuses=None) -> Optional[Dict[str, Any]]:
        states = list(statuses or _STATUSES)
        if not states or not set(states).issubset(_STATUSES):
            raise ValueError("不支持的任务状态。")
        with self._db() as db:
            sql = "SELECT * FROM jobs WHERE source_id=? AND source_revision=? AND status IN ({}) ORDER BY created_at DESC,id DESC LIMIT 1".format(",".join("?" for _ in states))
            return self._job(db.execute(sql, (source_id, revision, *states)).fetchone())

    def _page(self, row) -> Optional[Dict[str, Any]]:
        if row is None:
            return None
        result = dict(row)
        result["source_ids"] = json.loads(result["source_ids"])
        result["sources"] = json.loads(result["sources"])
        result["slug"] = result["id"]
        result["path"] = "wiki/{}.md".format(result["id"])
        result["content_hash"] = _hash(result["body"])
        return result

    @staticmethod
    def _markdown(title: str, body: str, sources: List[Dict[str, Any]]) -> str:
        clean_title = title.replace("\n", " ").replace("\r", " ")
        lines = ["# " + clean_title, "", body.rstrip(), "", "---", "", "## 来源", ""]
        for source in sources:
            label = source["title"].replace("\n", " ").replace("[", "\\[").replace("]", "\\]")
            lines.append("- [{}](../{}) — `{}` · 版本 {}".format(label, source["path"], source["id"], source["revision"]))
        return "\n".join(lines) + "\n"

    def _check_manual_edit(self, page: Optional[Dict[str, Any]]) -> None:
        if page:
            path = self._safe_path(page["path"])
            if path.exists() and path.read_text(encoding="utf-8") != page["markdown"]:
                raise ValueError("页面 {} 存在手工修改，已保留文件；请先核对后再更新。".format(page["id"]))

    def _save_page(self, db, page: Dict[str, Any]) -> None:
        db.execute(
            "INSERT INTO pages VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
            "title=excluded.title,body=excluded.body,markdown=excluded.markdown,source_ids=excluded.source_ids,"
            "sources=excluded.sources,revision=excluded.revision,model=excluded.model,updated_at=excluded.updated_at",
            (page["id"], page["title"], page["body"], page["markdown"], _json(page["source_ids"]), _json(page["sources"]), page["revision"], page["model"], page["created_at"], page["updated_at"]),
        )
        stored = self._page(db.execute("SELECT * FROM pages WHERE id=?", (page["id"],)).fetchone())
        snapshot = _json(stored)
        db.execute("INSERT INTO page_revisions VALUES(?,?,?)", (page["id"], page["revision"], snapshot))
        self._queue_file(db, "wiki/{}.md".format(page["id"]), page["markdown"])
        self._queue_file(db, self._revision_path(page["id"], page["revision"]), snapshot, True)

    def apply_learning(self, job_id: str, source_id: str, payload: Dict[str, Any], model: str, expected_revisions: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
        with self._lock:
            job = self.get_job(job_id)
            if job is None:
                raise ValueError("学习任务不存在。")
            if job["status"] == "succeeded":
                if job["source_id"] != source_id:
                    raise ValueError("学习任务与资料不匹配。")
                return {"job": job, "pages": [self.get_page(i) for i in job["page_ids"]]}
            try:
                self._flush_files()
                if not isinstance(model, str) or not model.strip():
                    raise ValueError("未提供真实模型信息，不能发布学习结果。")
                if not isinstance(payload, dict) or not isinstance(payload.get("pages"), list) or not 1 <= len(payload["pages"]) <= 12:
                    raise ValueError("模型必须返回包含 1–12 个页面的 pages 列表。")
                if expected_revisions is not None and (
                    not isinstance(expected_revisions, dict)
                    or any(not isinstance(key, str) or not isinstance(value, int) or isinstance(value, bool) or value < 1 for key, value in expected_revisions.items())
                ):
                    raise ValueError("预期页面版本必须是页面 ID 到正整数版本的映射。")
                with self._db() as db:
                    # Hold a write transaction across version checks and writes
                    # so another connection cannot restore or update a page in
                    # between the optimistic check and publication.
                    db.execute("BEGIN IMMEDIATE")
                    source = self._source(db, source_id)
                    if source is None or job["source_id"] != source_id:
                        raise ValueError("学习任务与资料不匹配。")
                    if source["revision"] != job["source_revision"]:
                        raise ValueError("资料在学习过程中已更新，请针对新版本重新学习。")
                    seen = set()
                    page_ids = []
                    stamp = _now()
                    for candidate in payload["pages"]:
                        if not isinstance(candidate, dict):
                            raise ValueError("模型返回了无效的页面对象。")
                        slug = _slug(candidate.get("slug"))
                        if slug in seen:
                            raise ValueError("一次学习不能包含重复的页面 slug。")
                        seen.add(slug)
                        title, body = candidate.get("title"), candidate.get("body")
                        if not isinstance(title, str) or not title.strip() or len(title) > 300:
                            raise ValueError("页面标题无效。")
                        if not isinstance(body, str) or not body.strip() or len(body) > 150_000:
                            raise ValueError("页面正文无效。")
                        supplied = candidate.get("source_ids", [])
                        if not isinstance(supplied, list) or any(not isinstance(s, str) for s in supplied):
                            raise ValueError("页面 source_ids 必须是资料 ID 列表。")
                        existing = self._page(db.execute("SELECT * FROM pages WHERE id=?", (slug,)).fetchone())
                        if expected_revisions is not None:
                            expected = expected_revisions.get(slug)
                            actual = existing["revision"] if existing else None
                            if expected != actual:
                                raise ValueError("页面 {} 在学习过程中已发生变更或未被本次读取，请重新学习。".format(slug))
                        self._check_manual_edit(existing)
                        refs = {ref["id"]: ref for ref in (existing["sources"] if existing else [])}
                        for sid in dict.fromkeys(supplied + [source_id]):
                            cited = self._source(db, sid)
                            if cited is None:
                                raise ValueError("模型引用了不存在的资料：{}".format(sid))
                            # Only the active source was freshly read. Preserve
                            # older supporting references until they are learned
                            # again, even if the model repeats their source IDs.
                            if sid in refs and sid != source_id:
                                continue
                            refs[sid] = {key: cited[key] for key in ("id", "title", "origin", "revision", "content_hash", "path")}
                        sources = list(refs.values())
                        page = {
                            "id": slug, "title": title.strip(), "body": body.strip(),
                            "source_ids": list(refs), "sources": sources,
                            "revision": existing["revision"] + 1 if existing else 1,
                            "model": model.strip(), "created_at": existing["created_at"] if existing else stamp,
                            "updated_at": stamp,
                        }
                        page["markdown"] = self._markdown(page["title"], page["body"], sources)
                        self._save_page(db, page)
                        page_ids.append(slug)
                    db.execute("UPDATE jobs SET status='running',model=?,result=?,page_ids=?,updated_at=? WHERE id=?", (model.strip(), _json({"publication": "pending"}), _json(page_ids), stamp, job_id))
                self._flush_files()
                complete = self.update_job(job_id, status="succeeded", model=model.strip(), error="", result={"page_count": len(page_ids), "publication": "complete"}, page_ids=page_ids)
                return {"job": complete, "pages": [self.get_page(slug) for slug in page_ids]}
            except Exception as exc:
                self.update_job(job_id, status="failed", error=str(exc))
                raise

    def list_pages(self, query: str = "") -> List[Dict[str, Any]]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM pages ORDER BY updated_at DESC,id").fetchall()
            if query:
                needle = query.casefold()
                rows = [row for row in rows if needle in (row["title"] + "\n" + row["body"]).casefold()]
            return [self._page(row) for row in rows]

    def get_page(self, page_id: str) -> Optional[Dict[str, Any]]:
        with self._db() as db:
            return self._page(db.execute("SELECT * FROM pages WHERE id=?", (page_id,)).fetchone())

    def list_revisions(self, page_id: str) -> List[Dict[str, Any]]:
        with self._db() as db:
            return [json.loads(row["snapshot"]) for row in db.execute("SELECT snapshot FROM page_revisions WHERE page_id=? ORDER BY revision DESC", (page_id,)).fetchall()]

    def get_revision(self, page_id: str, revision: int) -> Optional[Dict[str, Any]]:
        with self._db() as db:
            row = db.execute("SELECT snapshot FROM page_revisions WHERE page_id=? AND revision=?", (page_id, revision)).fetchone()
            return json.loads(row["snapshot"]) if row else None

    def restore_page(self, page_id: str, revision: int) -> Dict[str, Any]:
        _slug(page_id)
        with self._lock:
            self._flush_files()
            with self._db() as db:
                row = db.execute("SELECT snapshot FROM page_revisions WHERE page_id=? AND revision=?", (page_id, revision)).fetchone()
                current = self._page(db.execute("SELECT * FROM pages WHERE id=?", (page_id,)).fetchone())
                if row is None or current is None:
                    raise ValueError("页面或历史版本不存在。")
                self._check_manual_edit(current)
                restored = json.loads(row["snapshot"])
                restored["revision"] = current["revision"] + 1
                restored["created_at"] = current["created_at"]
                restored["updated_at"] = _now()
                restored["model"] = "restore:{}".format(revision)
                self._save_page(db, restored)
            self._flush_files()
        return self.get_page(page_id)

    def search(self, query: str, limit: int = 6) -> List[Dict[str, Any]]:
        if not isinstance(query, str) or not query.strip():
            return []
        needle = query.strip().casefold()
        tokens = re.findall(r"[a-z0-9_-]+|[\u3400-\u9fff]+", needle)
        # Chinese questions can be longer than a stored phrase. Bigrams provide
        # a deliberately simple local fallback; this is not vector retrieval.
        terms = set(tokens)
        for token in tokens:
            if re.fullmatch(r"[\u3400-\u9fff]+", token) and len(token) > 2:
                terms.update(token[i:i + 2] for i in range(len(token) - 1))
        results = []
        for page in self.list_pages():
            title, body = page["title"].casefold(), page["body"].casefold()
            score = (15 if needle in title else 0) + (8 if needle in body else 0)
            score += sum((4 if term in title else 0) + min(body.count(term), 3) for term in terms)
            if not score:
                continue
            positions = [body.find(t) for t in terms if t in body]
            start = max(0, min(positions) - 60) if positions else 0
            results.append({"id": page["id"], "page_id": page["id"], "title": page["title"], "excerpt": page["body"][start:start + 700], "score": score, "source_ids": page["source_ids"]})
        return sorted(results, key=lambda p: (-p["score"], p["id"]))[:max(1, min(int(limit), 50))]

    def log_chat(self, role: str, content: str, citations: Optional[List[Any]] = None) -> Dict[str, Any]:
        if role not in {"user", "assistant", "system"}:
            raise ValueError("不支持的聊天角色。")
        if not isinstance(content, str):
            raise ValueError("聊天内容必须是文本。")
        if citations is not None and not isinstance(citations, list):
            raise ValueError("引用必须是列表。")
        stamp = _now()
        with self._lock, self._db() as db:
            cursor = db.execute("INSERT INTO chat(role,content,citations,created_at) VALUES(?,?,?,?)", (role, content, _json(citations or []), stamp))
            return {"id": cursor.lastrowid, "role": role, "content": content, "citations": citations or [], "created_at": stamp}

    def list_chat(self) -> List[Dict[str, Any]]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM (SELECT * FROM chat ORDER BY id DESC LIMIT 200) ORDER BY id").fetchall()
            return [dict(dict(row), citations=json.loads(row["citations"])) for row in rows]

    def lint(self) -> Dict[str, Any]:
        issues = []
        pages = self.list_pages()
        page_ids = {page["id"] for page in pages}
        sources = {source["id"]: source for source in self.list_sources()}
        with self._db() as db:
            versions = db.execute("SELECT * FROM source_versions").fetchall()
            revisions = db.execute("SELECT * FROM page_revisions").fetchall()
            pending = db.execute("SELECT path FROM file_outbox").fetchall()
        for row in versions:
            rel = self._raw_path(row["source_id"], row["revision"])
            path = self._safe_path(rel)
            if not path.exists():
                issues.append({"kind": "missing_source_file", "source_id": row["source_id"], "message": "原始资料文件缺失：" + rel})
            elif _hash(path.read_text(encoding="utf-8")) != row["content_hash"]:
                issues.append({"kind": "modified_source_file", "source_id": row["source_id"], "message": "原始资料文件被修改：" + rel})
        for page in pages:
            path = self._safe_path(page["path"])
            if not path.exists():
                issues.append({"kind": "missing_page_file", "page_id": page["id"], "message": "页面文件缺失。"})
            elif path.read_text(encoding="utf-8") != page["markdown"]:
                issues.append({"kind": "manual_page_edit", "page_id": page["id"], "message": "页面文件与数据库不一致；手工修改已保留。"})
            if not page["sources"]:
                issues.append({"kind": "missing_citation", "page_id": page["id"], "message": "页面缺少来源。"})
            for ref in page["sources"]:
                source = sources.get(ref["id"])
                if source is None:
                    issues.append({"kind": "invalid_source", "page_id": page["id"], "message": "引用的资料不存在：" + ref["id"]})
                elif source["revision"] != ref["revision"]:
                    issues.append({"kind": "stale_source", "page_id": page["id"], "source_id": ref["id"], "message": "引用资料已有新版本，页面需要重新核验。"})
            links = re.findall(r"\[\[([^\]|#]+)(?:[^\]]*)\]\]", page["body"])
            links += re.findall(r"\]\((?:\./)?([a-z0-9][a-z0-9_-]{0,79})\.md(?:#[^)]*)?\)", page["body"])
            for target in set(links):
                if target not in page_ids:
                    issues.append({"kind": "broken_link", "page_id": page["id"], "target": target, "message": "关联页面不存在：" + target})
        for row in revisions:
            rel = self._revision_path(row["page_id"], row["revision"])
            path = self._safe_path(rel)
            if not path.exists():
                issues.append({"kind": "missing_revision_file", "page_id": row["page_id"], "message": "历史快照缺失：" + rel})
            elif path.read_text(encoding="utf-8") != row["snapshot"]:
                issues.append({"kind": "modified_revision_file", "page_id": row["page_id"], "message": "历史快照被修改：" + rel})
        for row in pending:
            issues.append({"kind": "pending_file_write", "message": "待恢复文件写入：" + row["path"]})
        return {"ok": not issues, "issues": issues, "stats": {"sources": len(sources), "pages": len(pages), "revisions": len(revisions), "pending_writes": len(pending)}}
