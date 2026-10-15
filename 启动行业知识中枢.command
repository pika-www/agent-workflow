#!/bin/zsh
set -u
FEDERATION_PROJECT_ROOT="${0:A:h}"
"$FEDERATION_PROJECT_ROOT/.venv/bin/python" "$FEDERATION_PROJECT_ROOT/federation/launcher.py" "$@"
FEDERATION_RESULT=$?
if [[ "$FEDERATION_RESULT" -ne 0 && "$FEDERATION_RESULT" -ne 130 && $# -eq 0 && -t 0 ]]; then
  read -r '?启动未完成。按回车关闭窗口。'
fi
exit "$FEDERATION_RESULT"
