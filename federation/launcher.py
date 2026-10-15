"""Reuse the existing local model supervisor, launch only the federation UI."""
import argparse
import fcntl
import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("openwiki_local_supervisor", ROOT / "openwiki-launcher.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)
PORT = 18732


def main():
    parser = argparse.ArgumentParser(description="启动行业分库与中央知识中枢")
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if (ROOT / '.runtime/server-connection.json').is_file():
        # Keep the browser origin, history and bookmarks while storage lives on
        # the server. Never silently start a second writable local instance.
        from server_entry import main as server_main
        try:
            return server_main(check=args.check, no_open=args.no_open)
        except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
            print('连接未完成：' + str(exc), flush=True)
            return 1
    supervisor = runtime.Supervisor()
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, runtime.stop_requested)
    try:
        model = runtime.read_config()
        digest = runtime.check_files(model)
        expected = str((ROOT / "openwiki-federation").resolve())

        def app_ready():
            result = runtime.request_json(PORT, "/api/federation")
            return isinstance(result, dict) and result.get("instance") == expected

        if args.check:
            if not runtime.model_available(model, digest) or not app_ready():
                raise RuntimeError("行业知识中枢尚未启动。请双击 启动行业知识中枢.command。")
            print("行业知识中枢与本地模型均已就绪：http://127.0.0.1:18732", flush=True)
            return 0
        lock = runtime.acquire_startup_lock()
        try:
            if runtime.listening(runtime.MODEL_PORT):
                if not runtime.ollama_healthy() or not runtime.model_available(model, digest):
                    raise RuntimeError("11436 的服务与本项目模型不匹配；未停止任何现有服务。")
                print("复用本地 Qwen3.5 模型服务。", flush=True)
            else:
                env = os.environ.copy()
                env.update(OLLAMA_HOST="127.0.0.1:11436", OLLAMA_MODELS=str(runtime.MODELS),
                           OLLAMA_NO_CLOUD="1", OLLAMA_CONTEXT_LENGTH="32768", OLLAMA_NUM_PARALLEL="1")
                child = supervisor.start("ollama", [str(runtime.OLLAMA), "serve"], env)
                supervisor.wait_ready(child, lambda: runtime.ollama_healthy() and runtime.model_available(model, digest), 45, "本地模型启动失败。")
            if runtime.listening(PORT):
                if not app_ready():
                    raise RuntimeError("18732 端口已被其他程序占用；未停止该程序。")
                print("复用已运行的行业知识中枢。", flush=True)
            else:
                python = ROOT / ".venv" / "bin" / "python"
                if not python.is_file():
                    raise RuntimeError("缺少本项目 .venv Python 运行环境。")
                child = supervisor.start("federation", [str(python), "-m", "federation.app", "--port", str(PORT)], os.environ.copy())
                supervisor.wait_ready(child, app_ready, 35, "行业知识中枢启动失败。")
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
            lock.close()
        print("行业知识中枢：http://127.0.0.1:18732", flush=True)
        if not args.no_open:
            subprocess.run(["/usr/bin/open", "http://127.0.0.1:18732"], check=False)
        if not supervisor.children:
            print("服务已就绪，本窗口可以关闭。", flush=True)
            return 0
        print("请保持此窗口运行。Ctrl+C 仅停止本窗口启动的服务。", flush=True)
        while not runtime.STOP:
            for label, child in supervisor.children:
                if child.poll() is not None:
                    raise RuntimeError("{} 已退出，请查看 openwiki-runtime/launcher-{}.log。".format(label, label))
            time.sleep(0.5)
        return 130
    except KeyboardInterrupt:
        return 130
    except (RuntimeError, OSError) as exc:
        print("启动未完成：" + str(exc), flush=True)
        return 1
    finally:
        supervisor.close()


if __name__ == "__main__":
    sys.exit(main())
