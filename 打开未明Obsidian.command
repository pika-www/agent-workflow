#!/bin/zsh
set -eu
WIKI_ENTRY_ROOT="${0:A:h}"
if [[ -f "$WIKI_ENTRY_ROOT/.runtime/server-connection.json" ]]; then
  print 'Obsidian 知识库已迁移到服务器：/home/winfield/knowledge-base/未明知识库'
  exec "$WIKI_ENTRY_ROOT/启动行业知识中枢.command" "$@"
fi
if [[ ! -d /Applications/Obsidian.app ]]; then
  print '尚未找到 /Applications/Obsidian.app。请从 https://obsidian.md/download 安装官方应用。'
  exit 1
fi
/usr/bin/open -a /Applications/Obsidian.app 'obsidian://open?vault=%E6%9C%AA%E6%98%8E%E7%9F%A5%E8%AF%86%E5%BA%93&file=00+%E5%BC%80%E5%A7%8B%2F%E6%9C%AA%E6%98%8E'
