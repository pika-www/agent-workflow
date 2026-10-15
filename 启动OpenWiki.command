#!/bin/zsh
set -euo pipefail
WIKI_ENTRY_ROOT="${0:A:h}"
exec "$WIKI_ENTRY_ROOT/启动行业知识中枢.command" "$@"
