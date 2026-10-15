"""Versioned official Vite template snapshots for scoped frontend Agents.

Only registry/repository metadata and files are fetched. No upstream script is
executed, and downloaded source bytes are never passed through HTML extraction.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import http.client
import json
import os
from pathlib import PurePosixPath
import re
import shutil
import stat
import time
from urllib.parse import quote, urljoin, urlsplit, urlunsplit
import uuid

from .core import _write_json
from .web_learning import (SafeFetcher, canonical_url, MAX_REDIRECTS, FETCH_TIMEOUT, USER_AGENT,
                           _resolve_public, _PinnedHTTPSConnection)

REPOSITORY = "vitejs/vite"
CATALOG = {
    "vue-ts": {"framework": "vue", "path": "packages/create-vite/template-vue-ts",
               "guide_url": "https://vuejs.org/guide/quick-start.html"},
    "react-ts": {"framework": "react", "path": "packages/create-vite/template-react-ts",
                 "guide_url": "https://react.dev/learn/build-a-react-app-from-scratch"},
}
MAX_FILES = 80
MAX_FILE_BYTES = 1_000_000
MAX_TEMPLATE_BYTES = 4_000_000
TRUSTED_HOSTS = {"registry.npmjs.org", "api.github.com", "raw.githubusercontent.com"}
JSON_TYPES = {"application/json", "application/vnd.github+json"}
SOURCE_TYPES = {"text/plain", "text/html", "application/json", "application/javascript",
                "text/javascript", "text/css", "image/svg+xml", "image/png", "image/jpeg",
                "image/webp", "image/x-icon", "application/octet-stream"}


class TemplateError(ValueError):
    code = "template_error"


class TemplateConflict(TemplateError):
    code = "template_conflict"


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat()


def match_frameworks(text):
    """Bounded, explicit keyword routing; not a claim of semantic parsing."""
    if not isinstance(text, str):
        return []
    pattern = re.compile(r"(?<![A-Za-z0-9_])(?P<name>react(?:\.?js)?|vue(?:\.?js)?)(?![A-Za-z_])", re.I)
    choices = {}
    for match in pattern.finditer(text):
        framework = "react" if match.group("name").lower().startswith("react") else "vue"
        suffix = text[match.end():]
        if framework == "react" and re.match(r"[\s_-]*native\b", suffix, re.I):
            continue
        prefix = text[max(0, match.start() - 30):match.start()]
        excluded = bool(re.search(r"(?:不要(?:用|使用)?|不是|不用|不使用|不采用|无需|排除|without|except|not)\s*$", prefix, re.I))
        choices[framework] = (not excluded, match.start())
    return [name for name, _ in sorted(choices.items(), key=lambda item: item[1][1]) if choices[name][0]]


def supports_templates(store, space):
    try:
        current = store._definition(space)
        seen = set()
        while current:
            if current["id"] == "software-frontend":
                return True
            if current["id"] in seen or not current.get("parent_id"):
                return False
            seen.add(current["id"])
            current = store._definition(current["parent_id"])
    except (ValueError, KeyError, TypeError):
        return False
    return False


supports_framework_templates = supports_templates


def _root(store, space):
    if not supports_templates(store, space):
        raise TemplateError("框架模板仅属于前端 Agent 及其子分支，不能跨知识库读取或同步")
    return store._safe(store._home(space), "templates")


def _identifier(value):
    if not isinstance(value, str) or value not in CATALOG:
        raise TemplateError("只支持官方 vue-ts 和 react-ts 模板")
    return value


def _ids(frameworks):
    if frameworks is None:
        return list(CATALOG)
    if not isinstance(frameworks, (list, tuple)) or not 1 <= len(frameworks) <= 2:
        raise TemplateError("框架列表只能包含 vue 和 react")
    result = []
    for framework in frameworks:
        if not isinstance(framework, str):
            raise TemplateError("框架标识无效")
        identifier = framework.lower().strip()
        if identifier in {"vue", "react"}:
            identifier += "-ts"
        _identifier(identifier)
        if identifier not in result:
            result.append(identifier)
    return result


def _relative(path):
    if (not isinstance(path, str) or not path or len(path) > 300 or "\\" in path
            or re.search(r"[\x00-\x1f\x7f]", path)):
        raise TemplateError("上游文件路径无效")
    pure = PurePosixPath(path)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in path.split("/")):
        raise TemplateError("上游文件路径越界")
    return path


class _OfficialFetcher(SafeFetcher):
    """Reuse pinned DNS/TLS/robots transport, with a narrow artifact MIME policy."""
    def _request(self, url, limit=MAX_FILE_BYTES):
        # GitHub's JSON API rejects unrelated Accept headers. Keep the existing
        # fixed-IP/TLS transport and size limits while using artifact headers.
        url = canonical_url(url)
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname not in TRUSTED_HOSTS or parsed.port not in {None, 443}:
            raise TemplateError("模板只允许从固定官方 HTTPS 主机读取")
        family, address = _resolve_public(parsed.hostname, 443)
        connection = _PinnedHTTPSConnection(parsed.hostname, 443, address, family, FETCH_TIMEOUT)
        accept = "application/vnd.github+json" if parsed.hostname == "api.github.com" else "application/json" if parsed.hostname == "registry.npmjs.org" else "*/*"
        started = time.monotonic()
        try:
            target = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
            connection.request("GET", target, headers={"User-Agent": USER_AGENT, "Accept": accept,
                "Accept-Encoding": "identity", "Connection": "close"})
            response = connection.getresponse()
            headers = {key.lower(): value for key, value in response.getheaders()}
            if headers.get("content-encoding", "identity").lower() not in {"", "identity"}:
                raise TemplateError("模板源返回压缩内容，已停止本轮受限下载")
            if headers.get("content-length") and int(headers["content-length"]) > limit:
                raise TemplateError("模板源文件超过下载大小上限")
            total, chunks = 0, []
            while True:
                if time.monotonic() - started > FETCH_TIMEOUT:
                    raise TemplateError("模板源文件读取超时")
                chunk = response.read(min(65536, limit - total + 1))
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise TemplateError("模板源文件超过下载大小上限")
                chunks.append(chunk)
            return {"url": url, "status": response.status, "headers": headers, "body": b"".join(chunks)}
        except (OSError, http.client.HTTPException) as exc:
            raise TemplateError("模板源连接失败：" + type(exc).__name__) from None
        finally:
            connection.close()

    def artifact(self, url, allowed_types):
        seen = set()
        for _ in range(MAX_REDIRECTS + 1):
            url = canonical_url(url)
            parsed = urlsplit(url)
            if parsed.scheme != "https" or parsed.hostname not in TRUSTED_HOSTS or parsed.port not in {None, 443}:
                raise TemplateError("模板只允许从固定官方 HTTPS 主机读取")
            if url in seen:
                raise TemplateError("模板来源重定向循环")
            seen.add(url)
            self._robots(url)
            response = self._request(url, MAX_FILE_BYTES)
            if response["status"] in {301, 302, 303, 307, 308}:
                target = response["headers"].get("location")
                if not target:
                    raise TemplateError("模板来源重定向没有目标")
                url = urljoin(url, target)
                continue
            if response["status"] != 200:
                raise TemplateError("官方模板来源读取失败（HTTP " + str(response["status"]) + "）")
            mime = response["headers"].get("content-type", "").split(";", 1)[0].strip().lower()
            if mime not in allowed_types:
                raise TemplateError("官方来源返回了非预期文件类型：" + mime)
            return response["body"]
        raise TemplateError("模板来源重定向次数超过上限")

    def json(self, url):
        try:
            return json.loads(self.artifact(url, JSON_TYPES))
        except (ValueError, UnicodeError) as exc:
            if isinstance(exc, TemplateError):
                raise
            raise TemplateError("官方元数据不是有效 JSON") from None


def _api(path):
    return "https://api.github.com/repos/" + REPOSITORY + "/" + path


def _raw(commit, path):
    return "https://raw.githubusercontent.com/" + REPOSITORY + "/" + commit + "/" + quote(path, safe="/")


def _git_blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def _release(client):
    metadata = client.json("https://registry.npmjs.org/create-vite/latest")
    version = metadata.get("version") if isinstance(metadata, dict) else None
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise TemplateError("create-vite latest 不是可确认的稳定版本")
    repository = metadata.get("repository", {})
    if (metadata.get("name") != "create-vite" or metadata.get("license") != "MIT"
            or not isinstance(repository, dict)
            or repository.get("url") not in {"git+https://github.com/vitejs/vite.git", "https://github.com/vitejs/vite.git"}
            or repository.get("directory") != "packages/create-vite"):
        raise TemplateError("create-vite 版本的仓库或许可证与固定官方来源不一致")
    tag = "create-vite@" + version
    commit_data = client.json(_api("commits/" + quote(tag, safe="")))
    commit = commit_data.get("sha") if isinstance(commit_data, dict) else None
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise TemplateError("稳定版本标签未解析成固定提交，不回退 main")
    directory = client.json(_api("contents/packages/create-vite?ref=" + commit))
    if not isinstance(directory, list):
        raise TemplateError("create-vite 目录元数据不完整")
    trees = {}
    for identifier, config in CATALOG.items():
        matches = [item for item in directory if isinstance(item, dict) and item.get("path") == config["path"]]
        if len(matches) == 1 and matches[0].get("type") == "dir" and re.fullmatch(r"[0-9a-f]{40}", str(matches[0].get("sha", ""))):
            trees[identifier] = matches[0]["sha"]
    license_body = client.artifact(_raw(commit, "LICENSE"), SOURCE_TYPES)
    if not license_body.decode("utf-8").startswith("MIT License"):
        raise TemplateError("固定提交的根许可证不是已支持的 MIT 许可证")
    source_package = json.loads(client.artifact(_raw(commit, "packages/create-vite/package.json"), SOURCE_TYPES))
    if source_package.get("name") != "create-vite" or source_package.get("version") != version:
        raise TemplateError("标签内的 create-vite 版本与稳定发布元数据不一致")
    return {"version": version, "commit": commit, "ref": tag, "trees": trees,
            "license": license_body, "node": source_package.get("engines", {}).get("node", "未声明"),
            "fetched_at": _now()}


def _guidelines(identifier, package, release):
    framework = CATALOG[identifier]["framework"]
    style = ("Vue 使用当前模板的单文件组件与 Composition API；组件采用 <script setup lang=\"ts\"> 风格。保留项目已有的样式组织方式。"
             if framework == "vue" else
             "React 使用 TypeScript 函数组件和 Hooks；组件入口与状态管理遵循当前源码及已有项目约定，不移植 Vue 的单文件组件规范。")
    scripts = package.get("scripts", {})
    if not isinstance(scripts, dict) or len(scripts) > 20 or any(not isinstance(k, str) or not isinstance(v, str) for k, v in scripts.items()):
        raise TemplateError("上游 package.json scripts 格式无效")
    text = f"""# {framework.title()} + TypeScript 模板使用约定

这份 GUIDELINES.md 是本地 Agent 的默认使用约定，由同步器根据官方模板元数据生成；它不是框架官方的完整业务工程规范。template/ 内文件来自 Vite 的 create-vite {release['version']}，固定提交 `{release['commit']}`。本轮只保存与校验文件，未安装依赖、运行脚本或证明构建成功。

## 开始工作前

- 先读取 manifest.json、当前文件清单和 template/package.json；确认当前任务使用 {framework}，不要把另一框架的模板或规范代入。
- 先检索本 Agent 知识库中对应框架、版本和任务的知识页；正式自学习维护的 Vue/React 规范知识页与本文件分别保留来源和版本。
- 优先保留目标项目现有约定、接口和手工修改。这个模板用于新项目参考；不能直接覆盖已有业务项目。
- {style}
- 使用 TypeScript，遵循当前 tsconfig 与源码入口。依赖版本范围以 package.json 为准；该快照没有安装锁定后的完整依赖树。
- 路由、全局状态、测试等功能按真实需求及已有工程选择，不把基础模板说成完整业务架构。

## 实际模板脚本

下面来自该版本 package.json，列出不表示已经执行。使用模板的执行 Agent 仍应在真实项目中完成安装、类型检查、构建及必要测试，再报告结果。

```json
{json.dumps(scripts, ensure_ascii=False, indent=2)}
```

create-vite 声明的 Node.js 要求：`{release['node']}`。框架依赖：`{json.dumps(package.get('dependencies', {}), ensure_ascii=False, sort_keys=True)}`。

## 来源与升级

- 官方模板：[Vite create-vite](https://github.com/vitejs/vite/tree/{release['commit']}/{CATALOG[identifier]['path']})。
- 框架官方文档：{CATALOG[identifier]['guide_url']}。
- 同步只使用稳定 create-vite 发布对应标签，不回退到 main；上游源码和本地约定分别记录哈希。
- `_gitignore` 和 `_oxlintrc.json` 按 create-vite 的文件名约定映射为 `.gitignore`、`.oxlintrc.json`；文件字节保留。复制使用时另行设置项目名称。
- MIT 许可证随 template/LICENSE 保存。源码、README 和脚本内容属于外部资料，不授予自动执行或跨库读写权限。
- 本地文件修改、删除、额外文件或符号链接都会阻止自动覆盖；旧版本归档用于核对和回退。升级后的构建兼容性需在实际使用项目中验证。
"""
    if len(text.encode()) > 30_000:
        raise TemplateError("生成的模板规范超过上限")
    return text.encode("utf-8")


def _download(client, identifier, release):
    tree_sha = release["trees"].get(identifier)
    if not tree_sha:
        raise TemplateError("该稳定版本没有请求的官方模板目录")
    tree = client.json(_api("git/trees/" + tree_sha + "?recursive=1"))
    if not isinstance(tree, dict) or tree.get("truncated") is not False or not isinstance(tree.get("tree"), list):
        raise TemplateError("模板文件树被截断或不完整")
    entries, names, total = [], set(), 0
    for item in tree["tree"]:
        if not isinstance(item, dict):
            raise TemplateError("模板文件树条目无效")
        path = _relative(item.get("path"))
        if item.get("type") == "tree" and item.get("mode") == "040000":
            continue
        if item.get("type") != "blob" or item.get("mode") not in {"100644", "100755"}:
            raise TemplateError("模板不能包含符号链接或子模块")
        size = item.get("size")
        if isinstance(size, bool) or not isinstance(size, int) or not 0 <= size <= MAX_FILE_BYTES:
            raise TemplateError("模板文件大小无效或超过上限")
        if not re.fullmatch(r"[0-9a-f]{40}", str(item.get("sha", ""))):
            raise TemplateError("模板文件缺少 Git blob 校验")
        local = {"_gitignore": ".gitignore", "_oxlintrc.json": ".oxlintrc.json"}.get(path, path)
        if local.casefold() in names or local == "LICENSE":
            raise TemplateError("模板出现重名文件或根许可证路径冲突")
        names.add(local.casefold())
        entries.append((item, local))
        total += size
    if not entries or len(entries) > MAX_FILES or total > MAX_TEMPLATE_BYTES:
        raise TemplateError("模板文件数量或总大小超过上限")
    files, evidence = {}, {}
    for item, local in entries:
        upstream_path = CATALOG[identifier]["path"] + "/" + item["path"]
        url = _raw(release["commit"], upstream_path)
        body = client.artifact(url, SOURCE_TYPES)
        if len(body) != item["size"] or _git_blob(body) != item["sha"]:
            raise TemplateError("上游模板正文与固定 Git blob 不一致：" + item["path"])
        name = "template/" + local
        files[name] = body
        evidence[name] = {"upstream_path": upstream_path, "git_blob_sha": item["sha"], "sha256": _sha(body), "url": url}
    try:
        package = json.loads(files["template/package.json"])
    except (KeyError, ValueError, UnicodeError):
        raise TemplateError("模板缺少可读取的 package.json") from None
    if not isinstance(package, dict):
        raise TemplateError("模板 package.json 必须是对象")
    for required in ("template/index.html", "template/vite.config.ts", "template/src/main.ts" if identifier == "vue-ts" else "template/src/main.tsx"):
        if required not in files:
            raise TemplateError("模板缺少预期的 TypeScript 源码入口：" + required)
    files["template/LICENSE"] = release["license"]
    evidence["template/LICENSE"] = {"upstream_path": "LICENSE", "sha256": _sha(release["license"]), "url": _raw(release["commit"], "LICENSE")}
    files["GUIDELINES.md"] = _guidelines(identifier, package, release)
    manifest = {"schema_version": 1, "id": identifier, "framework": CATALOG[identifier]["framework"],
        "source_version": release["version"], "upstream_commit": release["commit"], "upstream_ref": release["ref"],
        "source_url": "https://github.com/" + REPOSITORY + "/tree/" + release["commit"] + "/" + CATALOG[identifier]["path"],
        "upstream_repository": REPOSITORY, "upstream_license": "MIT", "license_url": _raw(release["commit"], "LICENSE"),
        "framework_documentation": CATALOG[identifier]["guide_url"], "created_at": _now(),
        "files": {name: _sha(data) for name, data in sorted(files.items())}, "source_files": evidence,
        "guidelines_origin": "local agent conventions generated from official template metadata",
        "framework_dependencies": package.get("dependencies", {}), "scripts": package.get("scripts", {}),
        "node_requirement": release["node"], "execution_status": "not-run", "status": "ready"}
    return manifest, files


@contextmanager
def _lock(store, root, create=False, shared=False):
    if not root.exists() and not create:
        yield
        return
    if create:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = store._safe(root, ".sync.lock")
    if not path.exists() and not create:
        yield
        return
    fd = os.open(path, (os.O_RDWR | os.O_CREAT if create else os.O_RDONLY) | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _registry(store, root):
    path = store._safe(root, ".framework-registry.json")
    if not path.exists():
        return {}
    if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        raise TemplateConflict("模板登记文件不是受支持的普通文件")
    try:
        registry = json.loads(path.read_text("utf-8"))
    except (ValueError, UnicodeError):
        raise TemplateConflict("模板登记文件损坏，已保留现有文件") from None
    if not isinstance(registry, dict):
        raise TemplateConflict("模板登记内容无效")
    return registry


def _validate(store, root, identifier, registry):
    folder = store._safe(root, identifier)
    if not folder.is_dir():
        raise TemplateConflict("受管模板目录缺失或被删除：" + identifier)
    record = registry.get(identifier)
    manifest_path = store._safe(folder, "manifest.json")
    if not isinstance(record, dict) or not manifest_path.is_file():
        raise TemplateConflict("已有模板目录未经登记，拒绝覆盖：" + identifier)
    raw = manifest_path.read_bytes()
    if len(raw) > MAX_FILE_BYTES or _sha(raw) != record.get("manifest_sha256"):
        raise TemplateConflict("模板 manifest.json 已被修改或损坏：" + identifier)
    manifest = json.loads(raw)
    if (not isinstance(manifest, dict) or manifest.get("id") != identifier
            or manifest.get("framework") != CATALOG[identifier]["framework"]
            or not isinstance(manifest.get("files"), dict)):
        raise TemplateConflict("模板清单与受管模板身份不一致")
    expected = manifest["files"]
    if "GUIDELINES.md" not in expected or not expected or len(expected) > MAX_FILES + 2:
        raise TemplateConflict("模板清单缺少规范文件或超过文件数上限")
    expected_dirs = set()
    for name, checksum in expected.items():
        _relative(name)
        if name != "GUIDELINES.md" and not name.startswith("template/"):
            raise TemplateConflict("模板清单文件不在允许目录内")
        if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise TemplateConflict("模板清单哈希无效")
        parent = PurePosixPath(name).parent
        while str(parent) != ".":
            expected_dirs.add(str(parent))
            parent = parent.parent
    actual = set()
    for parent, dirs, files in os.walk(folder, followlinks=False):
        for name in dirs:
            path = store._safe(folder, str(PurePosixPath(os.path.relpath(parent, folder)) / name))
            if not path.is_dir() or path.relative_to(folder).as_posix() not in expected_dirs:
                raise TemplateConflict("模板含额外目录或符号链接，拒绝覆盖")
        for name in files:
            relative = os.path.relpath(os.path.join(parent, name), folder).replace(os.sep, "/")
            path = store._safe(folder, relative)
            if not stat.S_ISREG(path.lstat().st_mode):
                raise TemplateConflict("模板含非普通文件，拒绝读取或覆盖")
            if relative == "manifest.json":
                continue
            actual.add(relative)
            if relative not in expected or _sha(path.read_bytes()) != expected[relative]:
                raise TemplateConflict("模板文件被修改或增加：" + relative)
    if actual != set(expected):
        missing = sorted(set(expected) - actual)
        raise TemplateConflict("模板文件被删除：" + ", ".join(missing[:5]))
    return manifest


def validate_template(store, space, identifier):
    _identifier(identifier)
    root = _root(store, space)
    try:
        with _lock(store, root, shared=True):
            return _validate(store, root, identifier, _registry(store, root))
    except ValueError as exc:
        if isinstance(exc, TemplateError):
            raise
        raise TemplateConflict(str(exc)) from None


def list_templates(store, space):
    root = _root(store, space)
    if not root.exists():
        return []
    try:
        with _lock(store, root, shared=True):
            registry = _registry(store, root)
            return [_validate(store, root, identifier, registry) for identifier in CATALOG
                    if identifier in registry or (root / identifier).exists() or (root / identifier).is_symlink()]
    except ValueError as exc:
        if isinstance(exc, TemplateError):
            raise
        raise TemplateConflict(str(exc)) from None


def _adopt(store, root, identifier, candidate, files):
    """Publish one complete version only after a second local integrity check."""
    with _lock(store, root, create=True):
        registry = _registry(store, root)
        target = store._safe(root, identifier)
        previous = None
        if identifier in registry or target.exists():
            previous = _validate(store, root, identifier, registry)
            if (previous["source_version"] == candidate["source_version"]
                    and previous["upstream_commit"] != candidate["upstream_commit"]):
                raise TemplateError("同一稳定版本标签指向不同提交，停止自动采用")
            if tuple(map(int, candidate["source_version"].split('.'))) < tuple(map(int, previous["source_version"].split('.'))):
                raise TemplateError("拒绝将模板自动降级到较旧稳定版本")
            if (previous["files"] == candidate["files"] and previous["upstream_commit"] == candidate["upstream_commit"]
                    and previous["source_version"] == candidate["source_version"]):
                return {**previous, "status": "unchanged", "changed_files": []}
        changed = [{"path": name, "change": "new" if not previous or name not in previous["files"] else
                    "removed" if name not in candidate["files"] else "updated"}
                   for name in sorted(set(candidate["files"]) | set(previous["files"] if previous else {}))
                   if (previous or {}).get("files", {}).get(name) != candidate["files"].get(name)]
        staging = store._safe(root, ".staging-" + identifier + "-" + uuid.uuid4().hex)
        staging.mkdir(mode=0o700)
        archive = None
        promoted = False
        try:
            for name, body in files.items():
                path = store._safe(staging, name)
                path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with path.open("xb") as output:
                    output.write(body)
                path.chmod(0o600)
            _write_json(store._safe(staging, "manifest.json"), candidate)
            if previous:
                archive = store._safe(root, ".archives/" + identifier + "/" +
                                      datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex)
                archive.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                os.replace(target, archive)
            os.replace(staging, target)
            promoted = True
            registry[identifier] = {"manifest_sha256": _sha((target / "manifest.json").read_bytes()),
                                    "upstream_commit": candidate["upstream_commit"], "updated_at": _now()}
            _write_json(store._safe(root, ".framework-registry.json"), registry)
        except BaseException:
            # Keep the uncommitted candidate recoverable rather than risking an
            # accidental deletion if somebody edited it during this short window.
            if promoted and target.exists():
                os.replace(target, store._safe(root, ".failed-" + identifier + "-" + uuid.uuid4().hex))
            if archive is not None and archive.exists() and not target.exists():
                os.replace(archive, target)
            raise
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        return {**candidate, "status": "updated" if previous else "new", "changed_files": changed,
                "archive_path": str(archive.relative_to(store.base)) if archive else None}


async def sync_templates(store, space, frameworks=None):
    """Sync fixed official templates; no package manager or model is invoked."""
    root = _root(store, space)
    identifiers = _ids(frameworks)
    result = {"templates": [], "errors": [], "space_id": space}
    eligible = []
    for identifier in identifiers:
        try:
            with _lock(store, root, shared=True):
                registry = _registry(store, root)
                target = store._safe(root, identifier)
                if identifier in registry or target.exists():
                    _validate(store, root, identifier, registry)
            eligible.append(identifier)
        except (ValueError, OSError) as exc:
            result["templates"].append({"id": identifier, "framework": CATALOG[identifier]["framework"],
                                         "status": "conflict", "error": str(exc)})
            result["errors"].append({"id": identifier, "code": "template_conflict", "error": str(exc)})
    if not eligible:
        return result
    client = _OfficialFetcher()
    try:
        release = await asyncio.to_thread(_release, client)
    except Exception as exc:
        result["errors"].append({"code": "upstream_error", "error": str(exc)[:1000]})
        return result
    for identifier in eligible:
        try:
            candidate, files = await asyncio.to_thread(_download, client, identifier, release)
            result["templates"].append(_adopt(store, root, identifier, candidate, files))
        except Exception as exc:
            code = "template_conflict" if isinstance(exc, (TemplateConflict, OSError)) else getattr(exc, "code", "upstream_error")
            if code == "template_conflict":
                result["templates"].append({"id": identifier, "framework": CATALOG[identifier]["framework"], "status": "conflict", "error": str(exc)})
            result["errors"].append({"id": identifier, "code": code, "error": str(exc)[:1000]})
    return result
