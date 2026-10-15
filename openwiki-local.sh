#!/bin/zsh
# Project-local launcher for the unmodified upstream OpenWiki CLI.
set -euo pipefail
WIKI_PROJECT_ROOT="${0:A:h}"
if [[ -f "$WIKI_PROJECT_ROOT/.runtime/server-connection.json" && "${1:-}" != "--version" ]]; then
  print '知识、上下文与学习任务已迁移到服务器。'
  print '网页入口：./启动行业知识中枢.command'
  print '服务器终端：~/Applications/未明服务器终端.command'
  print '此旧版入口不再创建本地知识库。'
  exit 2
fi
export OPENWIKI_CONFIG_DIR="$WIKI_PROJECT_ROOT/openwiki-data"
export OPENWIKI_TELEMETRY_DISABLED=1
export DO_NOT_TRACK=1
export LANGCHAIN_TRACING_V2=false
export LANGSMITH_TRACING=false
unset LANGSMITH_API_KEY LANGCHAIN_API_KEY
# Model credentials come from this project's OpenWiki .env, not another shell session.
unset OPENWIKI_PROVIDER OPENWIKI_MODEL_ID OPENAI_API_KEY OPENAI_BASE_URL
unset OPENROUTER_API_KEY ANTHROPIC_API_KEY ANTHROPIC_BASE_URL
unset OPENAI_COMPATIBLE_API_KEY OPENAI_COMPATIBLE_BASE_URL
unset OPENWIKI_OPENAI_COMPATIBLE_USE_RESPONSES_API OPENWIKI_OPENAI_COMPATIBLE_STREAMING
unset OPENWIKI_OPENAI_COMPATIBLE_STREAM_MESSAGES OPENWIKI_OPENAI_COMPATIBLE_REASONING_EFFORT_SUPPORTED
unset OPENWIKI_REASONING_EFFORT OPENWIKI_MAX_OUTPUT_TOKENS
unset OPENWIKI_DEBUG OPENWIKI_DEBUG_CREDENTIALS OPENWIKI_DEV OPENWIKI_SCHEDULED

WIKI_NODE="$(command -v node || true)"
if [[ -z "$WIKI_NODE" ]]; then
  WIKI_NODE="/Users/winfield/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
fi
WIKI_CLI="$WIKI_PROJECT_ROOT/openwiki-upstream/dist/cli/cli.js"
if [[ ! -x "$WIKI_NODE" || ! -f "$WIKI_CLI" ]]; then
  print -u2 'OpenWiki 尚未构建，或 Node 不可用。请查看 OpenWiki-使用说明.md。'
  exit 1
fi
cd "$WIKI_PROJECT_ROOT"
if [[ $# -eq 0 || "$1" == "--help" ]]; then
  print '用法：'
  print './openwiki-local.sh --init --print      初始化个人 Wiki（需要模型）'
  print './openwiki-local.sh ingest             学习本地资料（需要模型）'
  print './openwiki-local.sh --print "问题"     向个人智能体提问（需要模型）'
  print './openwiki-local.sh visualize          打开原生 Wiki 查看器'
  exit 0
fi
case "$1" in
  visualize)
    shift
    exec "$WIKI_NODE" "$WIKI_CLI" visualize "$OPENWIKI_CONFIG_DIR/wiki" --port 18731 "$@"
    ;;
  ingest)
    shift
    exec "$WIKI_NODE" "$WIKI_CLI" ingest custom-mcp "$@"
    ;;
  --version)
    exec "$WIKI_NODE" -p 'JSON.parse(require("fs").readFileSync("openwiki-upstream/package.json", "utf8")).version'
    ;;
  *)
    WIKI_PRINT_MODE=false
    for WIKI_ARGUMENT in "$@"; do
      if [[ "$WIKI_ARGUMENT" == "--print" || "$WIKI_ARGUMENT" == "-p" ]]; then
        WIKI_PRINT_MODE=true
      fi
    done
    if [[ "$WIKI_PRINT_MODE" != true ]]; then
      print -u2 '此入口只运行单次任务，请加 --print；它不会启动系统定时任务向导。'
      exit 2
    fi
    exec "$WIKI_NODE" "$WIKI_CLI" personal --language zh-CN "$@"
    ;;
esac
