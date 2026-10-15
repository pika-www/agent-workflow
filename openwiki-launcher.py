#!/usr/bin/env python3
"""Supervise the project's bundled Ollama and unmodified OpenWiki visualizer.

--check performs read-only local preflight checks, including /api/tags. It never
downloads a model or generates a response. No process discovered by PID is killed.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "openwiki-runtime"
OLLAMA = RUNTIME / "ollama-v0.35.0" / "ollama"
MODELS = RUNTIME / "models"
WIKI = ROOT / "openwiki-data" / "wiki"
CLI = ROOT / "openwiki-upstream" / "dist" / "cli" / "cli.js"
MODEL_PORT = 11436
VIEW_PORTS = range(18731, 18752)
HTTP = build_opener(ProxyHandler({}))
STOP = False


def say(message):
    print(message, flush=True)


def read_config():
    path = ROOT / "openwiki-data" / ".env"
    if not path.is_file():
        raise RuntimeError("未找到 openwiki-data/.env，请先完成本项目的模型配置。")
    wanted = {"OPENWIKI_MODEL_ID", "OPENWIKI_PROVIDER", "OPENAI_COMPATIBLE_BASE_URL"}
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.strip().removeprefix("export ").partition("=")
        if separator and key.strip() in wanted:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values[key.strip()] = value
    model = values.get("OPENWIKI_MODEL_ID", "").strip()
    if not model:
        raise RuntimeError("尚未填写 OPENWIKI_MODEL_ID。请在 openwiki-data/.env 中指定已经下载的本地模型。")
    if values.get("OPENWIKI_PROVIDER") != "openai-compatible" or values.get("OPENAI_COMPATIBLE_BASE_URL", "").rstrip("/") not in {
        "http://127.0.0.1:11436/v1", "http://localhost:11436/v1"
    }:
        raise RuntimeError("模型配置未指向本项目服务。请将 provider 设为 openai-compatible，基础地址设为 http://127.0.0.1:11436/v1。")
    return model


def manifest_path(model):
    if not re.fullmatch(r"[A-Za-z0-9._:/-]+", model) or ".." in model or model.startswith("/"):
        raise RuntimeError("本地模型名称格式无效。")
    parts = model.split("/")
    name, separator, tag = parts[-1].partition(":")
    parts[-1] = name
    if len(parts) == 1:
        parts = ["registry.ollama.ai", "library"] + parts
    elif "." not in parts[0] and ":" not in parts[0] and parts[0] != "localhost":
        parts = ["registry.ollama.ai"] + parts
    if not name or (separator and not tag) or any(not part for part in parts):
        raise RuntimeError("本地模型名称格式无效。")
    return MODELS / "manifests" / Path(*parts) / (tag if separator else "latest")


def check_files(model):
    if not OLLAMA.is_file() or not os.access(OLLAMA, os.X_OK):
        raise RuntimeError("项目内 Ollama 程序缺失或不可执行：openwiki-runtime/ollama-v0.35.0/ollama。")
    if not CLI.is_file() or not (ROOT / "openwiki-local.sh").is_file():
        raise RuntimeError("OpenWiki 上游尚未构建，请先完成安装。")
    if not WIKI.is_dir():
        raise RuntimeError("Wiki 目录不存在：openwiki-data/wiki。请先完成初始化。")
    manifest = manifest_path(model)
    if not manifest.is_file():
        raise RuntimeError("模型 {} 尚未完整下载到 openwiki-runtime/models；本启动器不会自动下载模型。".format(model))
    try:
        raw = manifest.read_bytes()
        info = json.loads(raw)
        descriptors = [info["config"]] + info["layers"]
        for descriptor in descriptors:
            digest, size = descriptor["digest"], descriptor["size"]
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
                raise ValueError("invalid digest")
            blob = MODELS / "blobs" / digest.replace(":", "-")
            if not blob.is_file() or blob.stat().st_size != size:
                raise RuntimeError("模型 {} 的文件缺失或下载未完成；请完成下载后重试。".format(model))
        if not any(layer.get("mediaType") == "application/vnd.ollama.image.model" for layer in info["layers"]):
            raise RuntimeError("此模型没有本地模型权重，不能作为本地离线模型启动。")
        return hashlib.sha256(raw).hexdigest()
    except (ValueError, KeyError, TypeError, OSError) as error:
        raise RuntimeError("模型清单无法读取，请检查本地模型下载是否完整。") from error


def request_json(port, path):
    try:
        with HTTP.open("http://127.0.0.1:{}{}".format(port, path), timeout=2) as response:
            return json.loads(response.read(8 * 1024 * 1024))
    except (HTTPError, URLError, OSError, ValueError):
        return None


def listening(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.15):
            return True
    except OSError:
        return False


def model_available(model, digest):
    result = request_json(MODEL_PORT, "/api/tags")
    if not isinstance(result, dict) or not isinstance(result.get("models"), list):
        return False
    expected = manifest_path(model)
    for item in result["models"]:
        try:
            if manifest_path(item.get("name") or item.get("model") or "") == expected and item.get("digest") == digest:
                return True
        except (RuntimeError, TypeError):
            continue
    return False


def ollama_healthy():
    result = request_json(MODEL_PORT, "/api/version")
    return isinstance(result, dict) and isinstance(result.get("version"), str)


def viewer_belongs_here(port):
    """Graph.root is only a basename upstream, so also inspect the listener argv."""
    lsof = shutil.which("lsof") or "/usr/sbin/lsof"
    try:
        result = subprocess.run([lsof, "-nP", "-a", "-iTCP:{}".format(port), "-sTCP:LISTEN", "-Fp"], capture_output=True, text=True, timeout=3)
        pids = [line[1:] for line in result.stdout.splitlines() if line.startswith("p") and line[1:].isdigit()]
        for pid in pids:
            command = subprocess.run(["/bin/ps", "-p", pid, "-o", "command="], capture_output=True, text=True, timeout=3).stdout
            if str(CLI) in command and str(WIKI) in command:
                return True
    except (OSError, subprocess.TimeoutExpired):
        pass
    return False


def find_viewer():
    for port in VIEW_PORTS:
        if not listening(port):
            continue
        graph = request_json(port, "/api/graph")
        if isinstance(graph, dict) and isinstance(graph.get("nodes"), list) and isinstance(graph.get("edges"), list) and viewer_belongs_here(port):
            return port
    return None


def stop_requested(signum, frame):
    global STOP
    STOP = True


class Supervisor:
    def __init__(self):
        self.children = []
        self.logs = []

    def start(self, label, command, env):
        log_path = RUNTIME / ("launcher-" + label + ".log")
        fd = os.open(str(log_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        log = os.fdopen(fd, "ab", buffering=0)
        self.logs.append(log)
        child = subprocess.Popen(command, cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        self.children.append((label, child))
        return child

    def wait_ready(self, child, ready, seconds, message):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if STOP:
                raise KeyboardInterrupt
            if child.poll() is not None:
                raise RuntimeError(message + " 服务提前退出，请查看 openwiki-runtime/launcher-*.log。")
            result = ready()
            if result:
                return result
            time.sleep(0.35)
        raise RuntimeError(message + " 等待超时，请查看 openwiki-runtime/launcher-*.log。")

    def close(self):
        # Only Popen children created by this supervisor are signalled. Reused
        # services never enter self.children, even when their PID is inspected.
        for label, child in reversed(self.children):
            if child.poll() is not None:
                continue
            say("正在停止本次启动的 {}…".format(label))
            for sig, timeout in ((signal.SIGINT, 5), (signal.SIGTERM, 3), (signal.SIGKILL, 2)):
                if child.poll() is not None:
                    break
                try:
                    os.killpg(child.pid, sig)
                    child.wait(timeout=timeout)
                except ProcessLookupError:
                    break
                except subprocess.TimeoutExpired:
                    continue
        for log in self.logs:
            log.close()


def acquire_startup_lock():
    fd = os.open(str(RUNTIME / "launcher.lock"), os.O_RDWR | os.O_CREAT, 0o600)
    lock = os.fdopen(fd, "a+")
    deadline = time.monotonic() + 70
    while True:
        if STOP:
            lock.close()
            raise KeyboardInterrupt
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return lock
        except BlockingIOError:
            if time.monotonic() > deadline:
                lock.close()
                raise RuntimeError("另一个启动器仍在启动服务，请等待该窗口完成。")
            time.sleep(0.3)


def main():
    parser = argparse.ArgumentParser(description="启动项目内 Ollama 与原版 OpenWiki 查看器；Ctrl+C 仅停止本次启动的服务。")
    parser.add_argument("--no-open", action="store_true", help="启动服务但不打开浏览器")
    parser.add_argument("--check", action="store_true", help="仅检查本地模型文件与现有服务，不启动、不下载、不调用模型")
    args = parser.parse_args()
    supervisor = Supervisor()
    signal.signal(signal.SIGINT, stop_requested)
    signal.signal(signal.SIGTERM, stop_requested)
    signal.signal(signal.SIGHUP, stop_requested)
    try:
        model = read_config()
        digest = check_files(model)
        if args.check:
            if not ollama_healthy() or not model_available(model, digest):
                raise RuntimeError("本项目模型服务尚未就绪。请先打开 启动OpenWiki.command，并保持该窗口运行。")
            say("本地模型检查通过：{}，http://127.0.0.1:11436；未进行生成调用。".format(model))
            return 0
        say("OpenWiki · 本地模型 {}".format(model))
        lock = acquire_startup_lock()
        try:
            if listening(MODEL_PORT):
                if not ollama_healthy():
                    raise RuntimeError("端口 11436 已被其他或未就绪的服务占用；没有停止任何现有进程。")
                if not model_available(model, digest):
                    raise RuntimeError("端口 11436 的现有服务未提供本项目的同一模型。请检查该服务的模型目录；没有停止该服务。")
                say("复用已运行的本地模型服务：http://127.0.0.1:11436")
            else:
                env = os.environ.copy()
                env.update(OLLAMA_HOST="127.0.0.1:11436", OLLAMA_MODELS=str(MODELS), OLLAMA_NO_CLOUD="1", OLLAMA_CONTEXT_LENGTH="32768", OLLAMA_NUM_PARALLEL="1")
                child = supervisor.start("ollama", [str(OLLAMA), "serve"], env)
                supervisor.wait_ready(child, lambda: ollama_healthy() and model_available(model, digest), 45, "本地模型服务启动失败。")
                say("本地模型服务已就绪：http://127.0.0.1:11436")
            port = find_viewer()
            if port:
                say("复用本项目已运行的原版 Wiki 查看器。")
            else:
                child = supervisor.start("visualizer", [str(ROOT / "openwiki-local.sh"), "visualize", "--no-open"], os.environ.copy())
                port = supervisor.wait_ready(child, find_viewer, 35, "Wiki 查看器启动失败。")
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
            lock.close()
        url = "http://127.0.0.1:{}".format(port)
        say("Wiki：" + url)
        if not args.no_open:
            subprocess.run(["/usr/bin/open", url], check=False)
        if not supervisor.children:
            say("已复用现有服务，本窗口可以关闭。")
            return 0
        say("请保持本窗口运行。按 Ctrl+C 退出；仅停止本窗口启动的服务。")
        while not STOP:
            for label, child in supervisor.children:
                if child.poll() is not None:
                    raise RuntimeError("{} 已退出，请查看 openwiki-runtime/launcher-{}.log。".format(label, label))
            time.sleep(0.5)
        return 130
    except KeyboardInterrupt:
        return 130
    except (RuntimeError, OSError) as error:
        say("启动未完成：" + str(error))
        return 1
    finally:
        supervisor.close()


if __name__ == "__main__":
    sys.exit(main())
