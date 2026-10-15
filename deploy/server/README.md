# 未明：服务器模型与存储，本机访问

目标服务器为 `winfield@192.168.1.12`（`xiaoxin-server`）。Mac 保留项目源码、测试脚本和开发依赖；服务器保存模型、知识、会话、上下文、记忆与学习任务，并运行数据读写 API。Mac 通过 SSH 保留原来的 `http://127.0.0.1:18732/` 界面入口。首次切换记录保存在服务器 `backups/migration-20261011/verification.json`，后续本机数据清理记录保存在 `/home/winfield/knowledge-base/迁移记录/`。

后续知识、会话与学习操作直接使用服务器。本机改代码后再按实际改动部署源码；不要把整个本机目录覆盖同步到服务器的数据目录。

服务器的独立目录为 `/home/winfield/knowledge-base/`：`实时数据` 入口直接指向正在运行的 `project/openwiki-federation`；`未明知识库` 保存独立 Obsidian 库；`项目知识原件` 和 `原Mac数据` 为迁移时归档。归档不自动回写或定时同步到运行中的知识库。

## 目录与进程

- 服务器项目：`/home/winfield/services/weiming/project/`
- 实时数据：项目下的 `openwiki-federation/`；个人旧库为 `openwiki-data/`，早期原型为 `data/`。
- Qwen 权重：`project/openwiki-runtime/models/`；语音模型：`project/models/faster-whisper-small/`。
- Linux Python：`/home/winfield/services/weiming/venv/`，项目 `.venv` 指向它。
- Node、Ollama CPU 运行程序、Chrome 与浏览器依赖：`/home/winfield/services/weiming/bin/`。
- 迁移记录与历史备份：`/home/winfield/services/weiming/backups/`。
- Ollama 服务：`weiming-ollama.service`，只监听服务器 `127.0.0.1:11436`。
- 后端服务：`weiming-api.service`，只监听服务器 `127.0.0.1:18732`。

服务使用 `winfield` 的 systemd 用户服务，并开启 linger，SSH 退出后继续运行，系统启动时由已启用的用户服务启动。没有把模型或未鉴权 API 暴露到局域网监听地址。

## Mac 入口

继续双击 `启动行业知识中枢.command`、`启动OpenWiki.command` 或 `浏览OpenWiki.command`。启用服务器连接时，启动器读取 `.runtime/server-connection.json`，核对远端实例标识，然后打开原地址。它不会在连接失败时悄悄启动另一份本机数据库。

SSH 连接由 `~/Library/LaunchAgents/com.winfield.weiming-server.plist` 管理，登录后启动，掉线后重连。原浏览器地址不变；打开更新后的页面时，该浏览器原来的收藏、短笺和草稿会先保存到服务器，确认后移除旧内容存储键，具体目录见下文。

Mac 上的新文件继续通过聊天附件按钮上传。工具面板中的路径导入读取服务器上的文件，提示已改为服务器路径；服务不会通过 `/Users/...` 访问 Mac 硬盘。

会话列表校验使用实时 Agent 身份与层级注册表，避免每读取一个会话就重复扫描全部知识文件。参与者、发言者与委派层级仍逐次校验；知识目录和发言提示仍读取真实知识统计。这个调整解决了服务器上会话轮询占住后端、导致页面和健康检查等待的问题。

旧的 `启动知行.command` 和 `打开未明Obsidian.command` 在服务器模式下也进入远程界面；手动 `openwiki-local.sh` 不再创建本地知识库。直接启动后端时，服务器连接标记会阻止默认的本地数据目录重新生成；开发测试仍可显式使用独立临时目录。Obsidian 库已保存到服务器，没有新增双向同步。

额外的本机连接入口为 `~/Applications/未明服务器.command` 和 `~/Applications/未明服务器终端.command`。前者打开远程界面，后者通过 SSH 进入服务器运行项目目录。连接日志保存在 `~/Library/Logs/未明服务器/`。

浏览器的阅读足迹、星标、短笺和聊天草稿也通过 API 保存到服务器的 `openwiki-federation/metadata/browser-state/`。打开更新后的界面时，旧浏览器内容先在服务器的 `imports/` 中保留副本，收到保存确认后才清除旧存储键；并发修改按实际变化合并，冲突前的服务器版本另存于 `conflicts/`。浏览器只保留不含正文的随机客户端标识。网络故障时不回退到本机保存，界面会要求保留当前页面并重试。用户主动选择“导出探索手记”仍会触发浏览器下载。

## 模型与上下文

### 持续自主学习与 Mac 代理出口

自主学习可以启用 `continuous_learning`，让各行业按上次尝试时间持续轮转；成功后继续寻找知识缺口，失败保留原目标、原文和草稿，并按原有退避间隔续跑。单个失败成员不会持续独占队列。服务器的 `WEIMING_AUTONOMY_LOCAL_ONLY=1` 强制自动学习、知识复查和自动策略审核使用本机 Ollama，禁止回退到云模型；`local-budget.json` 单独记录调用次数，原 `budget.json` 的云模型额度和历史保留。这里改变的是后台自主任务，普通聊天的模型配置保持原有设置。

本地调用使用 Ollama `/api/chat`、JSON 输出格式、关闭思考输出，并继续校验结构、逐字引用、来源版本及审核结果。JSON 返回成功不等于知识审核通过。一次只运行一个后台学习任务；前台任务到来时取消正在进行的后台模型请求，保留当前步骤，等待空闲后继续。由相同本地模型发起的另一轮自动审核仍可能出错，页面继续标注自动审核及来源，不冒充人工审核。

Mac 的 Clash Verge 当前监听 `127.0.0.1:7897`。独立 LaunchAgent `~/Library/LaunchAgents/com.winfield.weiming-proxy.plist` 通过 `ssh -R 127.0.0.1:17897:127.0.0.1:7897 winfield@192.168.1.12` 提供服务器回环代理端口，保持连接并在断线后重连。它没有修改原来的 UI 隧道，也不复制 Clash 订阅或密钥。后端用户服务另行读取 `~/services/weiming/learning.env`，其中 `HTTP_PROXY`、`HTTPS_PROXY` 指向 `http://127.0.0.1:17897`；`NO_PROXY` 排除 `localhost,127.0.0.1,::1`，本地模型客户端还明确忽略代理环境。重新执行 `prepare-runtime.sh` 不会覆盖这个学习策略文件。

这种出口依赖 Mac 开机、联网并保持 Clash 运行。Mac 休眠、关闭或 VPN 断线时，服务器无法通过这条通道抓取海外资料，任务保存失败记录并等待续跑；未配置绕过代理的自动直连回退。服务器自身常驻不代表 Mac 出口永久可用。需要真正独立于 Mac 时，应另行把受支持的 VPN 配置部署到服务器。

配置和回执位于服务器 `/home/winfield/knowledge-base/验证/20261011-continuous-learning/`。界面入口为 `/autonomy`，显示本地模型调用次数、持续轮转开关、实际运行和待续跑任务。

接口依据：[Ollama Chat API](https://docs.ollama.com/api/chat)、[OpenSSH 反向端口转发](https://man.openbsd.org/ssh.1)。

保留 `qwen3.5:9b` 的原始权重及清单，Ollama 版本为 `0.35.0`，上下文设置为 `32768`，一次处理一个请求。此服务器使用 CPU 推理，速度以验收记录中的实测结果为准。`faster-whisper-small` 的文件一并迁移。

完整 Agent 上下文实测为 19,349 个输入 token，预填充每秒约 23.36 token，模型请求约 13 分 49 秒，应用从收件到保存“连接正常”约 14 分 2 秒。短句模型接口测试为 11.69 秒，包含首次加载。不同任务和上下文的耗时会不同。服务器把普通任务上限设为 30 分钟、报告任务设为 40 分钟，避免 CPU 仍在正常处理时被旧上限中断；这不会提高推理速度。Mac 原有的 10/20 分钟默认值保留。执行上限只接受操作系统环境配置，并限制在 1 至 60 分钟内。

本机 Ollama 客户端的单次连接上限同为 30 分钟，覆盖 HTTP 默认的 5 分钟首响应限制和 SDK 默认的 10 分钟限制，并保留调用方主动取消信号。适配只匹配服务器的 `http://127.0.0.1:11436/v1`，不会改变云模型或其他 HTTP 连接。`prepare-runtime.sh` 会调用 `patch-upstream.py` 对固定构建中的模型工厂应用有校验的适配，原文件保存在 `backups/upstream-transport/`；重建 upstream 后应重新执行此准备脚本。

原生聊天 SDK 及云端不可用时的 Qwen 回退也使用这一服务器超时配置，避免仍被旧的 2 分钟连接上限中断；云端原有超时保持不变。2026-10-11 的真实验收中，重启后的主聊天用约 41 秒正确回忆了重启前的测试代号，手动资料学习执行约 22 分 10 秒并生成待审核知识页。学习期间主队列会等待；生成完成不代表事实审核或自动发布完成。回执、历史完整性核对及本机目录监测保存在服务器 `/home/winfield/knowledge-base/验证/20261011-chat-learning/`。

报告/工具用云模型仍读取原有私有配置，云端模型权重不在本次迁移范围内。会话、用户记忆、上下文压缩记录、项目记忆、后台学习计划、预算、候选稿和待续跑任务均来自项目数据目录；不把“复制配置”当作模型已经完成真实推理。

## Linux 适配

Linux 使用 Python 3.12 专用锁定清单 `requirements-linux.lock.txt`。原 Mac Python 3.9 环境保持不变。Node 原生 SQLite 模块按 Linux/Node ABI 单独安装。

公开网页浏览使用官方 Chrome Linux 包，位置由 `WEIMING_CHROME_PATH` 指定；公开网址校验、读取范围、请求与截图预算保持原逻辑。

策略代码及 Python 图表工具使用固定 SHA-256 标识的空 Docker 镜像。容器没有网络，根目录只读，删除所有 capability，禁止获得新权限，限制 CPU、内存、进程数和输出文件大小。只挂载解释器/库、指定运行目录，不挂载整个项目、用户目录、私有凭据或 Docker socket。Mac 继续使用原来的 Seatbelt 沙箱。宿主不裸跑模型生成代码。

平台 MCP 的源码和私有配置分别保存；跨系统重建运行环境后，需要重新读取握手与登录状态。保存过 Cookie 不代表登录永久有效。需要扫码/OAuth 的流程仍由用户完成。

四个平台的 Linux MCP 握手均已通过；贴吧还通过了真实 Chrome 启动检查。抖音开放接口使用固定来源提交重新编译，Rust 1.90.0、用户目录内的 GCC 13 工具链与编译记录均已保留；可用 `sh deploy/server/build-openapi.sh` 重建。平台账号权限与协议安装分开验证，具体状态见验收记录。

B站二维码可继续在工具面板中使用。服务器没有交互桌面；抖音或贴吧需要重新登录时，在 Mac 的项目目录运行下面对应的一条命令，在独立 Chrome 窗口完成扫码：

```sh
.venv/bin/python deploy/server/login_on_mac.py douyin
.venv/bin/python deploy/server/login_on_mac.py tieba
```

入口只同步所选平台的登录文件，通过 SSH 传输，并保存服务器上的前一版本；不会复制个人 Chrome 资料。贴吧通过私有 Cookie 文件恢复服务器的专用浏览器会话，不依赖 macOS 加密的 Chrome 数据库。未在迁移过程中代替用户登录或授权。

## 检查与恢复

### 视频接口参数提交

聊天输入框的“发送方式”可选“普通对话”或“生成视频（本次）”。提交前按当前消息区分普通问答、视频进度查询和新视频生成；问句、否定、取消、文件查找等不会仅因保留的视频选项而创建任务。明确要求生成新视频，或为本次选择视频模式并填写画面描述时，消息原文直接作为 `prompt` 发送到默认文字工作流的 `/run` 地址，外部 JSON 请求体只有 `{"prompt":"消息原文"}`；不调用聊天模型，也不传历史上下文、时长、比例、种子、图片或回调地址。提交回执保存在当前聊天，重复请求编号不重复发送。`/video-generation` 只管理连接、默认文字工作流和提交记录，不再提供参数填写表单。功能默认关闭；配置生成服务的 HTTP BASE_URL 和可选 API Key 后启用，默认使用 `reference_4step_sla_server_upload`。该地址需来自生成服务，不能用 SSH 地址或视频接收端口代替。

生成成功提交后，输入框自动返回普通对话；不确定的提交继续保留原文和请求编号。旧版保存的视频模式不会在刷新后继续生效。

“检查一下视频生成好了吗”“视频进度怎么样”等走只读查询：根据当前聊天已保存的任务编号调用 `GET /api/jobs/{promptId}`，不调用模型，不创建新生成任务。无明确视频词语的“好了吗”只在最近话题仍是视频时续接。跳过旧版误把查询句当成提示词的任务；显式编号只匹配当前聊天。单次上游查询总等待最多 8 秒，失败时明确返回未能获取状态，保留任务编号。完成状态与服务器实际收到上传文件分别说明，不把生成成功当作上传验收。

聊天入口只提供带服务器上传的文字工作流，参数固定为 `prompt`。底层通用提交 API 保留原有十个工作流的兼容能力；历史记录继续保留，不会随页面简化而删除。

这个功能只转发参数并保存提交回执，不执行本地生成，不进行后台轮询或自动下载结果；用户追问进度时按上述只读路径查询。带 `_server_upload` 的工作流在外部生成完成后，通过其中已配置的上传节点送到服务器。现有独立接收服务是 `video-upload.service`，内网接口 `POST http://192.168.1.12:18733/api/v1/videos`，使用 Bearer Token、multipart 的 `file` 字段，保存到 `/srv/uploads/videos`。其公网入口由 `video-upload-public.service` 管理，当前地址读取 `/home/winfield/services/video-upload/tunnel/public-url.txt`。这个上传服务不在本次代码改动范围内；不要把仅收到 HTTP 202 当作已收到视频。接入文档没有 `callbackUrl` 参数，不会向上游发送自造的回调字段。

配置保存到运行数据目录下的 `private/video-generation.json`（权限 600），密钥不返回浏览器、不进入模型上下文；图片及提交记录保存在 `video-generation/inputs/` 和 `video-generation/jobs/`。关闭网页不影响已经开始的提交；关闭功能阻止后续新请求，不撤销已发往外部的任务。

每条提交使用 `request_id`，同编号和相同参数只发送一次。收到 HTTP 202 且有 `promptId` 才显示“已提交”。超时、断线、服务重启或不完整响应显示“提交结果待核对”，不会自动重发可能已经被外部接收的请求。聊天在未确认发送时保留原文和同一个请求编号，刷新后重试也不会重复提交；收到确定回执后，再发送同样文字才创建新任务。

主接口为 `GET/PUT /api/video-generation/config`、`POST /api/video-generation/images`、`GET/POST /api/video-generation/jobs`。这些控制接口沿用未明的回环监听与同源保护，没有对外开放新的管理入口。

在 Mac 上检查当前入口：

```sh
./启动行业知识中枢.command --check
```

查看服务器服务：

```sh
ssh winfield@192.168.1.12 'systemctl --user status weiming-api weiming-ollama --no-pager'
ssh winfield@192.168.1.12 'journalctl --user -u weiming-api -n 50 --no-pager'
```

Mac 原始模型已删除。正式知识数据、上下文、学习状态和历史数据副本在服务器校验归档后从本机清理；源码、测试脚本、依赖与 Git 历史保留。切回本机前，应先停止服务器写入，把服务器最新数据另存并取回，校验完整性，再转换运行配置路径、关闭 SSH 入口并启动本机。不要只删除连接标记后启动一套空的本机知识库。

迁移过程先在 `validation-data/` 隔离副本上运行测试；测试房间不进入正式数据。正式同步在本机服务空闲并停止后进行；先核对文件哈希，再仅替换活动连接器和说明文件中的运行路径。原对话、知识正文、历史回执保持原文，旧路径作为历史信息保留。路径修改前的文件另存于服务器备份目录。

## 原子排空发布

2026-10-15 起，源码更新通过 `deploy.server.atomic_release` 激活。只读空闲快照不能作为重启许可。先在独立发布目录准备 `staged/<源码相对路径>` 和 `manifest.json`；清单逐文件记录当前服务器 `before` SHA-256 与候选 `after` SHA-256，新文件的 before 为 null。只允许 federation、deploy、tests 内的明确源码路径，不包含运行数据或私有配置。候选先在临时数据目录通过相关测试。

```sh
cd /home/winfield/services/weiming/project
/home/winfield/services/weiming/venv/bin/python -m deploy.server.atomic_release \
  --project /home/winfield/services/weiming/project \
  --release /home/winfield/services/weiming/releases/<本次发布目录> \
  --timeout 120
```

执行顺序为：取得发布独占权 → 持久化关闭新操作入口 → 等待已受理请求、排队任务和当前后台轮次完成 → 取得跨进程活动独占锁 → 复核队列与源码哈希 → 备份并切换文件 → 重启 API → 核对新进程、聊天历史、设置及源码 → 重新开放。已有任务不会因为排空超时而被杀掉。后台学习和摘要停止启动新轮次，设置与待续任务保留；重新开放后调度器自动唤醒。

`GET /api/release/status` 返回 phase、ready、活动请求数、任务编号、后台轮次与 API PID，仅供观察。开始和结束发布必须由服务器上的发布进程持有文件锁，网页不能解除闸门。排空时草稿和手记仍通过同一活动锁持久化，进入 sealed 后一起暂停；其余新写入得到 HTTP 503、Retry-After 和 accepted=false，聊天输入保留，用户稍后重新发送；已受理的排队任务继续处理。读接口仍可观察进度。

草稿保存遇到发布封闭时，页面按原顺序最多尝试 30 次，每次间隔 1 秒，服务恢复后补存。此重试仅适用于浏览器状态，不会重新提交聊天或工具任务。保存尚未确认前应保留页面；持续故障会明确提示，不能将内存中的草稿当作已经写入服务器。

运行状态位于 `openwiki-federation/metadata/runtime-release/`。draining 表示正在排空，sealed 表示已交接到发布阶段。状态跨 API 重启保留，没有自动过期后提前开门的租约。默认排空上限为 120 秒；若排空达到上限且还没有换文件，脚本恢复入口并退出；已经切换过文件或重启后的异常则保持关闭，防止部分版本继续接收操作。此时先检查发布目录内的备份、清单和核验回执，恢复匹配版本、确认任务与历史后，再由同一 owner 的 ReleaseSession 重新开放；不要直接删除闸门文件。

正常发布不修改自主学习开关，也不重启 Ollama。旧的 guarded_agent_release.checkpoint 只接受已经 sealed 的状态。首次安装闸门使用了当前私有 SSH 入口的临时维护代理和后台断点校验；该一次性引导脚本不适用于未经盘点的多入口环境。

前台执行保留两个通用任务位，并给经过严格识别的寒暄、身份问答及明确限定本轮内容和短篇幅的问答保留一个短对话位；空闲通用位也能运行短问答。模型执行进程上限仍为 2；已知本地调用先经过单独的单槽队列，不占住两个共享执行位。短寒暄继续使用既有的最多两条服务请求竞速，因此执行位不等于底层 HTTP 请求数。短问答最多连续优先两次，最早等待达到 30 秒时恢复先来先服务。优先级在当前模型调用结束后生效，不会强制中断正在推理的调用。普通工具任务和长回答在满载时仍可能排队。
