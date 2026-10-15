#!/bin/zsh
set -euo pipefail
WIKI_ENTRY_ROOT="${0:A:h}"
print '请在网页选择中央智能体或行业分支，再打开提问页签。'
exec "$WIKI_ENTRY_ROOT/启动行业知识中枢.command" "$@"
