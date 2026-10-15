# 我的 OpenWiki 知识智能体

> 本文记录旧单库方案的安装与验收。当前使用“行业分库 + 中央智能体”，新入口是 `http://127.0.0.1:18732/`，请以 [行业知识中枢使用说明](./行业知识中枢-使用说明.md) 为准。根目录启动、学习和提问快捷入口已改为打开新行业界面；下文旧单库命令仅供历史参考。

本项目采用 [langchain-ai/openwiki](https://github.com/langchain-ai/openwiki) 的个人知识模式，复用它的智能体、来源连接器、Wiki 写入和原生可视化。没有替换上游的知识引擎。

- 上游版本：0.6.1。
- 检出提交：`2b63e88fa1c60286430347aa6b1adbcaa08e0f64`。
- 上游源码：`openwiki-upstream/`，保留独立 Git 历史和 MIT 许可证。
- 本地文件来源：官方 `@modelcontextprotocol/server-filesystem@2026.8.31`，通过 OpenWiki 的 `custom-mcp` 接入。
- 本地模型方案：项目内 Ollama 0.35.0，模型 `qwen3.5:9b`，专用接口 `http://127.0.0.1:11436/v1`。
- 现阶段先手动学习；没有注册系统定时任务，也没有修改系统唤醒设置。

## 当前状态（2026-10-02 文档更新时）

本地 Ollama 0.35.0 与 `qwen3.5:9b` 已完成安装和 SHA-256 核对，模型以 32K 上下文在 Apple Metal 上运行。真实模型的工具调用往返、读取示例、生成 12 个 Wiki 页面、读取第二版资料并更新知识，以及只读问答均已完成验收。浏览器已实际打开首页、主题页、来源页，并验证它们之间的链接。

本次成果经过人工审核：模型曾输出错误的复盘频率、文件名、页面链接和时间等元数据，已根据原始资料与采集证据校正，并保留修改前备份。不能将这次完成状态理解为无人干预的全自动学习已经可靠运行。详细验收记录见下文。

当前 `openwiki-inbox/` 只有 `示例-海岚读书计划.md`，用于测试读取、写入 Wiki 和引用来源。文件中的计划与内容均为虚构，不代表用户的经历、偏好或待办。用户自己的资料可以另放入该目录；示例生成的知识也应始终注明“虚构验收示例”。

## 首次使用

1. 直接双击 `启动OpenWiki.command`。模型已下载在项目的 `openwiki-runtime/models/`，连接配置已保存到 `openwiki-data/.env`，无需另填云端 API 密钥。启动器启动或复用专用端口 `11436` 上的本地 Ollama，再启动或复用本项目的原生 Wiki 查看器并打开浏览器。查看器首选地址为 `http://127.0.0.1:18731/`，以终端显示的实际地址为准。
2. 如果启动窗口提示服务正在运行，请保持该窗口打开。`Ctrl+C` 会停止这个启动器本次创建的服务；原先存在并被复用的服务不会被停止。若模型服务和查看器都已复用，启动器会结束，可关闭该窗口。旧的 `浏览OpenWiki.command` 现在委托同一启动入口。
3. 将自己的 UTF-8 `.md` 或 `.txt` 资料放进 `openwiki-inbox/`。首次从一份短资料开始，也可以先查看现有的虚构验收示例。PDF、Word、图片先转换为文本，本次未配置这些格式的解析。
4. 双击 `学习资料.command`。它调用原版 OpenWiki 的 `ingest custom-mcp`，读取来源并运行个人知识更新。检查来源结果、实际生成的 Wiki 页面及其引用后，才能判断本次学习是否成功。
5. 在浏览器查看图谱和 Markdown 页面；原生查看器不提供上传或聊天表单。双击 `向智能体提问.command` 输入问题，使用原版 CLI 问答。

启动器只检查模型文件和现有服务，不会自动下载模型或学习资料。模型文件不完整、配置不匹配或端口被其他服务占用时，会明确报错。连接参数可参考 `OpenWiki-模型配置.env.example`；启动入口不会寻找其他项目的密钥。

也可在本项目终端运行。第一个命令可能持续占用终端；服务就绪后，在另一个终端执行学习或问答：

```sh
./启动OpenWiki.command
./openwiki-local.sh ingest
./openwiki-local.sh --print "根据我的资料，解释已有知识并给出来源。"
```

只检查模型文件和现有本地服务，可以运行 `./启动OpenWiki.command --check`。这个检查不启动服务、不下载模型、不进行生成；检查通过也不代表模型工具调用或学习已经通过。`--no-open` 可启动服务但不自动打开浏览器。

## 本地模型配置

模型配置参考 `OpenWiki-模型配置.env.example`，主要参数为：

```dotenv
OPENWIKI_PROVIDER=openai-compatible
OPENAI_COMPATIBLE_BASE_URL=http://127.0.0.1:11436/v1
OPENAI_COMPATIBLE_API_KEY=ollama
OPENWIKI_MODEL_ID=qwen3.5:9b
OPENWIKI_MAX_OUTPUT_TOKENS=4096
```

`ollama` 是本地接口的非秘密占位值。接口使用 Chat Completions；地址应为 `/v1` 根地址，不应再加 `/chat/completions`。当前启动器只接受本项目的回环地址和端口；若将来改接云服务，需要同时调整启动方案。云模型会接收参与处理的资料。

原版 OpenWiki 的本地学习调用将 `OPENWIKI_OPENAI_COMPATIBLE_USE_RESPONSES_API`、`OPENWIKI_OPENAI_COMPATIBLE_STREAMING` 和 `OPENWIKI_OPENAI_COMPATIBLE_STREAM_MESSAGES` 设为 `false`，保留非流式兼容路径。网页普通咨询自 2026-10-07 起另由 `federation/native-agent.mjs` 显式使用原生 Chat Completions 流和工具回传循环；这没有把 Ollama 改成 Responses 协议，也没有修改学习调用配置。已通过 `OPENWIKI_OPENAI_COMPATIBLE_REASONING_EFFORT_SUPPORTED=true` 与 `OPENWIKI_REASONING_EFFORT=none`，让 Ollama 0.35 的兼容接口关闭 thinking；这组配置已完成实际结构化工具调用及工具结果回复验证。这组参数针对当前 Ollama 方案，不能原样假定适用于任意网关。独立深度报告模型采用私有配置的 Responses 路径，原生 `commentary` 与 `final_answer` 仅在真实接口返回这些 phase 时成立。

启动器在 Ollama 服务环境中设置 `OLLAMA_CONTEXT_LENGTH=32768`、`OLLAMA_NUM_PARALLEL=1` 和 `OLLAMA_NO_CLOUD=1`。32K 上下文是本地服务设置，不是 OpenWiki 的 `.env` 上下文选项。若复用已有服务，启动器不会重启或重配它，已有服务的上下文等参数需保持一致。

`OPENWIKI_MAX_OUTPUT_TOKENS=4096` 只限制单次回复的输出，不限制整个学习任务总量。OpenWiki 的工具定义和系统提示本身会占用上下文，首次应只测试短资料，并观察是否反复调用相同工具。遇到循环、输出截断或错误，应停止本次学习并检查日志，不能只凭退出或最终文字判断完成。

## 数据与接入范围

```text
openwiki-upstream/                原版上游代码与依赖
openwiki-tools/                   官方文件系统 MCP 包及锁文件
openwiki-runtime/
  ollama-v0.35.0/                 项目内 Ollama 可执行程序
  models/                        本项目下载的模型文件
  launcher-ollama.log             启动器创建的模型服务日志
  launcher-visualizer.log         启动器创建的查看器日志
openwiki-inbox/                   原始资料；当前只有虚构验收示例
openwiki-data/
  .env                           模型连接配置，权限 600
  INSTRUCTIONS.md                中文智能体职责和知识维护约定
  onboarding.json                本地资料源注册信息
  connectors/custom-mcp/         来源连接配置、采集证据和记录
  wiki/                          模型生成的个人知识页面
  conversation_history/          上游保存的对话记录
```

资料、模型文件和项目配置保存在本项目目录内，不覆盖已有的 `~/.openwiki`，不使用默认 Ollama 端口 `11434` 或默认模型目录。文件系统 MCP 只允许访问 `openwiki-inbox`；OpenWiki 的 MCP 调用策略拒绝写入、修改、移动等非只读来源工具。智能体仍能使用原版 Wiki 工具更新 `openwiki-data/wiki`。

Ollama 官方程序首次启动服务时还会在 `~/.ollama` 创建本地身份文件；本次已发生这一标准初始化，没有进行账户登录。因此这里的项目隔离指模型权重、OpenWiki 数据和模型配置，不代表 Ollama 完全不写用户目录。

本地入口明确使用 `personal`，避免误把源码仓库当成你的知识库。查看器也显式指向个人 Wiki，不会显示上游附带的项目文档。界面若为空，表示尚未生成知识页面，不是模型已学习。

`INSTRUCTIONS.md` 可以调整智能体职责、主题重点和中文输出要求。本次已核对示例的来源引用和版本变更；其他资料的去重、冲突处理与事实准确性仍需逐次检查，这些约定不是准确性的保证。

## 自动更新与限制

原版 OpenWiki 有摄取调度能力，但首次交互向导可能写入 macOS LaunchAgents，并继续询问电源设置。本项目入口采用单次命令，不运行该向导。应先确认手动学习成功，再决定调度频率和模型调用预算。

目前没有配置文件变更监听或定时学习。本次已验证同一示例从第一版到第二版的更新，并保留旧版复盘时间；任意资料的重复导入合并、多来源冲突、撤回来源等情况仍需另行验证。当前手动学习和人工审核流程不等于无人值守自动学习。

已关闭 OpenWiki 使用遥测和 LangSmith tracing。原生可视化仍会加载上游使用的 CDN 脚本及字体，因此当前查看器不等于完全离线运行。

## 维护

- 备份整个 `openwiki-data/` 和 `openwiki-inbox/`。运行结束后再备份，避免复制到正在写入的数据。`openwiki-runtime/models/` 体积较大，可按需要另行备份，避免日后重新下载。
- 启动器创建的服务日志在 `openwiki-runtime/launcher-ollama.log`、`openwiki-runtime/launcher-visualizer.log`；如果复用已有服务，这些文件不一定包含该服务的输出。日志和 raw 证据可能包含处理过的资料，不要直接对外发布。
- 不直接覆盖上游目录。后续按 Git 分支进行小范围修改，保留上游更新能力。
- 若项目移动，运行 `node setup-local-sources.mjs` 重新保存文件源的绝对路径。
- 原版构建命令为在 `openwiki-upstream` 内执行 `pnpm install --frozen-lockfile`、`pnpm run build`；需要 Node ≥22.22.0。
- 本次安装曾遇到三个 tarball 下载超时；已从相同 npm 官方地址下载并逐一匹配锁文件 SHA-512。临时下载适配位于 `.install-cache/`，没有更改上游锁文件或全局 pnpm 配置。

旧的 FastAPI 自建原型文件仍保留作参考，原有 `启动知行.command` 属于旧原型。后续以本说明中的 OpenWiki 入口为准。

## 真实模型与内容验收（2026-10-02，接入本地模型后）

- 官方 Ollama 0.35.0 程序包和 `qwen3.5:9b` 模型文件已核对 SHA-256；模型权重约 6.6 GB，并经 Ollama 原生拉取流程再次校验完成。安装来源、版本与摘要保存在 `openwiki-runtime/installation.json`。
- 本地服务实际使用 Apple Metal，模型运行信息显示 `context_length=32768`。真实兼容接口完成“结构化工具调用 → 工具返回 → 中文回答”，记录在 `openwiki-data/validation/model-tool-smoke.json`。
- 首次学习通过文件系统 MCP 读取第一版示例正文，生成 12 个 Wiki 页面。第二版学习实际读取修订后的正文，将复盘时间从“每周五 15:00”更新为“每周三 10:30”，保留旧版记录。对应日志和结果在 `openwiki-data/validation/first-learning*`、`chinese-update*`；成功采集的原始内容保存在 `openwiki-data/connectors/custom-mcp/raw/`。
- 最终只读问答正确回答五项事实：负责人陈知、目标 12 篇阅读笔记、当前每周三 10:30、旧版每周五 15:00、属于虚构验收示例，并引用实际存在的 Wiki 页面路径。记录在 `openwiki-data/validation/final-answer-verified.log` 和对应结果 JSON。
- 浏览器实际显示 12 个页面，中文首页、海岚主题页和本地资料来源页能够打开，相互引用链接已验证。
- 以上验收包含人工校正。首次尝试只列出目录、未读取正文时已中止，不能计为成功学习；随后补充了明确的来源读取要求。成功生成后，仍发现频率、文件名、链接和元数据错误，已依据源文与真实采集记录修正。校正前 Wiki 备份位于 `openwiki-data/backups/content-review-20261002T125155Z/`，校正清单位于 `openwiki-data/validation/content-review.json`。

这些结果只覆盖当前虚构示例及本机手动流程。尚未导入用户实际资料，也没有验证无人值守学习或自动调度。

## 历史安装验证（2026-10-02，接入本地模型前）

- 上游依赖安装和 TypeScript / 浏览器资源构建通过；上游 Git 工作区保持干净，未改动源码、依赖清单或锁文件。
- 9 个相关上游测试文件全部通过，共 270 项；覆盖模式选择、配置、兼容模型接口、个人模式工具边界、摄取流程、可视化和遥测。这些是本地自动测试，不代表真实模型验收。
- 真实 OpenWiki MCP runtime 连接官方 filesystem 服务通过：发现工具、读取中文资料、保存原始证据、拒绝写入原文、拒绝读取目录外文件。全部使用隔离临时目录，验证结束后已清理。
- 当时浏览器实际显示 OpenWiki 原生查看器，状态为 `0 pages`，没有用户资料或已生成页面。这是当时的安装快照，不是后续学习结果。
- 当时 `ingest` 能识别“本地中文资料”，随后以退出码 1 报告缺少模型 API 密钥；问答同样明确失败。这是接入本地模型前的失败路径验证，不表示当前配置仍应缺少占位密钥。
- 本地启动脚本的语法、帮助、版本以及单次运行参数检查通过。

以上是接入本地模型前的安装与自动测试记录；后续真实模型生成、示例学习、来源核对和版本更新的结果已单独记录在上一节。这 270 项测试没有因接入模型而全部重跑，也不用于证明自动调度或任意资料准确性。

注意：MCP 读取被拒绝时，原生调用可能正常返回并保存证据，但 `result.isError` 为 `true`。排查时应同时检查这一字段，不能仅用是否生成证据文件判断采集成功。
