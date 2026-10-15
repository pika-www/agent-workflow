# Agent 工作目录

此目录是服务器上当前 Agent 的实时配置。中央 Agent 位于 `openwiki-federation/central/`，其他 Agent 位于 `openwiki-federation/branches/<id>/`。

`IDENTITY.md`、`SOUL.md`、`AGENTS.md` 分别定义身份、交流方式和工作规则，每次模型对话读取，编辑后下一轮生效。
`USER.md` 手工部分定义当前 Agent 使用的稳定背景和偏好；“称呼”字段是全局称呼。自动同步区保留现有个人资料的范围控制以及带会话来源的昵称记录。当前会话的最新明确纠正优先。
`MEMORY.md` 手工部分可保存当前 Agent 的长期决策；自动区从既有记忆 API 同步。两类内容按问题选择，不每轮加载全文。
不要手工修改 `weiming:managed` 标记内的内容；请通过原有个人资料、记忆 API 和聊天更正来源。标记外的修改会保留。
`memory/YYYY-MM-DD.md` 按 `USER.md` 时区记录宿主确认的工作状态和证据位置。只记实际状态，不把助手的建议升级为已完成事项。问到工作记录时按日期或相关词读取节选。
`skills/<name>/SKILL.md` 沿用项目技能校验和按需加载器；文件安装与工具执行权限独立。
`BOOTSTRAP.md` 由首次初始化流程消费，完成状态在 `metadata/agent-workspaces/`。`BOOT.md` 的已知 check 标记在每次 API 启动时执行，其他文本不作为 shell 脚本。

文件修改接口：`GET /api/agent-workspaces/<id>` 查看文件、版本和启动回执；`PUT /api/agent-workspaces/<id>/files/<name>` 提交 `content` 与 `expected_sha256`。编辑前版本会归档，版本冲突不会覆盖。
启动回执和每轮 `context_usage.workspace` 记录实际提供的文件与哈希。只读文件成功不等于外部操作或知识审核完成。
