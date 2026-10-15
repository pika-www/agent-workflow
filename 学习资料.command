#!/bin/zsh
set -euo pipefail
WIKI_ENTRY_ROOT="${0:A:h}"
print '请在行业知识中枢选择行业，添加资料后点击学习；审核后才汇入中央。'
exec "$WIKI_ENTRY_ROOT/启动行业知识中枢.command" "$@"
