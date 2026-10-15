#!/bin/zsh
set -e
cd "${0:A:h}"
if [[ -f .runtime/server-connection.json ]]; then
  exec ./启动行业知识中枢.command "$@"
fi
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install -r requirements.txt
fi
print "知行正在启动：http://127.0.0.1:${WIKI_PORT:-18731}"
print "关闭此窗口或按 Control+C 可停止；知识资料会保存在当前目录的 data 中。"
exec .venv/bin/python -m backend.app
